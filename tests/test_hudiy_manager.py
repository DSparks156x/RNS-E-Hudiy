"""Management boundaries tested without changing a service or installed config."""
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hudiy_manager.config_store import ConfigStore, ConfigError, ConflictError, MAX_CONFIG_BYTES, parse_document
from hudiy_manager.service_control import ServiceController, ServiceError, BusyError

try:
    from hudiy_manager.app import create_app
except ModuleNotFoundError as error:
    if error.name != 'flask':
        raise
    create_app = None


class TemporaryConfigCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.home = self.root / 'home'
        self.project.mkdir()
        self.home.mkdir()
        self.document = {'interfaces': {'can': {'infotainment': 'can0'}, 'zmq': {}},
                         'features': {'custom': 'untouched'}, 'future': {'hello': [1, False, None]}}
        self.original = json.dumps(self.document).encode()
        self.path = self.project / 'config.json'
        self.path.write_bytes(self.original)
        self.store = ConfigStore(self.project, self.home)

    def tearDown(self):
        self.temp.cleanup()


class StoreTests(TemporaryConfigCase):
    def test_saved_replacement_keeps_unknowns_backups_exact_original_and_changes_revision(self):
        os.chmod(self.path, 0o640)
        original_mode = stat.S_IMODE(self.path.stat().st_mode)
        current = self.store.read('rnse')
        changed = {**current['document'], 'branch': 'testing'}
        result = self.store.save('rnse', changed, current['revision'])
        self.assertNotEqual(result['revision'], current['revision'])
        self.assertEqual(Path(result['backup']).read_bytes(), self.original)
        self.assertEqual(self.store.read('rnse')['document'], changed)
        self.assertEqual(changed['future'], self.document['future'])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), original_mode)
        self.assertIn('hudiy_dataview', result['affected_services'])

    def test_stale_and_missing_revisions_cannot_overwrite(self):
        revision = self.store.read('rnse')['revision']
        self.path.write_text(json.dumps({**self.document, 'branch': 'external'}))
        for stale in (revision, None, '', 'missing'):
            with self.subTest(revision=stale), self.assertRaises(ConflictError):
                self.store.save('rnse', self.document, stale)
        self.assertEqual(json.loads(self.path.read_text())['branch'], 'external')
        self.assertFalse((self.home / 'confbackup').exists())

    def test_parallel_stores_only_one_save_for_same_revision(self):
        revision = self.store.read('rnse')['revision']
        second = ConfigStore(self.project, self.home)
        barrier = threading.Barrier(2)
        results = []
        def save(store, branch):
            barrier.wait()
            try:
                results.append(store.save('rnse', {**self.document, 'branch': branch}, revision))
            except ConflictError:
                results.append('conflict')
        threads = [threading.Thread(target=save, args=(store, str(index)))
                   for index, store in enumerate((self.store, second))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results.count('conflict'), 1)
        self.assertEqual(len(list((self.home / 'confbackup').rglob('config.json'))), 1)

    def test_failed_publication_keeps_original_and_backup_and_cleans_temporary(self):
        revision = self.store.read('rnse')['revision']
        with patch('hudiy_manager.config_store.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.store.save('rnse', {**self.document, 'branch': 'new'}, revision)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(len(list((self.home / 'confbackup').rglob('config.json'))), 1)
        self.assertFalse(list(self.project.glob('.management-*')))

    def test_named_targets_and_structural_validation(self):
        with self.assertRaises(ConfigError):
            self.store.read('../../outside.json')
        bad = [{}, [], {'interfaces': []}, {'interfaces': {}, 'diagnostics': {'enabled': 'yes'}},
               {'interfaces': {}, 'rnse': {'auto_brightness': {'enabled': True, 'day_brightness': 11}}},
               {'interfaces': {}, 'rnse': {'auto_brightness': {'night_brightness': True}}},
               {'interfaces': {}, 'custom': float('nan')}]
        revision = self.store.read('rnse')['revision']
        for document in bad:
            with self.subTest(document=document), self.assertRaises(ConfigError):
                self.store.save('rnse', document, revision)
        with self.assertRaises(ConfigError):
            self.store.save('hudiy-applications', {'applications': [1]}, 'missing')
        with self.assertRaises(ConfigError):
            self.store.save('hudiy-menu', {'categories': []}, 'missing')
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_missing_named_hudiy_file_can_be_created_only_with_missing_revision(self):
        current = self.store.read('hudiy-applications')
        self.assertFalse(current['exists'])
        self.assertEqual(current['revision'], 'missing')
        document = {'applications': [{'action': 'hudiy_manager', 'url': 'http://localhost:5004'}], 'future': 3}
        result = self.store.save('hudiy-applications', document, current['revision'])
        self.assertIsNone(result['backup'])
        self.assertEqual(self.store.read('hudiy-applications')['document'], document)
        self.assertEqual(result['affected_services'], [])

    def test_brightness_protocol_bounds_require_both_levels_when_enabled(self):
        revision = self.store.read('rnse')['revision']
        for day in (-1, 11, 1.5, True, None):
            document = {**self.document, 'rnse': {'auto_brightness': {
                'enabled': True, 'day_brightness': day, 'night_brightness': 3}}}
            with self.subTest(day=day), self.assertRaises(ConfigError):
                self.store.save('rnse', document, revision)
        valid = {**self.document, 'rnse': {'auto_brightness': {
            'enabled': True, 'day_brightness': 10, 'night_brightness': 0}}}
        result = self.store.save('rnse', valid, revision)
        self.assertEqual(self.store.read('rnse')['document'], valid)
        disabled = {**self.document, 'rnse': {'auto_brightness': {
            'enabled': False, 'day_brightness': None, 'night_brightness': None}}}
        self.store.save('rnse', disabled, result['revision'])

    def test_tv_simulation_payload_validation_and_normalization(self):
        revision = self.store.read('rnse')['revision']
        for payload in ('', 'A', '0x01', 'GG', '001122334455667788', 'AA-BB',
                        '0 9', 'AABB C', 'AA  BB CC DD EE FF 00 11 22', 12):
            document = {**self.document, 'features': {'tv_simulation': {'payload': payload}}}
            with self.subTest(payload=payload), self.assertRaises(ConfigError):
                self.store.save('rnse', document, revision)
        for payload, expected in (('aa', 'AA'), (' aa bb 0c ', 'AABB0C'),
                                  ('0912302020202020', '0912302020202020')):
            document = {**self.document, 'features': {'tv_simulation': {'payload': payload}}}
            result = self.store.save('rnse', document, revision)
            self.assertEqual(self.store.read('rnse')['document']['features']['tv_simulation']['payload'], expected)
            revision = result['revision']

    def test_invalid_json_duplicate_nonfinite_size_and_depth(self):
        for content in (b'{broken', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xff',
                        b' ' * (MAX_CONFIG_BYTES + 1)):
            with self.subTest(content=content[:20]), self.assertRaises(ConfigError):
                parse_document(content)
        nested = 0
        for _ in range(70):
            nested = {'nested': nested}
        with self.assertRaises(ConfigError):
            self.store.save('rnse', {**self.document, 'deep': nested}, self.store.read('rnse')['revision'])

    def make_link(self, target, link, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest(f'OS does not permit test symbolic links: {error}')

    def test_symbolic_link_target_cannot_read_or_replace_external_file(self):
        external = self.root / 'outside.json'
        external.write_bytes(self.original)
        self.path.unlink()
        self.make_link(external, self.path)
        with self.assertRaises(ConfigError):
            self.store.read('rnse')
        with self.assertRaises(ConfigError):
            self.store.save('rnse', self.document, 'missing')
        self.assertEqual(external.read_bytes(), self.original)

    def test_symbolic_link_backup_directory_rejected_before_replacement(self):
        external = self.root / 'backups'
        external.mkdir()
        self.make_link(external, self.home / 'confbackup', directory=True)
        with self.assertRaises(ConfigError):
            self.store.save('rnse', {**self.document, 'branch': 'new'}, self.store.read('rnse')['revision'])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(external.iterdir()), [])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.guard_events = []
        @contextmanager
        def guard():
            self.guard_events.append('enter')
            yield
            self.guard_events.append('exit')
        def runner(args, **kwargs):
            self.calls.append((args, kwargs, list(self.guard_events)))
            if 'show' in args:
                return {'returncode': 0, 'text': 'Id=tp2_worker.service\nActiveState=active\nSubState=running\nLoadState=loaded\n', 'truncated': False}
            return {'returncode': 0, 'text': 'recent log output', 'truncated': False}
        self.controller = ServiceController(runner=runner, flash_guard=guard,
                                            systemctl='/usr/bin/systemctl', journalctl='/usr/bin/journalctl', sudo='/usr/bin/sudo')

    def test_allowlisted_action_uses_argv_and_holds_flash_guard_through_blocking_job(self):
        result = self.controller.action('tp2_worker', 'restart')
        args, kwargs, events = self.calls[0]
        self.assertEqual(args, ['/usr/bin/sudo', '-n', '/usr/bin/systemctl', 'restart', 'tp2_worker.service'])
        self.assertEqual(events, ['enter'])
        self.assertEqual(self.guard_events, ['enter', 'exit'])
        self.assertEqual(kwargs['timeout'], 30)
        self.assertEqual(result['service']['active_state'], 'active')

    def test_delayed_dis_start_can_return_activating_without_flash_guard(self):
        self.controller.action('dis_display', 'start')
        self.assertEqual(self.calls[0][0], ['/usr/bin/sudo', '-n', '/usr/bin/systemctl', '--no-block', 'start', 'dis_display.service'])
        self.assertEqual(self.guard_events, [])

    def test_rejects_unknown_units_actions_and_self_stop_without_running_command(self):
        for service, action in (('../can_handler', 'restart'), ('tp2_worker;reboot', 'stop'),
                                ('tp2_worker', 'enable'), ('hudiy_manager', 'stop')):
            with self.subTest(service=service), self.assertRaises(ConfigError):
                self.controller.action(service, action)
        self.assertEqual(self.calls, [])

    def test_journal_is_bounded_allowlisted_and_does_not_use_sudo(self):
        result = self.controller.logs('tp2_worker', 150)
        self.assertEqual(self.calls[0][0], ['/usr/bin/journalctl', '-u', 'tp2_worker.service', '-n', '150', '--no-pager', '-o', 'short-iso'])
        self.assertEqual(result['text'], 'recent log output')
        for lines in (0, 501, True, '100'):
            with self.subTest(lines=lines), self.assertRaises(ConfigError):
                self.controller.logs('tp2_worker', lines)

    def test_permission_failure_is_reported(self):
        self.controller.runner = lambda *args, **kwargs: {'returncode': 1, 'text': 'sudo: a password is required', 'truncated': False}
        with self.assertRaisesRegex(ServiceError, 'password'):
            self.controller.action('tp2_worker', 'stop')

    def test_active_controller_lock_blocks_disruptive_action_but_saved_flashing_mode_does_not(self):
        from flasher import traffic
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hudiy = home / '.hudiy'
            hudiy.mkdir()
            controller = ServiceController(home=home, runner=self.controller.runner,
                                           systemctl='/usr/bin/systemctl', sudo='/usr/bin/sudo')
            with patch('flasher.traffic._directory', return_value=hudiy):
                with traffic.flashing_operation():
                    with self.assertRaises(BusyError):
                        controller.action('tp2_worker', 'restart')
                    self.assertEqual(self.calls, [])
                (hudiy / 'flashing_mode.json').write_text('{"enabled":true}')
                controller.action('tp2_worker', 'restart')
                self.assertTrue(self.calls)


@unittest.skipIf(create_app is None, 'Run with the Flask-enabled test environment')
class RouteTests(TemporaryConfigCase):
    def setUp(self):
        super().setUp()
        services = ServiceController(runner=lambda *args, **kwargs: {'returncode': 0, 'text': '', 'truncated': False})
        self.app = create_app(self.project, self.home, controller=services, theme_loader=lambda: (None, None))
        self.app.testing = True
        self.client = self.app.test_client()
        self.headers = {'X-Hudiy-Management': '1'}

    def tearDown(self):
        self.app.extensions['management_video'].close()
        super().tearDown()

    def test_mutations_require_same_origin_custom_header_and_current_pin(self):
        revision = self.store.read('rnse')['revision']
        body = {'document': self.document, 'revision': revision}
        self.assertEqual(self.client.put('/api/manage/configs/rnse', json=body).status_code, 403)
        for origin in ('https://evil.example', 'https://localhost', 'null'):
            response = self.client.put('/api/manage/configs/rnse', json=body, headers={**self.headers, 'Origin': origin})
            self.assertEqual(response.status_code, 403)
        response = self.client.put('/api/manage/configs/rnse', json=body, headers={**self.headers, 'Sec-Fetch-Site': 'same-site'})
        self.assertEqual(response.status_code, 403)
        pinned = {**self.document, 'file_portal': {'upload_pin': '2468'}}
        self.path.write_text(json.dumps(pinned))
        body['revision'] = self.store.read('rnse')['revision']
        self.assertTrue(self.client.get('/api/manage/configs').get_json()['pin_required'])
        self.assertEqual(self.client.put('/api/manage/configs/rnse', json=body, headers=self.headers).status_code, 403)
        response = self.client.put('/api/manage/configs/rnse', json=body, headers={**self.headers, 'X-Hudiy-Pin': '2468', 'Origin': 'http://localhost'})
        self.assertEqual(response.status_code, 200)

    def test_put_and_import_share_revision_backup_and_fixed_destination(self):
        current = self.client.get('/api/manage/configs/rnse').get_json()
        imported = {**self.document, 'branch': 'imported'}
        response = self.client.post('/api/manage/configs/rnse/import', headers=self.headers,
                                    data={'revision': current['revision'], 'file': (io.BytesIO(json.dumps(imported).encode()), '../../outside.json')})
        self.assertEqual(response.status_code, 200)
        saved = response.get_json()
        self.assertEqual(Path(saved['backup']).read_bytes(), self.original)
        self.assertEqual(self.store.read('rnse')['document'], imported)
        self.assertFalse((self.root / 'outside.json').exists())
        stale = self.client.put('/api/manage/configs/rnse', headers=self.headers,
                                json={'revision': current['revision'], 'document': self.document})
        self.assertEqual(stale.status_code, 409)
        missing = self.client.put('/api/manage/configs/rnse', headers=self.headers, json={'document': self.document})
        self.assertEqual(missing.status_code, 409)

    def test_routes_do_not_accept_unknown_service_or_unbounded_logs(self):
        self.assertEqual(self.client.post('/api/manage/services/arbitrary/restart', headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get('/api/manage/services/tp2_worker/logs?lines=99999').status_code, 400)
        self.assertEqual(self.client.get('/api/manage/services/tp2_worker/logs?lines=bad').status_code, 400)
        self.assertEqual(self.client.get('/api/manage/services/tp2_worker/logs').status_code, 200)


if __name__ == '__main__':
    unittest.main()
