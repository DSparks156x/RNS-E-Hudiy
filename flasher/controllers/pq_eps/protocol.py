"""PQ EPS conventional KWP readout and programming policy."""
import hashlib
import json
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from ...engine import (
    PQFlashProfile, PQFlasher, PQMemoryReader, PQReadError, PQReadProfile,
    SecurityAccess, add32, capture_sparse, parse_vag_identification,
)
from ...socketcan_device import SocketCANDevice
from ...vag_protocols.kwp import KWPClient, KWPProfile
from ...vag_protocols.tp2 import TP20Transport
from .patches import (
    DATASET_END, DATASET_SIZE, DATASET_START, DEFAULT_END, DEFAULT_START,
    FLASH_START, prepare_image, validate_selection,
)

EPS_MODULE_ADDR = 0x09
EPS_IMAGE_SIZE = 0x60000
SESSION_DIAGNOSTIC = 0x89
SESSION_ENGINEERING = 0x86
READ_REQUEST_SEED = 0x03
READ_SEND_KEY = 0x04
READ_KEY_ADD = 0x1596
MAX_READ_MEMORY_BLOCK = 0xF0
SESSION_PROGRAMMING = 0x85
RC_ERASE = 0xC4
RC_CHECKSUM = 0xC5
CHUNK_SIZE = 240


def decorate_identification(info: dict) -> dict:
    """Add EPS application/loader state and the Kl. dataset identifier."""
    result = dict(info)
    description = str(result.get("system_desc", "")).strip()
    dataset = re.search(r"\bKl\.\s*(\d+)\b", description, re.IGNORECASE)
    result["dataset_version"] = dataset.group(1) if dataset else None
    result["in_bootloader"] = "EPS_ZFLS BB" in description.upper()
    return result


def programming_key(seed: bytes):
    """Known PQ EPS 27 01/02 seed/key algorithm."""
    if len(seed) != 4:
        raise RuntimeError(f"Expected four-byte security seed, got {len(seed)}")
    if not any(seed):
        return None
    key = int.from_bytes(seed, "big")
    for _ in range(3):
        tmp = (key ^ 0x003F1735) & 0xFFFFFFFF
        key = (tmp + 0xA3FF7890) & 0xFFFFFFFF
        if key < 0xA3FF7890:
            key = (key >> 1) | (tmp << 31)
        key &= 0xFFFFFFFF
    return key.to_bytes(4, "big")


EPS_PROGRAMMING_SECURITY = SecurityAccess(
    0x01, 0x02, programming_key, "pq-eps-programming")
PQEPSProtocolError = PQReadError


def a3(value: int) -> bytes:
    return struct.pack(">I", value)[1:]


EPS_FLASH_KWP_PROFILE = KWPProfile(
    exact_routine_responses={RC_ERASE: b"\x71\xC4\x01", RC_CHECKSUM: b"\x71\xC5"},
    reject_unprofiled_routines=True,
    single_byte_positive_services=frozenset({0x36, 0x37, 0x82}),
    exact_response_lengths={0x33: 3},
)


class EPSKWPClient(KWPClient):
    def __init__(self, transport, **kwargs):
        kwargs.setdefault("profile", EPS_FLASH_KWP_PROFILE)
        super().__init__(transport, **kwargs)

    def security_seed(self, subfunction: int, *, length=4) -> bytes:
        return super().security_seed(subfunction, length=length)

    sa_seed = security_seed


def validate_eps_range(start: int, length: int):
    if length <= 0 or start < 0 or start + length > EPS_IMAGE_SIZE:
        raise ValueError("PQ EPS range must be within 0x000000..0x05FFFF")


def read_memory_request(address: int, length: int) -> bytes:
    validate_eps_range(address, length)
    if length > 0xFF:
        raise ValueError("KWP ReadMemoryByAddress length must fit in one byte")
    return b"\x23" + address.to_bytes(3, "big") + bytes([length])


def eps_upload_request(address: int, length: int) -> bytes:
    validate_eps_range(address, length)
    return b"\x35" + address.to_bytes(3, "big") + b"\x00" + length.to_bytes(3, "big")


def additive_key(seed: bytes, constant: int = READ_KEY_ADD) -> bytes:
    result = add32(constant)(seed)
    return b"" if result is None else result


