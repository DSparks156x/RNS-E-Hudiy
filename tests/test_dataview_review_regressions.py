"""Regression cases found while reviewing DataView, without vehicle hardware."""
import csv
import ast
import io
import math
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path

from hudiy_dataview.data_logger import DataLogger, HALDEX_MODE_COMMAND_ID
from hudiy_dataview.data_logs import DataLogs

try:
    from flask import Flask
except ImportError:
    Flask = None


class InterpolatorReviewTests(unittest.TestCase):
    def test_numeric_segments_restart_after_unavailable_samples_or_unit_changes(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ('app.py', 'app_mock.py'):
            with self.subTest(filename=filename):
                # Extract this class so importing the live app does not start
                # its command worker or load vehicle configuration.
                tree = ast.parse((root / 'hudiy_dataview' / filename).read_text(encoding='utf-8'))
                node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Interpolator')
                namespace = {'threading': threading, 'time': time, 'math': math, 'EMA_ALPHA': .98}
                exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), namespace)
                interpolator = namespace['Interpolator']()
                interpolator.update(1, 3, [{'value': 900, 'unit': 'rpm'}])
                interpolator.update(1, 3, [{'value': '--', 'unit': 'rpm'}])
                interpolator.update(1, 3, [{'value': 2000, 'unit': 'rpm'}])
                self.assertEqual(interpolator.get_interpolated(1, 3)['data'][0]['value'], 2000)
                interpolator.update(1, 3, [{'value': 2, 'unit': 'bar'}])
                self.assertEqual(interpolator.get_interpolated(1, 3)['data'][0]['value'], 2)
                interpolator.update(1, 3, [{'value': float('nan'), 'unit': 'bar'}])
                interpolator.update(1, 3, [{'value': 3, 'unit': 'bar'}])
                self.assertEqual(interpolator.get_interpolated(1, 3)['data'][0]['value'], 3)


