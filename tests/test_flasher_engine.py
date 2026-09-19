"""Offline protocol/state regression tests. No sockets or CAN devices opened."""
import hashlib
import struct
import unittest
from unittest.mock import patch
from flasher import engine as shared_engine
from flasher.controllers.haldex_gen4 import protocol as engine
from flasher.controllers.haldex_gen4 import patches as artifacts
from flasher.controllers.haldex_gen4.patches import APP_BLOCKS, HOOK_BYTES, ROUTINE_BYTES, SIMULATOR_PATCHES
from flasher.controllers.haldex_gen4.patches import patch_firmware
from flasher.controllers.haldex_gen4.patches import layer1


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
    def can_clear(self, _flags): pass
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
    def session(self, session): self.calls.append(('session', session))
    def sa_seed(self, sub):
        self.calls.append(('seed', sub))
        return b'bad!' if self.bad_seed else engine.LOADER_SEED
    def sa_key(self, *args):
        self.calls.append(('key', args[0]))
        return b'\x67\x02\x34'
    def request_download(self, *args): return 145
    def routine(self, *args): self.calls.append(('routine', args))
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
        self.calls.append(('ident', ident))
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

    def test_flash_status_counter_attempts_and_date_layout(self):
        ident = b'\x5a\x9b0BR907554A  7016' + bytes(10) + b'HaldexRE'
        status = b'\x5a\x9c\x00\xc0\xb6\x00' + bytes.fromhex('20260918') + b'\x00\x01'
        info = shared_engine.parse_vag_identification(ident, status)
        self.assertEqual(info['flash_attempts'], 0xC0)
        self.assertEqual(info['flash_counter'], 0xB6)
        self.assertEqual(info['flash_date'], '2026-09-18')
        self.assertEqual(info['flash_tool_id'], 1)

    def test_default_transport_trace_is_quiet_and_verbose_is_opt_in(self):
        for debug in (False, True):
            flasher = engine.HaldexFlasher(device=Device(), debug=debug)
            with patch.object(engine, 'TP20Transport', return_value=Session(0x764)) as factory:
                flasher.reconnect_tp()
            self.assertEqual(factory.call_args.kwargs['debug'], debug)

    def test_system_date_is_written_into_erase_stamp(self):
        with patch.object(shared_engine, 'system_flash_date', return_value='2031-12-09'):
            result = self.run_flash()
        erase_args = next(value for kind, value in FakeKwp.calls
                          if kind == 'routine' and value[0] == engine.RC_ERASE)
        self.assertEqual(erase_args[1][-6:], bytes.fromhex('203112090001'))
        self.assertEqual(result['flash_date'], '2031-12-09')

    def test_invalid_preflight(self):
        for kwargs in ({'start_addr': 0x30001, 'end_addr': 0x3ffff}, {'file_off': -1},
                       {'simulator_mode': 1}, {'start_addr': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                artifacts.prepare_image(self.image, **kwargs)
        for data in (self.image[:0x10000], self.image+b'0', bytes(0x50000)):
            with self.assertRaises(ValueError): artifacts.prepare_image(data)

    def test_simulator_mode_is_applied_in_memory_to_selected_sectors(self):
        source = bytearray(self.image)
        for address, stock, _bench, _description in SIMULATOR_PATCHES:
            source[address:address + len(stock)] = stock
        for start, size in APP_BLOCKS:
            struct.pack_into('<H', source, start + size - 2,
                             layer1(source, start, size))
        before = bytes(source)
        result = artifacts.prepare_image(source, simulator_mode=True)
        self.assertTrue(result['metadata']['simulator_mode'])
        self.assertTrue(result['metadata']['bench_only'])
        self.assertEqual(result['metadata']['patch_result']['sim_patches_applied'], 6)
        self.assertEqual(bytes(source), before)
        partial = artifacts.prepare_image(source, 0x30000, 0x3ffff,
                                          simulator_mode=True)
        expected = sum(0x30000 <= address <= 0x3ffff
                       for address, _stock, _bench, _description in SIMULATOR_PATCHES)
        self.assertEqual(partial['metadata']['patch_result']['sim_patches_applied'],
                         expected)
        self.assertTrue(partial['metadata']['simulator_mode'])
        self.assertTrue(partial['metadata']['bench_only'])
        self.assertEqual(bytes(source), before)

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

    def test_simulator_manifest_rejects_unknown_firmware_outside_selection(self):
        data = bytearray(self.image)
        for address, stock, _bench, _description in SIMULATOR_PATCHES:
            data[address:address + len(stock)] = stock
        data[SIMULATOR_PATCHES[0][0]] ^= 1
        before = bytes(data)
        with self.assertRaisesRegex(ValueError, "simulator-mode patch manifest"):
            artifacts.prepare_image(data, 0x30000, 0x3FFFF, simulator_mode=True)
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

    def run_flash(self, *, recovery=False):
        self.device = Device()
        self.flasher = engine.HaldexFlasher(device=self.device, log_cb=lambda _: None)
        sessions = ([Session(0x765), Session(0x764)] if recovery else
                    [Session(0x764), Session(0x765), Session(0x764)])
        with patch.object(engine, 'Kwp', FakeKwp), patch.object(self.flasher, 'reconnect_tp',
                side_effect=sessions):
            return self.flasher.flash_binary(self.image, recovery=recovery)

    def test_normal_flash_identifies_and_gates_before_programming(self):
        result = self.run_flash()
        self.assertEqual(result['source_controller']['software_part_number'], '0BR907554A')
        self.assertEqual([value for kind, value in FakeKwp.calls if kind == 'ident'],
                         [0x9B, 0x9C, 0x9B, 0x9C])
        self.assertEqual([value for kind, value in FakeKwp.calls if kind == 'session'],
                         [engine.SESSION_EXTENDED, engine.SESSION_PROGRAMMING])

    def test_recovery_starts_in_loader_without_application_identification_or_sessions(self):
        result = self.run_flash(recovery=True)
        self.assertTrue(result['recovery_mode'])
        self.assertNotIn('source_controller', result)
        self.assertEqual([value for kind, value in FakeKwp.calls if kind == 'ident'],
                         [0x9B, 0x9C])
        self.assertFalse(any(kind == 'session' for kind, _value in FakeKwp.calls))

    def test_recovery_refuses_an_application_channel(self):
        flasher = engine.HaldexFlasher(device=Device(), log_cb=lambda _: None)
        with patch.object(engine, 'Kwp', FakeKwp), \
                patch.object(flasher, 'reconnect_tp', return_value=Session(0x764)), \
                self.assertRaisesRegex(RuntimeError, 'did not enter loader'):
            flasher.flash_binary(self.image, recovery=True)
        self.assertFalse(flasher.destructive_started)

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
        self.assertEqual(sum(kind == 'transfer' for kind, _value in FakeKwp.calls), 1)
        self.assertTrue(self.flasher.recovery_required)
        self.assertTrue(self.device.closed)

    def test_bad_loader_seed_stops_before_erase(self):
        FakeKwp.bad_seed = True
        with self.assertRaisesRegex(RuntimeError, 'loader challenge'): self.run_flash()
        self.assertFalse(self.flasher.destructive_started)
        self.assertTrue(self.device.closed)

    def test_normal_mode_redirects_an_already_bootloadered_module_to_recovery(self):
        with patch.object(engine.HaldexFlasher, '_ident', return_value={
                'in_bootloader': True, 'sw_version': '6716', 'part_number': '0BR907554A',
                'flash_status': 0}):
            with self.assertRaisesRegex(RuntimeError, 'retry with --recovery'):
                self.run_flash()
        self.assertFalse(self.flasher.destructive_started)
        self.assertFalse(self.flasher.recovery_required)

    def test_normal_flash_rejects_wrong_identified_family_before_programming(self):
        with patch.object(engine.HaldexFlasher, '_ident', return_value={
                'in_bootloader': False, 'firmware_revision': '2501',
                'software_part_number': '1K0909144E', 'flash_status': 0}):
            with self.assertRaisesRegex(RuntimeError, 'not a recognized Haldex'):
                self.run_flash()
        self.assertFalse(self.flasher.destructive_started)
        self.assertFalse(any(kind == 'session' for kind, _value in FakeKwp.calls))

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
