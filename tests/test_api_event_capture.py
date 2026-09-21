import json
import tempfile
import unittest
from pathlib import Path

from hudiy_client.api_event_capture import ApiEventCapture


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
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hudiy-api-events.log"
            capture = ApiEventCapture({"path": str(path), "max_size_mb": 1})

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

    def test_disabled_capture_creates_no_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disabled.log"
            capture = ApiEventCapture({"enabled": False, "path": str(path)})
            capture.record("navigation_status", _Message())
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