def make_eps_read_profile(key_add=READ_KEY_ADD):
    return PQReadProfile(
        name="pq-eps",
        module=EPS_MODULE_ADDR,
        image_size=EPS_IMAGE_SIZE,
        validate_range=validate_eps_range,
        initial_session=SESSION_DIAGNOSTIC,
        privileged_session=SESSION_ENGINEERING,
        security=SecurityAccess(READ_REQUEST_SEED, READ_SEND_KEY, add32(key_add), "pq-eps-read"),
        methods=("read-memory", "upload"),
        upload_block_max=0x1000,
        strict_upload_blocks=False,
        mark_upload_before_request=False,
        leave_requests=(bytes([0x10, SESSION_DIAGNOSTIC]),),
    )


@dataclass(frozen=True)
class ProbeResult:
    method: str
    session: int
    security_unlocked: bool
    sample_address: int
    sample_hex: str


class PQEPSReader(PQMemoryReader):
    def __init__(self, transport, *, key_add=READ_KEY_ADD, record=lambda event: None):
        super().__init__(transport, make_eps_read_profile(key_add), record=record)

    def unlock_engineering(self):
        self.enter(ensure_diagnostic=False)

    def probe(self, addresses, *, requested="auto") -> ProbeResult:
        return ProbeResult(**super().probe(addresses, requested=requested))


def capture_eps(reader: PQEPSReader, output: Path, start: int, length: int, method: str,
            *, chunk: int, record=lambda event: None, progress=lambda done, total: None):
    return capture_sparse(reader, output, start, length, method, chunk=chunk,
                          image_size=EPS_IMAGE_SIZE, validate_range=validate_eps_range,
                          record=record, progress=progress)


# --- EPS flash target ---


def make_eps_flash_profile(*, kwp_factory, image_preparer, device_factory,
                           transport_factory, identify):
    def validate_controller(info, metadata):
        part = info.get("software_part_number", info.get("part_number", "")).upper()
        if not part.startswith(("1K0909144", "8J0909144")):
            raise RuntimeError(
                f"Identification {part or '<empty>'} is not a recognized PQ EPS family")
        full_flash = (metadata.get("start_addr"), metadata.get("end_addr")) == (
            FLASH_START, EPS_IMAGE_SIZE - 1)
        revision_text = str(
            info.get("sw_version", info.get("firmware_revision", ""))).strip()
        revision = (int(revision_text)
                    if len(revision_text) == 4 and revision_text.isdigit() else None)
        if not full_flash and (revision is None or revision < 3000):
            raise RuntimeError(
                f"EPS software revision {revision_text or 'unknown'!r} does not approve "
                "partial-region flashing; select full firmware 0x0A000..0x05FFFF")

    def validate_application(info):
        if (not info.get("sw_version", "").strip()
                or not info.get("part_number", "").strip()
                or info.get("flash_status") not in (0, 1)):
            raise RuntimeError("Fresh expected EPS application boot was not verified")

    def verify_programming_channel(tp):
        kwp = EPSKWPClient(tp)
        info = decorate_identification(parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C)))
        description = str(info.get("system_desc", "")).strip()
        if not info["in_bootloader"]:
            raise RuntimeError(
                f"EPS did not enter its resident loader; identified {description or '<empty>'!r}")

    return PQFlashProfile(
        name="pq-eps",
        module=EPS_MODULE_ADDR,
        kwp_factory=kwp_factory,
        prepare_image=image_preparer,
        device_factory=device_factory,
        transport_factory=transport_factory,
        identify=identify,
        validate_controller=validate_controller,
        # The EPS loader reconnects on the same logical TP2 module/channel IDs;
        # unlike Haldex there is no address change to use as a channel gate.
        is_application_channel=lambda tp: True,
        initial_session=None,
        programming_session=SESSION_PROGRAMMING,
        pre_programming_security=None,
        programming_security=EPS_PROGRAMMING_SECURITY,
        verify_programming_channel=verify_programming_channel,
        chunk_size=CHUNK_SIZE,
        erase_routine=RC_ERASE,
        checksum_routine=RC_CHECKSUM,
        erase_payload=lambda start, end, metadata: a3(start) + a3(end),
        checksum_payload=lambda start, end, metadata:
            a3(start) + a3(end) + struct.pack(">H", metadata["checksum"]),
        validate_fresh_application=validate_application,
        commit_services=(0x82,),
        programming_reconnect_delay=1.0,
    )


