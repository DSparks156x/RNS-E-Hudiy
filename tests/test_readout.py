"""Offline regression tests; no hardware access."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from flasher import readout
from flasher.haldex_flash import ApplicationReader, ProtocolError
from test_flasher_engine import fixture, TP
from flasher.haldex_flash import (ApplicationReader, ProtocolError,
                                    upload_request, application_checksums)


class Device:
    def __init__(self, **kw): self.closed = False
    def can_clear(self): pass
    def close(self): self.closed = True


class Endpoint:
    tx_addr = 0x764
    def __init__(self, image):
        self.image = image
        self.requests = []
        self.offset = self.remaining = 0
        self.closed = False
        self.transfer_count = 0
        self.fail_at = None
        self.bad_key = False
    def send(self, request):
        self.requests.append(request)
        self.request = request
    def recv(self):
        request = self.request
        if request == b'\x1a\x9b':
            return b'\x5a\x9b0BR907554A  6716' + bytes(10) + b'Haldex'
        if request[0] == 0x10:
            return bytes([0x50, request[1]])
        if request == b'\x27\x03': return b'\x67\x03\x00\x00\x00\x01'
        if request[:2] == b'\x27\x04': return b'\x67\x04' + (b'\x00' if self.bad_key else b'\x34')
        if request[0] == 0x35:
            self.offset = int.from_bytes(request[1:4], 'big')
            self.remaining = int.from_bytes(request[5:8], 'big')
            return bytes([0x75, min(200, self.remaining)])
        if request == b'\x36':
            self.transfer_count += 1
            if self.transfer_count == self.fail_at:
                raise TimeoutError('lost upload response')
            size = min(200, self.remaining)
            response = b'\x76' + self.image[self.offset:self.offset+size]
            self.offset += size
            self.remaining -= size
            return response
        if request == b'\x37': return b'\x77'
        if request == b'\x20': return b'\x60'
        raise AssertionError('Unexpected/mutating request: ' + request.hex())
    def disconnect(self): self.closed = True


class ReadoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = fixture()
        self.device = Device()
        self.endpoint = Endpoint(self.image)
        self.operation = readout.HaldexReadout()
        self.bus = patch.object(readout, 'SocketCANDevice', return_value=self.device)
        self.tp = patch.object(readout, 'TP20Transport', return_value=self.endpoint)
        self.bus.start(); self.tp.start()
        self.addCleanup(self.bus.stop); self.addCleanup(self.tp.stop)
    def run_capture(self):
        return self.operation.readout(self.temp.name, 0x30000, 0x3ffff)
    def test_complete_autonamed_capture_has_correct_padding_and_checksums(self):
        report = self.run_capture()
        self.assertEqual(report['status'], 'ok')
        self.assertTrue(report['filename'].startswith('0BR907554A_6716_segments6_'))
        path = Path(self.temp.name) / report['capture_id'] / report['filename']
        data = path.read_bytes()
        self.assertEqual(len(data), 0x50000)
        self.assertEqual(data[:0x30000], b'\xff' * 0x30000)
        self.assertEqual(data[0x30000:0x40000], self.image[0x30000:0x40000])
        self.assertEqual(data[0x40000:], b'\xff' * 0x10000)
        self.assertTrue(report['checksums_verified'])
        self.assertFalse(report['firmware_writes'])
        self.assertTrue(self.device.closed and self.endpoint.closed)
        self.assertFalse(any(req[0] in (0x34, 0x31, 0x82, 0x11) for req in self.endpoint.requests))
        self.assertTrue(all(req == b'\x36' for req in self.endpoint.requests if req[0] == 0x36))
    def test_transfer_timeout_retains_partial_coverage_and_is_not_retried(self):
        self.endpoint.fail_at = 23  # First 4096-byte window needs 21 requests.
        with self.assertRaises(TimeoutError): self.run_capture()
        report = self.operation.last_result
        self.assertEqual(self.endpoint.transfer_count, 23)
        self.assertEqual(report['saved_ranges']['pass1.bin']['end_exclusive'], 0x31000)
        directory = Path(self.temp.name) / report['capture_id']
        saved = json.loads((directory/'report.json').read_text())
        self.assertEqual(saved['status'], 'failed')
        self.assertTrue((directory/'pass1.bin').exists())
        self.assertTrue(self.device.closed)
    def test_cancel_preserves_capture_and_cleans_session(self):
        self.operation.progress_cb = lambda stage, percent, *args: setattr(self.operation, 'abort_requested', percent > 0)
        with self.assertRaises(readout.ReadoutCancelled): self.run_capture()
        self.assertEqual(self.operation.last_result['status'], 'cancelled')
        self.assertIn(b'\x20', self.endpoint.requests)
        self.assertTrue(self.device.closed)
    def test_bad_security_response_stops_before_upload(self):
        self.endpoint.bad_key = True
        with self.assertRaises(ProtocolError): self.run_capture()
        self.assertFalse(any(req[0] == 0x35 for req in self.endpoint.requests))
        self.assertTrue(self.device.closed)
    def test_invalid_bounds_never_open_can(self):
        with patch.object(readout, 'SocketCANDevice') as device:
            with self.assertRaises(ValueError):
                self.operation.readout(self.temp.name, 0x30001, 0x3ffff)
            device.assert_not_called()
    def test_filename_segments_and_path_sanitization(self):
        name = readout.automatic_filename({'part_number': '../part:foo', 'sw_version': '../3016'},
            0x18000, 0x4ffff, datetime(2026, 9, 16, tzinfo=timezone.utc))
        self.assertEqual(name, 'part_foo_3016_segments4-7_20260916T000000000000Z.bin')

    def test_pending_waits_without_repeating_upload_transfer(self):
        tp = TP([b'\x75\x20', b'\x7f\x36\x78', b'\x76'+bytes(32), b'\x77'])
        self.assertEqual(ApplicationReader(tp).read_window(0x30000, 32), bytes(32))
        self.assertEqual(tp.sent.count(b'\x36'), 1)

    def test_pending_is_bounded(self):
        with self.assertRaisesRegex(ProtocolError, 'deadline'):
            ApplicationReader(TP([b'\x7f\x1a\x78']*32)).identify()

    def test_cleanup_failure_cannot_produce_successful_download(self):
        original = self.endpoint.recv
        def receive():
            if self.endpoint.request == b'\x20':
                raise TimeoutError('session exit unconfirmed')
            return original()
        self.endpoint.recv = receive
        with self.assertRaises(ProtocolError): self.run_capture()
        self.assertEqual(self.operation.last_result['status'], 'requires_attention')
        self.assertTrue(self.device.closed)


class ScriptedTransport:
    def __init__(self, pairs):
        self.pairs = list(pairs)
        self.requests = []
        self.pending = None

    def send(self, request):
        self.requests.append(request)
        if not self.pairs:
            raise AssertionError('Unexpected request '+request.hex())
        expected, response = self.pairs.pop(0)
        if expected != request:
            raise AssertionError(f'Expected {expected.hex()}, got {request.hex()}')
        self.pending = response

    def recv(self):
        if isinstance(self.pending, Exception):
            raise self.pending
        return self.pending


class ReaderTests(unittest.TestCase):

    def test_upload_wire_format_and_short_final_block(self):
        block = bytes(range(200))
        t = ScriptedTransport([
            (bytes.fromhex('35030000000000c9'), bytes.fromhex('75c8')),
            (b'\x36', b'\x76'+block), (b'\x36', b'\x76\xa5'),
            (b'\x37', b'\x77'),
        ])
        r = ApplicationReader(t)
        self.assertEqual(r.read_window(0x30000, 201), block+b'\xa5')
        self.assertFalse(r.upload_active)
        self.assertEqual(t.pairs, [])


    def test_short_response_rejected(self):
        t = ScriptedTransport([(upload_request(0x30000, 32), b'\x75\x20'),
                               (b'\x36', b'\x76\x00')])
        with self.assertRaises(ProtocolError):
            ApplicationReader(t).read_window(0x30000, 32)


    def test_rejects_all_mutating_flash_commands(self):
        t = ScriptedTransport([])
        r = ApplicationReader(t)
        for command in ('1085', '1086', '34', '31c4', '31c5', '361122', '82', '11'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                r.exchange(bytes.fromhex(command), b'')
        self.assertEqual(t.requests, [])


    def test_sector_checksum_includes_payload_but_excludes_stored_word(self):
        data = bytearray(0x8000)
        data[:4] = bytes.fromhex('01003412')
        data[-2:] = (0xedca).to_bytes(2, 'little')
        self.assertTrue(application_checksums(data, 0x18000)[0]['valid'])
        data[100] ^= 1
        self.assertFalse(application_checksums(data, 0x18000)[0]['valid'])


if __name__ == "__main__":
    unittest.main()
