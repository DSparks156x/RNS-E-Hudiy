"""Controller-neutral PQ flash and memory-read engine.\n\nController packages supply policy; this module owns only shared lifecycle machinery.\n"""
import hashlib
import inspect
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from .vag_protocols.kwp import KWPClient, KWPNegativeResponse


KeyDeriver = Callable[[bytes], Optional[bytes]]


@dataclass(frozen=True)
class ControllerRuntime:
    """Process-level services supplied to a selected controller package."""

    open_adapter: Callable[[Any], Any]
    progress: Callable[..., None]


@dataclass(frozen=True)
class SecurityAccess:
    request_seed: int
    send_key: int
    derive_key: KeyDeriver
    name: str

    def unlock(self, kwp):
        seed = kwp.sa_seed(self.request_seed)
        key = self.derive_key(seed)
        # A zero seed conventionally means the requested level is unlocked.
        if key is not None:
            kwp.sa_key(self.send_key, key)
        return seed


def add32(constant: int) -> KeyDeriver:
    def derive(seed: bytes) -> Optional[bytes]:
        if len(seed) != 4:
            raise RuntimeError(f"Expected four-byte security seed, got {len(seed)}")
        if not any(seed):
            return None
        return ((int.from_bytes(seed, "big") + constant) & 0xFFFFFFFF).to_bytes(4, "big")
    return derive


def fixed_challenge(expected_seed: bytes, key: bytes) -> KeyDeriver:
    expected_seed = bytes(expected_seed)
    key = bytes(key)

    def derive(seed: bytes) -> Optional[bytes]:
        if seed != expected_seed:
            raise RuntimeError(f"Unexpected loader challenge: {seed.hex()}")
        return key
    return derive


@dataclass(frozen=True)
class PQFlashProfile:
    name: str
    module: int
    kwp_factory: Callable[[Any, Callable[[str], None], bool], Any]
    prepare_image: Callable[..., dict]
    device_factory: Callable[[str], Any]
    transport_factory: Callable[..., Any]
    identify: Callable[[Any, Any], dict]
    validate_controller: Callable[[dict, dict], None]
    is_application_channel: Callable[[Any], bool]
    initial_session: Optional[int]
    programming_session: int
    pre_programming_security: Optional[SecurityAccess]
    programming_security: Optional[SecurityAccess]
    verify_programming_channel: Callable[[Any], None]
    chunk_size: int
    erase_routine: int
    checksum_routine: int
    erase_payload: Callable[[int, int, dict], bytes]
    checksum_payload: Callable[[int, int, dict], bytes]
    validate_fresh_application: Callable[[dict], None]
    commit_services: Tuple[int, ...] = (0x20, 0x82)


def parse_vag_flash_date(raw: bytes) -> Optional[str]:
    """Decode the four-byte packed-BCD YYYYMMDD used by VAG flash status."""
    raw = bytes(raw[:4])
    if len(raw) != 4 or raw in (b"\x00" * 4, b"\xFF" * 4):
        return None
    if not all((value >> 4) <= 9 and (value & 0x0F) <= 9 for value in raw):
        return None
    value = raw.hex()
    try:
        parsed = date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    except ValueError:
        return None
    return parsed.isoformat()


def encode_vag_flash_date(value: str) -> bytes:
    """Encode an ISO date as packed-BCD YYYYMMDD."""
    return bytes.fromhex(date.fromisoformat(value).strftime("%Y%m%d"))


def system_flash_date() -> Optional[str]:
    """Return the host's current local date, or None when unavailable."""
    try:
        return date.today().isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def parse_vag_identification(ident_response: bytes, status_response: bytes) -> dict:
    """Parse the common VAG KWP 0x1A/0x9B and 0x9C identification layout."""
    ident_response = bytes(ident_response)
    status_response = bytes(status_response)
    if not ident_response.startswith(b"\x5A\x9B") or len(ident_response) < 18:
        raise RuntimeError("Truncated or invalid ECU identification response")
    if not status_response.startswith(b"\x5A\x9C") or len(status_response) < 5:
        raise RuntimeError("Truncated or invalid flash-status response")
    payload = ident_response[2:]
    software_part_number = payload[:12].decode("ascii", errors="strict").strip()
    firmware_revision = payload[12:16].decode("ascii", errors="strict").strip()
    system_description = payload[26:].decode("ascii", errors="replace").strip("\x00 ")
    return {
        "raw_9b": ident_response.hex(),
        "raw_9c": status_response.hex(),
        "part_number": software_part_number,
        "software_part_number": software_part_number,
        "sw_version": firmware_revision,
        "firmware_revision": firmware_revision,
        "system_desc": system_description,
        "flash_status": status_response[2],
        "flash_attempts": status_response[3],
        "flash_counter": status_response[4],
        "flash_date": parse_vag_flash_date(status_response[6:10]),
        "flash_tool_id": (int.from_bytes(status_response[10:12], "big")
                          if len(status_response) >= 12 else None),
    }