class PQEPSFlasher(PQFlasher):
    """PQ EPS binding backed by the controller-neutral PQ lifecycle."""

    def __init__(self, channel: str = "can0", module: int = EPS_MODULE_ADDR,
                 device: Optional[Any] = None,
                 device_factory: Optional[Callable[[], Any]] = None,
                 progress_cb: Optional[Callable[..., None]] = None,
                 log_cb: Optional[Callable[[str], None]] = None,
                 debug: bool = False):
        profile = make_eps_flash_profile(
            kwp_factory=lambda tp, log, debug: EPSKWPClient(
                tp, log_fn=log, debug=debug),
            image_preparer=lambda *args, **kwargs: prepare_image(*args, **kwargs),
            device_factory=lambda selected_channel: SocketCANDevice(channel=selected_channel),
            transport_factory=lambda *args, **kwargs: TP20Transport(*args, **kwargs),
            identify=lambda kwp, tp: self._ident(kwp, tp),
        )
        super().__init__(profile, channel=channel, module=module, device=device,
                         device_factory=device_factory, progress_cb=progress_cb,
                         log_cb=log_cb, debug=debug)

    @staticmethod
    def prepare_image(source, start_addr=DEFAULT_START, end_addr=DEFAULT_END,
                      file_off=None, simulator_mode=False):
        """Expose the common UI/controller keyword contract for EPS images."""
        return prepare_image(
            source, start_addr, end_addr, file_off=file_off,
            simulator_mode=simulator_mode)

    @staticmethod
    def _ident(kwp, tp):
        result = decorate_identification(parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C)))
        result["connected"] = True
        return result

    def flash_binary(self, binary_data_or_path, start_addr=DEFAULT_START,
                     end_addr=DEFAULT_END, file_off=None, dry_run=False,
                     simulator_mode=False, recovery=False):
        return super().flash_binary(
            binary_data_or_path, start_addr, end_addr, file_off=file_off,
            dry_run=dry_run, simulator_mode=simulator_mode, recovery=recovery)


# --- Command-line controller interface ---


def add_cli_arguments(parser):
    parser.add_argument(
        "--readout-method", choices=("auto", "read-memory", "upload"), default="auto",
        help="Conventional KWP read service")
    parser.add_argument(
        "--eps-sa-add", type=lambda value: int(value, 0), default=READ_KEY_ADD,
        help=f"27 03/04 additive constant (default 0x{READ_KEY_ADD:04X})")


def apply_defaults(args):
    if (args.read_eeprom or args.read_eps_faults or args.read_eps_motion
            or args.read_eps_assist or args.read_eps_supply or args.read_eps_can_config):
        return
    flash = not args.readout and not args.ident_only
    if (flash and args.input and args.start is None and args.end is None
            and Path(args.input).is_file()
            and Path(args.input).stat().st_size == DATASET_SIZE):
        args.start, args.end = DATASET_START, DATASET_END
    args.start = (DEFAULT_START if flash else 0) if args.start is None else args.start
    args.end = (DEFAULT_END if flash else EPS_IMAGE_SIZE - 1) if args.end is None else args.end
    args.out = args.out or "data/raw/readout/pq-eps"


def validate_cli(parser, args):
    if args.read_eps_can_config:
        if not args.out:
            parser.error("--read-eps-can-config requires --out FILE")
        if not 1 <= args.can_config_samples <= 200:
            parser.error("--can-config-samples must be 1..200")
        if not 50 <= args.can_config_interval_ms <= 1000:
            parser.error("--can-config-interval-ms must be 50..1000")
        if (args.input or args.recovery or args.start is not None or args.end is not None
                or args.reference or args.readout_passes != 1
                or args.readout_window != 0x10000 or args.readout_method != "auto"):
            parser.error("--read-eps-can-config cannot be combined with flash or CPU-readout options")
        return
    if args.read_eps_supply:
        if not args.out:
            parser.error("--read-eps-supply requires --out FILE")
        if not 1 <= args.supply_samples <= 200:
            parser.error("--supply-samples must be 1..200")
        if not 50 <= args.supply_interval_ms <= 1000:
            parser.error("--supply-interval-ms must be 50..1000")
        if (args.input or args.recovery or args.start is not None or args.end is not None
                or args.reference or args.readout_passes != 1
                or args.readout_window != 0x10000 or args.readout_method != "auto"):
            parser.error("--read-eps-supply cannot be combined with flash or CPU-readout options")
        return
    if args.read_eps_assist:
        if not args.out:
            parser.error("--read-eps-assist requires --out FILE")
        if not 1 <= args.assist_samples <= 200:
            parser.error("--assist-samples must be 1..200")
        if not 50 <= args.assist_interval_ms <= 1000:
            parser.error("--assist-interval-ms must be 50..1000")
        if (args.input or args.recovery or args.start is not None or args.end is not None
                or args.reference or args.readout_passes != 1
                or args.readout_window != 0x10000 or args.readout_method != "auto"):
            parser.error("--read-eps-assist cannot be combined with flash or CPU-readout options")
        return
    if args.read_eps_motion:
        if not args.out:
            parser.error("--read-eps-motion requires --out FILE")
        if not 1 <= args.motion_samples <= 200:
            parser.error("--motion-samples must be 1..200")
        if not 50 <= args.motion_interval_ms <= 1000:
            parser.error("--motion-interval-ms must be 50..1000")
        if (args.input or args.recovery or args.start is not None or args.end is not None
                or args.reference or args.readout_passes != 1
                or args.readout_window != 0x10000 or args.readout_method != "auto"):
            parser.error("--read-eps-motion cannot be combined with flash or CPU-readout options")
        return
    if args.read_eps_faults:
        if not args.out:
            parser.error("--read-eps-faults requires --out FILE")
        if (args.input or args.recovery or args.start is not None or args.end is not None
                or args.reference or args.readout_passes != 1
                or args.readout_window != 0x10000 or args.readout_method != "auto"):
            parser.error("--read-eps-faults cannot be combined with flash or CPU-readout options")
        return
    if args.read_eeprom:
        if not args.out:
            parser.error("--read-eeprom requires --out FILE")
        if (args.input or args.recovery or args.start is not None or args.end is not None
                or args.reference or args.readout_passes != 1
                or args.readout_window != 0x10000 or args.readout_method != "auto"):
            parser.error("--read-eeprom cannot be combined with flash or CPU-readout options")
        return
    if args.ident_only:
        if args.input or args.dry_run:
            parser.error("--ident-only cannot be combined with flash or dry-run options")
        return
    if args.readout:
        if args.input or args.recovery:
            parser.error("--readout cannot be combined with flash or recovery options")
        if args.reference:
            parser.error("--reference currently applies only to Haldex readout")
        if args.readout_passes != 1:
            parser.error("PQ EPS probing currently supports one pass")
        validate_eps_range(args.start, args.end - args.start + 1)
        return
    if not args.input:
        parser.error("--input is required unless --readout or --ident-only is selected")
    validate_selection(args.start, args.end)


