"""Offline regression tests; no hardware access."""
import ast
import logging
import os
from pathlib import Path
import threading
import types
import unittest
from unittest.mock import Mock, patch
import uuid
import json
import sys
import tempfile
from unittest.mock import Mock, MagicMock, patch
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def definitions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    for n in nodes:
        n.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        def response(cmd, **kw):
            self.commands.append((cmd, kw))
            return {'status': 'ok', 'quiescent': True, 'owner': kw.get('owner')}
        self.ns = definitions('hudiy_dataview/app.py', {'DiagnosticOwnership'}, {
            'uuid': uuid, 'os': os, '_recovery_file': '__nonexistent_test_marker__',
            '_diagnostic_lock': threading.Lock(), 'logger': logging.getLogger('test'),
            'worker': types.SimpleNamespace(send_command=response),
            'send_haldex_command': lambda data, **kw: response(
                data['cmd'], **{key: value for key, value in data.items() if key != 'cmd'})})

    def test_info_and_flash_cannot_overlap(self):
        first = self.ns['DiagnosticOwnership'](); second = self.ns['DiagnosticOwnership']()
        first.acquire()
        with self.assertRaisesRegex(RuntimeError, 'Another diagnostic'):
            second.acquire()
        first.release()
        second.acquire(); second.release()
        self.assertFalse(self.ns['_diagnostic_lock'].locked())

    def test_unacknowledged_closure_never_grants_ownership(self):
        self.ns['worker'].send_command = lambda *a, **kw: {'status': 'ok'}
        owner = self.ns['DiagnosticOwnership']()
        with self.assertRaisesRegex(RuntimeError, 'TP2 worker did not acknowledge'):
            owner.acquire()
        self.assertFalse(owner.acquired)
        self.assertFalse(self.ns['_diagnostic_lock'].locked())
        self.assertTrue(any(c == 'RELEASE' for c, _ in self.commands))

    def test_recovery_retains_service_inhibits(self):
        owner = self.ns['DiagnosticOwnership'](); owner.acquire(); owner.release(True)
        releases = [kwargs for command, kwargs in self.commands if command == 'RELEASE']
        self.assertEqual(len(releases), 2)
        self.assertTrue(all(item['recovery_required'] is True for item in releases))
        self.assertFalse(self.ns['_diagnostic_lock'].locked())

    def test_previous_settings_never_overwritten(self):
        owner = self.ns['DiagnosticOwnership'](); owner.acquire(); owner.release()
        self.assertEqual([c for c, _ in self.commands], ['QUIESCE', 'QUIESCE', 'RELEASE', 'RELEASE'])

    def test_persistent_recovery_blocks_before_commands(self):
        with patch('os.path.exists', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'incomplete flash'):
                self.ns['DiagnosticOwnership']().acquire()
        self.assertEqual(self.commands, [])

    def test_persistent_marker_allows_flash_to_resume(self):
        with patch('os.path.exists', return_value=True):
            owner = self.ns['DiagnosticOwnership']()
            owner.acquire(allow_incomplete_flash=True)
            owner.release(recovery_required=True)
        self.assertEqual([c for c, _ in self.commands],
                         ['QUIESCE', 'QUIESCE', 'RELEASE', 'RELEASE'])
        quiesce = [kwargs for command, kwargs in self.commands if command == 'QUIESCE']
        releases = [kwargs for command, kwargs in self.commands if command == 'RELEASE']
        self.assertTrue(all(item['recovery_resume'] is True for item in quiesce))
        self.assertTrue(all(item['recovery_required'] is True for item in releases))


