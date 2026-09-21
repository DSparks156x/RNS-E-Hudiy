"""Hudiy progress, naming and persistence around the shared application reader."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
import uuid

from .controllers.haldex_gen4.protocol import ApplicationReader, ProtocolError, capture
from .controllers.haldex_gen4.patches import selected_blocks, application_checksums
from .controllers.pq_eps.protocol import (
    EPS_IMAGE_SIZE, MAX_READ_MEMORY_BLOCK, PQEPSReader, capture_eps,
    validate_eps_range,
)
from .socketcan_device import SocketCANDevice
from .vag_protocols.tp2 import TP20Transport


def validate_selection(start_addr, end_addr):
    if type(start_addr) is not int or type(end_addr) is not int:
        raise ValueError('Sector bounds must be integers')
    return selected_blocks(start_addr, end_addr)


def identification(payload):
    if len(payload) < 26:
        raise ProtocolError('Truncated Controller identification')
    part = payload[:12].decode('ascii', errors='strict').strip()
    version = payload[12:16].decode('ascii', errors='strict').strip()
    if not part or not version:
        raise ProtocolError('Controller identification lacks part number or software version')
    return {'part_number': part, 'sw_version': version, 'raw_9b': (b'\x5a\x9b' + payload).hex()}


def automatic_filename(info, start, end, timestamp):
    blocks = validate_selection(start, end)
    indices = {0x18000: 4, 0x20000: 5, 0x30000: 6, 0x40000: 7}
    first, last = indices[blocks[0][0]], indices[blocks[-1][0]]
    segments = str(first) if first == last else f'{first}-{last}'
    def safe(value):
        return re.sub(r'[^A-Za-z0-9_-]+', '_', value).strip('_')[:48] or 'unknown'
    return f"{safe(info['part_number'])}_{safe(info['sw_version'])}_segments{segments}_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}.bin"


class ReadoutCancelled(ProtocolError):
    pass


class HaldexReadout:
    """Owns one device; callers acquire the shared diagnostic/Flashing Mode lease."""
    def __init__(self, channel='can0', progress_cb=None, log_cb=None):
        self.channel = channel
        self.progress_cb = progress_cb or (lambda *args: None)
        self.log_cb = log_cb or (lambda message: None)
        self.abort_requested = False
        self.device = self.transport = self.reader = None
        self.last_result = {}
        self.recovery_required = False  # This flow never erases or writes firmware.
        self.destructive_started = False
        self._cleaning = False

    def close(self):
        transport, device = self.transport, self.device
        self.transport = self.device = None
        try:
            if transport is not None:
                transport.disconnect()
        finally:
            if device is not None:
                device.close()

    def _cancel(self):
        if self.abort_requested and not self._cleaning:
            raise ReadoutCancelled('Readout cancelled; saved partial capture retained')

    def readout(self, output_root, start_addr=0x18000, end_addr=0x4ffff):
        blocks = validate_selection(start_addr, end_addr)
        self._cancel()
        started = datetime.now(timezone.utc)
        directory = Path(output_root) / uuid.uuid4().hex
        directory.mkdir(parents=True, exist_ok=False)
        report = self.last_result = {
            'capture_id': directory.name, 'status': 'incomplete',
            'started_utc': started.isoformat(), 'firmware_writes': False,
            'recovery_required': False, 'start_addr': start_addr, 'end_addr': end_addr,
            'segments': [{'start': a, 'size': size} for a, size in blocks],
            'requested_length': end_addr-start_addr+1, 'received_length': 0, 'captured_length': 0, 'size': 0x50000,
            'padding_byte': 255, 'unread_ranges_are_padding': True,
            'saved_ranges': {}, 'cleanup_errors': [],
        }
        report_path = directory / 'report.json'
        def persist():
            temporary = directory / 'report.tmp'
            with temporary.open('w', encoding='utf-8') as handle:
                json.dump(report, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, report_path)
        persist()
        failure = None
        with (directory / 'diagnostic.jsonl').open('x', encoding='utf-8', buffering=1) as log:
            def record(event):
                if event.get('event') == 'request':
                    self._cancel()
                log.write(json.dumps({'monotonic': time.monotonic(), **event}) + '\n')
                self.log_cb(json.dumps(event))
                if event.get('event') == 'block_received':
                    report['received_length'] = event['end_exclusive'] - start_addr
                    progress(1, report['received_length'], end_addr-start_addr+1)
                if event.get('event') == 'window_saved':
                    report['captured_length'] = event['address'] + event['length'] - start_addr
                    report['saved_ranges']['pass1.bin'] = {
                        'start': start_addr, 'end_exclusive': event['address']+event['length']}
                    persist()
            try:
                self.progress_cb('READING', 0, 'Connecting for firmware readout', 0, 0)
                self.device = SocketCANDevice(channel=self.channel)
                self.device.can_clear()
                self.transport = TP20Transport(self.device, module=0x0a, timeout=2.0, debug=True,
                    log_fn=lambda message: record({'event': 'tp20', 'message': message}))
                if self.transport.tx_addr != 0x764:
                    raise ProtocolError('Readout requires the running application; no loader commands sent')
                self.transport.keepalive_after_response = True
                self.reader = ApplicationReader(self.transport, record)
                before = self.reader.identify()
                report['identification'] = info = identification(before)
                report['filename'] = automatic_filename(info, start_addr, end_addr, started)
                persist()
                self.reader.enter()
                transfer_started = time.monotonic()
                def progress(pass_index, done, total):
                    self._cancel()
                    speed = done / max(time.monotonic()-transfer_started, 0.001)
                    self.progress_cb('READING', 95*done/total,
                        f'Received {done}/{total} bytes; saved {report["captured_length"]} bytes', speed, (total-done)/speed)
                # No ambiguous TransferData retry. A failed window is preserved
                # as partial evidence; a subsequent read starts a fresh operation.
                report['captures'] = capture(self.reader, directory, start_addr,
                    end_addr-start_addr+1, 1, 4096, record, progress, recover=None)
                data = (directory / 'pass1.bin').read_bytes()[start_addr:end_addr+1]
                rows = report['application_checksums'] = application_checksums(data, start_addr)
                if not rows or not all(row['complete'] and row['valid'] for row in rows):
                    raise ProtocolError('Readout sector checksum validation failed; raw capture retained')
                report['checksums_verified'] = True
            except Exception as exc:
                failure = exc
                report.update(status='cancelled' if isinstance(exc, ReadoutCancelled) else 'failed', error=str(exc))
                record({'event': 'failure', 'error': str(exc)})
            finally:
                self._cleaning = True
                if self.reader is not None:
                    try:
                        report['cleanup_errors'].extend(self.reader.leave())
                        after = self.reader.identify()
                        report['identification_after'] = identification(after)
                        if 'identification' in report and after != before:
                            report['cleanup_errors'].append('Controller identification changed during readout')
                    except Exception as exc:
                        report['cleanup_errors'].append(str(exc))
                try:
                    self.close()
                except Exception as exc:
                    report['cleanup_errors'].append('device close: ' + str(exc))
                self._cleaning = False
                if report['cleanup_errors']:
                    report['status'] = 'requires_attention'
                    failure = failure or ProtocolError('; '.join(report['cleanup_errors']))
                if failure is None:
                    path = directory / report['filename']
                    (directory / 'pass1.bin').rename(path)
                    report['captures'][0]['path'] = path.name
                    report['saved_ranges'][path.name] = report['saved_ranges'].pop('pass1.bin')
                    report['status'] = 'ok'
                report['finished_utc'] = datetime.now(timezone.utc).isoformat()
                persist()
                log.flush()
                os.fsync(log.fileno())
        if failure is not None:
            raise failure
        self.progress_cb('READOUT_COMPLETE', 100, 'Firmware readout saved; captured sector checksums verified', 0, 0)
        return report


def eps_automatic_filename(info, start, end, timestamp):
    def safe(value):
        return re.sub(r'[^A-Za-z0-9_-]+', '_', str(value)).strip('_')[:48] or 'unknown'
    return (f"{safe(info.get('part_number'))}_{safe(info.get('sw_version'))}_"
            f"eps_{start:05x}-{end:05x}_{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}.bin")


class PQEPSReadout:
    """Experimental non-mutating conventional-KWP EPS readout."""

    def __init__(self, channel='can0', progress_cb=None, log_cb=None):
        self.channel = channel
        self.progress_cb = progress_cb or (lambda *args: None)
        self.log_cb = log_cb or (lambda message: None)
        self.abort_requested = False
        self.device = self.transport = self.reader = None
        self.last_result = {}
        self.recovery_required = False
        self.destructive_started = False
        self._cleaning = False

    def close(self):
        transport, device = self.transport, self.device
        self.transport = self.device = None
        try:
            if transport is not None:
                transport.disconnect()
        finally:
            if device is not None:
                device.close()

    def _cancel(self):
        if self.abort_requested and not self._cleaning:
            raise ReadoutCancelled('EPS readout cancelled')

    def readout(self, output_root, start_addr=0x5E000, end_addr=0x5EFFF):
        validate_eps_range(start_addr, end_addr - start_addr + 1)
        self._cancel()
        started = datetime.now(timezone.utc)
        directory = Path(output_root) / uuid.uuid4().hex
        directory.mkdir(parents=True, exist_ok=False)
        report = self.last_result = {
            'capture_id': directory.name, 'status': 'incomplete',
            'started_utc': started.isoformat(), 'firmware_writes': False,
            'controller': 'pq-eps', 'experimental': True,
            'recovery_required': False, 'start_addr': start_addr,
            'end_addr': end_addr, 'requested_length': end_addr - start_addr + 1,
            'size': EPS_IMAGE_SIZE, 'padding_byte': 255,
            'unread_ranges_are_padding': True, 'cleanup_errors': [],
        }
        report_path = directory / 'report.json'

        def persist():
            temporary = directory / 'report.tmp'
            with temporary.open('w', encoding='utf-8') as handle:
                json.dump(report, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, report_path)

        persist()
        failure = None
        with (directory / 'diagnostic.jsonl').open('x', encoding='utf-8', buffering=1) as log:
            def record(event):
                if event.get('event') == 'request':
                    self._cancel()
                log.write(json.dumps({'monotonic': time.monotonic(), **event}) + '\n')
                self.log_cb(json.dumps(event))

            try:
                self.progress_cb('EPS_READING', 0, 'Connecting for experimental EPS readout', 0, 0)
                self.device = SocketCANDevice(channel=self.channel)
                self.device.can_clear()
                self.transport = TP20Transport(
                    self.device, module=0x09, timeout=2.0, debug=True,
                    log_fn=lambda message: record({'event': 'tp20', 'message': message}))
                self.transport.keepalive_after_response = True
                self.reader = PQEPSReader(self.transport, record=record)
                report['identification'] = info = self.reader.identification()
                part = info.get('software_part_number', info.get('part_number', '')).upper()
                if not part.startswith(('1K0909144', '8J0909144')):
                    raise ProtocolError(f'Unexpected EPS identification: {part or "<empty>"}')
                report['filename'] = eps_automatic_filename(info, start_addr, end_addr, started)
                candidates = [address for address in (start_addr, 0xA000, 0x5D000, 0x5E000)
                              if start_addr <= address <= end_addr - 15]
                probe = self.reader.probe(list(dict.fromkeys(candidates)), requested='auto')
                report['probe'] = probe
                method = probe['method']
                chunk = MAX_READ_MEMORY_BLOCK if method == 'read-memory' else 0x1000
                transfer_started = time.monotonic()

                def progress(done, total):
                    self._cancel()
                    speed = done / max(time.monotonic() - transfer_started, 0.001)
                    self.progress_cb('EPS_READING', 95 * done / total,
                                     f'Attempted {done}/{total} bytes', speed,
                                     (total - done) / max(speed, 0.001))

                report['capture'] = capture_eps(
                    self.reader, directory, start_addr, end_addr - start_addr + 1,
                    method, chunk=chunk, record=record, progress=progress)
                if report['capture']['readable_bytes'] == 0:
                    raise ProtocolError('EPS rejected every requested read range')
            except Exception as exc:
                failure = exc
                report.update(status='cancelled' if isinstance(exc, ReadoutCancelled) else 'failed',
                              error=str(exc))
                record({'event': 'failure', 'error': str(exc)})
            finally:
                self._cleaning = True
                if self.reader is not None:
                    try:
                        report['cleanup_errors'].extend(self.reader.leave())
                    except Exception as exc:
                        report['cleanup_errors'].append(str(exc))
                try:
                    self.close()
                except Exception as exc:
                    report['cleanup_errors'].append('device close: ' + str(exc))
                self._cleaning = False
                if report['cleanup_errors']:
                    report['status'] = 'requires_attention'
                    failure = failure or ProtocolError('; '.join(report['cleanup_errors']))
                if failure is None:
                    source = directory / 'kwp_readout.bin'
                    target = directory / report['filename']
                    source.rename(target)
                    report['capture']['path'] = target.name
                    report['status'] = 'ok'
                    report['partial'] = report['capture']['unreadable_bytes'] != 0
                report['finished_utc'] = datetime.now(timezone.utc).isoformat()
                persist()
                log.flush()
                os.fsync(log.fileno())
        if failure is not None:
            raise failure
        detail = ('EPS readout saved with unreadable ranges padded FF' if report['partial']
                  else 'EPS readout saved')
        self.progress_cb('READOUT_COMPLETE', 100, detail, 0, 0)
        return report