def run_flash(args, runtime):
    prepared = prepare_image(args.input, args.start, args.end)
    if args.dry_run:
        print(json.dumps(dict(prepared["metadata"], status="validated", dry_run=True,
                              recovery_mode=args.recovery), indent=2, sort_keys=True))
        print("No CAN traffic sent.")
        return 0
    print(json.dumps(dict(prepared["metadata"], recovery_mode=args.recovery),
                     indent=2, sort_keys=True))
    if not args.yes and input("Type YES to erase and flash the selected EPS range: ") != "YES":
        print("Cancelled before adapter access.")
        return 1
    device = runtime.open_adapter(args)
    flasher = PQEPSFlasher(
        device=device, module=args.module,
        device_factory=lambda: runtime.open_adapter(args),
        progress_cb=runtime.progress, debug=args.verbose,
    )
    result = flasher.flash_prepared(prepared, recovery=args.recovery)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def run_readout(args, runtime):
    length = args.end - args.start + 1
    plan = {
        "operation": "readout", "controller_family": args.family.name,
        "adapter": args.adapter, "module": args.module, "start": args.start,
        "end": args.end, "length": length, "method": args.readout_method,
        "security_level": "27 03/04", "security_algorithm": "add32",
        "security_constant": args.eps_sa_add,
        "hardware_access": not args.dry_run, "firmware_writes": False,
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=False)
    events = []
    cleanup_errors = []
    report = dict(plan, status="in_progress", cleanup_errors=cleanup_errors)
    device = tp = reader = None
    try:
        device = runtime.open_adapter(args)
        tp = TP20Transport(device, module=args.module, timeout=2.0, debug=args.verbose)
        reader = PQEPSReader(tp, key_add=args.eps_sa_add, record=events.append)
        report["controller"] = reader.identification()
        args.family.validate_identification(report["controller"])
        candidates = []
        for address in (args.start, 0xA000, 0x5E000):
            if args.start <= address <= args.end - 15 and address not in candidates:
                candidates.append(address)
        probe = reader.probe(candidates, requested=args.readout_method)
        report["probe"] = probe.__dict__
        chunk = (MAX_READ_MEMORY_BLOCK if probe.method == "read-memory"
                 else min(args.readout_window, 0xFFFFFF))
        report["capture"] = capture_eps(
            reader, output, args.start, length, probe.method, chunk=chunk,
            record=events.append,
            progress=lambda done, total: runtime.progress(
                "EPS READ", 100 * done / total, f"{done}/{total} bytes"),
        )
        report["status"] = (
            "captured_complete" if report["capture"]["unreadable_bytes"] == 0
            else "captured_partial")
    except Exception as exc:
        report.update(status="requires_attention", error=f"{type(exc).__name__}: {exc}")
    finally:
        if reader is not None:
            cleanup_errors.extend(reader.leave())
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                cleanup_errors.append(f"disconnect: {exc}")
        if device is not None:
            try:
                device.close()
            except Exception as exc:
                cleanup_errors.append(f"adapter close: {exc}")
        if cleanup_errors:
            report["status"] = "requires_attention"
        (output / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
        (output / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] in ("captured_complete", "captured_partial") else 1


def run_eeprom(args, runtime):
    """Capture the full 1 KiB EPS serial EEPROM via read-only KWP upload."""
    output = Path(args.out)
    if output.exists():
        raise ValueError(f"Refusing to overwrite {output}")
    plan = {
        "operation": "read_eeprom", "controller_family": args.family.name,
        "adapter": args.adapter, "module": args.module,
        "eeprom_offset": 0, "length": 0x400,
        "kwp_upload_request": "35 00 00 00 00 00 04 00",
        "security_level": "27 03/04", "security_constant": args.eps_sa_add,
        "output": str(output), "hardware_access": not args.dry_run,
        "firmware_writes": False,
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    device = tp = reader = None
    cleanup_errors = []
    data = identity = None
    read_error = None
    try:
        device = runtime.open_adapter(args)
        tp = TP20Transport(device, module=args.module, timeout=2.0, debug=args.verbose)
        reader = PQEPSReader(tp, key_add=args.eps_sa_add)
        identity = reader.identification()
        args.family.validate_identification(identity)
        reader.diagnostic_session()
        reader.enter(ensure_diagnostic=False)
        data = reader.read_upload(0, 0x400)
        if len(data) != 0x400:
            raise PQReadError(f"Expected 1024 EEPROM bytes, got {len(data)}")
    except Exception as exc:
        read_error = f"{type(exc).__name__}: {exc}"
    finally:
        if reader is not None:
            cleanup_errors.extend(reader.leave())
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                cleanup_errors.append(f"disconnect: {exc}")
        if device is not None:
            try:
                device.close()
            except Exception as exc:
                cleanup_errors.append(f"adapter close: {exc}")

    if read_error is not None:
        print(json.dumps(dict(plan, status="requires_attention", error=read_error,
                              cleanup_errors=cleanup_errors), indent=2, sort_keys=True))
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(data)
    result = dict(plan, controller=identity, status="captured_complete",
                  sha256=hashlib.sha256(data).hexdigest().upper(),
                  cleanup_errors=cleanup_errors)
    if cleanup_errors:
        result["status"] = "requires_attention"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not cleanup_errors else 1


EPS_FAULT_GROUPS = tuple(range(0x32, 0x46))
EPS_FAULT_HEADERS = frozenset((0x32, 0x36, 0x3A, 0x3E, 0x42))


def run_faults(args, runtime):
    """Save all five EPS fault slots and their three snapshot pages via SID 21."""
    output = Path(args.out)
    if output.exists():
        raise ValueError(f"Refusing to overwrite {output}")
    report = {
        "operation": "read_eps_faults", "controller_family": args.family.name,
        "adapter": args.adapter, "module": args.module,
        "service": "21", "groups": [f"{group:02X}" for group in EPS_FAULT_GROUPS],
        "hardware_access": not args.dry_run, "firmware_writes": False,
        "output": str(output),
    }
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    device = tp = None
    responses = {}
    errors = []
    cleanup_errors = []
    try:
        device = runtime.open_adapter(args)
        tp = TP20Transport(device, module=args.module, timeout=2.0, debug=args.verbose)
        kwp = EPSKWPClient(tp)
        identity = parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C))
        args.family.validate_identification(identity)
        report["controller"] = identity
        for group in EPS_FAULT_GROUPS:
            try:
                payload = kwp.read_local_identifier(group)
                if len(payload) < 2 or payload[1] != group:
                    raise PQReadError(f"SID 21 group {group:02X} response echo mismatch")
                responses[f"{group:02X}"] = payload.hex(" ").upper()
                if (group in EPS_FAULT_HEADERS and len(payload) == 14
                        and payload[2] == 0x4B and payload[5] == 0x4B
                        and payload[8] == 0xA1 and payload[11] == 0x6B):
                    report.setdefault("headers", {})[f"{group:02X}"] = {
                        "internal_id": int.from_bytes(payload[3:5], "big"),
                        "subcode": int.from_bytes(payload[6:8], "big"),
                        "flags": int.from_bytes(payload[9:11], "big"),
                        "occurrences": payload[12],
                    }
            except Exception as exc:
                errors.append(f"21 {group:02X}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        errors.append(f"session: {type(exc).__name__}: {exc}")
    finally:
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                cleanup_errors.append(f"disconnect: {exc}")
        if device is not None:
            try:
                device.close()
            except Exception as exc:
                cleanup_errors.append(f"adapter close: {exc}")

    report.update(responses=responses, errors=errors, cleanup_errors=cleanup_errors,
                  status="captured_complete" if not errors and not cleanup_errors
                  else "captured_partial" if responses else "requires_attention")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "captured_complete" else 1


def decode_eps_motion_response(payload: bytes) -> int:
    """Extract TT 3001 SID 21 01 field 3 (signed gp-0x665E)."""
    if len(payload) != 14 or payload[:2] != b"\x61\x01" or payload[8] != 0x74:
        raise PQReadError("Unexpected TT 3001 21 01 motion-rate field layout")
    return int.from_bytes(payload[9:11], "big", signed=True)


def decode_eps_post_slew_selector(payload: bytes) -> int:
    """Extract TT 3001 SID 21 01 field 1 raw gp-0x65C7 byte."""
    if len(payload) != 14 or payload[:4] != b"\x61\x01\x1A\x46":
        raise PQReadError("Unexpected TT 3001 21 01 cap-selector field layout")
    return payload[4]


def run_motion(args, runtime):
    """Read the stock motion-rate group on a stationary EPS; never enter programming."""
    output = Path(args.out)
    if output.exists():
        raise ValueError(f"Refusing to overwrite {output}")
    report = {
        "operation": "read_eps_motion", "controller_family": args.family.name,
        "adapter": args.adapter, "module": args.module,
        "request": "21 01", "sample_count": args.motion_samples,
        "minimum_interval_ms": args.motion_interval_ms,
        "hardware_access": not args.dry_run, "firmware_writes": False,
        "output": str(output),
        "limiter_branch_rate_magnitude": 3650,
        "post_slew_cap_source_ram": "0x03FF2B39",
        "post_slew_minimum_cap_selector_max": 38,
        "limitation": "Stationary sampling only; host timestamps and KWP latency can miss brief motion-rate or cap-selector changes.",
    }
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    device = tp = None
    samples = []
    errors = []
    cleanup_errors = []
    try:
        device = runtime.open_adapter(args)
        tp = TP20Transport(device, module=args.module, timeout=2.0, debug=args.verbose)
        kwp = EPSKWPClient(tp)
        identity = parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C))
        args.family.validate_identification(identity)
        report["controller"] = identity
        for index in range(args.motion_samples):
            started_mono_ns = time.monotonic_ns()
            started_ns = time.time_ns()
            try:
                payload = kwp.read_local_identifier(0x01)
                rate = decode_eps_motion_response(payload)
                cap_selector = decode_eps_post_slew_selector(payload)
                samples.append({"index": index, "host_time_ns": started_ns,
                                "response": payload.hex(" ").upper(),
                                "signed_rate": rate, "rate_magnitude": abs(rate),
                                "at_or_above_branch": abs(rate) >= 3650,
                                "post_slew_cap_selector": cap_selector,
                                "at_min_post_slew_cap_knot": cap_selector <= 38})
            except Exception as exc:
                errors.append(f"sample {index}: {type(exc).__name__}: {exc}")
            if index + 1 < args.motion_samples:
                elapsed_ms = (time.monotonic_ns() - started_mono_ns) / 1_000_000
                time.sleep(max(0, args.motion_interval_ms - elapsed_ms) / 1000)
    except Exception as exc:
        errors.append(f"session: {type(exc).__name__}: {exc}")
    finally:
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                cleanup_errors.append(f"disconnect: {exc}")
        if device is not None:
            try:
                device.close()
            except Exception as exc:
                cleanup_errors.append(f"adapter close: {exc}")

    report.update(samples=samples, errors=errors, cleanup_errors=cleanup_errors,
                  status="captured_complete" if len(samples) == args.motion_samples
                  and not errors and not cleanup_errors else
                  "captured_partial" if samples else "requires_attention")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "captured_complete" else 1


