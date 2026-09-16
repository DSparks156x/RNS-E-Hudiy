"""Offline protocol/state regression tests. No sockets or CAN devices opened."""
import hashlib
import struct
import unittest
from unittest.mock import patch
from flasher import haldex_flasher as engine
from flasher import artifacts
from flasher.haldex_patcher import APP_BLOCKS, HOOK_BYTES, ROUTINE_BYTES
from flasher.haldex_patcher import patch_firmware
from flasher.haldex_patcher import layer1


def fixture():
    data = bytearray(0x50000)
    data[0x2027c:0x2027c+len(ROUTINE_BYTES)] = ROUTINE_BYTES
    data[0x20364:0x20364+len(HOOK_BYTES)] = HOOK_BYTES
    for start, size in APP_BLOCKS:
        struct.pack_into('<H', data, start+size-2, layer1(data, start, size))
    return bytes(data)


class TP:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []
    def send(self, request):
        self.sent.append(request)
    def recv(self):
        result = next(self.replies)
        if isinstance(result, Exception):
            raise result
        return result


class ProtocolTests(unittest.TestCase):
    def test_bad_positive_and_echo_and_lengths(self):
        for req, reply in [(b'\x36abcd', b'\x00'), (b'\x36abcd', b''),
                           (b'\x31\xc4', b'\x71\xc5'), (b'\x33\xc4', b'\x73\xc4'),
                           (b'\x27\x01', b'\x67\x01'), (b'\x27\x02', b'\x67\x02\x00')]:
            with self.subTest(reply=reply), self.assertRaises(RuntimeError):
                engine.Kwp(TP([reply]), debug=False).raw(req)

    def test_pending_waits_without_resend(self):
        tp = TP([b'\x7f\x36\x78', b'\x76'])
        self.assertEqual(engine.Kwp(tp, debug=False).transfer(b'abcd'), b'\x76')
        self.assertEqual(len(tp.sent), 1)

    def test_pending_bounded(self):
        with self.assertRaises(TimeoutError):
            engine.Kwp(TP([b'\x7f\x36\x78']*32), debug=False).transfer(b'abcd')

    def test_transfer_timeout_not_retried(self):
        tp = TP([TimeoutError('ambiguous')])
        with self.assertRaises(TimeoutError):
            engine.Kwp(tp, debug=False).transfer(b'abcd')
        self.assertEqual(len(tp.sent), 1)

    @patch.object(engine.time, 'sleep')
    def test_busy_only_retries_reads(self, _):
        tp = TP([b'\x7f\x33\x21', b'\x73\xc4\x00'])
        engine.Kwp(tp, debug=False).routine_result(0xc4)
        self.assertEqual(len(tp.sent), 2)
        tp = TP([b'\x7f\x36\x21'])
        with self.assertRaises(RuntimeError):
            engine.Kwp(tp, debug=False).transfer(b'abcd')
        self.assertEqual(len(tp.sent), 1)


class Device:
    closed = False
    def close(self): self.closed = True


class Session:
    def __init__(self, addr): self.tx_addr = addr
    def disconnect(self): pass