class RequestTests(unittest.TestCase):
    def test_malformed_requests_never_set_busy(self):
        for payload in (None, [], {}, {'filepath': '/tmp/a.bin'}, {'artifact_id': 'f'*64, 'dry_run': 'false'}, {'artifact_id': 4}, {'artifact_id': 'f'*64, 'start_addr': 0}):
            with self.subTest(payload=payload):
                emitted = []
                ns = definitions('hudiy_dataview/app.py', {'handle_start_haldex_flash'}, {
                    'emit': lambda *args: emitted.append(args), '_flasher_running': False,
                    '_validated_artifacts': lambda: {}, '_flasher_lock': threading.Lock(),
                    'os': os, '_recovery_file': '__nonexistent_test_marker__'})
                ns['handle_start_haldex_flash'](payload)
                self.assertFalse(ns['_flasher_running'])
                self.assertEqual(emitted[-1][0], 'haldex_flash_error')

    def test_dryrun_does_not_acquire_or_change_services(self):
        events = []
        engine = Mock()
        engine.flash_binary.return_value = {'status': 'validated', 'dry_run': True}
        factory = Mock(return_value=engine)
        owner = Mock()
        class InlineThread:
            def __init__(self, target, **kw): self.target = target
            def start(self): self.target()
        ns = definitions('hudiy_dataview/app.py', {'handle_start_haldex_flash'}, {
            'emit': lambda *a: events.append(a), 'socketio': types.SimpleNamespace(emit=lambda *a: events.append(a)),
            '_validated_artifacts': lambda: {'f'*64: {'_path': 'image.bin'}},
            '_flasher_lock': threading.Lock(), '_flasher_running': False, '_cfg': {},
            'threading': types.SimpleNamespace(Thread=InlineThread), 'HaldexFlasher': factory,
            'DiagnosticOwnership': lambda: owner, '_recovery_marker': Mock(), 'FlashOperationLog': Mock(), 'logger': logging.getLogger('test'),
            'json': __import__('json')})
        ns['handle_start_haldex_flash']({'artifact_id': 'f'*64, 'dry_run': True})
        owner.acquire.assert_not_called()
        ns['_recovery_marker'].assert_not_called()
        engine.close.assert_called_once()
        self.assertFalse(ns['_flasher_running'])
        self.assertIn('haldex_flash_complete', [e[0] for e in events])

    def test_cancel_endpoint_cannot_interrupt_flash(self):
        active = Mock(abort_requested=False)
        events = []
        ns = definitions('hudiy_dataview/app.py', {'handle_cancel_haldex_flash'}, {
            '_flasher_lock': threading.Lock(), '_active_flasher': active,
            '_active_operation': 'flash', 'emit': lambda *args: events.append(args)})
        ns['handle_cancel_haldex_flash']()
        self.assertFalse(active.abort_requested)
        self.assertEqual(events, [])

        ns['_active_operation'] = 'readout'
        ns['handle_cancel_haldex_flash']()
        self.assertTrue(active.abort_requested)
        self.assertEqual(events[-1][0], 'haldex_flash_cancel_requested')


class ServiceQuiescenceTests(unittest.TestCase):
    def test_tp2_recovery_sentinel_can_be_claimed_by_flash(self):
        ns = definitions('tp2/tp2_worker.py', {'TP2Service'}, {
            'logger': logging.getLogger('test'), 'threading': threading,
            'time': types.SimpleNamespace(sleep=lambda _: None)})
        service = ns['TP2Service'].__new__(ns['TP2Service'])
        service.lock = threading.Lock()
        service.diagnostic_owner = 'recovery-required'
        service.quiescent = threading.Event()
        token = 'a' * 32
        with service.lock:
            self.assertIn(service.diagnostic_owner, (None, token, 'recovery-required'))
            service.diagnostic_owner = token
            service.quiescent.clear()
        self.assertEqual(service.diagnostic_owner, token)

    def test_worker_acknowledges_only_after_protocol_close(self):
        log = []
        shutdown = threading.Event()
        class Ack:
            def set(self):
                log.append('ack')
                shutdown.set()
        class NoThread:
            def __init__(self, **kw): pass
            def start(self): pass
        ns = definitions('tp2/tp2_worker.py', {'TP2Service'}, {
            'logger': logging.getLogger('test'), 'threading': types.SimpleNamespace(Thread=NoThread),
            'time': types.SimpleNamespace(sleep=lambda _: None)})
        service = ns['TP2Service'].__new__(ns['TP2Service'])
        service.shutdown_event = shutdown
        service.lock = threading.Lock()
        service.running = True
        service.diagnostic_owner = 'owner'
        service.quiescent = Ack()
        service.process_ignition = lambda: None
        proto = types.SimpleNamespace(close=lambda: log.append('close'))
        service.sessions = {1: {'protocol': proto, 'connected': True}}
        service.run()
        self.assertEqual(log[:2], ['close', 'ack'])
        self.assertFalse(service.sessions[1]['connected'])