def run_assist(args, runtime):
    """Read stock group 05 assist stages on a stationary EPS, without security access."""
    output = Path(args.out)
    if output.exists():
        raise ValueError(f"Refusing to overwrite {output}")
    report = {
        "operation": "read_eps_assist", "controller_family": args.family.name,
        "adapter": args.adapter, "module": args.module,
        "request": "21 05", "sample_count": args.assist_samples,
        "minimum_interval_ms": args.assist_interval_ms,
        "hardware_access": not args.dry_run, "firmware_writes": False,
        "output": str(output),
        "fields": ["speed-selected assist map output", "protected motor request",
                   "pre-limiter final assist", "published driver torque"],
        "limitation": "Stationary sampling only; stock values are compressed formatter fields and KWP can miss fast transients.",
    }
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    device = tp = None
    samples = []
    errors = []
    cleanup_errors = []
    try:
        device = runtime.open_adapter(args)
        tp = TP20Transport(device, module=args.module, timeout=2.0, debug=args.verbose)
        kwp = EPSKWPClient(tp)
        identity = parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C))
        args.family.validate_identification(identity)
        report["controller"] = identity
        for index in range(args.assist_samples):
            started_mono_ns = time.monotonic_ns()
            started_ns = time.time_ns()
            try:
                payload = kwp.read_local_identifier(0x05)
                ended_ns = time.time_ns()
                round_trip_ns = time.monotonic_ns() - started_mono_ns
                layout_valid = (len(payload) == 14 and payload[:2] == b"\x61\x05"
                                and [payload[pos] for pos in (2, 5, 8, 11)]
                                == [0x5D, 0x5D, 0x5D, 0x5E])
                samples.append({"index": index, "host_time_ns": started_ns,
                                "host_end_time_ns": ended_ns,
                                "request_round_trip_ms": round(round_trip_ns / 1_000_000, 3),
                                "response": payload.hex(" ").upper(),
                                "layout_valid": layout_valid,
                                "field_triples": [payload[pos:pos + 3].hex(" ").upper()
                                                  for pos in (2, 5, 8, 11)]
                                if layout_valid else []})
                if not layout_valid:
                    errors.append(f"sample {index}: unexpected TT 3001 21 05 assist-field layout")
            except Exception as exc:
                errors.append(f"sample {index}: {type(exc).__name__}: {exc}")
            if index + 1 < args.assist_samples:
                elapsed_ms = (time.monotonic_ns() - started_mono_ns) / 1_000_000
                time.sleep(max(0, args.assist_interval_ms - elapsed_ms) / 1000)
    except Exception as exc:
        errors.append(f"session: {type(exc).__name__}: {exc}")
    finally:
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                cleanup_errors.append(f"disconnect: {exc}")
        if device is not None:
            try:
                device.close()
            except Exception as exc:
                cleanup_errors.append(f"adapter close: {exc}")

    report.update(samples=samples, errors=errors, cleanup_errors=cleanup_errors,
                  status="captured_complete" if len(samples) == args.assist_samples
                  and not errors and not cleanup_errors else
                  "captured_partial" if samples else "requires_attention")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "captured_complete" else 1


