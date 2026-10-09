"""Raw callback captures accompany Save Logs service-journal exports."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from hudiy_client.api_event_capture import ApiEventCapture


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('save_logs_review', ROOT / 'rns-e_can/save_logs.py')
SAVE_LOGS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAVE_LOGS)


class SaveAPICaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / 'scratch')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.destination = self.root / 'saved'
        self.destination.mkdir()
        self.capture = self.root / 'logs/hudiy-api/hudiy-api-events.log'
        self.capture.parent.mkdir(parents=True)
        self.config = {'diagnostics': {'hudiy_api_capture': {
            'enabled': False, 'path': str(self.root / 'obsolete.log'), 'max_size_mb': 1}}}
        for target, field in ((SAVE_LOGS, 'API_CAPTURE_PATH'), (ApiEventCapture, 'DEFAULT_PATH')):
            patcher = patch.object(target, field, str(self.capture))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_both_files_are_saved_in_order_without_changing_source(self):
        previous = self.capture.with_name('hudiy-api-events-previous.log')
        previous.write_bytes(b'{"sequence":1}\n')
        self.capture.write_bytes(b'{"sequence":2}\n{"sequence":3')
        paths = SAVE_LOGS.save_api_captures(self.destination)
        self.assertEqual([Path(path).name for path in paths],
                         ['hudiy-api-events-previous_1.log', 'hudiy-api-events_1.log'])
        self.assertEqual([Path(path).read_bytes() for path in paths],
                         [b'{"sequence":1}\n', b'{"sequence":2}\n'])
        self.assertEqual(self.capture.read_bytes(), b'{"sequence":2}\n{"sequence":3')

    def test_repeated_save_keeps_previous_snapshots(self):
        self.capture.write_bytes(b'{"sequence":1}\n')
        first = SAVE_LOGS.save_api_captures(self.destination)
        self.capture.write_bytes(b'{"sequence":2}\n')
        second = SAVE_LOGS.save_api_captures(self.destination)
        self.assertEqual(Path(first[0]).read_bytes(), b'{"sequence":1}\n')
        self.assertEqual(Path(second[0]).name, 'hudiy-api-events_2.log')
        self.assertEqual(Path(second[0]).read_bytes(), b'{"sequence":2}\n')

    def test_missing_and_incomplete_captures_produce_no_snapshot(self):
        self.assertEqual(SAVE_LOGS.save_api_captures(self.destination), [])
        self.capture.write_bytes(b'{"unfinished":true')
        self.assertEqual(SAVE_LOGS.save_api_captures(self.destination), [])
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_button_saves_api_and_service_logs_together_without_capture_config(self):
        config = {'features': {'log_saver': {
            'services': ['hudiy_data_api.service'],
            'log_directory': str(self.destination)}}}
        (self.root / 'config.json').write_text(json.dumps(config))
        capture_path = self.root / 'logs/hudiy-api/hudiy-api-events.log'
        def expand_home(value):
            if value == '~':
                return str(self.root)
            if value.startswith('~/'):
                return str(self.root / value[2:])
            return value
        with patch.object(SAVE_LOGS.os.path, 'expanduser', side_effect=expand_home):
            capture = ApiEventCapture()
            capture.record('navigation_status', provider='carplay')
            with patch.object(SAVE_LOGS, 'Client', None), \
                 patch.object(SAVE_LOGS.subprocess, 'run',
                              return_value=Mock(returncode=0, stdout='service log\n')):
                SAVE_LOGS.main()
        raw = list(self.destination.rglob('hudiy-api-events_1.log'))
        journals = list(self.destination.rglob('hudiy_data_api_1.log'))
        self.assertEqual(len(raw), 1)
        self.assertEqual(len(journals), 1)
        self.assertEqual(raw[0].parent, journals[0].parent)
        self.assertEqual(raw[0].parent.name, '1')
        self.assertRegex(raw[0].parent.parent.name, r'^\d{4}-\d{2}-\d{2}$')
        self.assertEqual(raw[0].read_bytes(), capture_path.read_bytes())
        self.assertEqual(json.loads(raw[0].read_text().splitlines()[-1])['provider'], 'carplay')

    def test_raw_only_save_still_has_a_notification_index(self):
        self.capture.write_bytes(b'{}\n')
        self.config['features'] = {'log_saver': {
            'services': [], 'log_directory': str(self.destination)}}
        (self.root / 'config.json').write_text(json.dumps(self.config))
        client = Mock()
        client.wait_for_message.return_value = False
        with patch.object(SAVE_LOGS, 'Client', return_value=client), \
             patch.object(SAVE_LOGS.os.path, 'expanduser',
                          side_effect=lambda value: str(self.root) if value == '~' else value):
            SAVE_LOGS.main()
        handler = client.set_event_handler.call_args.args[0]
        self.assertEqual(handler.index, 1)
        self.assertEqual(len(list(self.destination.rglob('hudiy-api-events_1.log'))), 1)

    def test_repeated_button_saves_keep_matching_numbered_bundles_and_old_config_is_ignored(self):
        self.config['features'] = {'log_saver': {
            'services': ['hudiy_data_api.service', 'tp2_worker.service'],
            'log_directory': str(self.destination)}}
        (self.root / 'config.json').write_text(json.dumps(self.config))
        self.capture.write_bytes(b'{"sequence":1}\n')
        client = Mock()
        client.wait_for_message.return_value = False
        with patch.object(SAVE_LOGS, 'Client', return_value=client), \
             patch.object(SAVE_LOGS.os.path, 'expanduser',
                          side_effect=lambda value: str(self.root) if value == '~' else value), \
             patch.object(SAVE_LOGS.subprocess, 'run',
                          return_value=Mock(returncode=0, stdout='service log\n')):
            SAVE_LOGS.main()
            self.capture.write_bytes(b'{"sequence":2}\n')
            SAVE_LOGS.main()
        bundles = sorted(path for date in self.destination.iterdir() for path in date.iterdir())
        self.assertEqual([path.name for path in bundles], ['1', '2'])
        for index, bundle in enumerate(bundles, start=1):
            self.assertEqual(sorted(path.name for path in bundle.iterdir()),
                             [f'hudiy-api-events_{index}.log', f'hudiy_data_api_{index}.log',
                              f'tp2_worker_{index}.log'])
            self.assertEqual(json.loads((bundle / f'hudiy-api-events_{index}.log').read_text())['sequence'], index)
        self.assertEqual([call.args[0].index for call in client.set_event_handler.call_args_list], [1, 2])

    def test_simultaneous_button_saves_preserve_first_bundle_after_restart(self):
        self.config['features'] = {'log_saver': {
            'services': ['tp2_worker.service'], 'log_directory': str(self.destination)}}
        (self.root / 'config.json').write_text(json.dumps(self.config))
        self.capture.write_bytes(b'{"sequence":1}\n')
        date = self.destination / '2026-10-08'
        first = date / '1'
        first.mkdir(parents=True)
        original = first / 'tp2_worker_1.log'
        original.write_text('first bundle\n', encoding='utf-8')
        ready = threading.Barrier(2)
        failures = []
        def journal(*args, **kwargs):
            ready.wait(timeout=3)
            return Mock(returncode=0, stdout='new journal\n')
        def save():
            try:
                SAVE_LOGS.main()
            except Exception as error:
                failures.append(error)
        with patch.object(SAVE_LOGS, 'Client', None), \
                patch.object(SAVE_LOGS, 'datetime') as clock, \
                patch.object(SAVE_LOGS.os.path, 'expanduser',
                             side_effect=lambda value: str(self.root) if value == '~' else value), \
                patch.object(SAVE_LOGS.subprocess, 'run', side_effect=journal):
            clock.now.return_value.strftime.return_value = '2026-10-08'
            workers = [threading.Thread(target=save) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(original.read_text(encoding='utf-8'), 'first bundle\n')
        self.assertEqual(sorted(path.name for path in date.iterdir()), ['1', '2', '3'])
        for index in (2, 3):
            self.assertEqual((date / str(index) / f'tp2_worker_{index}.log').read_text(), 'new journal\n')
            self.assertEqual((date / str(index) / f'hudiy-api-events_{index}.log').read_bytes(), b'{"sequence":1}\n')


if __name__ == '__main__':
    unittest.main()