class ManagerRaceTests(unittest.TestCase):
    def manager(self):
        import typing
        ns = definitions('rns-e_can/haldex_manager.py', {'HaldexManager'}, {
            'Optional': typing.Optional, 'Dict': typing.Dict, 'Any': typing.Any,
            'logger': logging.getLogger('test'), 'os': os})
        manager = ns['HaldexManager'].__new__(ns['HaldexManager'])
        manager.burst_lock = threading.Lock()
        manager.inhibited = False
        manager.diagnostic_owner = None
        manager.previous_inhibited = False
        return manager

    def test_inflight_burst_and_sender_barrier_must_finish_before_ack(self):
        manager = self.manager()
        burst_started = threading.Event(); finish_burst = threading.Event()
        barrier_started = threading.Event(); finish_barrier = threading.Event()
        acknowledged = threading.Event(); sends = []
        def burst(mode):
            if manager.inhibited:
                return
            burst_started.set()
            self.assertTrue(finish_burst.wait(2))
            sends.append(mode)
        def barrier(token):
            barrier_started.set()
            self.assertTrue(finish_barrier.wait(2))
        manager._send_mode_burst_locked = burst
        manager._drain_mode_queue = barrier
        sender = threading.Thread(target=lambda: manager.send_mode_burst(1))
        sender.start(); self.assertTrue(burst_started.wait(2))
        pause = threading.Thread(target=lambda: (manager.quiesce('a'*32), acknowledged.set()))
        pause.start()
        self.assertFalse(acknowledged.wait(0.03))
        self.assertFalse(barrier_started.is_set())
        finish_burst.set(); self.assertTrue(barrier_started.wait(2))
        self.assertFalse(acknowledged.is_set())
        finish_barrier.set(); sender.join(2); pause.join(2)
        self.assertTrue(acknowledged.is_set())
        manager.send_mode_burst(2)
        self.assertEqual(sends, [1])

    def test_failed_barrier_retains_inhibition_without_ack(self):
        manager = self.manager()
        manager._drain_mode_queue = Mock(side_effect=TimeoutError('barrier timeout'))
        with self.assertRaises(TimeoutError):
            manager.quiesce('a'*32)
        self.assertTrue(manager.inhibited)
        self.assertEqual(manager.diagnostic_owner, 'a'*32)

    def test_recovery_sentinel_can_be_claimed_by_flash(self):
        manager = self.manager()
        manager.diagnostic_owner = 'recovery-required'
        manager.inhibited = True
        manager._drain_mode_queue = Mock()
        token = 'a' * 32
        self.assertEqual(manager.quiesce(token), {'quiescent': True, 'owner': token})
        self.assertEqual(manager.diagnostic_owner, token)
        self.assertTrue(manager.inhibited)

    def test_recovery_marker_allows_explicit_stale_owner_takeover(self):
        manager = self.manager()
        manager.diagnostic_owner = 'stale-operation-token'
        manager.inhibited = True
        manager._drain_mode_queue = Mock()
        token = 'b' * 32
        with patch('os.path.exists', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'already owned'):
                manager.quiesce(token)
            self.assertEqual(
                manager.quiesce(token, recovery_resume=True),
                {'quiescent': True, 'owner': token})
        self.assertEqual(manager.diagnostic_owner, token)
        self.assertTrue(manager.inhibited)


class InfoRaceTests(unittest.TestCase):
    setUp = OwnershipTests.setUp
    def test_info_handler_cannot_release_active_flash_lease(self):
        flash_owner = self.ns['DiagnosticOwnership'](); flash_owner.acquire()
        before = list(self.commands)
        events = []
        flasher_factory = Mock()
        ns = definitions('hudiy_dataview/app.py', {'handle_get_ecu_flash_info'}, {
            'DiagnosticOwnership': self.ns['DiagnosticOwnership'], 'HaldexFlasher': flasher_factory,
            'socketio': types.SimpleNamespace(start_background_task=lambda target: target(),
                                             emit=lambda *a: events.append(a)), '_cfg': {}})
        ns['handle_get_ecu_flash_info']()
        self.assertEqual(self.commands, before)
        flasher_factory.assert_not_called()
        self.assertFalse(events[0][1]['connected'])
        self.assertTrue(self.ns['_diagnostic_lock'].locked())
        flash_owner.release()