def run_supply(args, runtime):
    """Read TT 3001 group 02 while stationary, without security access."""
    output = Path(args.out)
    if output.exists():
        raise ValueError(f"Refusing to overwrite {output}")
    report = {
        "operation": "read_eps_supply", "controller_family": args.family.name,
        "adapter": args.adapter, "module": args.module,
        "request": "21 02", "sample_count": args.supply_samples,
        "minimum_interval_ms": args.supply_interval_ms,
        "hardware_access": not args.dry_run, "firmware_writes": False,
        "output": str(output),
        "source_ram_address": "0x03FF2BAA",
        "encoding": "byte 4 = (u16(raw supply proxy) >> 3) & 0xFF",
        "normal_adc_producer_range": [19, 1703],
        "limitation": "Stationary sampling only; field is an eight-count raw supply-proxy interval, not a calibrated voltage or held rate factor.",
    }
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    device = tp = None
    samples = []
    errors = []
    cleanup_errors = []
    try:
        device = runtime.open_adapter(args)
        tp = TP20Transport(device, module=args.module, timeout=2.0, debug=args.verbose)
        kwp = EPSKWPClient(tp)
        identity = parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C))
        args.family.validate_identification(identity)
        report["controller"] = identity
        for index in range(args.supply_samples):
            started_mono_ns = time.monotonic_ns()
            started_ns = time.time_ns()
            try:
                payload = kwp.read_local_identifier(0x02)
                ended_ns = time.time_ns()
                round_trip_ns = time.monotonic_ns() - started_mono_ns
                layout_valid = (len(payload) >= 5 and
                                payload[:4] == b"\x61\x02\x06\x7D")
                sample = {
                    "index": index, "host_time_ns": started_ns,
                    "host_end_time_ns": ended_ns,
                    "request_round_trip_ms": round(round_trip_ns / 1_000_000, 3),
                    "response": payload.hex(" ").upper(),
                    "layout_valid": layout_valid,
                }
                if layout_valid:
                    encoded = payload[4]
                    sample.update(encoded_byte=encoded,
                                  raw_count_interval_mod_2048=[encoded * 8, encoded * 8 + 7])
                else:
                    errors.append(f"sample {index}: unexpected TT 3001 21 02 supply-field layout")
                samples.append(sample)
            except Exception as exc:
                errors.append(f"sample {index}: {type(exc).__name__}: {exc}")
            if index + 1 < args.supply_samples:
                elapsed_ms = (time.monotonic_ns() - started_mono_ns) / 1_000_000
                time.sleep(max(0, args.supply_interval_ms - elapsed_ms) / 1000)
    except Exception as exc:
        errors.append(f"session: {type(exc).__name__}: {exc}")
    finally:
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                cleanup_errors.append(f"disconnect: {exc}")
        if device is not None:
            try:
                device.close()
            except Exception as exc:
                cleanup_errors.append(f"adapter close: {exc}")

    report.update(samples=samples, errors=errors, cleanup_errors=cleanup_errors,
                  status="captured_complete" if len(samples) == args.supply_samples
                  and not errors and not cleanup_errors else
                  "captured_partial" if samples else "requires_attention")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "captured_complete" else 1