# --- Shared read-only memory lifecycle ---

class PQReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class PQReadProfile:
    name: str
    module: int
    image_size: int
    validate_range: Callable[[int, int], None]
    initial_session: int
    privileged_session: int
    security: SecurityAccess
    methods: Tuple[str, ...]
    upload_block_max: int
    strict_upload_blocks: bool
    mark_upload_before_request: bool
    leave_requests: Tuple[bytes, ...]
    key_response: Optional[bytes] = None


class PQMemoryReader:
    """One state machine for KWP 0x23 and 0x35 reads across PQ modules."""

    def __init__(self, transport, profile: PQReadProfile, *, record=lambda event: None,
                 kwp_factory=KWPClient):
        self.transport = transport
        self.profile = profile
        self.kwp = kwp_factory(transport, debug=False)
        self.record = record
        self.upload_active = False
        self.privileged_active = False
        self.security_unlocked = False

    def _allowed(self, request: bytes) -> bool:
        fixed = {b"\x1A\x9B", b"\x1A\x9C", b"\x36", b"\x37",
                 bytes([0x10, self.profile.initial_session]),
                 bytes([0x10, self.profile.privileged_session]),
                 bytes([0x27, self.profile.security.request_seed]),
                 *self.profile.leave_requests}
        return (request in fixed
                or (request[:2] == bytes([0x27, self.profile.security.send_key])
                    and len(request) == 6)
                or ("read-memory" in self.profile.methods and request[:1] == b"\x23"
                    and len(request) == 5)
                or ("upload" in self.profile.methods and request[:1] == b"\x35"
                    and len(request) == 8 and request[4] == 0))

    def _exchange(self, request: bytes) -> bytes:
        request = bytes(request)
        if not self._allowed(request):
            raise ValueError("Request is outside PQ read-only allowlist: " + request.hex())
        if request[:1] in (b"\x23", b"\x35"):
            if request[:1] == b"\x23":
                address, length = int.from_bytes(request[1:4], "big"), request[4]
            else:
                address, length = int.from_bytes(request[1:4], "big"), int.from_bytes(request[5:8], "big")
            self.profile.validate_range(address, length)
        self.record({"event": "request", "hex": request.hex()})
        response = self.kwp.request(request)
        self.record({"event": "response", "hex": response.hex()})
        return response

    def exchange(self, request: bytes) -> bytes:
        return self._exchange(request)

    def identify(self) -> bytes:
        return self._exchange(b"\x1A\x9B")[2:]

    def identification(self) -> dict:
        return parse_vag_identification(
            self._exchange(b"\x1A\x9B"), self._exchange(b"\x1A\x9C"))

    def diagnostic_session(self):
        self._exchange(bytes([0x10, self.profile.initial_session]))

    def enter(self, *, ensure_diagnostic=True):
        if ensure_diagnostic:
            self.diagnostic_session()
        seed_response = self._exchange(bytes([0x27, self.profile.security.request_seed]))
        seed = seed_response[2:]
        key = self.profile.security.derive_key(seed)
        if key is not None:
            response = self._exchange(bytes([0x27, self.profile.security.send_key]) + key)
            if self.profile.key_response is not None and response != self.profile.key_response:
                raise PQReadError("Security key response did not match controller profile")
        self.security_unlocked = True
        # Set before sending: an uncertain response still requires restoration.
        self.privileged_active = True
        self._exchange(bytes([0x10, self.profile.privileged_session]))

    def read_memory(self, address: int, length: int) -> bytes:
        if "read-memory" not in self.profile.methods:
            raise PQReadError("ReadMemoryByAddress is not enabled for this controller")
        self.profile.validate_range(address, length)
        if not 1 <= length <= 0xFF:
            raise ValueError("ReadMemoryByAddress length must be 1..255")
        response = self._exchange(b"\x23" + address.to_bytes(3, "big") + bytes([length]))
        data = response[1:]
        if len(data) != length:
            raise PQReadError(f"ReadMemoryByAddress at 0x{address:06X}: "
                              f"expected {length}, got {len(data)}")
        return data

    def read_upload(self, address: int, length: int) -> bytes:
        if "upload" not in self.profile.methods:
            raise PQReadError("RequestUpload is not enabled for this controller")
        self.profile.validate_range(address, length)
        request = b"\x35" + address.to_bytes(3, "big") + b"\x00" + length.to_bytes(3, "big")
        if self.profile.mark_upload_before_request:
            self.upload_active = True
        response = self._exchange(request)
        self.upload_active = True
        limit_bytes = response[1:]
        if len(limit_bytes) not in (1, 2):
            raise PQReadError("Unexpected RequestUpload block limit: " + response.hex())
        limit = int.from_bytes(limit_bytes, "big")
        expected_limit = min(self.profile.upload_block_max, length)
        if self.profile.strict_upload_blocks:
            if limit != expected_limit:
                raise PQReadError(f"Unexpected upload block limit {limit}; expected {expected_limit}")
        elif not 1 <= limit <= 0x1000:
            raise PQReadError(f"Implausible RequestUpload block limit: {limit}")
        data = bytearray()
        while len(data) < length:
            # Never retry an ambiguous 0x36; the ECU may have advanced.
            response = self._exchange(b"\x36")
            block = response[1:]
            remaining = length - len(data)
            expected = min(limit, remaining)
            if (not block or len(block) > expected
                    or (self.profile.strict_upload_blocks and len(block) != expected)):
                raise PQReadError(f"Upload at 0x{address + len(data):06X}: "
                                  f"invalid block length {len(block)}")
            data.extend(block)
            self.record({"event": "block_received", "address": address + len(data) - len(block),
                         "length": len(block), "end_exclusive": address + len(data)})
        self._exchange(b"\x37")
        self.upload_active = False
        return bytes(data)

    def read_window(self, address: int, length: int, method: Optional[str] = None) -> bytes:
        selected = method or self.profile.methods[0]
        return (self.read_memory(address, length) if selected == "read-memory"
                else self.read_upload(address, length))

    def probe(self, addresses, *, requested="auto"):
        methods = self.profile.methods if requested == "auto" else (requested,)
        last_error = None
        self.diagnostic_session()
        for privileged in (False, True):
            if privileged:
                self.enter(ensure_diagnostic=False)
            for method in methods:
                for address in addresses:
                    try:
                        sample = self.read_window(address, 16, method)
                        return {"method": method,
                                "session": (self.profile.privileged_session if privileged
                                            else self.profile.initial_session),
                                "security_unlocked": self.security_unlocked,
                                "sample_address": address, "sample_hex": sample.hex()}
                    except KWPNegativeResponse as exc:
                        last_error = exc
                        self.record({"event": "probe_rejected", "method": method,
                                     "address": address, "nrc": exc.code,
                                     "privileged": privileged})
        raise PQReadError(f"No conventional KWP memory-read method accepted: {last_error}")

    def leave(self):
        errors = []
        if self.upload_active:
            try:
                self._exchange(b"\x37")
            except Exception as exc:
                errors.append("transfer exit: " + str(exc))
            self.upload_active = False
        if self.privileged_active:
            for request in self.profile.leave_requests:
                try:
                    self._exchange(request)
                except Exception as exc:
                    errors.append(f"session cleanup {request.hex()}: {exc}")
            self.privileged_active = False
        return errors


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def capture_contiguous(reader, output, start, length, passes, window, record, progress,
                       *, image_size, validate_selection, recover=None, max_window_retries=2,
                       protocol_errors=(PQReadError,)):
    validate_selection(start, start + length - 1)
    if passes not in (1, 2) or not 1 <= window <= 65536:
        raise ValueError("passes must be 1 or 2; window must be 1..65536")
    output = Path(output)
    results = []
    for pass_index in range(1, passes + 1):
        path = output / f"pass{pass_index}.bin"
        with path.open("xb") as stream:
            stream.write(b"\xFF" * image_size)
            stream.flush()
            for offset in range(0, length, window):
                size = min(window, length - offset)
                for attempt in range(max_window_retries + 1):
                    try:
                        block = reader.read_window(start + offset, size)
                        break
                    except (TimeoutError, ConnectionError, RuntimeError) as exc:
                        if isinstance(exc, protocol_errors) or recover is None or attempt == max_window_retries:
                            raise
                        record({"event": "window_restart", "pass": pass_index,
                                "address": start + offset, "length": size,
                                "attempt": attempt + 1, "error": str(exc)})
                        recover(exc)
                if len(block) != size:
                    raise PQReadError("Incomplete window")
                stream.seek(start + offset)
                stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
                record({"event": "window_saved", "pass": pass_index,
                        "address": start + offset, "length": size, "sha256": sha256(block)})
                progress(pass_index, offset + size, length)
        data = path.read_bytes()
        results.append({"path": path.name, "length": len(data), "sha256": sha256(data),
                        "captured_start": start, "captured_end_exclusive": start + length,
                        "captured_length": length,
                        "captured_sha256": sha256(data[start:start + length])})
    if passes == 2 and (output / "pass1.bin").read_bytes() != (output / "pass2.bin").read_bytes():
        raise PQReadError("Independent captures differ; do not treat this as a verified dump")
    return results


