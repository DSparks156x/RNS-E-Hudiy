"""PQ EPS conventional KWP readout and programming policy."""
import hashlib
import json
import struct
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
    DEFAULT_END, DEFAULT_START, FLASH_START, prepare_image, validate_selection,
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
        verify_programming_channel=lambda tp: None,
        chunk_size=CHUNK_SIZE,
        erase_routine=RC_ERASE,
        checksum_routine=RC_CHECKSUM,
        erase_payload=lambda start, end, metadata: a3(start) + a3(end),
        checksum_payload=lambda start, end, metadata:
            a3(start) + a3(end) + struct.pack(">H", metadata["checksum"]),
        validate_fresh_application=validate_application,
        commit_services=(0x82,),
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

    prepare_image = staticmethod(prepare_image)

    @staticmethod
    def _ident(kwp, tp):
        result = parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C))
        result.update(connected=True, in_bootloader=False)
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
    if args.read_eeprom:
        return
    flash = not args.readout and not args.ident_only
    args.start = (DEFAULT_START if flash else 0) if args.start is None else args.start
    args.end = (DEFAULT_END if flash else EPS_IMAGE_SIZE - 1) if args.end is None else args.end
    args.out = args.out or "data/raw/readout/pq-eps"


def validate_cli(parser, args):
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
