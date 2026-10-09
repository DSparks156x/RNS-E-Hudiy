"""Publisher behavior without importing API/Flask modules or opening sockets."""
import ast
import hashlib
import io
import json
import logging
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image


REPO = Path(os.environ.get('COVER_PUBLISH_REPO', Path(__file__).resolve().parents[1]))


def source_method(relative_path, method_name, namespace):
    tree = ast.parse((REPO / relative_path).read_text(encoding='utf-8'))
    matches = [node for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef) and node.name == method_name]
    if len(matches) != 1:
        raise AssertionError(f'Expected one actual method {method_name}, got {len(matches)}')
    module = ast.Module(body=[matches[0]], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(relative_path), 'exec'), namespace)
    return namespace[method_name]


def png_bytes(color='red'):
    with io.BytesIO() as output:
        with Image.new('RGB', (160, 120), color) as image:
            image.save(output, format='PNG')
        return output.getvalue()


class CoverSourcePublishTests(unittest.TestCase):
    def setUp(self):
        self.opened_sources = []
        self.opened_images = []
        self.source_files = []
        self.processed_sizes = []
        self.dis_image = SimpleNamespace(
            process_image=Mock(side_effect=self.process_image),
            image_to_bitmap=Mock(return_value=b'\xaa\xbb'),
        )
        self.socketio = SimpleNamespace(emit=Mock())
        namespace = {
            'Image': SimpleNamespace(open=self.open_image),
            'io': io, 'hashlib': hashlib, 'time': time,
            'dis_image': self.dis_image,
            'logger': logging.getLogger('cover-source-test'),
            'json': json, 'os': os, 'socketio': self.socketio,
            'open': self.open_file,
        }
        self.metadata = source_method('hudiy_client/hudiy_data.py', 'on_media_metadata', namespace)
        self.publish = source_method('hudiy_client/hudiy_data.py', 'publish', namespace)
        self.send_image = source_method('dis_emulator/emulator_service.py', 'send_image_file', namespace)
        self.handler = SimpleNamespace(
            current_media_data={}, last_media='', last_coverart_hash=None,
            coverart_args={'contrast': 1.4},
            safe_pub=SimpleNamespace(publish=Mock(return_value=True)),
            _capture_api_event=Mock(), _provider_name=Mock(return_value='android_auto'),
            publish_and_write_media=Mock(),
        )

    def open_image(self, source):
        self.opened_sources.append(source)
        image = Image.open(source)
        self.opened_images.append(image)
        return image

    def open_file(self, *args, **kwargs):
        source = open(*args, **kwargs)
        self.source_files.append(source)
        return source

    def process_image(self, image, **kwargs):
        self.processed_sizes.append(image.size)
        image.getpixel((0, 0))  # Exercise actual decoding while source is available.
        return image

    def message(self, data=None, title='Track'):
        return SimpleNamespace(artist='Artist', title=title, album='Album', coverart=data)

    def run_metadata(self, data=None, title='Track'):
        self.metadata(self.handler, None, self.message(data, title))

    def cover_payloads(self):
        return [call.args[1] for call in self.handler.safe_pub.publish.call_args_list
                if call.args[0] == b'HUDIY_COVERART']

    def assert_sources_closed(self):
        self.assertTrue(self.opened_sources)
        for source in self.opened_sources:
            self.assertIsInstance(source, io.BytesIO)
            self.assertTrue(source.closed)
        for image in self.opened_images:
            self.assertIsNone(image.fp)
        for source in self.source_files:
            self.assertTrue(source.closed)

    def test_initial_cover_keeps_original_encoded_image_and_legacy_bitmap(self):
        data = png_bytes()
        self.run_metadata(data)
        payload = self.cover_payloads()[0]
        self.assertEqual(payload['image_hex'], data.hex())
        self.assertEqual(payload['bitmap_hex'], 'aabb')
        self.assertTrue(payload['is_new_track'])
        self.assertEqual(self.processed_sizes, [(160, 120)])
        self.dis_image.process_image.assert_called_once_with(self.opened_images[0], contrast=1.4)
        self.assertEqual(self.handler.last_coverart_hash, hashlib.md5(data).hexdigest())
        self.assert_sources_closed()

    def test_duplicate_suppressed_but_changed_cover_and_new_track_publish(self):
        first, second = png_bytes(), png_bytes('blue')
        self.run_metadata(first)
        self.run_metadata(first)
        self.assertEqual(len(self.cover_payloads()), 1)
        self.run_metadata(second)
        self.run_metadata(second, title='Next Track')
        self.assertEqual([p['is_new_track'] for p in self.cover_payloads()], [True, False, True])
        self.assertEqual([p['image_hex'] for p in self.cover_payloads()],
                         [first.hex(), second.hex(), second.hex()])
        self.assert_sources_closed()

    def test_new_track_without_cover_still_sends_clear(self):
        self.run_metadata(None)
        self.assertEqual(self.cover_payloads()[0]['bitmap_hex'], '')
        self.assertTrue(self.cover_payloads()[0]['is_new_track'])
        self.dis_image.process_image.assert_not_called()
        self.assertIsNone(self.handler.last_coverart_hash)

    def test_rejected_initial_publish_remains_retryable(self):
        data = png_bytes()
        self.handler.safe_pub.publish.side_effect = [False, True]
        self.run_metadata(data)
        self.assertIsNone(self.handler.last_coverart_hash)
        self.run_metadata(data)
        self.assertEqual(self.handler.safe_pub.publish.call_count, 2)
        self.assertEqual(self.handler.last_coverart_hash, hashlib.md5(data).hexdigest())
        self.assert_sources_closed()

    def test_rejected_changed_cover_retains_prior_hash_for_retry(self):
        first, second = png_bytes(), png_bytes('blue')
        self.run_metadata(first)
        self.handler.safe_pub.publish.side_effect = [False, True]
        self.run_metadata(second)
        self.assertEqual(self.handler.last_coverart_hash, hashlib.md5(first).hexdigest())
        self.run_metadata(second)
        self.assertEqual(self.handler.last_coverart_hash, hashlib.md5(second).hexdigest())
        self.assertEqual(self.handler.safe_pub.publish.call_count, 3)
        self.assert_sources_closed()

    def test_publish_exception_keeps_hash_and_retries(self):
        data = png_bytes()
        self.handler.safe_pub.publish.side_effect = [RuntimeError('queue rejected'), True]
        self.run_metadata(data)
        self.assertIsNone(self.handler.last_coverart_hash)
        self.run_metadata(data)
        self.assertEqual(self.handler.last_coverart_hash, hashlib.md5(data).hexdigest())
        self.assert_sources_closed()

    def test_processing_failure_closes_source_and_retries(self):
        data = png_bytes()
        self.dis_image.image_to_bitmap.side_effect = [RuntimeError('conversion failed'), b'\xaa\xbb']
        self.run_metadata(data)
        self.handler.safe_pub.publish.assert_not_called()
        self.assertIsNone(self.handler.last_coverart_hash)
        self.assert_sources_closed()
        self.run_metadata(data)
        self.assertEqual(self.cover_payloads()[0]['bitmap_hex'], 'aabb')
        self.assert_sources_closed()

    def test_queue_acceptance_is_explicit_and_stopped_publisher_rejects(self):
        publisher = SimpleNamespace(running=True, queue=SimpleNamespace(put=Mock()))
        self.assertIs(self.publish(publisher, b'TOPIC', {'value': 1}), True)
        publisher.queue.put.assert_called_once_with((b'TOPIC', {'value': 1}))
        publisher.running = False
        self.assertIs(self.publish(publisher, b'TOPIC', {'value': 2}), False)
        self.assertEqual(publisher.queue.put.call_count, 1)

    def test_queue_failure_cannot_report_acceptance(self):
        publisher = SimpleNamespace(running=True,
                                    queue=SimpleNamespace(put=Mock(side_effect=RuntimeError('closed'))))
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            self.publish(publisher, b'TOPIC', {})

    def test_emulator_reads_source_once_and_preserves_payload_and_track_flag(self):
        data = png_bytes()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cover.png'
            path.write_bytes(data)
            bridge = SimpleNamespace(_publish=Mock())
            for new_track in (True, False):
                self.send_image(bridge, str(path), is_new_track=new_track)
                socket_name, frames = bridge._publish.call_args.args
                self.assertEqual(socket_name, 'hudiy_pub')
                topic, raw = frames
                payload = json.loads(raw)
                self.assertEqual(topic, b'HUDIY_COVERART')
                self.assertEqual(payload['image_hex'], data.hex())
                self.assertEqual(payload['bitmap_hex'], 'aabb')
                self.assertIs(payload['is_new_track'], new_track)
            self.assertEqual(len(self.source_files), 2)  # Once per invocation.
            self.assertEqual(self.processed_sizes, [(160, 120), (160, 120)])
            self.assert_sources_closed()

    def test_emulator_failure_closes_sources_and_reports_error_without_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cover.png'
            path.write_bytes(png_bytes())
            bridge = SimpleNamespace(_publish=Mock())
            self.dis_image.image_to_bitmap.side_effect = RuntimeError('bitmap failed')
            self.send_image(bridge, str(path), is_new_track=True)
            bridge._publish.assert_not_called()
            self.socketio.emit.assert_called_once()
            self.assertIn('bitmap failed', self.socketio.emit.call_args.args[1]['text'])
            self.assert_sources_closed()


if __name__ == '__main__':
    unittest.main()