def capture_sparse(reader, output, start, length, method, *, chunk, image_size,
                   validate_range, record=lambda event: None,
                   progress=lambda done, total: None):
    validate_range(start, length)
    if method == "read-memory" and not 1 <= chunk <= 0xFF:
        raise ValueError("ReadMemoryByAddress chunk must be 1..255 bytes")
    if method == "upload" and chunk <= 0:
        raise ValueError("Upload window must be positive")
    image = bytearray(b"\xFF" * image_size)
    holes = []
    for offset in range(0, length, chunk):
        address = start + offset
        amount = min(chunk, length - offset)
        try:
            if hasattr(reader, "read_window"):
                data = reader.read_window(address, amount, method)
            else:
                data = (reader.read_memory(address, amount) if method == "read-memory"
                        else reader.read_upload(address, amount))
        except KWPNegativeResponse as exc:
            hole = {"start": address, "end_exclusive": address + amount,
                    "nrc": exc.code, "error": str(exc)}
            holes.append(hole)
            record({"event": "unreadable", **hole})
        else:
            image[address:address + amount] = data
            record({"event": "saved", "address": address, "length": amount,
                    "sha256": sha256(data)})
        progress(offset + amount, length)
    path = Path(output) / "kwp_readout.bin"
    with path.open("xb") as stream:
        stream.write(image)
        stream.flush()
        os.fsync(stream.fileno())
    readable = length - sum(h["end_exclusive"] - h["start"] for h in holes)
    return {"path": path.name, "image_size": image_size, "start": start,
            "end_exclusive": start + length, "requested_bytes": length,
            "readable_bytes": readable, "unreadable_bytes": length - readable,
            "holes": holes, "sha256": sha256(image)}



