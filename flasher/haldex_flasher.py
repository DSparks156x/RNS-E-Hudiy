#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
haldex_flasher.py
Haldex Gen4 (0BR907554A sw3016) OBD Flasher Engine for Linux / SocketCAN.
Adapted from the battle-tested J2534 reference implementation.
"""
import sys
import os
import time
import struct
import logging
import json
from typing import Optional, Callable, Dict, Any, Union

from .socketcan_device import SocketCANDevice
from .tp20 import TP20Transport, MessageTimeoutError
from .artifacts import prepare_image, DEFAULT_START, DEFAULT_END

logger = logging.getLogger("HaldexFlasher")

from .haldex_flash import (Kwp, a3, parse_flash_date, AWD_MODULE_ADDR, APP_KEY_CONST,
    LOADER_SEED, LOADER_KEY, SESSION_EXTENDED, SESSION_PROGRAMMING,
    SA_APP_REQUEST_SEED, SA_APP_SEND_KEY, SA_LDR_REQUEST_SEED, SA_LDR_SEND_KEY,
    RC_ERASE, RC_CHECKSUM, IDENT_ECU_IDENT, IDENT_STATUS_FLASH, ERASE_STAMP, CHUNK_SIZE)


class HaldexFlasher:
    """
    High-level Haldex Gen4 OBD Flasher Controller.
    Manages TP2.0 channel, security access, sector erase, data streaming,
    checksum verification, and anti-brick recovery.
    """
    def __init__(
        self,
        channel: str = "can0",
        module: int = AWD_MODULE_ADDR,
        device: Optional[Any] = None,
        progress_cb: Optional[Callable[[str, float, str, float], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None
    ):
        self.channel = channel
        self.module = module
        self.device = device
        self.progress_cb = progress_cb
        self.log_cb = log_cb or logger.info
        self.abort_requested = False
        self.destructive_started = False
        self.recovery_required = False
        self.last_result = {}

    def log(self, msg: str):
        logger.info(msg)
        if self.log_cb:
            try:
                self.log_cb(msg)
            except Exception:
                pass

    def report_progress(self, stage: str, percent: float, detail: str = "", speed: float = 0.0, eta_sec: float = 0.0):
        if self.progress_cb:
            try:
                # Support both 4-arg and 5-arg callbacks
                import inspect
                sig = inspect.signature(self.progress_cb)
                if len(sig.parameters) >= 5:
                    self.progress_cb(stage, percent, detail, speed, eta_sec)
                else:
                    self.progress_cb(stage, percent, detail, speed)
            except Exception:
                try:
                    self.progress_cb(stage, percent, detail, speed)
                except Exception:
                    pass

    prepare_image = staticmethod(prepare_image)

    def _ensure_device(self):
        if self.device is None:
            self.device = SocketCANDevice(channel=self.channel)

    def _disconnect(self):
        tp = getattr(self, '_tp', None)
        self._tp = None
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                self.log(f'Transport close: {exc}')

    def close(self):
        self._disconnect()
        if self.device is not None:
            try:
                self.device.close()
            finally:
                self.device = None

    def reconnect_tp(self, tries=5, heartbeat=False):
        self._disconnect()
        self._ensure_device()
        for attempt in range(tries):
            if self.abort_requested:
                raise RuntimeError('Cancellation requested; operation stopped')
            try:
                self.device.can_clear(0xffff)
                self._tp = TP20Transport(self.device, module=self.module, timeout=2.0,
                                         debug=True, log_fn=self.log)
                self._tp.keepalive_after_response = heartbeat
                return self._tp
            except Exception as exc:
                self.log(
                    f'[TP20] connection attempt {attempt + 1}/{tries} failed: '
                    f'{type(exc).__name__}: {exc}'
                )
                if attempt == tries-1:
                    raise
                time.sleep(1)

    @staticmethod
    def _ident(kwp, tp):
        ident = kwp.read_ecu_ident(IDENT_ECU_IDENT)
        status = kwp.read_ecu_ident(IDENT_STATUS_FLASH)
        payload = ident[2:]
        if len(payload) < 26 or len(status) < 12:
            raise RuntimeError('Truncated Controller identification/status')
        return {'connected': True, 'in_bootloader': tp.tx_addr != 0x764 or b'B_111545' in payload,
                'raw_9b': ident.hex(), 'raw_9c': status.hex(),
                'part_number': payload[:12].decode('ascii', errors='strict').strip(),
                'sw_version': payload[12:16].decode('ascii', errors='strict'),
                'system_desc': payload[26:].decode('ascii', errors='replace').strip('\x00 '),
                'flash_status': status[2], 'flash_counter': status[3], 'flash_attempts': status[4],
                'last_flash_date': parse_flash_date(status[6:10]),
                'last_tool_id': int.from_bytes(status[10:12], 'big')}

    def read_ecu_info(self):
        try:
            tp = self.reconnect_tp()
            return self._ident(Kwp(tp, log_fn=self.log), tp)
        finally:
            self.close()

    def reset_ecu(self, to_bootloader=False):
        # Entering/resuming the loader is handled as part of the normal flash.
        raise RuntimeError('Standalone reset is disabled; start a flash to enter or resume bootloader programming')

    def _cancel(self):
        if self.abort_requested:
            raise RuntimeError('Cancellation requested; operation stopped' +
                               ('; Controller remains in bootloader and can be flashed again' if self.destructive_started else ''))

    def _routine_done(self, kwp, rid):
        for _ in range(30):
            self._cancel()
            try:
                response = kwp.routine_result(rid)
            except (TimeoutError, ConnectionError) as exc:
                # The loader intentionally closes TP with A8 while erase is
                # running. Result polling is read-only and repeatable: reopen
                # the loader channel and continue, but never resend erase.
                self.log(
                    f'[TP20] routine 0x{rid:02X} polling lost its channel '
                    f'({type(exc).__name__}: {exc}); reconnecting'
                )
                if isinstance(exc, ConnectionError):
                    # A8 means the gateway has already torn down this dynamic
                    # channel. Do not transmit another A8 to the stale address;
                    # reconnect_tp will clear RX and perform a fresh 0x200 setup.
                    self._tp = None
                time.sleep(0.5)
                kwp = Kwp(self.reconnect_tp(15, heartbeat=True), log_fn=self.log)
                continue
            except RuntimeError as exc:
                if 'NRC 0x23' not in str(exc):
                    raise
                time.sleep(0.5)
                continue
            if response == bytes([0x73, rid, 0]):
                return kwp
            # Only the documented routine-not-complete status can be polled.
            if response != bytes([0x73, rid, 0x23]):
                raise RuntimeError(f'Routine {rid:#x} failed: {response.hex()}')
            time.sleep(0.5)
        raise TimeoutError(f'Routine {rid:#x} did not finish')

    def flash_binary(self, binary_data_or_path, start_addr=DEFAULT_START,
                     end_addr=DEFAULT_END, file_off=None, dry_run=False, simulator_mode=False):
        self.destructive_started = False
        self.recovery_required = False
        self.last_result = {}
        started = time.monotonic()
        prepared = prepare_image(binary_data_or_path, start_addr, end_addr, file_off, simulator_mode)
        metadata = prepared['metadata']
        self.last_result = dict(metadata, checksum_verified=False, boot_verified=False,
                                commit_outcome='not_attempted')
        self.log('PREFLIGHT ' + json.dumps(metadata, sort_keys=True))
        if dry_run:
            self.report_progress('VALIDATED', 100, 'Offline validation complete; no Controller verification performed')
            return dict(self.last_result, status='validated', dry_run=True)
        try:
            self._cancel()
            self.report_progress('CONNECTING', 5, 'Opening exclusive diagnostic session')
            tp = self.reconnect_tp(heartbeat=True)
            kwp = Kwp(tp, log_fn=self.log)
            if tp.tx_addr == 0x764:
                kwp.session(SESSION_EXTENDED)
                seed = kwp.sa_seed(SA_APP_REQUEST_SEED)
                if any(seed):
                    key = ((int.from_bytes(seed, 'big') + APP_KEY_CONST) & 0xffffffff).to_bytes(4, 'big')
                    kwp.sa_key(SA_APP_SEND_KEY, key)
                try:
                    # A8/no reply is valid while the application changes into
                    # the loader; do not insert a heartbeat into that transition.
                    tp.keepalive_after_response = False
                    kwp.session(SESSION_PROGRAMMING)
                except (TimeoutError, ConnectionError) as exc:
                    self.log(f'Programming transition ambiguous: {exc}; verifying loader connection')
                tp = self.reconnect_tp(15, heartbeat=True)
                kwp = Kwp(tp, log_fn=self.log)
                if tp.tx_addr == 0x764:
                    raise RuntimeError('Programming transition did not enter loader')
            seed = kwp.sa_seed(SA_LDR_REQUEST_SEED)
            if seed != LOADER_SEED:
                raise RuntimeError(f'Unexpected loader challenge: {seed.hex()}')
            kwp.sa_key(SA_LDR_SEND_KEY, LOADER_KEY)
            self._cancel()
            limit = kwp.request_download(start_addr, metadata['size'])
            chunk = (min(CHUNK_SIZE, limit - 1) // 4) * 4
            if chunk < 4:
                raise RuntimeError('Loader transfer size is too small')
            self._cancel()
            # Mark before send: even a missing erase reply is destructive ambiguity.
            self.destructive_started = self.recovery_required = True
            self.report_progress('ERASING', 30, 'Erasing selected sectors; interruption leaves Controller ready to flash again')
            kwp.routine(RC_ERASE, a3(start_addr) + a3(end_addr) + ERASE_STAMP)
            kwp = self._routine_done(kwp, RC_ERASE)
            region = prepared['region']
            write_started = time.monotonic()
            for off in range(0, len(region), chunk):
                self._cancel()
                block = region[off:off+chunk]
                kwp.transfer(block)  # A timeout is ambiguous: never resend TransferData.
                sent = off + len(block)
                speed = sent / max(time.monotonic() - write_started, 0.001)
                self.report_progress('WRITING', 35 + 55 * sent/len(region),
                                     f'{sent}/{len(region)} bytes', speed,
                                     (len(region)-sent)/speed)
            kwp.transfer_exit()
            self.report_progress('VERIFYING', 93, 'Checking transferred application checksum')
            kwp.routine(RC_CHECKSUM, a3(start_addr) + a3(end_addr) + struct.pack('>H', metadata['checksum']))
            kwp = self._routine_done(kwp, RC_CHECKSUM)
            self.last_result['checksum_verified'] = True
            self.report_progress('REBOOTING', 96, 'Committing; fresh application verification required')
            outcomes = {}
            # Commit/reset may close or replace the TP channel after a valid
            # KWP response. A heartbeat here would turn that transition into a
            # false failure.
            tp.keepalive_after_response = False
            # Always attempt StopCommunication, including after failed 0x20.
            for sid in (0x20, 0x82):
                try:
                    kwp.raw(bytes([sid]))
                    outcomes[f'{sid:02x}'] = 'acknowledged'
                except Exception as exc:
                    outcomes[f'{sid:02x}'] = str(exc)
                    self.log(f'Commit service {sid:#x} unconfirmed: {exc}')
            self.last_result['commit_responses'] = outcomes
            self.last_result['commit_outcome'] = ('acknowledged' if all(v == 'acknowledged' for v in outcomes.values()) else 'ambiguous')
            self.close()
            # Cancellation cannot replace the fresh completion check after commit.
            cancelled = self.abort_requested
            self.abort_requested = False
            try:
                tp = self.reconnect_tp(15, heartbeat=False)
                info = self._ident(Kwp(tp, log_fn=self.log), tp)
            finally:
                self.abort_requested = cancelled
            self.last_result['application'] = info
            if (info['in_bootloader'] or not info['sw_version'].strip()
                    or not info['part_number'].strip() or info['flash_status'] not in (0, 1)):
                raise RuntimeError('Fresh expected application boot was not verified')
            self.last_result['boot_verified'] = True
            # An application boot alone cannot prove an ambiguous EEPROM commit.
            if self.last_result['commit_outcome'] != 'acknowledged':
                raise RuntimeError('Application boot observed but commit outcome remains ambiguous')
            self.recovery_required = False
            self.last_result.update(status='ok', elapsed_sec=round(time.monotonic()-started, 1), recovery_required=False)
            self.report_progress('COMPLETE', 100, 'Transfer/checksum, commit acknowledgement and fresh application boot verified')
            return self.last_result
        except Exception as exc:
            self.last_result.update(status='recovery_required' if self.recovery_required else 'error',
                                    recovery_required=self.recovery_required, error=str(exc))
            self.log('FLASH RESULT ' + json.dumps(self.last_result, sort_keys=True))
            raise
        finally:
            self.close()