class FakeKwp:
    fail_commit = False
    fail_transfer = False
    bad_seed = False
    calls = []
    def __init__(self, *args, **kwargs): pass
    def sa_seed(self, sub): return b'bad!' if self.bad_seed else engine.LOADER_SEED
    def sa_key(self, *args): return b'\x67\x02\x34'
    def request_download(self, *args): return 145
    def routine(self, *args): pass
    def routine_result(self, rid): return bytes([0x73, rid, 0])
    def transfer(self, data):
        self.calls.append(('transfer', len(data)))
        if self.fail_transfer: raise TimeoutError('ambiguous transfer')
    def transfer_exit(self): pass
    def raw(self, request):
        self.calls.append(('raw', request[0]))
        if self.fail_commit and request == b'\x20': raise TimeoutError('commit timeout')
        return bytes([request[0]+0x40])
    def read_ecu_ident(self, ident):
        if ident == 0x9b:
            return b'\x5a\x9b0BR907554A  6716' + bytes(10) + b'HaldexRE'
        return b'\x5a\x9c' + bytes(18)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.image = fixture()
        FakeKwp.calls = []
        FakeKwp.fail_commit = FakeKwp.fail_transfer = FakeKwp.bad_seed = False

    def test_offline_full_app(self):
        with patch.object(engine, 'SocketCANDevice', side_effect=AssertionError('hardware forbidden')):
            result = engine.HaldexFlasher().flash_binary(self.image, dry_run=True)
        self.assertEqual(result['size'], 0x38000)
        self.assertEqual(len(result['sectors']), 4)
        self.assertEqual(result['patches'], [])
        self.assertFalse(result['boot_verified'])

    def test_invalid_preflight(self):
        for kwargs in ({'start_addr': 0x30001, 'end_addr': 0x3ffff}, {'file_off': -1},
                       {'simulator_mode': True}, {'start_addr': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                artifacts.prepare_image(self.image, **kwargs)
        for data in (self.image[:0x10000], self.image+b'0', bytes(0x50000)):
            with self.assertRaises(ValueError): artifacts.prepare_image(data)

    def test_checksums_are_automatically_repaired_without_changing_source(self):
        data = bytearray(self.image)
        data[0x18010] ^= 1
        before = bytes(data)
        result = artifacts.prepare_image(data)
        self.assertEqual(bytes(data), before)
        self.assertNotEqual(result['metadata']['original_sha256'], result['metadata']['prepared_sha256'])
        for start, size in APP_BLOCKS:
            self.assertEqual(struct.unpack_from('<H', result['image'], start+size-2)[0], layer1(result['image'], start, size))

    def test_any_checksum_valid_build_without_recovery_hooks_is_accepted(self):
        data = bytearray(self.image)
        data[0x2027c:0x2027c+len(ROUTINE_BYTES)] = b'\xff' * len(ROUTINE_BYTES)
        data[0x20364:0x20364+len(HOOK_BYTES)] = bytes.fromhex('da026e030dff')
        data[0x24554:0x24558] = b'3016'
        for start, size in APP_BLOCKS:
            struct.pack_into('<H', data, start+size-2, layer1(data, start, size))
        result = artifacts.prepare_image(data)
        self.assertEqual(result['image'][0x2027c:0x2027c+len(ROUTINE_BYTES)], ROUTINE_BYTES)
        self.assertEqual(result['image'][0x20364:0x20364+len(HOOK_BYTES)], HOOK_BYTES)
        self.assertEqual(result['metadata']['original_sha256'], hashlib.sha256(data).hexdigest())

    def test_all_contiguous_sector_selections_match_exact_source_bytes(self):
        for first in range(4):
            for last in range(first, 4):
                start = APP_BLOCKS[first][0]
                end = sum(APP_BLOCKS[last])-1
                result = artifacts.prepare_image(self.image, start, end)
                self.assertEqual(result['region'], self.image[start:end+1])
                self.assertEqual(len(result['metadata']['sectors']), last-first+1)
                self.assertEqual(result['metadata']['checksum'], sum(self.image[start:end+1]) & 0xffff)

    def test_other_software_versions_can_complete(self):
        with patch.object(engine.HaldexFlasher, '_ident', return_value={
                'in_bootloader': False, 'sw_version': '3016', 'part_number': '0BR907554A',
                'flash_status': 0}):
            self.assertTrue(self.run_flash()['boot_verified'])

    def test_unknown_patch_preimage_never_mutated(self):
        data = bytearray(self.image)
        data[0x20364] ^= 1
        before = bytes(data)
        with self.assertRaises(ValueError): patch_firmware(data)
        self.assertEqual(bytes(data), before)

    def test_patcher_failure_stops_before_can(self):
        with patch.object(artifacts, 'patch_firmware', side_effect=ValueError('patch failure')), patch.object(engine, 'SocketCANDevice') as device:
            with self.assertRaisesRegex(ValueError, 'patch failure'):
                engine.HaldexFlasher().flash_binary(self.image)
            device.assert_not_called()

    def test_calibration_patches_only_selected_sector(self):
        data = bytearray(self.image)
        data[0x20364:0x20364+len(HOOK_BYTES)] = bytes.fromhex('da026e030dff')
        data[0x30010] ^= 1
        result = artifacts.prepare_image(data, 0x30000, 0x3ffff)
        self.assertEqual(result['region'], result['image'][0x30000:0x40000])
        self.assertTrue(all(p['transferred'] for p in result['metadata']['patches']))
        self.assertEqual(result['image'][:0x30000], bytes(data[:0x30000]))
        self.assertEqual(result['image'][0x40000:], bytes(data[0x40000:]))
        self.assertTrue(any(p['transferred'] for p in result['metadata']['patches']))
        self.assertEqual(result['metadata']['checksum'], sum(result['region']) & 0xffff)

    def test_erase_poll_timeout_only_repeats_result_query(self):
        flasher = engine.HaldexFlasher()
        old = unittest.mock.Mock()
        old.routine_result.side_effect = TimeoutError('loader closed erase session')
        new = unittest.mock.Mock()
        new.routine_result.return_value = b'\x73\xc4\x00'
        with patch.object(engine, 'Kwp', return_value=new), patch.object(flasher, 'reconnect_tp'):
            self.assertIs(flasher._routine_done(old, 0xc4), new)
        old.routine.assert_not_called()
        new.routine.assert_not_called()

    def run_flash(self):
        self.device = Device()
        self.flasher = engine.HaldexFlasher(device=self.device, log_cb=lambda _: None)
        with patch.object(engine, 'Kwp', FakeKwp), patch.object(self.flasher, 'reconnect_tp',
                side_effect=[Session(0x765), Session(0x764)]):
            return self.flasher.flash_binary(self.image)

    def test_success_needs_fresh_application_and_cleanup(self):
        result = self.run_flash()
        self.assertTrue(result['boot_verified'])
        self.assertTrue(result['checksum_verified'])
        self.assertTrue(self.device.closed)
        self.assertEqual(sum(v for k,v in FakeKwp.calls if k == 'transfer'), 0x38000)
        self.assertLessEqual(max(v for k,v in FakeKwp.calls if k == 'transfer'), 144)
        self.assertEqual(result['application']['sw_version'], '6716')

    def test_commit_failure_attempts_stop_and_never_succeeds(self):
        FakeKwp.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, 'commit outcome remains ambiguous'):
            self.run_flash()
        self.assertIn(('raw', 0x82), FakeKwp.calls)
        self.assertTrue(self.device.closed)
        self.assertTrue(self.flasher.recovery_required)

    def test_transfer_failure_requires_recovery_and_closes(self):
        FakeKwp.fail_transfer = True
        with self.assertRaises(TimeoutError): self.run_flash()
        self.assertEqual(len(FakeKwp.calls), 1)
        self.assertTrue(self.flasher.recovery_required)
        self.assertTrue(self.device.closed)

    def test_bad_loader_seed_stops_before_erase(self):
        FakeKwp.bad_seed = True
        with self.assertRaisesRegex(RuntimeError, 'loader challenge'): self.run_flash()
        self.assertFalse(self.flasher.destructive_started)
        self.assertTrue(self.device.closed)

    def test_fresh_loader_does_not_count_as_application(self):
        with patch.object(engine.HaldexFlasher, '_ident', return_value={
                'in_bootloader': True, 'sw_version': '6716', 'part_number': '0BR907554A',
                'flash_status': 0}):
            with self.assertRaisesRegex(RuntimeError, 'Fresh expected application'):
                self.run_flash()
        self.assertTrue(self.flasher.recovery_required)

    def test_cancellation_during_write_requires_recovery(self):
        original = FakeKwp.transfer
        def cancel_after_first(fake, data):
            original(fake, data)
            self.flasher.abort_requested = True
        with patch.object(FakeKwp, 'transfer', cancel_after_first):
            with self.assertRaisesRegex(RuntimeError, 'can be flashed again'):
                self.run_flash()
        self.assertTrue(self.flasher.recovery_required)
        self.assertTrue(self.device.closed)

    def test_identification_failure_closes_device(self):
        device = Device()
        flasher = engine.HaldexFlasher(device=device)
        with patch.object(flasher, 'reconnect_tp', side_effect=RuntimeError('no connection')):
            with self.assertRaises(RuntimeError): flasher.read_ecu_info()
        self.assertTrue(device.closed)


if __name__ == '__main__':
    unittest.main()