class RecorderReviewTests(unittest.TestCase):
    def test_start_waits_for_previous_writer_drain_and_keeps_session_counts_separate(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'scratch') as directory:
            recorder = DataLogger()
            first_path, second_path = Path(directory) / 'first.csv', Path(directory) / 'second.csv'
            first_started, release_first = threading.Event(), threading.Event()
            second_started, stop_queued, start_attempted = threading.Event(), threading.Event(), threading.Event()
            original_writer = recorder._writer_worker
            results, failures = {}, []
            def controlled_writer(path, columns, pending):
                if path == str(first_path):
                    first_started.set()
                    if not release_first.wait(5):
                        raise RuntimeError('Test did not release the first writer')
                else:
                    second_started.set()
                original_writer(path, columns, pending)
            recorder._writer_worker = controlled_writer
            recorder.start_recording('raw_can', str(first_path))
            self.assertTrue(first_started.wait(2))
            recorder.ingest_can(0x123, b'\x01')
            pending = recorder._write_queue
            original_put = pending.put
            def observed_put(item, *args, **kwargs):
                result = original_put(item, *args, **kwargs)
                if item is recorder._STOP:
                    stop_queued.set()
                return result
            pending.put = observed_put
            def stop():
                try:
                    results['first'] = recorder.stop_recording()
                except Exception as error:
                    failures.append(error)
            def start():
                start_attempted.set()
                try:
                    results['second'] = recorder.start_recording('raw_can', str(second_path))
                except Exception as error:
                    failures.append(error)
            stopper, starter = threading.Thread(target=stop), threading.Thread(target=start)
            try:
                stopper.start()
                self.assertTrue(stop_queued.wait(2))
                starter.start()
                self.assertTrue(start_attempted.wait(2))
                self.assertFalse(second_started.wait(.1), 'A new writer started before the old session drained')
                release_first.set()
                stopper.join(2)
                starter.join(2)
                self.assertFalse(stopper.is_alive())
                self.assertFalse(starter.is_alive())
                self.assertEqual(failures, [])
                self.assertEqual(results['first']['rows_written'], 1)
                self.assertEqual(results['first']['output_path'], str(first_path))
                self.assertEqual(results['second']['rows_written'], 0)
                self.assertTrue(recorder.get_status()['recording'])
                recorder.ingest_can(0x123, b'\x02')
                self.assertEqual(recorder.stop_recording()['rows_written'], 1)
                for path, expected in ((first_path, '01'), (second_path, '02')):
                    with path.open(newline='', encoding='utf-8') as handle:
                        self.assertEqual([row['data_hex'] for row in csv.DictReader(handle)], [expected])
            finally:
                release_first.set()
                if stopper.ident is not None:
                    stopper.join(2)
                if starter.ident is not None:
                    starter.join(2)
                recorder.close()

    def test_timed_out_stop_preserves_writer_ownership_until_retry_finishes(self):
        class SlowWriter:
            alive = True
            def is_alive(self):
                return self.alive
            def join(self, timeout=None):
                pass  # Simulate a join timeout without spending five seconds.
        recorder = DataLogger()
        writer, pending = SlowWriter(), queue.Queue()
        recorder._writer_thread, recorder._write_queue, recorder._recording = writer, pending, True
        with self.assertRaisesRegex(RuntimeError, 'retry Stop'):
            recorder.stop_recording()
        self.assertIs(recorder._writer_thread, writer)
        self.assertIs(recorder._write_queue, pending)
        with self.assertRaisesRegex(RuntimeError, 'retry Stop'):
            recorder.start_recording('raw_can')
        writer.alive = False
        recorder.stop_recording()
        self.assertIsNone(recorder._writer_thread)
        self.assertIsNone(recorder._write_queue)

    def test_unbounded_value_age_does_not_interrupt_other_expiration(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'scratch') as directory:
            recorder = DataLogs({'data_logs': {'directory': directory}})
            try:
                session = recorder.start_recording('daily')['session_id']
                now = time.time()
                recorder.ingest({'client_id': recorder.CLIENT_ID, 'values': [
                    {'id': 'engine.rpm', 'value': 900, 'status': 'ok', 'timestamp': now,
                     'sample_sequence': 1, 'max_age_ms': None},
                    {'id': 'engine.coolant_temperature', 'value': 90, 'status': 'ok',
                     'timestamp': now, 'sample_sequence': 1, 'max_age_ms': 500},
                ]})
                recorder.expire(now + 100)
                recorder.stop_recording()
                samples = recorder.read_session(session)['samples']
                rpm = [row for row in samples if row['id'] == 'engine.rpm']
                coolant = [row for row in samples if row['id'] == 'engine.coolant_temperature']
                self.assertEqual([row['status'] for row in rpm], ['unavailable', 'ok'])
                self.assertEqual([row['status'] for row in coolant], ['unavailable', 'ok', 'stale'])
            finally:
                recorder.close()

    def test_mode_marker_uses_command_header_instead_of_payload_byte(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'scratch') as directory:
            output = Path(directory) / 'haldex.csv'
            recorder = DataLogger()
            try:
                recorder.start_recording(output_path=str(output))
                recorder.ingest_can(HALDEX_MODE_COMMAND_ID, bytes.fromhex('a55aff2233445566'))
                recorder.ingest_can(HALDEX_MODE_COMMAND_ID, bytes.fromhex('c33c020203040506'))
                recorder.stop_recording()
                with output.open(newline='', encoding='utf-8') as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(rows[0]['event_marker'], 'MODE_CMD_BURST: mode=1 (Performance)')
                self.assertEqual(rows[1]['event_marker'], '')
            finally:
                recorder.close()


@unittest.skipIf(Flask is None, 'Flask is installed by the Pi installer')
class PortalReviewTests(unittest.TestCase):
    def test_upload_cannot_replace_file_created_while_validation_runs(self):
        from hudiy_dataview.file_portal import register_file_portal
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'scratch') as directory:
            target = Path(directory) / 'tune.bin'
            def validator(_temporary):
                # Simulate a second accepted upload while the first validates.
                target.write_bytes(b'first validated image')
            app = Flask(__name__)
            register_file_portal(app, {'file_portal': {'firmware_targets': [{
                'id': 'test', 'directory': directory, 'validator': 'test', 'extensions': ['.bin'],
            }]}}, {'test': validator})
            response = app.test_client().post('/api/files/upload/firmware_test', data={
                'file': (io.BytesIO(b'second image'), 'tune.bin'),
            })
            self.assertEqual(response.status_code, 409)
            self.assertEqual(target.read_bytes(), b'first validated image')
            self.assertEqual([path.name for path in Path(directory).iterdir()], ['tune.bin'])


if __name__ == '__main__':
    unittest.main()