# --- Shared flash lifecycle ---

logger = logging.getLogger("PQFlasher")


class PQFlasher:
    def __init__(self, profile: PQFlashProfile, *, channel: str = "can0",
                 module: Optional[int] = None, device: Optional[Any] = None,
                 device_factory: Optional[Callable[[], Any]] = None,
                 progress_cb: Optional[Callable[..., None]] = None,
                 log_cb: Optional[Callable[[str], None]] = None,
                 debug: bool = False):
        self.profile = profile
        self.channel = channel
        self.module = profile.module if module is None else module
        self.device = device
        self.device_factory = device_factory
        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self.debug = debug
        self.abort_requested = False
        self.destructive_started = False
        self.recovery_required = False
        self.last_result = {}

    def log(self, message: str):
        logger.info(message)
        if self.log_cb:
            try:
                self.log_cb(message)
            except Exception:
                pass

    def report_progress(self, stage: str, percent: float, detail: str = "",
                        speed: float = 0.0, eta_sec: float = 0.0):
        if not self.progress_cb:
            return
        try:
            if len(inspect.signature(self.progress_cb).parameters) >= 5:
                self.progress_cb(stage, percent, detail, speed, eta_sec)
            else:
                self.progress_cb(stage, percent, detail, speed)
        except Exception:
            try:
                self.progress_cb(stage, percent, detail, speed)
            except Exception:
                pass

    def _new_kwp(self, tp):
        return self.profile.kwp_factory(tp, self.log, self.debug)

    def _ensure_device(self):
        if self.device is None:
            self.device = (self.device_factory() if self.device_factory is not None
                           else self.profile.device_factory(self.channel))

    def _disconnect(self):
        tp = getattr(self, "_tp", None)
        self._tp = None
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                self.log(f"Transport close: {exc}")

    def close(self):
        self._disconnect()
        if self.device is not None:
            try:
                self.device.close()
            finally:
                self.device = None

    def reconnect_tp(self, tries=5, heartbeat=False):
        self._disconnect()
        self._ensure_device()
        for attempt in range(tries):
            if self.abort_requested:
                raise RuntimeError("Cancellation requested; operation stopped")
            try:
                self.device.can_clear(0xFFFF)
                self._tp = self.profile.transport_factory(
                    self.device, module=self.module, timeout=2.0,
                    debug=self.debug, log_fn=self.log)
                self._tp.keepalive_after_response = heartbeat
                return self._tp
            except Exception as exc:
                self.log(f"[TP20] connection attempt {attempt + 1}/{tries} failed: "
                         f"{type(exc).__name__}: {exc}")
                if attempt == tries - 1:
                    raise
                time.sleep(1)

    def _identify(self, kwp, tp):
        return self.profile.identify(kwp, tp)

    def read_ecu_info(self):
        try:
            tp = self.reconnect_tp()
            return self._identify(self._new_kwp(tp), tp)
        finally:
            self.close()

    def _cancel(self):
        if self.abort_requested:
            suffix = ("; Controller remains in programming mode and can be flashed again"
                      if self.destructive_started else "")
            raise RuntimeError("Cancellation requested; operation stopped" + suffix)

    def _routine_done(self, kwp, routine):
        for _ in range(30):
            self._cancel()
            try:
                response = kwp.routine_result(routine)
            except (TimeoutError, ConnectionError) as exc:
                self.log(f"[TP20] routine 0x{routine:02X} polling lost its channel "
                         f"({type(exc).__name__}: {exc}); reconnecting")
                if isinstance(exc, ConnectionError):
                    self._tp = None
                time.sleep(0.5)
                kwp = self._new_kwp(self.reconnect_tp(15, heartbeat=True))
                continue
            except RuntimeError as exc:
                if "NRC 0x23" not in str(exc):
                    raise
                time.sleep(0.5)
                continue
            if response == bytes([0x73, routine, 0]):
                return kwp
            if response != bytes([0x73, routine, 0x23]):
                raise RuntimeError(f"Routine {routine:#x} failed: {response.hex()}")
            time.sleep(0.5)
        raise TimeoutError(f"Routine {routine:#x} did not finish")

    def _enter_programming(self, tp, kwp, *, recovery=False):
        if recovery:
            self.profile.verify_programming_channel(tp)
            if self.profile.programming_security is not None:
                self.profile.programming_security.unlock(kwp)
            return tp, kwp
        if self.profile.is_application_channel(tp):
            if self.profile.initial_session is not None:
                kwp.session(self.profile.initial_session)
            if self.profile.pre_programming_security is not None:
                self.profile.pre_programming_security.unlock(kwp)
            try:
                tp.keepalive_after_response = False
                kwp.session(self.profile.programming_session)
            except (TimeoutError, ConnectionError) as exc:
                self.log(f"Programming transition ambiguous: {exc}; verifying programming connection")
            tp = self.reconnect_tp(15, heartbeat=True)
            kwp = self._new_kwp(tp)
            self.profile.verify_programming_channel(tp)
        if self.profile.programming_security is not None:
            self.profile.programming_security.unlock(kwp)
        return tp, kwp

    def flash_prepared(self, prepared: dict, *, recovery=False):
        """Flash an already validated target artifact using the common lifecycle."""
        metadata = dict(prepared["metadata"])
        flash_date = system_flash_date()
        if flash_date is not None:
            metadata["flash_date"] = flash_date
        start_addr = metadata["start_addr"]
        end_addr = metadata["end_addr"]
        # Materialize controller payloads before any hardware or destructive work.
        erase_payload = self.profile.erase_payload(start_addr, end_addr, metadata)
        checksum_payload = self.profile.checksum_payload(start_addr, end_addr, metadata)
        started = time.monotonic()
        self.destructive_started = False
        self.recovery_required = False
        self.last_result = dict(metadata, checksum_verified=False, boot_verified=False,
                                commit_outcome="not_attempted", controller=self.profile.name,
                                recovery_mode=recovery)
        self.log("PREFLIGHT " + json.dumps(metadata, sort_keys=True))
        try:
            self._cancel()
            self.report_progress("CONNECTING", 5, "Opening exclusive diagnostic session")
            tp = self.reconnect_tp(heartbeat=True)
            kwp = self._new_kwp(tp)
            if recovery:
                self.log("RECOVERY MODE: skipping application identification and session transition")
            else:
                controller_info = self._identify(kwp, tp)
                self.profile.validate_controller(controller_info, metadata)
                self.last_result["source_controller"] = controller_info
            tp, kwp = self._enter_programming(tp, kwp, recovery=recovery)
            self._cancel()
            limit = kwp.request_download(start_addr, metadata["size"])
            chunk = (min(self.profile.chunk_size, limit - 1) // 4) * 4
            if chunk < 4:
                raise RuntimeError("Controller transfer size is too small")
            self._cancel()
            self.destructive_started = self.recovery_required = True
            self.report_progress("ERASING", 30, "Erasing selected regions")
            kwp.routine(self.profile.erase_routine, erase_payload)
            kwp = self._routine_done(kwp, self.profile.erase_routine)
            region = prepared["region"]
            write_started = time.monotonic()
            for offset in range(0, len(region), chunk):
                self._cancel()
                block = region[offset:offset + chunk]
                # A timeout is ambiguous: TransferData is never resent.
                kwp.transfer(block)
                sent = offset + len(block)
                speed = sent / max(time.monotonic() - write_started, 0.001)
                self.report_progress("WRITING", 35 + 55 * sent / len(region),
                                     f"{sent}/{len(region)} bytes", speed,
                                     (len(region) - sent) / speed)
            kwp.transfer_exit()
            self.report_progress("VERIFYING", 93, "Checking transferred image checksum")
            kwp.routine(self.profile.checksum_routine,
                        checksum_payload)
            kwp = self._routine_done(kwp, self.profile.checksum_routine)
            self.last_result["checksum_verified"] = True
            self.report_progress("REBOOTING", 96, "Committing; fresh application verification required")
            outcomes = {}
            tp.keepalive_after_response = False
            for service in self.profile.commit_services:
                try:
                    kwp.raw(bytes([service]))
                    outcomes[f"{service:02x}"] = "acknowledged"
                except Exception as exc:
                    outcomes[f"{service:02x}"] = str(exc)
                    self.log(f"Commit service {service:#x} unconfirmed: {exc}")
            self.last_result["commit_responses"] = outcomes
            self.last_result["commit_outcome"] = (
                "acknowledged" if all(v == "acknowledged" for v in outcomes.values()) else "ambiguous")
            self.close()
            cancelled = self.abort_requested
            self.abort_requested = False
            try:
                tp = self.reconnect_tp(15, heartbeat=False)
                info = self._identify(self._new_kwp(tp), tp)
            finally:
                self.abort_requested = cancelled
            self.last_result["application"] = info
            self.profile.validate_fresh_application(info)
            self.last_result["boot_verified"] = True
            if self.last_result["commit_outcome"] != "acknowledged":
                raise RuntimeError("Application boot observed but commit outcome remains ambiguous")
            self.recovery_required = False
            self.last_result.update(status="ok", elapsed_sec=round(time.monotonic() - started, 1),
                                    recovery_required=False)
            self.report_progress("COMPLETE", 100,
                                 "Transfer/checksum, commit and fresh application boot verified")
            return self.last_result
        except Exception as exc:
            self.last_result.update(status="recovery_required" if self.recovery_required else "error",
                                    recovery_required=self.recovery_required, error=str(exc))
            self.log("FLASH RESULT " + json.dumps(self.last_result, sort_keys=True))
            raise
        finally:
            self.close()

    def flash_binary(self, binary_data_or_path, start_addr, end_addr, file_off=None,
                     dry_run=False, simulator_mode=False, recovery=False):
        prepared = self.profile.prepare_image(binary_data_or_path, start_addr, end_addr,
                                              file_off, simulator_mode)
        if dry_run:
            metadata = prepared["metadata"]
            self.last_result = dict(metadata, checksum_verified=False, boot_verified=False,
                                    commit_outcome="not_attempted", controller=self.profile.name)
            self.report_progress("VALIDATED", 100,
                                 "Offline validation complete; no Controller verification performed")
            return dict(self.last_result, status="validated", dry_run=True)
        return self.flash_prepared(prepared, recovery=recovery)
