import io
import os
import sys
import tempfile
import unittest
import zipfile

try:
    from flask import Flask
except ImportError:  # Desktop unit-test Python may not have the Pi web stack.
    Flask = None


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if Flask is not None:
    from hudiy_dataview.file_portal import build_collections, register_file_portal  # noqa: E402


@unittest.skipIf(Flask is None, "Flask is installed by the Pi installer")
class FilePortalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = self.temporary.name
        self.firmware = os.path.join(root, "firmware")
        self.logs = os.path.join(root, "logs")
        self.service_logs = os.path.join(root, "service")
        self.runtime_logs = os.path.join(root, "runtime")
        self.api_logs = os.path.join(root, "hudiy-api")
        os.makedirs(self.firmware)
        os.makedirs(self.logs)
        os.makedirs(os.path.join(self.service_logs, "2026-09-17"))
        os.makedirs(self.runtime_logs)
        os.makedirs(self.api_logs)
        with open(os.path.join(self.logs, "drive.csv"), "wb") as handle:
            handle.write(b"timestamp,rpm\n")
        with open(os.path.join(self.service_logs, "2026-09-17", "tp2_worker.log"), "wb") as handle:
            handle.write(b"worker output")
        with open(os.path.join(self.runtime_logs, "can_handler.log"), "wb") as handle:
            handle.write(b"live output")
        with open(os.path.join(self.api_logs, "hudiy-api-events.log"), "wb") as handle:
            handle.write(b'{"event":"capture_started"}\n')

        config = {
            "data_logger": {"log_directory": self.logs},
            "features": {"log_saver": {"log_directory": self.service_logs}},
            "haldex": {"firmware_dir": self.firmware},
            "diagnostics": {"hudiy_api_capture": {
                "path": os.path.join(self.api_logs, "hudiy-api-events.log")
            }},
            "file_portal": {
                "upload_pin": "2468",
                "runtime_log_directory": self.runtime_logs,
                "firmware_targets": [{
                    "id": "engine",
                    "label": "Engine ECU",
                    "directory": self.firmware,
                    "extensions": [".bin"],
                    "validator": "test",
                    "max_size_mb": 1,
                }],
            },
        }
        self.validated = []
        app = Flask(__name__)
        register_file_portal(app, config, {"test": self.validated.append})
        app.testing = True
        self.client = app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_catalog_separates_drive_and_service_logs(self):
        response = self.client.get("/api/files")
        self.assertEqual(response.status_code, 200)
        collections = {item["id"]: item for item in response.get_json()["collections"]}
        self.assertEqual([item["name"] for item in collections["drive_logs"]["files"]], ["drive.csv"])
        self.assertEqual([item["name"] for item in collections["service_logs"]["files"]], ["tp2_worker.log"])
        self.assertEqual([item["name"] for item in collections["runtime_logs"]["files"]], ["can_handler.log"])
        self.assertEqual([item["name"] for item in collections["hudiy_api"]["files"]], ["hudiy-api-events.log"])
        self.assertTrue(response.get_json()["pin_required"])
        self.assertEqual(response.get_json()["all_logs_archive_url"], "/api/files/archive/all_logs")

    def test_eps_configuration_adds_a_separate_firmware_target(self):
        eps_directory = os.path.join(self.temporary.name, "eps")
        config = {
            "haldex": {"firmware_dir": self.firmware},
            "eps": {"firmware_dir": eps_directory},
            "file_portal": {"firmware_targets": [{
                "id": "haldex", "directory": self.firmware,
                "extensions": [".bin"], "validator": "haldex",
            }]},
        }
        collections = {item.id: item for item in build_collections(config)}
        self.assertEqual(collections["firmware_haldex"].directory, self.firmware)
        self.assertEqual(collections["firmware_pq-eps"].directory, eps_directory)
        self.assertEqual(collections["firmware_pq-eps"].validator, "pq-eps")

    def test_upload_requires_pin_validates_and_does_not_overwrite(self):
        denied = self.client.post("/api/files/upload/firmware_engine", data={
            "file": (io.BytesIO(b"firmware"), "tune.bin")
        })
        self.assertEqual(denied.status_code, 403)

        response = self.client.post("/api/files/upload/firmware_engine",
                                    headers={"X-Hudiy-Pin": "2468"}, data={
                                        "file": (io.BytesIO(b"firmware"), "tune.bin")
                                    })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.validated), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.firmware, "tune.bin")))

        duplicate = self.client.post("/api/files/upload/firmware_engine",
                                     headers={"X-Hudiy-Pin": "2468"}, data={
                                         "file": (io.BytesIO(b"other"), "tune.bin")
                                     })
        self.assertEqual(duplicate.status_code, 409)

    def test_rejects_wrong_extension_and_path_escape(self):
        response = self.client.post("/api/files/upload/firmware_engine",
                                    headers={"X-Hudiy-Pin": "2468"}, data={
                                        "file": (io.BytesIO(b"nope"), "notes.txt")
                                    })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/files/download/drive_logs/../secret.csv").status_code, 404)

    def test_archive_contains_relative_paths(self):
        response = self.client.get("/api/files/archive/service_logs")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.namelist(), ["2026-09-17/tp2_worker.log"])

        all_logs = self.client.get("/api/files/archive/all_logs")
        with zipfile.ZipFile(io.BytesIO(all_logs.data)) as archive:
            self.assertIn("drive_logs/drive.csv", archive.namelist())
            self.assertIn("runtime_logs/can_handler.log", archive.namelist())


if __name__ == "__main__":
    unittest.main()
