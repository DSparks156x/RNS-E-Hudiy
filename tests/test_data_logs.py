import csv
import io
import json
import tempfile
import time
import threading
import unittest
from pathlib import Path

from hudiy_dataview.data_logs import DataLogs, register_data_logs
from vehicle_data.workspace import WorkspaceStore, default_workspace, validate_workspace


class DataLogsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'scratch')
        self.config = {'data_logs': {'directory': self.temporary.name}}
        self.commands = []
        self.recorder = DataLogs(self.config, lambda command: self.commands.append(command) or {'status': 'ok'})

    def tearDown(self):
        self.recorder.close()
        self.temporary.cleanup()

    def test_workspace_atomic_persistence_and_validation(self):
        document = default_workspace()
        document['dis_pages'][0]['slots'][0]['precision'] = 2
        store = WorkspaceStore(self.config)
        saved = store.save(document)
        self.assertEqual(WorkspaceStore(self.config).load(), saved)
        document['dis_pages'][0]['slots'][0]['value_id'] = 'fake.value'
        with self.assertRaises(ValueError):
            store.save(document)
        self.assertEqual(store.load(), saved)
        invalid = default_workspace()
        invalid['profiles'][0]['values'] = [{'id': 'engine.rpm', 'rate_hz': float('nan')}]
        with self.assertRaises(ValueError):
            validate_workspace(invalid)

    def test_dis_source_permissions_require_explicit_boolean_and_persist(self):
        document = default_workspace()
        slot = document['dis_pages'][0]['slots'][0]
        slot.update(allow_estimated=True, allow_unverified=False)
        self.recorder.workspace.save(document)
        loaded = WorkspaceStore(self.config).load()['dis_pages'][0]['slots']
        self.assertTrue(loaded[0]['allow_estimated'])
        self.assertFalse(loaded[0]['allow_unverified'])
        self.assertNotIn('allow_estimated', loaded[1])
        for key in ('allow_estimated', 'allow_unverified'):
            for malformed in ('true', 1, None):
                slot[key] = malformed
                with self.assertRaises(ValueError):
                    validate_workspace(document)
            slot[key] = False

    def test_record_metadata_deduplication_status_gaps_markers_and_csv(self):
        started = self.recorder.start_recording('daily')
        sample = {'id': 'engine.rpm', 'value': 1723.25, 'unit': 'rpm', 'status': 'ok',
                  'timestamp': time.time(), 'sample_sequence': 42, 'max_age_ms': 500,
                  'source': {'id': 'diag:01:3:1', 'kind': 'diag'}, 'quality': 'measured'}
        self.recorder.ingest({'client_id': 'another_client', 'values': [sample]})
        for _ in range(2):
            self.recorder.ingest({'client_id': self.recorder.CLIENT_ID, 'values': [sample]})
        self.recorder.expire(sample['timestamp']+1)
        self.recorder.marker('Pull end')
        status = self.recorder.stop_recording()
        self.assertFalse(status['recording'])
        saved = self.recorder.read_session(started['session_id'])
        rpm = [row for row in saved['samples'] if row['id'] == 'engine.rpm']
        self.assertEqual([row['status'] for row in rpm], ['unavailable', 'ok', 'stale'])
        self.assertEqual(rpm[1]['timestamp'], sample['timestamp'])
        self.assertEqual(rpm[2]['sample_sequence'], 42)
        self.assertIsNone(rpm[2]['value'])
        self.assertEqual(saved['markers'][0]['note'], 'Pull end')
        self.assertEqual(saved['session']['samples'], 10)
        rows = list(csv.DictReader(io.StringIO(''.join(self.recorder.export_csv(started['session_id'])))))
        self.assertEqual(len(rows), 11)
        self.assertEqual(self.commands[0]['cmd'], 'SYNC_VALUES')
        self.assertEqual(self.commands[-1]['cmd'], 'UNSUBSCRIBE')
        self.assertEqual(self.commands[0]['client_id'], self.recorder.CLIENT_ID)

    def test_all_types_pagination_and_path_safety(self):
        document = default_workspace()
        from vehicle_data.catalog import CATALOG
        values = [next(value for value, entry in CATALOG.items() if entry['type'] == kind)
                  for kind in ('number', 'string', 'status', 'bitfield')]
        document['profiles'][0]['values'] = values
        self.recorder.save_config(document)
        sid = self.recorder.start_recording('daily')['session_id']
        self.recorder.ingest({'client_id': self.recorder.CLIENT_ID, 'values': [
            {'id': vid, 'value': value, 'status': 'ok', 'timestamp': 100, 'sample_sequence': 1}
            for vid, value in zip(values, [2.5, 'Identification', 'Enabled', '01X1'])]})
        with self.assertRaises(ValueError):
            self.recorder.delete_session(sid)
        self.recorder.stop_recording()
        page = self.recorder.read_session(sid, limit=3)
        self.assertTrue(page['truncated'])
        self.assertEqual(page['next_offset'], 3)
        recorded = self.recorder.read_session(sid)['samples'][-4:]
        self.assertEqual([row['value'] for row in recorded], [2.5, 'Identification', 'Enabled', '01X1'])
        for malicious in ('../workspace', '..', '/tmp', '0'*32+'/../workspace'):
            with self.assertRaises(ValueError):
                self.recorder.read_session(malicious)
        self.recorder.delete_session(sid)
        self.assertEqual(self.recorder.sessions(), [])

    def test_broker_rejection_does_not_create_recording(self):
        self.recorder.request_values = lambda _: {'status': 'error', 'message': 'Unknown source'}
        with self.assertRaises(RuntimeError):
            self.recorder.start_recording('daily')
        self.assertFalse(self.recorder.status()['recording'])
        self.assertEqual(self.recorder.sessions(), [])

    def test_snapshot_and_last_thirty_seconds_review_preserve_full_export(self):
        now = time.time()
        cached = {'id': 'engine.rpm', 'value': 800, 'status': 'ok',
                  'timestamp': now-60, 'sample_sequence': 1, 'max_age_ms': 2000}
        def broker(command):
            self.commands.append(command)
            return {'status': 'ok', 'values': [cached]} if command['cmd'] == 'SNAPSHOT' else {'status': 'ok'}
        self.recorder.request_values = broker
        sid = self.recorder.start_recording('daily')['session_id']
        self.recorder.ingest({'client_id': self.recorder.CLIENT_ID, 'values': [
            {**cached, 'timestamp': now, 'value': 900, 'sample_sequence': 2}]})
        self.recorder.stop_recording()
        window = self.recorder.read_session(sid, window_sec=30)
        values = [row['value'] for row in window['samples'] if row['status'] == 'ok']
        self.assertEqual(values, [900])
        full = self.recorder.read_session(sid)
        self.assertIn(800, [row['value'] for row in full['samples']])
        self.assertIn('800', ''.join(self.recorder.export_csv(sid)))

    def test_failed_writer_preserves_error_and_counts_unwritten_rows(self):
        failed = threading.Event()
        original = self.recorder._write
        class FailedFile:
            def __init__(self, handle):
                self.handle = handle
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.handle.close()
            def write(self, row):
                failed.set()
                raise OSError('No space left on device')
        self.recorder._write = lambda handle, pending: original(FailedFile(handle), pending)
        sid = self.recorder.start_recording('daily')['session_id']
        self.assertTrue(failed.wait(2))
        stopped = self.recorder.stop_recording()
        saved = self.recorder.read_session(sid)['session']
        self.assertFalse(stopped['recording'])
        self.assertTrue(saved['write_failed'])
        self.assertEqual(saved['last_error'], 'No space left on device')
        self.assertEqual(saved['dropped_rows'], 8)
        self.assertEqual(self.commands[-1]['cmd'], 'UNSUBSCRIBE')

    def test_http_endpoints_and_shared_dis_commands(self):
        from flask import Flask
        class Socket:
            def emit(self, *args, **kwargs):
                pass
        app = Flask(__name__)
        service = register_data_logs(app, Socket(), self.config)
        client = app.test_client()
        self.assertEqual(len(client.get('/api/data-logs').json['catalog']), 460)
        self.assertEqual(client.put('/api/data-logs/config', json={'profiles': []}).status_code, 400)
        self.assertEqual(client.post('/api/data-logs/start', json=[]).status_code, 400)
        for malformed in ([], 'wrong', 123, True):
            self.assertEqual(client.post('/api/data-logs/start', json=malformed).status_code, 400)
            self.assertEqual(client.post('/api/data-logs/marker', json=malformed).status_code, 400)
            self.assertEqual(client.put('/api/data-logs/config', json=malformed).status_code, 400)
        self.assertEqual(service.command({'cmd': 'START', 'profile_id': 'daily'})['status'], 'ok')
        sid = service.status()['session_id']
        self.assertEqual(client.post('/api/data-logs/marker', json={'label': 'Wheel mark'}).status_code, 200)
        self.assertEqual(service.command({'cmd': 'STOP'})['status'], 'ok')
        self.assertEqual(client.get('/api/data-logs/sessions/'+sid).status_code, 200)
        self.assertEqual(client.get('/api/data-logs/sessions/'+sid+'/export').mimetype, 'text/csv')
        self.assertEqual(client.delete('/api/data-logs/sessions/'+sid).status_code, 200)
        service.close()


if __name__ == '__main__':
    unittest.main()