def decode_eps_can_config_response(payload: bytes) -> dict:
    """Decode stock TT3001 21 08 field 1; retain the full raw response."""
    if len(payload) < 5 or payload[:3] != b"\x61\x08\x6B":
        raise ValueError("unexpected TT 3001 21 08 first-field layout")
    secondary_word = int.from_bytes(payload[3:5], "big")
    secondary_byte = secondary_word & 0xFF
    return {
        "secondary_config_word": secondary_word,
        "secondary_config_byte": secondary_byte,
        "secondary_bit0_set": bool(secondary_byte & 1),
        "secondary_telemetry_gate_open_if_selected": not bool(secondary_byte & 1),
    }


def run_can_config(args, runtime):
    """Read stock group 08 on a stationary EPS; no programming or security."""
    output = Path(args.out)
    if output.exists():
        raise ValueError(f"Refusing to overwrite {output}")
    report = {
        "operation": "read_eps_can_config", "controller_family": args.family.name,
        "adapter": args.adapter, "module": args.module,
        "request": "21 08", "sample_count": args.can_config_samples,
        "minimum_interval_ms": args.can_config_interval_ms,
        "hardware_access": not args.dry_run, "firmware_writes": False,
        "output": str(output),
        "source_ram_address": "0x03FF3238",
        "limitation": "Stationary read only. Field 1 exposes the secondary word, not the primary-branch selectors, page, CAN readiness or actual 0x6D0/1 transmission.",
    }
    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    device = tp = None
    samples, errors, cleanup_errors = [], [], []
    try:
        device = runtime.open_adapter(args)
        tp = TP20Transport(device, module=args.module, timeout=2.0, debug=args.verbose)
        kwp = EPSKWPClient(tp)
        identity = parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C))
        args.family.validate_identification(identity)
        report["controller"] = identity
        for index in range(args.can_config_samples):
            started_mono_ns = time.monotonic_ns()
            started_ns = time.time_ns()
            try:
                payload = kwp.read_local_identifier(0x08)
                ended_ns = time.time_ns()
                sample = {
                    "index": index, "host_time_ns": started_ns,
                    "host_end_time_ns": ended_ns,
                    "request_round_trip_ms": round(
                        (time.monotonic_ns() - started_mono_ns) / 1_000_000, 3),
                    "response": payload.hex(" ").upper(),
                }
                try:
                    sample.update(decode_eps_can_config_response(payload))
                    sample["layout_valid"] = True
                except ValueError as exc:
                    sample["layout_valid"] = False
                    errors.append(f"sample {index}: {exc}")
                samples.append(sample)
            except Exception as exc:
                errors.append(f"sample {index}: {type(exc).__name__}: {exc}")
            if index + 1 < args.can_config_samples:
                elapsed_ms = (time.monotonic_ns() - started_mono_ns) / 1_000_000
                time.sleep(max(0, args.can_config_interval_ms - elapsed_ms) / 1000)
    except Exception as exc:
        errors.append(f"session: {type(exc).__name__}: {exc}")
    finally:
        if tp is not None:
            try:
                tp.disconnect()
            except Exception as exc:
                cleanup_errors.append(f"disconnect: {exc}")
        if device is not None:
            try:
                device.close()
            except Exception as exc:
                cleanup_errors.append(f"adapter close: {exc}")

    report.update(samples=samples, errors=errors, cleanup_errors=cleanup_errors,
                  status="captured_complete" if len(samples) == args.can_config_samples
                  and not errors and not cleanup_errors else
                  "captured_partial" if samples else "requires_attention")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "captured_complete" else 1
