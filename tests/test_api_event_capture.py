import ast
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hudiy_client.api_event_capture import ApiEventCapture

SCRATCH = Path(__file__).resolve().parents[1] / 'scratch'

class _Field:
    def __init__(self, name, message_type=None):
        self.name = name
        self.message_type = message_type


class _Descriptor:
    full_name = "hudiy.NavigationStatus"
    fields = [_Field("source"), _Field("state"), _Field("description")]


class _Message:
    DESCRIPTOR = _Descriptor()

    def __init__(self):
        self.source = 2
        self.state = 1
        self.description = ""

    def ListFields(self):
        return [(_Descriptor.fields[0], self.source), (_Descriptor.fields[1], self.state)]

    def SerializeToString(self):
        return b"\x08\x02\x10\x01"


class ApiEventCaptureTests(unittest.TestCase):
    def test_records_raw_presence_wire_and_derived_data(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "hudiy-api-events.log"
            with patch.object(ApiEventCapture, "DEFAULT_PATH", str(path)):
                capture = ApiEventCapture()

            capture.record(
                "navigation_status",
                _Message(),
                provider="carplay",
                derived={"active": True},
                context={"nav_source_id": 2},
            )

            entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            event = entries[-1]
            self.assertEqual(event["provider"], "carplay")
            self.assertEqual(event["protobuf_type"], "hudiy.NavigationStatus")
            self.assertEqual(event["present_fields"], ["source", "state"])
            self.assertEqual(event["fields"]["description"], "")
            self.assertEqual(event["wire"]["hex"], "08021001")
            self.assertEqual(event["derived"], {"active": True})

    def test_capture_requires_no_configuration(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "hudiy-api-events.log"
            with patch.object(ApiEventCapture, "DEFAULT_PATH", str(path)):
                capture = ApiEventCapture()
            capture.record("navigation_status", _Message())
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([entry["event"] for entry in entries],
                             ["capture_started", "navigation_status"])

    def test_service_always_starts_capture_even_with_legacy_disabled_diagnostics(self):
        root = SCRATCH.parent
        tree = ast.parse((root / 'hudiy_client/hudiy_data.py').read_text(encoding='utf-8'))
        service_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'HudiyData')
        namespace = {'ApiEventCapture': ApiEventCapture, 'json': json, 'os': os,
                     'logger': logging.getLogger(__name__), 'SafePublisher': Mock(),
                     'HudiyEventHandler': Mock(), 'TP2BridgeHandler': Mock(), 'ConnectionManager': Mock()}
        exec(compile(ast.Module(body=[service_node], type_ignores=[]), 'hudiy_data.py', 'exec'), namespace)
        service_type = namespace['HudiyData']
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / 'hudiy-api-events.log'
            config_path = Path(directory) / 'config.json'
            config_path.write_text(json.dumps({'diagnostics': {'enabled': False,
                'hudiy_api_capture': {'enabled': False, 'path': str(Path(directory) / 'obsolete.log')}}}))
            with patch.object(ApiEventCapture, 'DEFAULT_PATH', str(path)), \
                 patch.object(service_type, '_setup_signals'):
                service = service_type(config_path=str(config_path))
            self.assertEqual(json.loads(path.read_text().splitlines()[0])['event'], 'capture_started')
            self.assertEqual(service.api_event_capture.path, str(path))
            self.assertIs(namespace['HudiyEventHandler'].call_args.kwargs['event_capture'], service.api_event_capture)

    def test_temporary_startup_write_failure_recovers_on_next_callback(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "hudiy-api-events.log"
            with patch.object(ApiEventCapture, "DEFAULT_PATH", str(path)), \
                 patch("hudiy_client.api_event_capture.os.makedirs", side_effect=OSError("temporary failure")):
                capture = ApiEventCapture()
            capture.record("navigation_status", _Message())
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(entries[-1]["event"], "navigation_status")

    def test_rotation_retains_one_previous_file_and_complete_events(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "hudiy-api-events.log"
            with patch.object(ApiEventCapture, "DEFAULT_PATH", str(path)):
                capture = ApiEventCapture()
            # Leave room for one record so the second forces rotation.
            path.write_bytes(b"")
            capture.max_bytes = 500
            capture.record("first", _Message())
            capture.record("second", _Message())
            current = [json.loads(line) for line in path.read_text().splitlines()]
            previous = [json.loads(line) for line in Path(capture.previous_path).read_text().splitlines()]
            self.assertEqual([entry['event'] for entry in current], ['second'])
            self.assertEqual([entry['event'] for entry in previous], ['first'])

    def test_default_limit_is_two_mib_per_file(self):
        self.assertEqual(ApiEventCapture.MAX_SIZE_MB, 2)

    def test_oversized_event_is_dropped(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "hudiy-api-events.log"
            with patch.object(ApiEventCapture, "DEFAULT_PATH", str(path)):
                capture = ApiEventCapture()
            capture.max_bytes = 512
            path.write_bytes(b"")
            capture.record("too_large", derived={"payload": "x" * 512})
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(entries, [])

    def test_failed_rotation_drops_incoming_event(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "hudiy-api-events.log"
            with patch.object(ApiEventCapture, "DEFAULT_PATH", str(path)):
                capture = ApiEventCapture()
            capture.max_bytes = path.stat().st_size + 1
            original = path.read_bytes()
            with patch("hudiy_client.api_event_capture.os.replace", side_effect=OSError("rotation failed")) as replace:
                capture.record("must_be_dropped")
            replace.assert_called_once()
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(Path(capture.previous_path).exists())

    def test_preexisting_oversized_files_keep_only_complete_recent_lines(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "hudiy-api-events.log"
            previous_path = Path(directory) / "hudiy-api-events-previous.log"
            huge_line = b'{"event":"' + b'x' * (ApiEventCapture.MAX_SIZE_MB * 1024 * 1024) + b'"}\n'
            path.write_bytes(huge_line + b'{"event":"new"}\n{"unfinished":')
            previous_path.write_bytes(huge_line + b'{"event":"recent"}\n')
            with patch.object(ApiEventCapture, "DEFAULT_PATH", str(path)):
                capture = ApiEventCapture()
            for file_path in (path, previous_path):
                payload = file_path.read_bytes()
                self.assertLessEqual(len(payload), capture.max_bytes)
                for line in payload.splitlines():
                    json.loads(line)
            self.assertIn(b'"new"', path.read_bytes())
            self.assertIn(b'"recent"', previous_path.read_bytes())

    def test_failed_startup_trim_retries_before_writing(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "hudiy-api-events.log"
            huge_line = b'{"event":"' + b'x' * (ApiEventCapture.MAX_SIZE_MB * 1024 * 1024) + b'"}\n'
            path.write_bytes(huge_line + b'{"event":"recent"}\n')
            original_size = path.stat().st_size
            with patch.object(ApiEventCapture, "DEFAULT_PATH", str(path)), \
                 patch("hudiy_client.api_event_capture.os.replace", side_effect=OSError("trim failed")):
                capture = ApiEventCapture()
            self.assertEqual(path.stat().st_size, original_size)
            self.assertFalse(Path(capture.previous_path).exists())
            capture.record("recovered")
            self.assertLessEqual(path.stat().st_size, capture.max_bytes)
            self.assertTrue(all(json.loads(line) for line in path.read_text().splitlines()))


if __name__ == "__main__":
    unittest.main()
