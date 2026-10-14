#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
haldex_manager.py
Manages Haldex Gen4 AWD mode switching, persistence, reconciliation, and telemetry.

Architecture:
- Selects the mode over KWP2000 (7716+ images): `3B F0 b0 b1` sets, `3B F0` queries,
  sent to module 0x0A through the TP2 worker (tp2_cmd.ipc KWP_REQUEST). The worker
  reuses its session if it is already polling the Haldex, or opens and closes one.
- Reconciles the ECU's applied mode against the desired mode (confirm ~300 ms after a
  set, then a query every RECONCILE_INTERVAL_S). The ECU latch is RAM only, so a reset
  or key cycle drops it to Stock and the next query re-sends.
- Subscribes to can_stream.ipc to decode 0x6DA and 0x679 telemetry @ 50 Hz (owner
  images only; for logging and the AWD tab, not for mode readback).
- Handles persistence according to config.json:
    - If "default_mode" is configured (0-4), resets to that mode on startup.
    - If "default_mode" is null/blank, restores last used mode on startup and saves changes.
- Exposes ZMQ REP command socket (haldex_cmd.ipc) and ZMQ PUB status socket (haldex_status.ipc).
- Also sends the exhaust valve commands (0x67A, C3 3C namespace) over can_send.ipc.
"""

import os
import sys
import json
import time
import struct
import logging
import threading
import signal
from typing import Optional, Dict, Any, Tuple
import zmq
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flasher.traffic import flashing_mode_enabled
from flasher.exhaust_valve import command as valve_command, CAN_ID as CAN_ID_VALVE

# --- Mode Constants ---
MODE_STOCK = 0
MODE_PERFORMANCE = 1
MODE_COMPETITION = 2
MODE_SNOW_DRIFT = 3
MODE_FULL_COUPLING = 4

MODE_NAMES = {
    MODE_STOCK: "Stock",
    MODE_PERFORMANCE: "Performance",
    MODE_COMPETITION: "Competition",
    MODE_SNOW_DRIFT: "Snow Drift",
    MODE_FULL_COUPLING: "Full Coupling",
}
ALL_MODES = tuple(MODE_NAMES)

CAN_ID_HALDEX_TELEMETRY_YAW = 0x679
CAN_ID_HALDEX_TELEMETRY_STATE = 0x6DA

KWP_MODULE_HALDEX = 0x0A
MODE_COMMAND_HEADERS = {
    MODE_STOCK: bytes.fromhex("5AA5"),
    MODE_PERFORMANCE: bytes.fromhex("A55A"),
    MODE_COMPETITION: bytes.fromhex("3CC3"),
    MODE_SNOW_DRIFT: bytes.fromhex("6996"),
    MODE_FULL_COUPLING: bytes.fromhex("9669"),
}
MODE_QUERY = bytes.fromhex("3BF0")

# The manager needs 8 consecutive 20 ms samples and applies on the 10th tick.
CONFIRM_DELAY_S = 0.3
RECONCILE_INTERVAL_S = 10.0
LINK_RETRY_S = 2.0
KWP_TIMEOUT_S = 4.0
# Sets per mismatch before reporting "failed" and dropping to one per interval.
MAX_QUICK_SETS = 2

REASON_NAMES = {
    0: "init", 1: "request changed", 2: "debouncing", 3: "steady",
    4: "applied (Stock row)", 5: "applied (retaining row)", 6: "no request, Stock fallback",
}

logger = logging.getLogger("HaldexManager")


def build_mode_request(mode: int) -> bytes:
    """KWP `3B F0 b0 b1`: the codeword is the same one the 0x67A frame carried."""
    mode = int(mode)
    if mode not in MODE_COMMAND_HEADERS:
        raise ValueError(f"Invalid mode {mode}. Expected 0-4.")
    return MODE_QUERY + MODE_COMMAND_HEADERS[mode]


def decode_mode_response(response: bytes) -> Dict[str, Any]:
    """
    Decode the answer to `3B F0 [b0 b1]`.
      7B F0 applied a48 candidate reason -> {'kind': 'state', ...}
      7F 3B 12 to the query               -> {'kind': 'unsupported'} (stock handler, not 7716+)
      anything else                       -> {'kind': 'error', 'message': ...}
    """
    response = bytes(response)
    if len(response) >= 6 and response[0] == 0x7B and response[1] == 0xF0:
        applied, a48, candidate, reason = response[2:6]
        return {
            'kind': 'state', 'applied': applied, 'a48': a48,
            'candidate': None if candidate == 0xFF else candidate,
            'reason': reason, 'reason_name': REASON_NAMES.get(reason, f"unknown ({reason})"),
        }
    if response == bytes((0x7F, 0x3B, 0x12)):
        return {'kind': 'unsupported'}
    return {'kind': 'error', 'message': f"Unexpected answer {response.hex(' ') or '<empty>'}"}


def decode_0x6da(payload_hex: str) -> Optional[Dict[str, Any]]:
    """
    Decode one page of the 0x6DA telemetry stream; bytes 2..7 are three LE words.
      five-mode (7416/7516): byte 0 = 0xE0|ABS<<3|page; byte 1 = mode bits 0-2,
                             B1CC 3-5, A78 6, token 7; pages 0-7
      7316:                  byte 0 = 0xD0|page; byte 1 = mode bits 0-1,
                             B1CC 2-4, A78 5, token 6, ABS 7; pages 0-6
    """
    try:
        data = bytes.fromhex(payload_hex)
        if len(data) != 8:
            return None
        status = data[1]
        if data[0] & 0xF0 == 0xE0:
            page = data[0] & 0x07
            image_modes = 5
            mode = status & 0x07
            flags = {
                'selector': (status >> 3) & 0x07,
                'force_zero': bool((status >> 6) & 0x01),
                'token_ok': bool((status >> 7) & 0x01),
                'abs_braking': bool((data[0] >> 3) & 0x01),
            }
        elif data[0] & 0xF8 == 0xD0:
            page = data[0] & 0x07
            if page > 6:
                return None
            image_modes = 3
            mode = status & 0x03
            flags = {
                'selector': (status >> 2) & 0x07,
                'force_zero': bool((status >> 5) & 0x01),
                'token_ok': bool((status >> 6) & 0x01),
                'abs_braking': bool((status >> 7) & 0x01),
            }
        else:
            return None
        words = struct.unpack('<HHH', data[2:8])
        decoded = {
            'page': page,
            'image_modes': image_modes,
            'mode': mode,
            'mode_name': MODE_NAMES.get(mode, f"Unknown ({mode})"),
            **flags,
        }
        signed = lambda value: value - 0x10000 if value & 0x8000 else value
        if page == 0:
            decoded.update({
                'a72_raw': words[0], 'a72_nm': round(words[0] * 0.0625, 2),
                'a74_raw': words[1], 'a74_nm': round(words[1] * 0.0625, 2),
                'a7c_raw': words[2], 'a7c_nm': round(words[2] * 0.0625, 2),
            })
        elif page == 1:
            measured_yaw = signed(words[2])
            decoded.update({'c9e_demanded_accel': signed(words[0]),
                            'c9c_actual_accel': signed(words[1]),
                            'measured_yaw_raw': measured_yaw,
                            'measured_yaw_deg_s': round(measured_yaw / 17.87, 3)})
        elif page == 2:
            decoded.update({'b26_lateral_feedforward': signed(words[0]),
                            'bc4_curvature': words[1],
                            'bb6_computed_axle_slip': signed(words[2])})
        elif page == 3:
            decoded.update({'wheel_vl_kmh': round(words[0] * 0.005, 3),
                            'wheel_vr_kmh': round(words[1] * 0.005, 3),
                            'wheel_hl_kmh': round(words[2] * 0.005, 3)})
        elif page == 4:
            decoded.update({'wheel_hr_kmh': round(words[0] * 0.005, 3),
                            'lat_accel_measured': signed(words[1]),
                            'throttle': words[2] & 0xFF,
                            'bls': (words[2] >> 8) & 0xFF})
        elif page == 5:
            decoded.update({'hold_a7e': words[0], 'c12_high_gear_factor': words[1],
                            'target_gear_word': words[2],
                            'target_gear': words[2] & 0xFF})
        elif page == 6:
            decoded.update({'c3a_slip_energy': words[0],
                            'c26_energy_ceiling': words[1],
                            'afe_fault_ceiling': words[2]})
        elif page == 7:
            decoded.update({'b1a_yaw_feedback': signed(words[0]),
                            'b0c_current_request': words[1],
                            'ac6_slip_error': signed(words[2])})
        return decoded
    except Exception as e:
        logger.debug(f"Error decoding 0x6DA: {e}")
        return None


def decode_0x679(payload_hex: str) -> Optional[Dict[str, Any]]:
    """
    Decode 0x679 yaw/torque telemetry frame (DLC 8, little-endian):
      bytes 0-1: model yaw (s16, 17.87 counts/deg/s)
      bytes 2-3: C06 (u16, raw proactive reference)
      bytes 4-5: C22 (u16, pre-RefGen reference)
      bytes 6-7: B08 (u16, real commanded coupling torque uncensored, 0.0625 Nm/count)
    """
    try:
        data = bytes.fromhex(payload_hex)
        if len(data) != 8:
            return None

        model_yaw_raw = struct.unpack('<h', data[0:2])[0]
        c06, c22, b08_raw = struct.unpack('<HHH', data[2:8])

        return {
            'model_yaw_raw': model_yaw_raw,
            'model_yaw_deg_s': round(model_yaw_raw / 17.87, 3),
            'c06': c06,
            'c22': c22,
            'b08_raw': b08_raw,
            'b08_nm': round(b08_raw * 0.0625, 2)
        }
    except Exception as e:
        logger.debug(f"Error decoding 0x679: {e}")
        return None


class HaldexManager:
    """
    Autonomous state machine managing mode selection, telemetry, and persistence.
    """
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.haldex_cfg = self.config.get('haldex', {})

        # Settings
        self.default_mode = self.haldex_cfg.get('default_mode')
        self.persistence_file = os.path.expanduser(
            self.haldex_cfg.get('persistence_file', '~/.hudiy/haldex_mode.json')
        )

        # ZMQ Addresses
        _zmq = self.config.get('interfaces', {}).get('zmq', {})
        self.can_send_addr = _zmq.get('send_address', 'ipc:///run/rnse_control/can_send.ipc')
        self.can_stream_addr = _zmq.get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc')
        self.tp2_cmd_addr = _zmq.get('tp2_command', 'ipc:///run/rnse_control/tp2_cmd.ipc')
        self.cmd_addr = _zmq.get('haldex_command', 'ipc:///run/rnse_control/haldex_cmd.ipc')
        self.status_addr = _zmq.get('haldex_status', 'ipc:///run/rnse_control/haldex_status.ipc')

        # State Variables
        self.desired_mode = MODE_STOCK
        self.active_mode: Optional[int] = None
        # Last decoded `7B F0` answer; None until the ECU has answered one.
        self.ecu_state: Optional[Dict[str, Any]] = None
        # None until probed; False when the image answers the query with 7F 3B 12.
        self.diag_supported: Optional[bool] = None
        self.link_error: Optional[str] = None
        self.pending_set = True       # the restored mode goes out once support is confirmed
        self.quick_sets = 0           # sets since the ECU last matched desired
        self.next_action: float = 0.0
        self.last_query_time: float = 0.0
        self.last_set_time: float = 0.0
        # Last set the ECU acknowledged; the Drive Logger marks each one.
        self.last_set: Optional[Dict[str, Any]] = None
        self.last_telemetry_state: Dict[str, Any] = {}
        self.last_telemetry_yaw: Dict[str, Any] = {}
        self.last_telemetry_time: float = 0.0
        self.last_switch_time: float = 0.0
        self.inhibited: bool = False
        self.state_lock = threading.Lock()
        # Serialises everything this manager transmits against QUIESCE.
        self.tx_lock = threading.Lock()
        self.wake = threading.Event()
        self.valve_tx = 0
        self.valve_target = None
        self.valve_intent_file = os.path.expanduser(self.config.get('exhaust_valve', {}).get(
            'intent_file', '~/.hudiy/exhaust_valve_intent.json'))
        try:
            with open(self.valve_intent_file) as stream:
                target = json.load(stream).get('target')
            if type(target) is int and 0 <= target <= 100:
                self.valve_target = target
        except (OSError, ValueError, AttributeError):
            pass
        self.diagnostic_owner = "recovery-required" if os.path.exists(os.path.expanduser("~/.hudiy/haldex_recovery_required.json")) else None
        if self.diagnostic_owner:
            self.inhibited = True
        self.previous_inhibited = False

        # Determine initial mode on startup
        self._init_desired_mode()

        # Threading & Control
        self.running = True
        self.context = zmq.Context()
        self.can_push_sock: Optional[zmq.Socket] = None
        self.can_sub_sock: Optional[zmq.Socket] = None
        self.cmd_sock: Optional[zmq.Socket] = None
        self.status_pub_sock: Optional[zmq.Socket] = None

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        paths = []
        if config_path:
            paths.append(os.path.expanduser(config_path))
        paths.extend([
            os.path.expanduser('~/config.json'),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json'),
            '/etc/rnse_control/config.json'
        ])
        for p in paths:
            if os.path.isfile(p):
                try:
                    with open(p, 'r') as f:
                        logger.info(f"Loaded config from {p}")
                        return json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to parse {p}: {e}")
        return {}

    def _init_desired_mode(self):
        """
        Evaluate default_mode vs persistence_file:
        - If default_mode is specified (0-4): force that mode.
        - If default_mode is null/empty: load last mode from persistence file.
        """
        if self.default_mode is not None and str(self.default_mode).strip() != "":
            try:
                m = int(self.default_mode)
                if m in ALL_MODES:
                    self.desired_mode = m
                    logger.info(f"Startup: Using configured default_mode = {m} ({MODE_NAMES[m]})")
                    return
            except ValueError:
                pass

        # If left blank, restore from persistence file
        saved = self._read_persisted_mode()
        if saved is not None and saved in ALL_MODES:
            self.desired_mode = saved
            logger.info(f"Startup: Restored last used mode = {saved} ({MODE_NAMES[saved]})")
        else:
            self.desired_mode = MODE_STOCK
            logger.info(f"Startup: No persisted mode found, defaulting to Stock (0)")

    def _read_persisted_mode(self) -> Optional[int]:
        if not os.path.exists(self.persistence_file):
            return None
        try:
            with open(self.persistence_file, 'r') as f:
                data = json.load(f)
                return data.get('saved_mode')
        except Exception as e:
            logger.warning(f"Could not read persistence file {self.persistence_file}: {e}")
            return None

    def _save_persisted_mode(self, mode: int):
        """Save mode if default_mode is not explicitly locking it."""
        if self.default_mode is not None and str(self.default_mode).strip() != "":
            return  # Config mandates static default; do not persist

        try:
            os.makedirs(os.path.dirname(self.persistence_file), exist_ok=True)
            temp_path = f"{self.persistence_file}.tmp"
            with open(temp_path, 'w') as f:
                json.dump({
                    'saved_mode': mode,
                    'mode_name': MODE_NAMES.get(mode, "Unknown"),
                    'updated_at': time.time()
                }, f, indent=2)
            os.replace(temp_path, self.persistence_file)
            logger.debug(f"Persisted mode {mode} to {self.persistence_file}")
        except Exception as e:
            logger.error(f"Failed to persist mode {mode}: {e}")

    def _synced(self) -> bool:
        ecu = self.ecu_state
        return ecu is not None and ecu['applied'] == ecu['a48'] == self.desired_mode

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive status dictionary."""
        with self.state_lock:
            active = self.active_mode
            desired = self.desired_mode
            now = time.time()
            online = (self.last_query_time > 0
                      and now - self.last_query_time < RECONCILE_INTERVAL_S + 5.0)

            if self.diag_supported is False:
                status_str = "unsupported"
            elif not online:
                status_str = "offline"
            elif self._synced():
                status_str = "synced"
            elif self.pending_set or self.quick_sets < MAX_QUICK_SETS:
                status_str = "switching"
            else:
                status_str = "failed"

            return {
                'status': status_str,
                'desired_mode': desired,
                'desired_name': MODE_NAMES.get(desired, "Unknown"),
                'active_mode': active,
                'active_name': MODE_NAMES.get(active, "Unknown") if active is not None else None,
                'ecu': dict(self.ecu_state) if self.ecu_state else None,
                'message': self.link_error,
                'last_query_age': round(now - self.last_query_time, 2) if self.last_query_time else None,
                'token_ok': self.last_telemetry_state.get('token_ok', False),
                'b08_torque_nm': self.last_telemetry_yaw.get('b08_nm', 0.0),
                'a7c_slip_nm': self.last_telemetry_state.get('a7c_nm', 0.0),
                'a72_ceiling_nm': self.last_telemetry_state.get('a72_nm', 0.0),
                'yaw_model_counts': self.last_telemetry_yaw.get('model_yaw_raw', 0),
                'hold_a7e': self.last_telemetry_state.get('hold_a7e', 0),
                'last_telemetry_age': round(now - self.last_telemetry_time, 2) if self.last_telemetry_time else None,
                'last_switch_time': self.last_switch_time,
                'last_set': dict(self.last_set) if self.last_set else None,
                'inhibited': self.inhibited,
                'available_modes': list(ALL_MODES),
            }

    def get_valve_status(self):
        with self.state_lock:
            return {'target': self.valve_target, 'confirmed': False,
                    'status': 'sent_unconfirmed' if self.valve_target is not None else 'unknown',
                    'inhibited': self.inhibited or flashing_mode_enabled()}

    def set_valve(self, target=None):
        # No startup replay or reconciliation: the valve owns remembered intent.
        with self.tx_lock:
            if self.inhibited or flashing_mode_enabled():
                raise RuntimeError('Valve commands paused during flashing')
            with self.state_lock:
                if target is None:
                    target = 0 if self.valve_target == 100 else 100
            payload = valve_command(target, (self.valve_tx + 1) & 255)
            self.valve_tx = (self.valve_tx + 1) & 255
            # A socket owned by this command thread avoids sharing the PUSH
            # socket between command and mode workers.
            sock = self.context.socket(zmq.PUSH)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.SNDTIMEO, 1000)
            sock.connect(self.can_send_addr)
            try:
                for _ in range(3):
                    sock.send_multipart([str(CAN_ID_VALVE).encode(), payload.hex().encode()])
                    time.sleep(0.02)  # Identical TX retries are deduplicated.
            finally:
                sock.close()
            with self.state_lock:
                self.valve_target = target
            try:
                os.makedirs(os.path.dirname(self.valve_intent_file), exist_ok=True)
                temporary = self.valve_intent_file + '.tmp'
                with open(temporary, 'w') as stream:
                    json.dump({'target': target, 'confirmed': False}, stream)
                os.replace(temporary, self.valve_intent_file)
            except OSError:
                logger.exception('Could not save last sent valve intent')
            return self.get_valve_status()

    def _publish_status(self):
        """Publish status snapshot over ZMQ PUB."""
        if not self.status_pub_sock:
            return
        try:
            status = self.get_status()
            payload = json.dumps(status).encode('utf-8')
            self.status_pub_sock.send_multipart([b"HALDEX_STATUS", payload], flags=zmq.NOBLOCK)
        except Exception:
            pass

    def _tp2_command(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        sock = self.context.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.SNDTIMEO, 1000)
        sock.setsockopt(zmq.RCVTIMEO, 1500)
        try:
            sock.connect(self.tp2_cmd_addr)
            sock.send_json(msg)
            return sock.recv_json()
        except zmq.Again:
            raise RuntimeError("TP2 worker not answering")
        finally:
            sock.close()

    def _kwp(self, payload: bytes) -> bytes:
        """One KWP request to the Haldex through the TP2 worker."""
        queued = self._tp2_command({'cmd': 'KWP_REQUEST', 'module': KWP_MODULE_HALDEX,
                                    'payload': payload.hex()})
        if queued.get('status') != 'queued':
            raise RuntimeError(queued.get('message', 'TP2 worker refused the request'))
        while True:
            time.sleep(0.05)
            result = self._tp2_command({'cmd': 'KWP_RESULT', 'job': queued['job'],
                                        'timeout': KWP_TIMEOUT_S})
            if result.get('status') == 'ok':
                return bytes.fromhex(result['response'])
            if result.get('status') != 'pending':
                raise RuntimeError(result.get('message', 'KWP request failed'))

    def set_mode(self, mode: int) -> Dict[str, Any]:
        """Request a mode change; the mode worker sends it."""
        mode = int(mode)
        if mode not in ALL_MODES:
            raise ValueError(f"Invalid mode {mode}. Expected 0-4.")

        with self.state_lock:
            self.desired_mode = mode
            self._save_persisted_mode(mode)
            self.pending_set = True
            self.quick_sets = 0
            self.next_action = 0.0
            self.last_switch_time = time.time()

        self.wake.set()
        self._publish_status()
        return self.get_status()

    def cycle_mode(self) -> Dict[str, Any]:
        """Cycle through the modes, wrapping to Stock."""
        with self.state_lock:
            later = [m for m in ALL_MODES if m > self.desired_mode]
            next_mode = later[0] if later else ALL_MODES[0]
        return self.set_mode(next_mode)

    def _mode_step(self):
        """Send at most one set or query, then schedule the next one."""
        with self.state_lock:
            if self.inhibited or flashing_mode_enabled() or time.time() < self.next_action:
                return
            desired = self.desired_mode
            # Never send a set before a query proves the image has the handler:
            # older images route `3B F0 b0 b1` to the stock coding write.
            is_set = self.pending_set and self.diag_supported is True
        payload = build_mode_request(desired) if is_set else MODE_QUERY

        with self.tx_lock:
            if self.inhibited or flashing_mode_enabled():
                return
            if is_set:
                logger.info(f"Setting mode {desired} ({MODE_NAMES[desired]}): {payload.hex(' ')}")
            try:
                response = self._kwp(payload)
                error = None
            except Exception as e:
                response, error = None, str(e)

        with self.state_lock:
            now = time.time()
            if error is not None:
                if self.link_error != error:
                    logger.warning(f"Haldex mode request failed: {error}")
                self.link_error = error
                self.diag_supported = None   # re-probe once the link is back
                self.next_action = now + LINK_RETRY_S
                return
            self._apply_response(decode_mode_response(response), is_set, desired, now)
        if is_set:
            self._publish_status()

    def _apply_response(self, decoded, is_set, sent_mode, now):
        # NOTE: Must be called within state_lock
        self.link_error = None
        if decoded['kind'] == 'unsupported':
            if self.diag_supported is not False:
                logger.warning("Haldex image has no KWP mode select (7F 3B 12); "
                               "it needs 7716 or later.")
            self.diag_supported = False
            self.ecu_state = self.active_mode = None
            self.next_action = now + RECONCILE_INTERVAL_S
            return
        if decoded['kind'] == 'error':
            logger.warning(f"Haldex mode request: {decoded['message']}")
            self.link_error = decoded['message']
            self.next_action = now + RECONCILE_INTERVAL_S
            return

        self.diag_supported = True
        self.ecu_state = {k: decoded[k] for k in ('applied', 'a48', 'candidate', 'reason', 'reason_name')}
        self.active_mode = decoded['applied']
        self.last_query_time = now
        desired = self.desired_mode

        if is_set:
            # The answer is the state before the debounce; confirm shortly.
            if sent_mode == desired:
                self.pending_set = False
            self.quick_sets += 1
            self.last_set_time = now
            self.last_set = {'mode': sent_mode, 'name': MODE_NAMES[sent_mode], 'time': now}
            self.next_action = now + CONFIRM_DELAY_S
        elif self._synced():
            if self.quick_sets:
                logger.info(f"Haldex confirmed {MODE_NAMES[desired]}")
            self.pending_set = False
            self.quick_sets = 0
            self.next_action = now + RECONCILE_INTERVAL_S
        elif decoded['candidate'] == desired and decoded['reason'] in (1, 2):
            self.next_action = now + CONFIRM_DELAY_S   # still debouncing toward it
        elif (self.pending_set or self.quick_sets < MAX_QUICK_SETS
              or now - self.last_set_time >= RECONCILE_INTERVAL_S):
            if not self.pending_set:
                logger.warning(
                    f"Haldex applied {MODE_NAMES.get(decoded['applied'], decoded['applied'])}, "
                    f"want {MODE_NAMES[desired]} ({decoded['reason_name']}). Re-sending.")
            self.pending_set = True
            self.next_action = now
        else:
            self.next_action = now + RECONCILE_INTERVAL_S

    def _can_listener_worker(self):
        """Worker thread: listens to CAN stream for 0x6DA and 0x679."""
        sub = self.context.socket(zmq.SUB)
        sub.set_hwm(2000)
        try:
            sub.connect(self.can_stream_addr)
            sub.subscribe(b"CAN_6DA")
            sub.subscribe(b"CAN_0x6DA")
            sub.subscribe(b"CAN_679")
            sub.subscribe(b"CAN_0x679")
            logger.info(f"Subscribed to CAN telemetry at {self.can_stream_addr}")
        except Exception as e:
            logger.error(f"CAN sub connect error: {e}")
            return

        self.can_sub_sock = sub
        poller = zmq.Poller()
        poller.register(sub, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(200))
                if sub in events:
                    while True:
                        try:
                            topic, msg_bytes = sub.recv_multipart(flags=zmq.NOBLOCK)
                            topic_str = topic.decode('utf-8', errors='ignore')
                            msg_dict = json.loads(msg_bytes.decode('utf-8'))
                            payload_hex = msg_dict.get('data_hex', '')

                            if '6DA' in topic_str:
                                decoded = decode_0x6da(payload_hex)
                                if decoded:
                                    with self.state_lock:
                                        self.last_telemetry_state.update(decoded)
                                        self.last_telemetry_time = time.time()
                            elif '679' in topic_str:
                                decoded = decode_0x679(payload_hex)
                                if decoded:
                                    with self.state_lock:
                                        self.last_telemetry_yaw = decoded
                                        self.last_telemetry_time = time.time()
                        except zmq.Again:
                            break
            except Exception as e:
                if self.running:
                    logger.debug(f"CAN listener loop: {e}")
                    time.sleep(0.05)

        sub.close()

    def _mode_worker(self):
        """Worker thread: sends sets and reconciliation queries."""
        logger.info("Mode worker started.")
        last_publish = 0.0
        while self.running:
            self.wake.wait(0.1)
            self.wake.clear()
            try:
                self._mode_step()
            except Exception as e:
                logger.error(f"Mode worker: {e}")
            if time.time() - last_publish >= 0.5:
                last_publish = time.time()
                self._publish_status()

    def quiesce(self, token, recovery_resume=False):
        with self.tx_lock:
            if not isinstance(token, str) or not token:
                raise ValueError("Missing diagnostic owner")
            recovery_marker = os.path.exists(os.path.expanduser(
                "~/.hudiy/haldex_recovery_required.json"))
            recovery_takeover = recovery_resume is True and recovery_marker
            if (self.diagnostic_owner not in (None, token, "recovery-required")
                    and not recovery_takeover):
                raise RuntimeError("Haldex already owned")
            if self.diagnostic_owner is None:
                self.previous_inhibited = self.inhibited
            elif self.diagnostic_owner == "recovery-required" or recovery_takeover:
                logger.info("Resuming incomplete flash under diagnostic owner %s", token)
            self.diagnostic_owner = token
            self.inhibited = True
            self._drain_can_queue(token)
        return {'quiescent': True, 'owner': token}

    def _drain_can_queue(self, token):
        if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
            raise ValueError("Invalid owner token")
        endpoint = 'ipc:///run/rnse_control/haldex_barrier_' + token + '.ipc'
        reply = self.context.socket(zmq.PULL)
        reply.setsockopt(zmq.LINGER, 0)
        reply.setsockopt(zmq.RCVTIMEO, 5000)
        try:
            reply.bind(endpoint)
            self.can_push_sock.send_multipart([b'BARRIER', token.encode(), endpoint.encode()])
            response = reply.recv_json()
            if response.get('token') != token or response.get('quiescent') is not True:
                raise RuntimeError("CAN sender did not acknowledge queue drain")
        finally:
            reply.close()
            try:
                os.unlink(endpoint[len('ipc://'):])
            except OSError:
                pass

    def release(self, owner, recovery_required=False):
        with self.tx_lock:
            if owner != self.diagnostic_owner:
                raise RuntimeError("Diagnostic owner mismatch")
            if recovery_required:
                self.inhibited = True
                self.diagnostic_owner = "recovery-required"
                return
            self.inhibited = self.previous_inhibited
            self.diagnostic_owner = None
            with self.state_lock:
                # A flash resets the ECU (and may change the image): probe again.
                self.diag_supported = None
                self.pending_set = True
                self.quick_sets = 0
                self.next_action = 0.0
        self.wake.set()

    def _command_server_worker(self):
        """Worker thread: handles JSON IPC commands on haldex_cmd.ipc."""
        cmd_sock = self.context.socket(zmq.REP)
        try:
            cmd_sock.bind(self.cmd_addr)
            logger.info(f"Haldex command socket bound to {self.cmd_addr}")
        except Exception as e:
            logger.error(f"Failed to bind command socket {self.cmd_addr}: {e}")
            return

        self.cmd_sock = cmd_sock
        poller = zmq.Poller()
        poller.register(cmd_sock, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(500))
                if cmd_sock in events:
                    req_bytes = cmd_sock.recv()
                    req = json.loads(req_bytes.decode('utf-8'))
                    cmd = req.get('cmd', '').upper()

                    resp = {'status': 'ok'}
                    if cmd == 'QUIESCE':
                        resp.update(self.quiesce(
                            req.get('owner'), req.get('recovery_resume') is True))
                    elif cmd == 'RELEASE':
                        self.release(req.get('owner'), req.get('recovery_required') is True)
                    elif cmd == 'GET_VALVE_STATUS':
                        resp['data'] = self.get_valve_status()
                    elif self.diagnostic_owner and cmd not in ('STATUS', 'GET_STATUS'):
                        resp = {'status': 'error', 'message': 'Exclusive diagnostics in progress'}
                    elif cmd in ('TOGGLE_VALVE', 'SET_VALVE'):
                        if cmd == 'SET_VALVE' and 'target' not in req:
                            raise ValueError('Missing valve target')
                        resp['data'] = self.set_valve(req.get('target') if cmd == 'SET_VALVE' else None)
                    elif cmd == 'CYCLE':
                        resp['data'] = self.cycle_mode()
                    elif cmd == 'SET_MODE':
                        mode = req.get('mode', 0)
                        resp['data'] = self.set_mode(mode)
                    elif cmd == 'GET_STATUS' or cmd == 'STATUS':
                        resp['data'] = self.get_status()
                    elif cmd in ('SET_INHIBIT', 'INHIBIT', 'PAUSE'):
                        val = req.get('inhibit', True) if cmd == 'SET_INHIBIT' else True
                        with self.state_lock:
                            self.inhibited = bool(val)
                        resp['inhibited'] = self.inhibited
                        resp['data'] = self.get_status()
                        logger.info(f"HaldexManager inhibited: {self.inhibited}")
                        self._publish_status()
                    elif cmd in ('RESUME', 'UNINHIBIT'):
                        with self.state_lock:
                            self.inhibited = False
                        resp['inhibited'] = False
                        resp['data'] = self.get_status()
                        logger.info("HaldexManager uninhibited/resumed.")
                        self._publish_status()
                    else:
                        resp = {'status': 'error', 'message': f"Unknown command '{cmd}'"}

                    cmd_sock.send_json(resp)
            except Exception as e:
                if self.running:
                    try:
                        cmd_sock.send_json({"status": "error", "message": str(e)})
                    except Exception:
                        pass
                    logger.debug(f"Command worker loop: {e}")
                    time.sleep(0.05)

        cmd_sock.close()

    def start(self):
        """Start manager threads."""
        logger.info("Starting HaldexManager...")

        # The CAN PUSH socket carries valve commands and the QUIESCE barrier.
        try:
            self.can_push_sock = self.context.socket(zmq.PUSH)
            self.can_push_sock.connect(self.can_send_addr)
            logger.info(f"Connected to CAN send socket at {self.can_send_addr}")
        except Exception as e:
            logger.error(f"Failed to connect to {self.can_send_addr}: {e}")

        # Initialize Status Publisher socket
        try:
            self.status_pub_sock = self.context.socket(zmq.PUB)
            self.status_pub_sock.bind(self.status_addr)
            logger.info(f"Status publisher bound to {self.status_addr}")
        except Exception as e:
            logger.warning(f"Could not bind status socket {self.status_addr}: {e}")

        logger.info(f"Startup mode {self.desired_mode} ({MODE_NAMES[self.desired_mode]}); "
                    "sent once the Haldex answers the mode query.")
        for target, name in ((self._can_listener_worker, "Haldex-CAN-Listener"),
                             (self._mode_worker, "Haldex-Mode"),
                             (self._command_server_worker, "Haldex-Command")):
            threading.Thread(target=target, daemon=True, name=name).start()

    def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping HaldexManager...")
        self.running = False
        self.wake.set()
        if self.can_push_sock:
            self.can_push_sock.close()
        if self.status_pub_sock:
            self.status_pub_sock.close()
        self.context.term()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (Haldex) %(message)s'
    )
    manager = HaldexManager()

    def handle_sig(sig, frame):
        manager.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    manager.start()
    while manager.running:
        time.sleep(1)


if __name__ == '__main__':
    main()
