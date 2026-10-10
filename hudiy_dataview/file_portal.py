"""Safe, configurable file-transfer routes for Hudiy DataView.

The portal deliberately exposes named collections instead of arbitrary paths.
That keeps a browser connected to the car from wandering through the Pi's home
directory, while allowing more firmware targets to be added in config later.
"""

from __future__ import annotations

import os
import re
import stat
import threading
import uuid
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Mapping, Optional
from urllib.parse import quote

from flask import abort, jsonify, request, send_file


DEFAULT_UPLOAD_LIMIT = 16 * 1024 * 1024
DEFAULT_ARCHIVE_LIMIT = 256 * 1024 * 1024
ARCHIVE_CHUNK_SIZE = 256 * 1024
ARCHIVE_JOB_TTL = 300
ARCHIVE_JOB_RETENTION = 2
ARCHIVE_MEMBER_LIMIT = 10000
ARCHIVE_SIZE_ERROR = "This collection is too large to bundle at once."
ARCHIVE_READ_ERROR = "A file changed or temporary storage is unavailable. Try again."
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
THEME_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class _ArchiveLimitExceeded(Exception):
    pass



def _write_archive(archive, members, archive_limit, progress=None):
    """Snapshot each source length, never follow a replaced symlink, and yield."""
    if len(members) > ARCHIVE_MEMBER_LIMIT:
        raise _ArchiveLimitExceeded
    sizes = []
    total = 0
    for index, (_, path) in enumerate(members):
        size = os.path.getsize(path)
        sizes.append(size)
        total += size
        if total > archive_limit:
            raise _ArchiveLimitExceeded
        if index % 64 == 0:
            time.sleep(0.001)
    copied = 0
    snapshot_total = 0
    if progress:
        progress(0, total, None)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=1) as bundle:
        for index, (member_name, path) in enumerate(members):
            if index % 64 == 0:
                time.sleep(0.001)
            before = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode):
                raise OSError("An archive source is no longer a regular file")
            with open(path, "rb") as source:
                snapshot = os.fstat(source.fileno())
                # Check identity separately from the length snapshot. This also
                # catches a source replaced by a symlink between stat and open.
                identity = os.stat(source.fileno())
                if (before.st_dev, before.st_ino) != (identity.st_dev, identity.st_ino):
                    raise OSError("An archive source changed while opening")
                remaining = snapshot.st_size
                total += remaining - sizes[index]
                snapshot_total += remaining
                if total > archive_limit or snapshot_total > archive_limit:
                    raise _ArchiveLimitExceeded
                if progress:
                    progress(copied, total, member_name)
                info = zipfile.ZipInfo.from_file(path, member_name)
                info.file_size = remaining
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = 1
                with bundle.open(info, "w", force_zip64=remaining >= zipfile.ZIP64_LIMIT) as output:
                    while remaining:
                        chunk = source.read(min(ARCHIVE_CHUNK_SIZE, remaining))
                        if not chunk:
                            raise OSError("A log was truncated while preparing its archive")
                        output.write(chunk)
                        remaining -= len(chunk)
                        copied += len(chunk)
                        if progress:
                            progress(copied, total, member_name)
                        # threading and sleep are cooperative under the mock
                        # server's gevent monkey patch. Yield after bounded work
                        # in both runtimes so polling and telemetry stay live.
                        time.sleep(0.001)
    return archive.tell()


