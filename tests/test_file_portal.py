import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

try:
    from flask import Flask
except ImportError:  # Desktop unit-test Python may not have the Pi web stack.
    Flask = None


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if Flask is not None:
    from hudiy_dataview.file_portal import build_collections, register_file_portal, cache_hudiy_theme  # noqa: E402


@unittest.skipIf(Flask is None, "Flask is installed by the Pi installer")
class FilePortalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = self.temporary.name
        self.firmware = os.path.join(root, "firmware")
        self.logs = os.path.join(root, "logs")
        self.service_logs = os.path.join(root, "service")
        self.runtime_logs = os.path.join(root, "runtime")
        self.api_logs = os.path.join(root, "logs", "hudiy-api")
        os.makedirs(self.firmware)
        os.makedirs(self.logs)
        os.makedirs(os.path.join(self.service_logs, "2026-09-17", "1"))
        os.makedirs(self.runtime_logs)
        os.makedirs(self.api_logs)
        with open(os.path.join(self.logs, "drive.csv"), "wb") as handle:
            handle.write(b"timestamp,rpm\n")
        with open(os.path.join(self.service_logs, "2026-09-17", "1", "tp2_worker.log"), "wb") as handle:
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
                "enabled": False, "path": os.path.join(root, "obsolete-api-location.log")
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
        real_expanduser = os.path.expanduser
        with patch("hudiy_dataview.file_portal.os.path.expanduser", side_effect=lambda path:
                   os.path.join(root, path[2:]) if path.startswith('~/') else real_expanduser(path)):
            register_file_portal(app, config, {"test": self.validated.append})
        app.testing = True
        self.app = app
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

    def test_theme_is_available_without_pin_and_tracks_native_updates(self):
        self.assertEqual(self.client.get("/api/files/theme").get_json(), {"theme": None})
        palette = {"primary": "#bfd98f", "surface": "#12170f", "darkThemeEnabled": True}
        self.assertTrue(cache_hudiy_theme(self.app, palette))
        palette["primary"] = "#ffffff"  # The cache must own its snapshot.
        response = self.client.get("/api/files/theme")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.get_json()["theme"]["primary"], "#bfd98f")
        self.assertTrue(response.get_json()["theme"]["darkThemeEnabled"])
        cache_hudiy_theme(self.app, {"primary": "#435b33", "darkThemeEnabled": False})
        self.assertFalse(self.client.get("/api/files/theme").get_json()["theme"]["darkThemeEnabled"])

    def test_theme_exposes_only_color_roles_and_preserves_cache_on_invalid_payload(self):
        cache_hudiy_theme(self.app, {"primary": "#abcdef", "onSurface": "#eee",
                                    "darkThemeEnabled": False, "secret": "private",
                                    "surface": "url(https://example.test/image)", "nested": {"value": "#fff"}})
        self.assertEqual(self.client.get("/api/files/theme").get_json()["theme"],
                         {"primary": "#abcdef", "onSurface": "#eee", "darkThemeEnabled": False})
        self.assertFalse(cache_hudiy_theme(self.app, None))
        self.assertFalse(cache_hudiy_theme(self.app, {"primary": "invalid"}))
        self.assertEqual(self.client.get("/api/files/theme").get_json()["theme"]["primary"], "#abcdef")

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
        self.assertIn("rnse-service_logs-", response.headers["Content-Disposition"])
        self.assertNotIn("tp2_worker.log", response.headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.namelist(), ["2026-09-17/1/tp2_worker.log"])

        all_logs = self.client.get("/api/files/archive/all_logs")
        with zipfile.ZipFile(io.BytesIO(all_logs.data)) as archive:
            self.assertIn("drive_logs/drive.csv", archive.namelist())
            self.assertIn("runtime_logs/can_handler.log", archive.namelist())

    def test_saved_service_folders_have_individual_bundles(self):
        folder = os.path.join(self.service_logs, "2026-09-17", "1")
        with open(os.path.join(folder, "can_handler.log"), "wb") as handle:
            handle.write(b"CAN output")
        other = os.path.join(self.service_logs, "2026-09-17", "2")
        os.makedirs(other)
        with open(os.path.join(other, "can_handler.log"), "wb") as handle:
            handle.write(b"next capture")
        collections = {item["id"]: item for item in self.client.get("/api/files").get_json()["collections"]}
        groups = collections["service_logs"]["groups"]
        self.assertEqual([group["path"] for group in groups], ["2026-09-17/2", "2026-09-17/1"])
        self.assertEqual(groups[1]["count"], 2)
        self.assertEqual(groups[1]["total_size"], len(b"worker outputCAN output"))
        self.assertEqual(groups[1]["date"], "2026-09-17")
        response = self.client.get(groups[1]["archive_url"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("rnse-service_logs-2026-09-17-1-", response.headers["Content-Disposition"])
        self.assertNotIn("tp2_worker.log", response.headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.namelist(), ["2026-09-17/1/can_handler.log", "2026-09-17/1/tp2_worker.log"])
            self.assertEqual(archive.read("2026-09-17/1/can_handler.log"), b"CAN output")

    def test_logs_sort_by_recording_date_and_numeric_sequence(self):
        for relative, modified in [("2026-09-18/haldex_0002.csv", 500),
                                   ("2026-09-18/haldex_0010.csv", 100),
                                   ("2026-09-17/haldex_0020.csv", 999999),
                                   ("haldex_20260916_235959_123456.csv", 9999999)]:
            path = os.path.join(self.logs, *relative.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"timestamp,rpm\n")
            os.utime(path, (modified, modified))
        os.utime(os.path.join(self.logs, "drive.csv"), (0, 0))
        collections = {item["id"]: item for item in self.client.get("/api/files").get_json()["collections"]}
        files = collections["drive_logs"]["files"]
        self.assertEqual([item["path"] for item in files[:4]], [
            "2026-09-18/haldex_0010.csv", "2026-09-18/haldex_0002.csv",
            "2026-09-17/haldex_0020.csv", "haldex_20260916_235959_123456.csv"])
        self.assertEqual(files[3]["date"], "2026-09-16")
        self.assertEqual(files[0]["folder"], "2026-09-18")
        self.assertEqual(files[0]["sequence"], 10)
        self.assertIsNone(files[3]["sequence"])

    def test_catalog_keeps_every_file_in_large_folder(self):
        folder = os.path.join(self.logs, "2026-09-18")
        os.makedirs(folder)
        for sequence in range(1, 502):
            with open(os.path.join(folder, f"haldex_{sequence:04d}.csv"), "wb") as handle:
                handle.write(b"timestamp,rpm\n")
        collections = {item["id"]: item for item in self.client.get("/api/files").get_json()["collections"]}
        self.assertEqual(collections["drive_logs"]["count"], 502)
        self.assertEqual(len(collections["drive_logs"]["files"]), 502)
        self.assertEqual(collections["drive_logs"]["groups"][0]["count"], 501)

    def test_folder_bundle_rejects_escape_missing_and_prefix_sibling(self):
        for path in ("../", "missing", "2026-09-17/11"):
            self.assertEqual(self.client.get("/api/files/archive/service_logs/" + path).status_code, 404)
        self.assertEqual(self.client.get("/api/files/archive/all_logs/2026-09-17").status_code, 404)

    def test_folder_bundle_keeps_collection_size_limit(self):
        from hudiy_dataview.file_portal import DEFAULT_ARCHIVE_LIMIT
        with patch("hudiy_dataview.file_portal.os.path.getsize", return_value=DEFAULT_ARCHIVE_LIMIT + 1), \
                patch("hudiy_dataview.file_portal.tempfile.TemporaryFile") as temporary:
            response = self.client.get("/api/files/archive/service_logs/2026-09-17/1")
        self.assertEqual(response.status_code, 413)
        temporary.assert_not_called()

    def test_archive_uses_uncompressed_temporary_file_and_closes_after_download(self):
        handles = []
        original = tempfile.TemporaryFile

        def tracked_temporary(*args, **kwargs):
            handle = original(*args, **kwargs)
            handles.append(handle)
            return handle

        with patch("hudiy_dataview.file_portal.tempfile.TemporaryFile", side_effect=tracked_temporary):
            response = self.client.get("/api/files/archive/all_logs", buffered=False)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(handles), 1)
            self.assertFalse(handles[0].closed)
            self.assertTrue(os.path.isfile(handles[0].name))
            contents = response.get_data()
            self.assertEqual(response.content_length, len(contents))
            with zipfile.ZipFile(io.BytesIO(contents)) as archive:
                self.assertTrue(archive.infolist())
                self.assertTrue(all(item.compress_type == zipfile.ZIP_STORED for item in archive.infolist()))
            response.close()
            self.assertTrue(handles[0].closed)

    def test_archive_temporary_file_closes_on_disconnect(self):
        handle = tempfile.TemporaryFile(mode="w+b")
        with patch("hudiy_dataview.file_portal.tempfile.TemporaryFile", return_value=handle):
            response = self.client.get("/api/files/archive/service_logs", buffered=False)
            self.assertFalse(handle.closed)
            response.close()
        self.assertTrue(handle.closed)

    def test_archive_temporary_file_closes_on_read_error(self):
        handle = tempfile.TemporaryFile(mode="w+b")
        with patch("hudiy_dataview.file_portal.tempfile.TemporaryFile", return_value=handle), \
                patch("hudiy_dataview.file_portal.zipfile.ZipFile.open", side_effect=OSError("file removed")):
            response = self.client.get("/api/files/archive/service_logs")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(handle.closed)

    def test_archive_copies_only_initial_length_of_growing_live_log(self):
        path = os.path.join(self.api_logs, "hudiy-api-events.log")
        with open(path, "rb") as source:
            initial = source.read()
        original = os.fstat
        grown = []

        def grow_after_snapshot(descriptor):
            snapshot = original(descriptor)
            if not grown:
                with open(path, "ab") as source:
                    source.write(b"appended after snapshot\n")
                grown.append(True)
            return snapshot

        with patch("hudiy_dataview.file_portal.os.fstat", side_effect=grow_after_snapshot):
            response = self.client.get("/api/files/archive/hudiy_api")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.get_data())) as archive:
            self.assertEqual(archive.read("hudiy-api-events.log"), initial)
        response.close()

    def test_archive_rechecks_size_limit_when_file_grows_before_copy(self):
        from hudiy_dataview.file_portal import DEFAULT_ARCHIVE_LIMIT
        handle = tempfile.TemporaryFile(mode="w+b")
        with patch("hudiy_dataview.file_portal.tempfile.TemporaryFile", return_value=handle), \
                patch("hudiy_dataview.file_portal.os.fstat") as stat:
            stat.return_value.st_size = DEFAULT_ARCHIVE_LIMIT + 1
            response = self.client.get("/api/files/archive/service_logs")
        self.assertEqual(response.status_code, 413)
        self.assertTrue(handle.closed)

    def test_archive_rejects_log_truncated_during_copy(self):
        handle = tempfile.TemporaryFile(mode="w+b")
        with patch("hudiy_dataview.file_portal.tempfile.TemporaryFile", return_value=handle), \
                patch("hudiy_dataview.file_portal.os.fstat") as stat:
            stat.return_value.st_size = len(b"worker output") + 1
            response = self.client.get("/api/files/archive/service_logs")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(handle.closed)

    def test_archive_temporary_file_closes_when_response_creation_fails(self):
        handle = tempfile.TemporaryFile(mode="w+b")
        with patch("hudiy_dataview.file_portal.tempfile.TemporaryFile", return_value=handle), \
                patch("hudiy_dataview.file_portal.send_file", side_effect=RuntimeError("response failed")):
            with self.assertRaisesRegex(RuntimeError, "response failed"):
                self.client.get("/api/files/archive/service_logs")
        self.assertTrue(handle.closed)


if __name__ == "__main__":
    unittest.main()
