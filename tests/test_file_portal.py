import io
import os
import sys
import threading
import time
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
        self.app.extensions["file_portal_archive_jobs"].close()
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
        response.close()
        all_logs.close()

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
        response.close()

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

    def test_archive_uses_compressed_temporary_file_and_closes_after_download(self):
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
                self.assertTrue(all(item.compress_type == zipfile.ZIP_DEFLATED for item in archive.infolist()))
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


    def wait_for_job(self, status_url, expected="ready"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = self.client.get(status_url)
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            if payload["state"] in ("ready", "error"):
                self.assertEqual(payload["state"], expected, payload)
                return payload
            threading.Event().wait(0.005)
        self.fail("Archive worker did not complete")

    def test_archive_start_poll_and_catalog_respond_while_worker_is_paused(self):
        from hudiy_dataview.file_portal import _write_archive
        entered = threading.Event()
        resume = threading.Event()

        def paused(*args, **kwargs):
            entered.set()
            self.assertTrue(resume.wait(5))
            return _write_archive(*args, **kwargs)

        with patch("hudiy_dataview.file_portal._write_archive", side_effect=paused):
            try:
                started = self.client.post("/api/files/archive/service_logs")
                self.assertEqual(started.status_code, 202)
                job = started.get_json()
                self.assertTrue(entered.wait(2))
                poll = self.client.get(job["status_url"])
                self.assertEqual(poll.status_code, 200)
                self.assertEqual(poll.headers["Cache-Control"], "no-store")
                self.assertEqual(poll.get_json()["state"], "preparing")
                self.assertLess(poll.get_json()["percent"], 100)
                self.assertIsNone(poll.get_json()["download_url"])
                self.assertIsNone(poll.get_json()["error"])
                self.assertEqual(self.client.get("/api/files").status_code, 200)
                self.assertEqual(self.client.post("/api/files/archive/all_logs").status_code, 409)
                self.assertEqual(self.client.get(job["status_url"] + "/download").status_code, 409)
            finally:
                resume.set()
            ready = self.wait_for_job(job["status_url"])
        self.assertEqual(ready["percent"], 100)

    def test_archive_job_reports_progress_within_a_file(self):
        from hudiy_dataview.file_portal import ARCHIVE_CHUNK_SIZE
        contents = b"timestamp,rpm\n" * (ARCHIVE_CHUNK_SIZE // 7)
        with open(os.path.join(self.logs, "drive.csv"), "wb") as source:
            source.write(contents)
        paused = threading.Event()
        resume = threading.Event()
        sleep = time.sleep

        def yield_after_chunk(duration):
            if not paused.is_set() and self.app.extensions["file_portal_archive_jobs"].jobs and any(job["bytes_processed"] for job in self.app.extensions["file_portal_archive_jobs"].jobs.values()):
                paused.set()
                self.assertTrue(resume.wait(5))
            sleep(duration)

        with patch("hudiy_dataview.file_portal.time.sleep", side_effect=yield_after_chunk):
            try:
                start = self.client.post("/api/files/archive/drive_logs").get_json()
                self.assertTrue(paused.wait(2))
                progress = self.client.get(start["status_url"]).get_json()
                self.assertEqual(progress["state"], "preparing")
                self.assertEqual(progress["bytes_processed"], ARCHIVE_CHUNK_SIZE)
                self.assertEqual(progress["total_bytes"], len(contents))
                self.assertEqual(progress["current_file"], "drive.csv")
                self.assertGreater(progress["percent"], 0)
                self.assertLess(progress["percent"], 100)
            finally:
                resume.set()
            ready = self.wait_for_job(start["status_url"])
        response = self.client.get(ready["download_url"])
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.read("drive.csv"), contents)
            self.assertEqual(archive.getinfo("drive.csv").compress_type, zipfile.ZIP_DEFLATED)
        self.assertLess(len(response.data), len(contents) // 4)
        response.close()

    def test_archive_job_folder_and_all_logs_downloads_are_reusable(self):
        for url, expected in [("/api/files/archive/service_logs/2026-09-17/1", "2026-09-17/1/tp2_worker.log"),
                              ("/api/files/archive/all_logs", "runtime_logs/can_handler.log")]:
            start = self.client.post(url)
            self.assertEqual(start.status_code, 202)
            ready = self.wait_for_job(start.get_json()["status_url"])
            first = self.client.get(ready["download_url"], buffered=False)
            second = self.client.get(ready["download_url"], buffered=False)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            first_data = first.get_data()
            second_data = second.get_data()
            self.assertEqual(first_data, second_data)
            self.assertEqual(first.content_length, len(first_data))
            with zipfile.ZipFile(io.BytesIO(first_data)) as archive:
                self.assertIn(expected, archive.namelist())
                self.assertTrue(all(member.compress_type == zipfile.ZIP_DEFLATED for member in archive.infolist()))
            first.close()
            second.close()
            self.assertEqual(self.client.get(ready["status_url"]).get_json()["state"], "ready")
            self.assertEqual(self.app.extensions["file_portal_archive_jobs"].jobs[ready["id"]]["downloads"], 0)

    def test_archive_job_rejects_unknown_and_escaping_paths(self):
        for url in ("/api/files/archive/missing", "/api/files/archive/service_logs/../",
                    "/api/files/archive/service_logs/missing", "/api/files/archive/all_logs/folder"):
            self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(self.client.get("/api/files/archive-jobs/missing").status_code, 404)
        self.assertEqual(self.client.get("/api/files/archive-jobs/missing/download").status_code, 404)

    def test_archive_job_errors_release_temporary_storage_and_worker_slot(self):
        manager = self.app.extensions["file_portal_archive_jobs"]
        with patch("hudiy_dataview.file_portal.zipfile.ZipFile.open", side_effect=OSError("disk full")):
            start = self.client.post("/api/files/archive/service_logs").get_json()
            failed = self.wait_for_job(start["status_url"], "error")
        self.assertIsInstance(failed["error"], str)
        self.assertIsNone(failed["download_url"])
        self.assertLess(failed["percent"], 100)
        self.assertIsNone(manager.jobs[failed["id"]]["path"])
        successful = self.client.post("/api/files/archive/service_logs")
        self.assertEqual(successful.status_code, 202)
        self.wait_for_job(successful.get_json()["status_url"])

    def test_archive_job_size_growth_truncation_and_member_limits(self):
        from hudiy_dataview.file_portal import ARCHIVE_SIZE_ERROR
        manager = self.app.extensions["file_portal_archive_jobs"]
        manager.archive_limit = 1024
        for snapshot_size, message in [(1025, ARCHIVE_SIZE_ERROR), (14, None)]:
            with patch("hudiy_dataview.file_portal.os.fstat") as snapshot:
                snapshot.return_value.st_size = snapshot_size
                start = self.client.post("/api/files/archive/service_logs").get_json()
                failed = self.wait_for_job(start["status_url"], "error")
            if message:
                self.assertEqual(failed["error"], message)
            self.assertIsNone(manager.jobs[failed["id"]]["path"])
        with patch("hudiy_dataview.file_portal.ARCHIVE_MEMBER_LIMIT", 0):
            start = self.client.post("/api/files/archive/service_logs").get_json()
            self.assertEqual(self.wait_for_job(start["status_url"], "error")["error"], ARCHIVE_SIZE_ERROR)

    def test_archive_enumeration_stops_at_member_limit_before_creating_storage(self):
        path = os.path.join(self.logs, "drive.csv")
        visited = []

        def many_members(*args, **kwargs):
            for index in range(100):
                visited.append(index)
                yield f"drive{index}.csv", path

        with patch("hudiy_dataview.file_portal._walk", side_effect=many_members), \
                patch("hudiy_dataview.file_portal.ARCHIVE_MEMBER_LIMIT", 2), \
                patch("hudiy_dataview.file_portal.tempfile.NamedTemporaryFile") as temporary:
            start = self.client.post("/api/files/archive/drive_logs").get_json()
            self.wait_for_job(start["status_url"], "error")
        self.assertEqual(visited, [0, 1, 2])
        temporary.assert_not_called()

    def test_archive_rejects_file_replaced_by_symlink_after_scan(self):
        from hudiy_dataview.file_portal import _write_archive
        entered = threading.Event()
        resume = threading.Event()

        def paused(*args, **kwargs):
            entered.set()
            self.assertTrue(resume.wait(5))
            return _write_archive(*args, **kwargs)

        with patch("hudiy_dataview.file_portal._write_archive", side_effect=paused):
            try:
                start = self.client.post("/api/files/archive/drive_logs").get_json()
                self.assertTrue(entered.wait(2))
                original = os.stat

                def replaced(path, *args, **kwargs):
                    result = original(path, *args, **kwargs)
                    if kwargs.get("follow_symlinks") is False and path.endswith("drive.csv"):
                        values = list(result)
                        values[0] = 0o120777
                        return os.stat_result(values)
                    return result

                with patch("hudiy_dataview.file_portal.os.stat", side_effect=replaced):
                    resume.set()
                    failed = self.wait_for_job(start["status_url"], "error")
            finally:
                resume.set()
        self.assertIsNone(self.app.extensions["file_portal_archive_jobs"].jobs[failed["id"]]["path"])

    def test_archive_limits_downloads_and_preserves_bound_when_results_are_busy(self):
        prepared = []
        responses = []
        try:
            for _ in range(2):
                start = self.client.post("/api/files/archive/service_logs").get_json()
                ready = self.wait_for_job(start["status_url"])
                prepared.append(ready)
                responses.append(self.client.get(ready["download_url"], buffered=False))
            for _ in range(3):
                responses.append(self.client.get(prepared[0]["download_url"], buffered=False))
            self.assertEqual(self.client.get(prepared[0]["download_url"]).status_code, 409)
            self.assertEqual(self.client.post("/api/files/archive/service_logs").status_code, 409)
            self.assertEqual(len(self.app.extensions["file_portal_archive_jobs"].jobs), 2)
        finally:
            for response in responses:
                response.close()
        started = self.client.post("/api/files/archive/service_logs")
        self.assertEqual(started.status_code, 202)
        self.wait_for_job(started.get_json()["status_url"])

    def test_archive_scavenge_only_removes_old_owned_prefix_regular_files(self):
        manager = self.app.extensions["file_portal_archive_jobs"]
        paths = []
        for name in ("hudiy-archive-old.zip", "hudiy-archive-recent.zip", "other-old.zip"):
            path = os.path.join(self.temporary.name, name)
            with open(path, "wb") as source:
                source.write(b"temporary")
            paths.append(path)
        old = time.time() - 2 * 24 * 60 * 60
        os.utime(paths[0], (old, old))
        os.utime(paths[2], (old, old))
        with patch("hudiy_dataview.file_portal.tempfile.gettempdir", return_value=self.temporary.name):
            manager._scavenge()
        self.assertFalse(os.path.exists(paths[0]))
        self.assertTrue(os.path.exists(paths[1]))
        self.assertTrue(os.path.exists(paths[2]))

    def test_archive_job_completed_retention_is_bounded(self):
        manager = self.app.extensions["file_portal_archive_jobs"]
        prepared = []
        for _ in range(3):
            start = self.client.post("/api/files/archive/service_logs").get_json()
            ready = self.wait_for_job(start["status_url"])
            prepared.append((ready, manager.jobs[ready["id"]]["path"]))
        self.assertEqual(len(manager.jobs), 2)
        self.assertEqual(self.client.get(prepared[0][0]["status_url"]).status_code, 404)
        self.assertFalse(os.path.exists(prepared[0][1]))
        self.assertTrue(os.path.exists(prepared[-1][1]))

    def test_archive_job_expires_without_more_http_requests(self):
        manager = self.app.extensions["file_portal_archive_jobs"]
        with patch("hudiy_dataview.file_portal.ARCHIVE_JOB_TTL", 0.1):
            start = self.client.post("/api/files/archive/service_logs").get_json()
            ready = self.wait_for_job(start["status_url"])
            path = manager.jobs[ready["id"]]["path"]
            deadline = time.monotonic() + 2
            while os.path.exists(path) and time.monotonic() < deadline:
                threading.Event().wait(0.02)
            self.assertFalse(os.path.exists(path))
        self.assertEqual(self.client.get(ready["status_url"]).status_code, 404)

    def test_archive_expiry_defers_unlink_until_download_closes(self):
        manager = self.app.extensions["file_portal_archive_jobs"]
        start = self.client.post("/api/files/archive/service_logs").get_json()
        ready = self.wait_for_job(start["status_url"])
        job = manager.jobs[ready["id"]]
        path = job["path"]
        response = self.client.get(ready["download_url"], buffered=False)
        with manager.lock:
            job["finished"] -= 301
        self.assertEqual(self.client.get(ready["status_url"]).status_code, 404)
        self.assertTrue(os.path.exists(path))
        with zipfile.ZipFile(io.BytesIO(response.get_data())) as archive:
            self.assertEqual(archive.read("2026-09-17/1/tp2_worker.log"), b"worker output")
        response.close()
        self.assertFalse(os.path.exists(path))
        self.assertNotIn(ready["id"], manager.jobs)

    def test_job_response_creation_failure_releases_download_handle(self):
        manager = self.app.extensions["file_portal_archive_jobs"]
        start = self.client.post("/api/files/archive/service_logs").get_json()
        ready = self.wait_for_job(start["status_url"])
        with patch("hudiy_dataview.file_portal.send_file", side_effect=RuntimeError("response failed")):
            with self.assertRaisesRegex(RuntimeError, "response failed"):
                self.client.get(ready["download_url"])
        self.assertEqual(manager.jobs[ready["id"]]["downloads"], 0)
        response = self.client.get(ready["download_url"])
        self.assertEqual(response.status_code, 200)
        response.close()


if __name__ == "__main__":
    unittest.main()