class _ArchiveJobs:
    """One lazy worker and a bounded set of expiring disk-backed results."""

    def __init__(self, prepare, archive_limit, logger):
        self.prepare = prepare
        self.archive_limit = archive_limit
        self.logger = logger
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.jobs = {}
        self.active = None
        self.worker = None
        self.stopped = False
        self.last_scavenge = None

    def _discard(self, job):
        if job["downloads"]:
            job["expired"] = True
            return False
        if job["path"]:
            try:
                os.unlink(job["path"])
            except FileNotFoundError:
                pass
            except OSError:
                # Retry temporary storage failures at the next worker wake.
                job["expired"] = True
                return False
        self.jobs.pop(job["id"], None)
        return True

    def _cleanup(self):
        now = time.monotonic()
        for job in list(self.jobs.values()):
            if job["finished"] is not None and (job["expired"] or now - job["finished"] >= ARCHIVE_JOB_TTL):
                self._discard(job)

    def _payload(self, job):
        return {key: job[key] for key in ("id", "state", "percent", "bytes_processed", "total_bytes", "current_file", "error")} | {
            "status_url": f"/api/files/archive-jobs/{job['id']}",
            "download_url": f"/api/files/archive-jobs/{job['id']}/download" if job["state"] == "ready" else None,
        }

    def start(self, collection_id, relative_path):
        with self.lock:
            self._cleanup()
            if self.active or self.stopped:
                return None
            completed = [job for job in self.jobs.values() if job["finished"] is not None]
            while len(completed) >= ARCHIVE_JOB_RETENTION:
                removable = next((job for job in completed if not job["downloads"]), None)
                if removable is None or not self._discard(removable):
                    return None
                completed.remove(removable)
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "state": "queued", "percent": 0,
                   "bytes_processed": 0, "total_bytes": 0, "current_file": None,
                   "error": None, "path": None, "size": 0, "name": None,
                   "finished": None, "expired": False, "downloads": 0,
                   "collection_id": collection_id, "relative_path": relative_path}
            self.jobs[job_id] = job
            self.active = job_id
            if self.worker is None:
                self.worker = threading.Thread(target=self._run, name="portal-archive", daemon=True)
                self.worker.start()
            self.wake.set()
            return self._payload(job)

    def status(self, job_id):
        with self.lock:
            self._cleanup()
            job = self.jobs.get(job_id)
            return self._payload(job) if job and not job["expired"] else None

    def _progress(self, job, processed, total, current):
        with self.lock:
            job.update(bytes_processed=processed, total_bytes=total, current_file=current,
                       percent=min(99, int(processed * 100 / total)) if total else 0)

    def _scavenge(self):
        # A process crash cannot unlink named results. Only reclaim old files
        # bearing our exact temporary prefix; leave recent/owned files alone.
        now = time.monotonic()
        if self.last_scavenge is not None and now - self.last_scavenge < ARCHIVE_JOB_TTL:
            return
        self.last_scavenge = now
        with self.lock:
            owned = {job["path"] for job in self.jobs.values() if job["path"]}
        cutoff = time.time() - 24 * 60 * 60
        try:
            with os.scandir(tempfile.gettempdir()) as entries:
                for index, entry in enumerate(entries):
                    if index % 64 == 0:
                        time.sleep(0.001)
                    if not entry.name.startswith("hudiy-archive-") or not entry.name.endswith(".zip") or entry.path in owned:
                        continue
                    try:
                        if entry.is_file(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_mtime < cutoff:
                            os.unlink(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass

    def _run(self):
        while True:
            self._scavenge()
            with self.lock:
                self._cleanup()
                if self.stopped or (self.active is None and not self.jobs):
                    self.worker = None
                    return
                job = self.jobs.get(self.active)
                self.wake.clear()
                if job:
                    job["state"] = "preparing"
            if not job:
                self.wake.wait(min(30, ARCHIVE_JOB_TTL))
                continue
            try:
                members, folder = self.prepare(job["collection_id"], job["relative_path"])
                with tempfile.NamedTemporaryFile(mode="w+b", prefix="hudiy-archive-", suffix=".zip", delete=False) as archive:
                    with self.lock:
                        job["path"] = archive.name
                    size = _write_archive(archive, members, self.archive_limit,
                                          lambda processed, total, current: self._progress(job, processed, total, current))
                stamp = time.strftime("%Y%m%d-%H%M%S")
                folder_name = "-" + folder.replace("/", "-") if folder else ""
                with self.lock:
                    job.update(state="ready", percent=100, size=size, current_file=None,
                               name=f"rnse-{job['collection_id']}{folder_name}-{stamp}.zip")
            except Exception as error:
                self.logger.warning("Portal archive preparation failed: %s", error)
                with self.lock:
                    job.update(state="error", error=ARCHIVE_SIZE_ERROR if isinstance(error, _ArchiveLimitExceeded) else ARCHIVE_READ_ERROR)
                    if job["path"]:
                        try:
                            os.unlink(job["path"])
                            job["path"] = None
                        except OSError:
                            job["expired"] = True
            finally:
                with self.lock:
                    job["finished"] = time.monotonic()
                    self.active = None
                    if self.stopped:
                        self._discard(job)

    def download(self, job_id):
        with self.lock:
            self._cleanup()
            job = self.jobs.get(job_id)
            if not job or job["expired"]:
                return None, 404
            if job["state"] != "ready" or job["downloads"] >= 4:
                return None, 409
            try:
                archive = open(job["path"], "rb")
            except OSError:
                job.update(state="error", error=ARCHIVE_READ_ERROR)
                return None, 409
            job["downloads"] += 1
        released = False

        def close():
            nonlocal released
            with self.lock:
                if released:
                    return
                released = True
                archive.close()
                job["downloads"] -= 1
                self._cleanup()
                self.wake.set()

        try:
            response = send_file(archive, mimetype="application/zip", as_attachment=True,
                                 download_name=job["name"])
            response.content_length = job["size"]
            # Include release in iterable.close: WSGI direct passthrough does
            # not always run Response.call_on_close callbacks.
            from werkzeug.wsgi import ClosingIterator
            response.response = ClosingIterator(response.response, close)
            response.call_on_close(close)
            return response, 200
        except BaseException:
            close()
            raise

    def close(self):
        """Stop the worker and release idle results (also useful to app tests)."""
        with self.lock:
            self.stopped = True
            for job in list(self.jobs.values()):
                if job["finished"] is not None:
                    self._discard(job)
            self.wake.set()
            worker = self.worker
        if worker:
            worker.join(timeout=5)

def cache_hudiy_theme(app, theme: object) -> bool:
    """Keep the last reported native palette for browsers outside Hudiy."""
    if not isinstance(theme, Mapping):
        return False
    palette = {
        key: value for key, value in theme.items()
        if isinstance(key, str) and re.fullmatch(r"[a-z][A-Za-z0-9]{0,63}", key)
        and isinstance(value, str) and THEME_COLOR.fullmatch(value)
    }
    if not palette:
        return False
    if isinstance(theme.get("darkThemeEnabled"), bool):
        palette["darkThemeEnabled"] = theme["darkThemeEnabled"]
    app.config["HUDIY_COLOR_SCHEME"] = palette
    return True


@dataclass(frozen=True)
class Collection:
    id: str
    label: str
    description: str
    directory: str
    extensions: tuple[str, ...]
    kind: str
    recursive: bool = True
    upload: bool = False
    validator: Optional[str] = None
    max_size: int = DEFAULT_UPLOAD_LIMIT


def _expanded(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _extensions(value: object, fallback: Iterable[str]) -> tuple[str, ...]:
    values = value if isinstance(value, list) else fallback
    cleaned = []
    for extension in values:
        if not isinstance(extension, str) or not extension.strip():
            continue
        extension = extension.strip().lower()
        cleaned.append(extension if extension.startswith(".") else "." + extension)
    return tuple(dict.fromkeys(cleaned))


def _configured_targets(config: Mapping) -> list[Collection]:
    portal = config.get("file_portal", {}) if isinstance(config, Mapping) else {}
    configured = portal.get("firmware_targets") if isinstance(portal, Mapping) else None
    if not isinstance(configured, list):
        configured = [{
            "id": "haldex",
            "label": "Haldex AWD",
            "description": "Validated controller firmware images",
            "directory": config.get("haldex", {}).get("firmware_dir", "~/haldexfw"),
            "extensions": [".bin"],
            "validator": "haldex",
            "max_size_mb": 4,
        }]
    else:
        configured = list(configured)

    # Existing installs preserve configured arrays during updates. Add the EPS
    # built-in when the newly merged top-level EPS configuration is present.
    configured_ids = {
        str(entry.get("id", "")).lower() for entry in configured
        if isinstance(entry, Mapping)
    }
    eps = config.get("eps", {}) if isinstance(config, Mapping) else {}
    if isinstance(eps, Mapping) and eps.get("firmware_dir") and "pq-eps" not in configured_ids:
        configured.append({
            "id": "pq-eps",
            "label": "PQ EPS",
            "description": "Validated full images or 4 KiB 0x5E steering datasets",
            "directory": eps["firmware_dir"],
            "extensions": [".bin"],
            "validator": "pq-eps",
            "max_size_mb": 4,
        })

    if "exhaust-valve" not in configured_ids:
        configured.append({
            "id": "exhaust-valve", "label": "Exhaust valve controller",
            "description": "SB2209 can-update.json and both native slot .bin images",
            "directory": config.get("exhaust_valve", {}).get("firmware_dir", "~/exhaustfw"),
            "extensions": [".zip", ".json", ".bin"], "validator": "exhaust-valve", "max_size_mb": 1,
        })

    targets = []
    for entry in configured:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("enabled") is False:
            continue
        target_id = str(entry.get("id", "")).lower()
        directory = entry.get("directory")
        if not SAFE_ID.fullmatch(target_id) or not isinstance(directory, str):
            continue
        max_size_mb = entry.get("max_size_mb", 16)
        try:
            max_size = max(1, min(int(max_size_mb), 128)) * 1024 * 1024
        except (TypeError, ValueError):
            max_size = DEFAULT_UPLOAD_LIMIT
        targets.append(Collection(
            id="firmware_" + target_id,
            label=str(entry.get("label") or target_id.replace("_", " ").title()),
            description=str(entry.get("description") or "Firmware artifacts"),
            directory=_expanded(directory),
            extensions=_extensions(entry.get("extensions"), (".bin",)),
            kind="firmware",
            recursive=True,
            upload=True,
            validator=str(entry.get("validator")) if entry.get("validator") else None,
            max_size=max_size,
        ))
    return targets


def build_collections(config: Mapping) -> list[Collection]:
    targets = _configured_targets(config)
    portal = config.get("file_portal", {}) if isinstance(config, Mapping) else {}
    log_root = _expanded(config.get("data_logger", {}).get("log_directory", "~/logs"))
    service_root = _expanded(config.get("features", {}).get("log_saver", {}).get(
        "log_directory", log_root))
    runtime_root = _expanded(portal.get("runtime_log_directory", "/var/log/rnse_control"))
    firmware_root = _expanded(config.get("haldex", {}).get("firmware_dir", "~/haldexfw"))
    eps_firmware_root = _expanded(config.get("eps", {}).get("firmware_dir", "~/epsfw"))
    capture_path = _expanded("~/logs/hudiy-api/hudiy-api-events.log")
    capture_root = os.path.dirname(capture_path)
    capture_extension = os.path.splitext(capture_path)[1].lower() or ".log"

    collections = targets + [
        Collection("hudiy_api", "Hudiy API captures",
                   "Provider-tagged projection, media, navigation, and phone events",
                   capture_root, (capture_extension,), "logs", False),
        Collection("drive_logs", "Drive & DataView logs",
                   "CSV recordings created by logger profiles", log_root,
                   (".csv",), "logs", True),
        Collection("service_logs", "Service & error logs",
                   "Saved journal output from Hudiy services", service_root,
                   (".log", ".txt"), "logs", True),
        Collection("runtime_logs", "Live service logs",
                   "Current service output and errors from the in-memory log store",
                   runtime_root, (".log", ".txt"), "logs", True),
        Collection("flash_logs", "Flashing operation logs",
                   "Detailed reports from controller read and write operations",
                   _expanded("~/.hudiy/flash_logs"), (".log",), "logs", True),
        Collection("readouts", "Haldex readouts",
                   "Haldex firmware images and capture reports",
                   os.path.join(firmware_root, "readouts"), (".bin", ".json"),
                   "readouts", True),
        Collection("eps_readouts", "PQ EPS readouts",
                   "EPS firmware, EEPROM images, and capture reports",
                   os.path.join(eps_firmware_root, "readouts"), (".bin", ".json"),
                   "readouts", True),
    ]
    return collections


def _is_allowed(collection: Collection, name: str) -> bool:
    return not collection.extensions or os.path.splitext(name)[1].lower() in collection.extensions


def _safe_path(collection: Collection, relative_path: str) -> str:
    root = os.path.realpath(collection.directory)
    relative_path = relative_path.replace("\\", "/").lstrip("/")
    candidate = os.path.realpath(os.path.join(root, *relative_path.split("/")))
    if candidate == root or os.path.commonpath((root, candidate)) != root:
        abort(404)
    return candidate


def _walk(collection: Collection, cooperative: bool = False):
    root = collection.directory
    if not os.path.isdir(root):
        return
    visited = 0
    for current, directories, filenames in os.walk(root, followlinks=False):
        if cooperative:
            time.sleep(0.001)
        directories[:] = sorted(d for d in directories if not d.startswith("."))
        for filename in sorted(filenames):
            visited += 1
            if cooperative and visited % 64 == 0:
                time.sleep(0.001)
            if filename.startswith(".") or not _is_allowed(collection, filename):
                continue
            path = os.path.join(current, filename)
            if not os.path.isfile(path) or os.path.islink(path):
                continue
            yield os.path.relpath(path, root).replace(os.sep, "/"), path
        if not collection.recursive:
            break


def _file_item(collection: Collection, relative_path: str, path: str) -> dict:
    stat = os.stat(path)
    folder = relative_path.rpartition("/")[0]
    number = re.search(r"_(\d+)\.[^.]+$", os.path.basename(path))
    folder_number = folder.rsplit("/", 1)[-1]
    # Legacy timestamp filenames end in microseconds; only interpret a suffix
    # as a capture number when its recording lives in a date folder.
    sequence = (int(number.group(1)) if number and re.search(r"(?:^|/)\d{4}-\d{2}-\d{2}(?:/|$)", folder)
                else int(folder_number) if folder_number.isdigit() else None)
    date = None
    for match in re.finditer(r"(?<!\d)(\d{4})-?(\d{2})-?(\d{2})(?!\d)", relative_path):
        try:
            date = datetime.strptime("".join(match.groups()), "%Y%m%d").strftime("%Y-%m-%d")
            break
        except ValueError:
            continue
    return {
        "name": os.path.basename(path),
        "path": relative_path,
        "size": stat.st_size,
        "modified": int(stat.st_mtime),
        "folder": folder,
        "date": date or datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
        "sequence": sequence,
        "download_url": f"/api/files/download/{collection.id}/{quote(relative_path)}",
    }


def _natural_path(path: str) -> tuple:
    return tuple((1, int(part)) if part.isdigit() else (0, part.lower())
                 for part in re.split(r"(\d+)", path))


def _log_sort(item: dict) -> tuple:
    return item["date"], item["sequence"] or 0, item["modified"], _natural_path(item["path"])


def _folder_groups(collection: Collection, files: list[dict]) -> list[dict]:
    groups = {}
    for item in files:
        folder = item["folder"]
        if not folder:
            continue
        group = groups.setdefault(folder, {
            "path": folder, "name": folder.rsplit("/", 1)[-1], "date": item["date"],
            "count": 0, "total_size": 0, "modified": 0,
            "archive_url": f"/api/files/archive/{collection.id}/{quote(folder)}",
        })
        group["count"] += 1
        group["total_size"] += item["size"]
        group["modified"] = max(group["modified"], item["modified"])
        group["date"] = max(group["date"], item["date"])
    return sorted(groups.values(), key=lambda group:
                  (group["date"], _natural_path(group["path"])), reverse=True)


def register_file_portal(app, config: Mapping,
                         validators: Optional[Mapping[str, Callable[[str], object]]] = None):
    validators = dict(validators or {})
    collections = {item.id: item for item in build_collections(config)}
    portal_config = config.get("file_portal", {}) if isinstance(config, Mapping) else {}
    upload_pin = str(portal_config.get("upload_pin", "")) if isinstance(portal_config, Mapping) else ""
    try:
        archive_limit = max(1, min(int(portal_config.get("archive_limit_mb", 256)), 2048)) * 1024 * 1024
    except (TypeError, ValueError):
        archive_limit = DEFAULT_ARCHIVE_LIMIT
    # Werkzeug enforces this before a maliciously large multipart body is spooled.
    if app.config.get("MAX_CONTENT_LENGTH") is None:
        app.config["MAX_CONTENT_LENGTH"] = 128 * 1024 * 1024

    def require_write_access():
        if upload_pin and request.headers.get("X-Hudiy-Pin", "") != upload_pin:
            return jsonify({"error": "The portal PIN is incorrect."}), 403
        return None

    @app.get("/api/files/theme")
    def portal_theme():
        response = jsonify({"theme": app.config.get("HUDIY_COLOR_SCHEME")})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/files")
    def portal_catalog():
        result = []
        for collection in collections.values():
            files = []
            total = 0
            try:
                for relative_path, path in _walk(collection):
                    item = _file_item(collection, relative_path, path)
                    files.append(item)
                    total += item["size"]
            except OSError:
                files = []
                total = 0
            files.sort(key=_log_sort if collection.kind == "logs" else
                       lambda item: (item["modified"], item["path"]), reverse=True)
            result.append({
                "id": collection.id,
                "label": collection.label,
                "description": collection.description,
                "kind": collection.kind,
                "upload": collection.upload,
                "extensions": list(collection.extensions),
                "max_size": collection.max_size,
                "count": len(files),
                "total_size": total,
                "archive_url": f"/api/files/archive/{collection.id}" if files else None,
                "files": files,
                "groups": _folder_groups(collection, files),
            })
        has_logs = any(item["kind"] == "logs" and item["count"] for item in result)
        return jsonify({
            "pin_required": bool(upload_pin),
            "all_logs_archive_url": "/api/files/archive/all_logs" if has_logs else None,
            "collections": result,
        })

    @app.get("/api/files/download/<collection_id>/<path:relative_path>")
    def portal_download(collection_id: str, relative_path: str):
        collection = collections.get(collection_id)
        if not collection:
            abort(404)
        path = _safe_path(collection, relative_path)
        if not os.path.isfile(path) or os.path.islink(path) or not _is_allowed(collection, path):
            abort(404)
        return send_file(path, as_attachment=True, download_name=os.path.basename(path))

    def archive_members(collection_id: str, relative_path: str = ""):
        if collection_id == "all_logs":
            if relative_path:
                abort(404)
            selected = [collection for collection in collections.values() if collection.kind == "logs"]
        else:
            collection = collections.get(collection_id)
            if not collection:
                abort(404)
            if relative_path:
                folder = _safe_path(collection, relative_path)
                if not os.path.isdir(folder) or os.path.islink(folder):
                    abort(404)
                relative_path = os.path.relpath(folder, collection.directory).replace(os.sep, "/")
            selected = [collection]
        members = []
        total = 0
        for collection in selected:
            for name, path in _walk(collection, cooperative=True):
                if relative_path and not name.startswith(relative_path + "/"):
                    continue
                if len(members) >= ARCHIVE_MEMBER_LIMIT:
                    raise _ArchiveLimitExceeded
                # Bound both enumeration memory and anticipated temporary disk
                # use before appending; do not build an unlimited member list.
                total += os.path.getsize(path)
                if total > archive_limit:
                    raise _ArchiveLimitExceeded
                if collection_id == "all_logs":
                    name = f"{collection.id}/{name}"
                members.append((name, path))
        if relative_path and not members:
            abort(404)
        return members, relative_path

    jobs = _ArchiveJobs(archive_members, archive_limit, app.logger)
    app.extensions["file_portal_archive_jobs"] = jobs

    @app.post("/api/files/archive/<collection_id>")
    @app.post("/api/files/archive/<collection_id>/<path:relative_path>")
    def portal_archive_start(collection_id: str, relative_path: str = ""):
        # Validate paths promptly; enumeration and file IO belong to the worker.
        if collection_id == "all_logs":
            if relative_path:
                abort(404)
        else:
            collection = collections.get(collection_id)
            if not collection:
                abort(404)
            if relative_path:
                folder = _safe_path(collection, relative_path)
                if not os.path.isdir(folder) or os.path.islink(folder):
                    abort(404)
        job = jobs.start(collection_id, relative_path)
        if job is None:
            return jsonify({"error": "Another archive is being prepared or downloaded. Try again shortly."}), 409
        response = jsonify(job)
        response.headers["Cache-Control"] = "no-store"
        return response, 202

    @app.get("/api/files/archive-jobs/<job_id>")
    def portal_archive_status(job_id: str):
        job = jobs.status(job_id)
        if job is None:
            abort(404)
        response = jsonify(job)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/files/archive-jobs/<job_id>/download")
    def portal_archive_job_download(job_id: str):
        response, status = jobs.download(job_id)
        if status == 404:
            abort(404)
        if status != 200:
            return jsonify({"error": "This archive is not ready to download. Try again shortly."}), status
        return response

    @app.get("/api/files/archive/<collection_id>")
    @app.get("/api/files/archive/<collection_id>/<path:relative_path>")
    def portal_archive(collection_id: str, relative_path: str = ""):
        archive = None
        try:
            members, relative_path = archive_members(collection_id, relative_path)
            # Legacy direct URLs remain available with fast compression and
            # bounded temporary disk storage, sharing the job copy safeguards.
            archive = tempfile.TemporaryFile(mode="w+b")
            size = _write_archive(archive, members, archive_limit)
            archive.seek(0)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            folder_name = "-" + relative_path.replace("/", "-") if relative_path else ""
            response = send_file(archive, mimetype="application/zip", as_attachment=True,
                                 download_name=f"rnse-{collection_id}{folder_name}-{stamp}.zip")
            response.content_length = size
            response.call_on_close(archive.close)
            return response
        except _ArchiveLimitExceeded:
            if archive is not None:
                archive.close()
            return jsonify({"error": ARCHIVE_SIZE_ERROR}), 413
        except OSError:
            if archive is not None:
                archive.close()
            return jsonify({"error": ARCHIVE_READ_ERROR}), 409
        except BaseException:
            if archive is not None:
                archive.close()
            raise

    @app.post("/api/files/upload/<collection_id>")
    def portal_upload(collection_id: str):
        denied = require_write_access()
        if denied:
            return denied
        collection = collections.get(collection_id)
        if not collection or not collection.upload:
            abort(404)
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename:
            return jsonify({"error": "Choose a file to upload."}), 400
        filename = os.path.basename(uploaded.filename.replace("\\", "/"))
        if filename in ("", ".", "..") or filename.startswith(".") or not _is_allowed(collection, filename):
            return jsonify({"error": "That file type is not allowed for this target."}), 400

        os.makedirs(collection.directory, exist_ok=True)
        if os.path.exists(os.path.join(collection.directory, filename)):
            return jsonify({"error": "A file with that name already exists."}), 409

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".upload-", suffix=os.path.splitext(filename)[1],
                                             dir=collection.directory, delete=False) as temporary:
                temporary_path = temporary.name
                size = 0
                while True:
                    chunk = uploaded.stream.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > collection.max_size:
                        return jsonify({"error": "The upload exceeds this target's size limit."}), 413
                    temporary.write(chunk)
            if size == 0:
                return jsonify({"error": "The uploaded file is empty."}), 400
            validator = validators.get(collection.validator or "")
            if collection.validator and validator is None:
                return jsonify({"error": "The validator for this firmware target is unavailable."}), 503
            validation = validator(temporary_path) if validator else None
            if collection.validator == 'exhaust-valve' and filename.lower().endswith('.zip'):
                # A complete, validated trio installs as an immutable versioned
                # directory, so subsequent updates can retain standard filenames.
                destination = os.path.join(collection.directory, validation['artifact_id'])
                staging = tempfile.mkdtemp(prefix='.bundle-', dir=collection.directory)
                try:
                    for name, contents in validation['files'].items():
                        with open(os.path.join(staging, name), 'xb') as stream:
                            stream.write(contents)
                    if not os.path.exists(destination):
                        os.rename(staging, destination)
                finally:
                    if os.path.exists(staging):
                        for name in os.listdir(staging):
                            os.unlink(os.path.join(staging, name))
                        os.rmdir(staging)
                return jsonify({'message': f'{filename} bundle is ready for {collection.label}.'}), 201
            destination = os.path.join(collection.directory, filename)
            # Publish the validated file atomically without overwriting a file
            # that another upload installed while validation was running.
            try:
                if os.name == 'nt':
                    # Windows rename already refuses an existing destination.
                    os.rename(temporary_path, destination)
                else:
                    os.link(temporary_path, destination)
            except FileExistsError:
                return jsonify({"error": "A file with that name already exists."}), 409
            if os.name != 'nt':
                os.unlink(temporary_path)
            temporary_path = None
            return jsonify({
                "message": f"{filename} is ready for {collection.label}.",
                "file": _file_item(collection, filename, destination),
            }), 201
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except Exception as error:
            app.logger.warning("Portal upload rejected: %s", error)
            return jsonify({"error": f"Firmware validation failed: {error}"}), 400
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    return collections