class ReadoutBackendTests(unittest.TestCase):
    def setup_handler(self, failure=False):
        self.events = []
        self.reader = Mock()
        self.reader.readout.return_value = {'status': 'ok', 'capture_id': 'a'*32, 'filename': 'part_fw_segments_date.bin'}
        self.reader.last_result = {'status': 'failed', 'capture_id': 'b'*32}
        if failure:
            self.reader.readout.side_effect = RuntimeError('interrupted')
        self.owner = Mock()
        self.traffic = MagicMock()
        class InlineThread:
            def __init__(self, target, **kwargs): self.target = target
            def start(self): self.target()
        self.module = types.ModuleType('flasher.readout')
        self.module.HaldexReadout = Mock(return_value=self.reader)
        def validate(start, end):
            if type(start) is not int or type(end) is not int or start != 0x18000 or end != 0x4ffff:
                raise ValueError('Invalid sectors')
        self.module.validate_selection = validate
        self.ns = definitions('hudiy_dataview/app.py', {'handle_start_haldex_readout'}, {
            '_flasher_running': False, '_flasher_lock': threading.Lock(), '_cfg': {}, '_readout_root': 'readouts',
            'emit': lambda *args: self.events.append(args), 'socketio': types.SimpleNamespace(emit=lambda *args: self.events.append(args)),
            'threading': types.SimpleNamespace(Thread=InlineThread), 'DiagnosticOwnership': lambda: self.owner,
            'FlashOperationLog': Mock(), 'flashing_operation': lambda: self.traffic, 'set_flashing_mode': Mock(),
            'logger': logging.getLogger('test')})

    def run_handler(self, data):
        with patch.dict(sys.modules, {'flasher.readout': self.module}):
            self.ns['handle_start_haldex_readout'](data)

    def test_rejects_client_paths_and_invalid_bounds_before_ownership(self):
        for data in (None, {'output_root': '/tmp'}, {'start_addr': True}, {'start_addr': 3}):
            self.setup_handler()
            self.run_handler(data)
            self.owner.acquire.assert_not_called()
            self.assertFalse(self.ns['_flasher_running'])
            self.assertEqual(self.events[-1][0], 'haldex_readout_error')

    def test_success_inhibits_and_exposes_capture_download(self):
        self.setup_handler()
        self.run_handler({})
        self.owner.acquire.assert_called_once()
        self.ns['set_flashing_mode'].assert_called_once_with(True)
        self.reader.close.assert_called_once()
        self.owner.release.assert_called_once_with()
        self.assertFalse(self.ns['_flasher_running'])
        self.assertIsNone(self.ns['_active_flasher'])
        self.assertEqual(self.events[-1][0], 'haldex_readout_complete')
        self.assertEqual(self.events[-1][1]['download_url'], '/haldex/readouts/'+'a'*32+'/image')
        self.assertFalse(self.events[-1][1]['recovery_required'])

    def test_failure_keeps_report_without_download_or_destructive_recovery(self):
        self.setup_handler(failure=True)
        self.run_handler({})
        event, result = self.events[-1]
        self.assertEqual(event, 'haldex_readout_error')
        self.assertIn('report_url', result)
        self.assertNotIn('download_url', result)
        self.assertFalse(result['recovery_required'])
        self.assertFalse(self.ns['_flasher_running'])

    def test_busy_excludes_simultaneous_operations(self):
        self.setup_handler()
        self.ns['_flasher_running'] = True
        self.run_handler({})
        self.owner.acquire.assert_not_called()
        self.assertFalse(self.events[-1][1]['stopped'])

    def test_cleanup_failure_clears_busy_and_reports_attention(self):
        self.setup_handler()
        self.reader.close.side_effect = RuntimeError('close failed')
        self.run_handler({})
        self.assertEqual(self.events[-1][0], 'haldex_readout_error')
        self.assertTrue(self.events[-1][1]['cleanup_attention'])
        self.assertFalse(self.ns['_flasher_running'])
        self.owner.release.assert_called_once()

    def test_download_only_server_capture_and_successful_image(self):
        class Missing(Exception): pass
        def abort(code): raise Missing(code)
        with tempfile.TemporaryDirectory() as root:
            capture = Path(root) / ('a'*32)
            capture.mkdir()
            report = capture / 'report.json'
            report.write_text(json.dumps({'status': 'ok', 'filename': 'part_fw_date.bin'}))
            (capture / 'part_fw_date.bin').write_bytes(b'data')
            ns = definitions('hudiy_dataview/app.py', {'_readout_download'}, {
                '_readout_root': root, 'os': os, 'json': json, 'abort': abort,
                'send_file': lambda path, **kw: (path, kw)})
            self.assertEqual(ns['_readout_download']('a'*32)[1]['download_name'], 'part_fw_date.bin')
            for identifier in ('../x', 'A'*32, 'b'*32):
                with self.assertRaises(Missing): ns['_readout_download'](identifier)
            for filename in ('../secret', 'C:\\secret', '/secret'):
                report.write_text(json.dumps({'status': 'ok', 'filename': filename}))
                with self.assertRaises(Missing): ns['_readout_download']('a'*32)
            report.write_text(json.dumps({'status': 'failed', 'filename': 'part_fw_date.bin'}))
            with self.assertRaises(Missing): ns['_readout_download']('a'*32)
            self.assertTrue(ns['_readout_download']('a'*32, report=True)[0].endswith('report.json'))


