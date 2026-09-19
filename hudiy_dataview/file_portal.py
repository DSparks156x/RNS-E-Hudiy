"""Safe, configurable file-transfer routes for Hudiy DataView.

The portal deliberately exposes named collections instead of arbitrary paths.
That keeps a browser connected to the car from wandering through the Pi's home
directory, while allowing more firmware targets to be added in config later.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional
from urllib.parse import quote

from flask import abort, jsonify, request, send_file


DEFAULT_UPLOAD_LIMIT = 16 * 1024 * 1024
DEFAULT_ARCHIVE_LIMIT = 256 * 1024 * 1024
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


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

    targets = []
    for entry in configured:
        if not isinstance(entry, Mapping):
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

    collections = targets + [
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
        Collection("readouts", "Controller readouts",
                   "Firmware images and reports read from vehicle controllers",
                   os.path.join(firmware_root, "readouts"), (".bin", ".json"),
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


def _walk(collection: Collection):
    root = collection.directory
    if not os.path.isdir(root):
        return
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if not d.startswith("."))
        for filename in sorted(filenames):
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
    return {
        "name": os.path.basename(path),
        "path": relative_path,
        "size": stat.st_size,
        "modified": int(stat.st_mtime),
        "download_url": f"/api/files/download/{collection.id}/{quote(relative_path)}",
    }


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
            files.sort(key=lambda item: item["modified"], reverse=True)
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
                "files": files[:500],
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

    @app.get("/api/files/archive/<collection_id>")
    def portal_archive(collection_id: str):
        if collection_id == "all_logs":
            members = [
                (f"{collection.id}/{relative_path}", path)
                for collection in collections.values() if collection.kind == "logs"
                for relative_path, path in _walk(collection)
            ]
        else:
            collection = collections.get(collection_id)
            if not collection:
                abort(404)
            members = list(_walk(collection))
        try:
            total = sum(os.path.getsize(path) for _, path in members)
        except OSError:
            return jsonify({"error": "A file changed while the bundle was being prepared. Try again."}), 409
        if total > archive_limit:
            return jsonify({"error": "This collection is too large to bundle at once."}), 413
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for relative_path, path in members:
                bundle.write(path, relative_path)
        archive.seek(0)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return send_file(archive, mimetype="application/zip", as_attachment=True,
                         download_name=f"rnse-{collection_id}-{stamp}.zip")

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
            if validator:
                validator(temporary_path)
            destination = os.path.join(collection.directory, filename)
            os.replace(temporary_path, destination)
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
