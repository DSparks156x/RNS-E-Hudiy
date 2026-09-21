"""Bounded JSON-lines capture of Hudiy API callbacks for provider comparisons."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


logger = logging.getLogger(__name__)


def _bytes_summary(value: bytes, preview_limit: int = 512) -> dict:
    raw = bytes(value)
    result = {
        "length": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if len(raw) <= preview_limit:
        result["hex"] = raw.hex()
    else:
        result["prefix_hex"] = raw[:preview_limit].hex()
        result["truncated"] = True
    return result


def _plain_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return _bytes_summary(value)
    if hasattr(value, "DESCRIPTOR") and hasattr(value, "ListFields"):
        return _protobuf_snapshot(value)[0]
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)) or (
        hasattr(value, "__iter__") and not isinstance(value, (str, bytes))
    ):
        try:
            return [_plain_value(item) for item in value]
        except TypeError:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _enum_value(enum_type: Any, value: Any) -> Any:
    def one(item: Any) -> dict:
        number = int(item)
        try:
            enum_item = enum_type.values_by_number.get(number)
            name = enum_item.name if enum_item is not None else "UNKNOWN"
        except Exception:
            name = "UNKNOWN"
        return {"number": number, "name": name}

    if isinstance(value, (list, tuple)) or (
        hasattr(value, "__iter__") and not isinstance(value, (str, bytes))
    ):
        return [one(item) for item in value]
    return one(value)


def _protobuf_snapshot(message: Any) -> tuple[dict, list[str], str]:
    """Return all decoded top-level fields, explicitly present fields, and type."""
    descriptor = getattr(message, "DESCRIPTOR", None)
    if descriptor is None:
        return {}, [], type(message).__name__

    try:
        present = {field.name for field, _ in message.ListFields()}
    except Exception:
        present = set()

    decoded = {}
    for field in getattr(descriptor, "fields", ()):
        try:
            value = getattr(message, field.name)
            # Unset nested messages should be represented as absent, rather
            # than expanded into a tree of protobuf defaults.
            is_repeated = bool(
                getattr(field, "is_repeated", False)
                or getattr(field, "label", None) == 3
            )
            if (getattr(field, "message_type", None) is not None
                    and field.name not in present and not is_repeated):
                decoded[field.name] = None
            elif getattr(field, "enum_type", None) is not None:
                decoded[field.name] = _enum_value(field.enum_type, value)
            else:
                decoded[field.name] = _plain_value(value)
        except Exception as exc:
            decoded[field.name] = {"capture_error": str(exc)}

    type_name = getattr(descriptor, "full_name", None) or getattr(descriptor, "name", None)
    return decoded, sorted(present), type_name or type(message).__name__


class ApiEventCapture:
    """Append callback events to a portal-visible, two-file rotating capture."""

    DEFAULT_PATH = "~/logs/hudiy-api/hudiy-api-events.log"

    def __init__(self, settings: Optional[Mapping[str, Any]] = None):
        settings = settings if isinstance(settings, Mapping) else {}
        self.enabled = bool(settings.get("enabled", True))
        self.path = os.path.abspath(os.path.expanduser(str(
            settings.get("path", self.DEFAULT_PATH)
        )))
        try:
            max_size_mb = max(1, min(int(settings.get("max_size_mb", 8)), 100))
        except (TypeError, ValueError):
            max_size_mb = 8
        self.max_bytes = max_size_mb * 1024 * 1024
        root, extension = os.path.splitext(self.path)
        self.previous_path = root + "-previous" + (extension or ".log")
        self.session_id = uuid.uuid4().hex
        self._sequence = 0
        self._lock = threading.Lock()

        if self.enabled:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                self.record("capture_started", derived={
                    "capture_path": self.path,
                    "max_size_mb": max_size_mb,
                    "format_version": 1,
                })
                logger.info("Hudiy API event capture enabled: %s", self.path)
            except Exception as exc:
                self.enabled = False
                logger.warning("Could not enable Hudiy API event capture: %s", exc)

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        try:
            current_size = os.path.getsize(self.path)
        except OSError:
            current_size = 0
        if current_size + incoming_bytes <= self.max_bytes:
            return
        try:
            if os.path.exists(self.previous_path):
                os.remove(self.previous_path)
            if os.path.exists(self.path):
                os.replace(self.path, self.previous_path)
        except OSError as exc:
            logger.warning("Could not rotate Hudiy API capture: %s", exc)

    def record(self, event: str, message: Any = None, *, provider: str = "unknown",
               derived: Optional[Mapping[str, Any]] = None,
               context: Optional[Mapping[str, Any]] = None) -> None:
        if not self.enabled:
            return
        try:
            decoded = {}
            present_fields: list[str] = []
            protobuf_type = None
            wire = None
            if message is not None:
                decoded, present_fields, protobuf_type = _protobuf_snapshot(message)
                try:
                    wire = _bytes_summary(message.SerializeToString(), preview_limit=2048)
                except Exception as exc:
                    wire = {"capture_error": str(exc)}

            with self._lock:
                self._sequence += 1
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "monotonic_ns": time.monotonic_ns(),
                    "session_id": self.session_id,
                    "sequence": self._sequence,
                    "event": str(event),
                    "provider": str(provider or "unknown"),
                    "protobuf_type": protobuf_type,
                    "present_fields": present_fields,
                    "fields": decoded,
                    "wire": wire,
                    "derived": _plain_value(dict(derived or {})),
                    "context": _plain_value(dict(context or {})),
                }
                encoded = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                self._rotate_if_needed(len(encoded))
                with open(self.path, "ab") as capture_file:
                    capture_file.write(encoded)
                    capture_file.flush()
        except Exception as exc:
            # Diagnostics must never interfere with the live Hudiy data path.
            logger.warning("Hudiy API event capture failed for %s: %s", event, exc)