class FirmwareStorageTests(unittest.TestCase):
    def test_recursive_discovery_excludes_incomplete_capture_files(self):
        ns = definitions('hudiy_dataview/app.py', {'firmware_paths'}, {'os': os, 'json': json})
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for folder, status in [('readouts/complete', 'ok'), ('readouts/failed', 'failed')]:
                directory = root / folder
                directory.mkdir(parents=True)
                (directory / 'image.bin').write_bytes(b'image')
                (directory / 'pass1.bin').write_bytes(b'partial')
                (directory / 'report.json').write_text(json.dumps({'status': status, 'filename': 'image.bin'}))
            (root / 'custom').mkdir()
            (root / 'custom' / 'tune.bin').write_bytes(b'tune')
            found = {Path(name).as_posix() for name, path in ns['firmware_paths'](str(root))}
            self.assertEqual(found, {'readouts/complete/image.bin', 'custom/tune.bin'})


class InstalledLayoutTests(unittest.TestCase):

    def test_installer_staged_package_import_and_update_preservation(self):
        source = (ROOT / 'install.sh').read_text()
        self.assertIn('install_folder "flasher" || exit 1', source)
        self.assertIn('install_folder "vag_protocols" || exit 1', source)
        sparse_paths = re.search(r'^SPARSE_PATHS=\((.*?)\)$', source, re.MULTILINE).group(1).split()
        installed_folders = re.findall(r'^install_folder "([^"]+)" \|\| exit 1$', source, re.MULTILINE)
        self.assertTrue(set(installed_folders).issubset(sparse_paths))
        self.assertNotIn('rm -rf "$REAL_HOME/tools"', source)
        self.assertIn('python3-can', source)
        function = re.search(r'(?ms)^install_folder\(\) \{.*?^\}', source).group()
        bash = (Path('C:/Program Files/Git/bin/bash.exe') if os.name == 'nt'
                else Path(shutil.which('bash') or '/bin/bash'))
        if not bash.exists():
            self.skipTest('bash required to exercise installer copy function')
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            home = stage / 'home'
            (home / 'tools').mkdir(parents=True)
            (home / 'tools' / 'keep.txt').write_text('user tool')
            script = stage / 'stage.sh'
            script.write_text('set -eu\n' + function + '\nmkdir -p "$REAL_HOME/tools"\n'
                              'install_folder "vag_protocols"\n'
                              'install_folder "flasher"\ninstall_folder "flasher"\n', newline='\n')
            environment = dict(os.environ, REAL_HOME=home.as_posix(), TEMP_DIR=ROOT.as_posix())
            subprocess.run([str(bash), str(script)], env=environment, check=True)
            self.assertEqual((home / 'tools' / 'keep.txt').read_text(), 'user tool')
            # Isolated process, unrelated cwd: repository import fallbacks cannot hide missing files.
            check = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                     'import flasher; from flasher import HaldexFlasher; from flasher.readout import HaldexReadout; from flasher.traffic import transmission_guard; '
                     'assert Path(flasher.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()); '
                     'print(flasher.__file__)')
            subprocess.run([sys.executable, '-I', '-B', '-c', check, str(home)],
                           cwd=stage, check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
