"""PQ35 EPS identification, experimental readout, and KWP flashing policy."""
import binascii
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Callable, Optional

from ...engine import (
    PQFlashProfile, PQFlasher, PQMemoryReader, PQReadError, PQReadProfile,
    SecurityAccess, add32, capture_sparse, parse_vag_identification,
)
from ...socketcan_device import SocketCANDevice
from ...vag_protocols.kwp import KWPClient, KWPProfile
from ...vag_protocols.tp2 import TP20Transport

EPS_MODULE_ADDR = 0x09
EPS_IMAGE_SIZE = 0x60000
EPS_FLASH_START = 0x0A000
EPS_FLASH_END = 0x5FFFF
EPS_CONFIG_START = 0x5D000
EPS_DATASET_START = 0x5E000
EPS_BLOCK_SIZE = 0x1000
SESSION_PROGRAMMING = 0x85
RC_ERASE = 0xC4
RC_CHECKSUM = 0xC5
CHUNK_SIZE = 240
SESSION_DIAGNOSTIC = 0x89
SESSION_ENGINEERING = 0x86
READ_KEY_ADD = 0x9CE8
MAX_READ_MEMORY_BLOCK = 0xF0

FLASH_REGIONS = {
    "firmware": (EPS_FLASH_START, EPS_FLASH_END),
    "configuration": (EPS_CONFIG_START, EPS_CONFIG_START + EPS_BLOCK_SIZE - 1),
    "steer-dataset": (EPS_DATASET_START, EPS_DATASET_START + EPS_BLOCK_SIZE - 1),
}


def a3(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFF:
        raise ValueError("EPS flash addresses must fit in 24 bits")
    return value.to_bytes(3, "big")


def programming_key(seed: bytes):
    """PQ35 EPS 27 01/02 programming seed/key algorithm."""
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


def validate_eps_range(start: int, length: int):
    if length <= 0 or start < 0 or start + length > EPS_IMAGE_SIZE:
        raise ValueError("PQ EPS range must be within 0x000000..0x05FFFF")


EPS_READ_KWP_PROFILE = KWPProfile(
    exact_session_responses={SESSION_DIAGNOSTIC: b"\x50\x89", SESSION_ENGINEERING: b"\x50\x86"},
)


def make_eps_read_profile(key_add=READ_KEY_ADD):
    return PQReadProfile(
        name="pq-eps", module=EPS_MODULE_ADDR, image_size=EPS_IMAGE_SIZE,
        validate_range=validate_eps_range, initial_session=SESSION_DIAGNOSTIC,
        privileged_session=SESSION_ENGINEERING,
        security=SecurityAccess(0x03, 0x04, add32(key_add), "pq-eps-read"),
        methods=("read-memory", "upload"), upload_block_max=0x1000,
        strict_upload_blocks=False, mark_upload_before_request=False,
        leave_requests=(bytes([0x10, SESSION_DIAGNOSTIC]),),
    )


class PQEPSReader(PQMemoryReader):
    """Experimental conventional-KWP EPS reader; contains no mutating services."""

    def __init__(self, transport, *, key_add=READ_KEY_ADD, record=lambda event: None):
        super().__init__(
            transport, make_eps_read_profile(key_add), record=record,
            kwp_factory=lambda tp, **kwargs: KWPClient(
                tp, profile=EPS_READ_KWP_PROFILE, debug=False),
        )


def capture_eps(reader: PQEPSReader, output: Path, start: int, length: int, method: str,
                *, chunk: int, record=lambda event: None,
                progress=lambda done, total: None):
    return capture_sparse(
        reader, output, start, length, method, chunk=chunk,
        image_size=EPS_IMAGE_SIZE, validate_range=validate_eps_range,
        record=record, progress=progress)


def crc16_xmodem(data: bytes) -> int:
    return binascii.crc_hqx(bytes(data), 0)


def validate_dataset(data: bytes) -> dict:
    if len(data) != EPS_BLOCK_SIZE:
        raise ValueError("A standalone steering dataset must be exactly 4096 bytes")
    if data in (b"\x00" * EPS_BLOCK_SIZE, b"\xFF" * EPS_BLOCK_SIZE):
        raise ValueError("Steering dataset is blank")
    pointers = [struct.unpack_from("<I", data, offset)[0]
                for offset in range(0, 32, 4)]
    if (not all(EPS_DATASET_START <= pointer < EPS_DATASET_START + EPS_BLOCK_SIZE
                for pointer in pointers)
            or pointers != sorted(pointers)):
        raise ValueError(
            "Steering dataset does not contain the expected 0x5E-relative pointer table")
    stored = int.from_bytes(data[-2:], "big")
    calculated = crc16_xmodem(data[:-2])
    if stored != calculated:
        raise ValueError(
            f"Steering dataset CRC-16/XMODEM mismatch: stored 0x{stored:04X}, "
            f"calculated 0x{calculated:04X}")
    return {
        "algorithm": "CRC-16/XMODEM",
        "stored": stored,
        "calculated": calculated,
        "valid": True,
        "pointer_table_entries_checked": len(pointers),
    }


def region_name(start_addr: int, end_addr: int) -> str:
    for name, bounds in FLASH_REGIONS.items():
        if bounds == (start_addr, end_addr):
            return name
    choices = ", ".join(
        f"{name}=0x{start:05X}..0x{end:05X}"
        for name, (start, end) in FLASH_REGIONS.items())
    raise ValueError(f"Select one complete EPS flash region: {choices}")


def firmware_revision_number(info: dict) -> Optional[int]:
    """Return the numeric four-character VAG software revision, if trustworthy."""
    value = str(info.get("sw_version", info.get("firmware_revision", ""))).strip()
    return int(value) if len(value) == 4 and value.isdigit() else None


def validate_partial_flash_revision(info: dict, metadata: dict) -> None:
    """Fail closed before programming when an older rack cannot flash one block."""
    if metadata.get("selection") == "firmware":
        return
    revision = firmware_revision_number(info)
    if revision is None or revision < 3000:
        displayed = info.get("sw_version", info.get("firmware_revision", "unknown"))
        raise RuntimeError(
            f"EPS software revision {displayed!r} does not approve partial-region "
            "flashing; select full firmware 0x0A000..0x05FFFF")


def prepare_image(source, start_addr=EPS_FLASH_START, end_addr=EPS_FLASH_END,
                  file_off=None, simulator_mode=False):
    if simulator_mode:
        raise ValueError("PQ EPS does not support simulator-mode patching")
    if type(start_addr) is not int or type(end_addr) is not int:
        raise ValueError("Addresses must be integers")
    selected = region_name(start_addr, end_addr)
    raw = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)

    dataset_validation = None
    if len(raw) == EPS_IMAGE_SIZE:
        image = raw
        region = image[start_addr:end_addr + 1]
        source_kind = "full-firmware"
        source_offset = start_addr
        if selected == "steer-dataset":
            dataset_validation = validate_dataset(region)
    elif len(raw) == EPS_BLOCK_SIZE:
        if selected != "steer-dataset":
            raise ValueError(
                "A 4096-byte input is only accepted for the 0x5E steer-dataset block")
        if file_off not in (None, EPS_DATASET_START):
            raise ValueError("Standalone dataset source offset must be 0x5E000")
        region = raw
        image = None
        source_kind = "steer-dataset"
        source_offset = 0
        dataset_validation = validate_dataset(region)
    else:
        raise ValueError(
            "PQ EPS input must be a 393216-byte full firmware image or a "
            "4096-byte steer dataset")

    if not region or len(region) != end_addr - start_addr + 1:
        raise ValueError("Input does not contain the complete selected EPS region")
    metadata = {
        "original_sha256": hashlib.sha256(raw).hexdigest(),
        "prepared_sha256": hashlib.sha256(region).hexdigest(),
        "patches": [],
        "patch_policy": "no mutation; exact source bytes are transferred",
        "start_addr": start_addr,
        "end_addr": end_addr,
        "size": len(region),
        "checksum": sum(region) & 0xFFFF,
        "selection": selected,
        "selection_policy": "one validated complete EPS flash region",
        "source_kind": source_kind,
        "source_size": len(raw),
        "source_offset": source_offset,
        "dataset_validation": dataset_validation,
        "simulator_mode": False,
        "bench_only": False,
    }
    return {"image": image, "region": region, "metadata": metadata}


def make_eps_profile(*, kwp_factory, prepare_image_fn, device_factory,
                     transport_factory, identify):
    def validate_controller(info, metadata):
        if not info.get("software_part_number", info.get("part_number", "")).strip():
            raise RuntimeError("EPS identification returned an empty part number")
        validate_partial_flash_revision(info, metadata)

    def validate_application(info):
        if (not info.get("software_part_number", info.get("part_number", "")).strip()
                or info.get("flash_status") not in (0, 1)):
            raise RuntimeError("Fresh EPS application boot was not verified")

    return PQFlashProfile(
        name="pq-eps",
        module=EPS_MODULE_ADDR,
        kwp_factory=kwp_factory,
        prepare_image=prepare_image_fn,
        device_factory=device_factory,
        transport_factory=transport_factory,
        identify=identify,
        validate_controller=validate_controller,
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
    def __init__(self, channel: str = "can0", module: int = EPS_MODULE_ADDR,
                 device: Optional[Any] = None,
                 device_factory: Optional[Callable[[], Any]] = None,
                 progress_cb: Optional[Callable[..., None]] = None,
                 log_cb: Optional[Callable[[str], None]] = None,
                 debug: bool = False):
        profile = make_eps_profile(
            kwp_factory=lambda tp, log, debug:
                KWPClient(tp, log_fn=log, debug=debug),
            prepare_image_fn=lambda *args, **kwargs: prepare_image(*args, **kwargs),
            device_factory=lambda selected_channel: SocketCANDevice(channel=selected_channel),
            transport_factory=lambda *args, **kwargs: TP20Transport(*args, **kwargs),
            identify=lambda kwp, tp: self._ident(kwp, tp),
        )
        super().__init__(
            profile, channel=channel, module=module, device=device,
            device_factory=device_factory, progress_cb=progress_cb,
            log_cb=log_cb, debug=debug)

    prepare_image = staticmethod(prepare_image)

    @staticmethod
    def _ident(kwp, tp):
        result = parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C))
        result.update(connected=True, in_bootloader=False)
        return result

    def flash_binary(self, binary_data_or_path, start_addr=EPS_FLASH_START,
                     end_addr=EPS_FLASH_END, file_off=None, dry_run=False,
                     simulator_mode=False, recovery=False):
        return super().flash_binary(
            binary_data_or_path, start_addr, end_addr, file_off=file_off,
            dry_run=dry_run, simulator_mode=simulator_mode, recovery=recovery)


def add_cli_arguments(parser):
    parser.add_argument(
        "--readout-method", choices=("auto", "read-memory", "upload"), default="auto",
        help="Experimental conventional KWP read service")
    parser.add_argument(
        "--eps-sa-add", type=lambda value: int(value, 0), default=READ_KEY_ADD,
        help=f"27 03/04 additive constant (default 0x{READ_KEY_ADD:04X})")


def apply_defaults(args):
    flash = not args.readout and not args.ident_only
    args.start = (EPS_CONFIG_START if flash else 0) if args.start is None else args.start
    args.end = ((EPS_CONFIG_START + EPS_BLOCK_SIZE - 1) if flash
                else EPS_IMAGE_SIZE - 1) if args.end is None else args.end
    args.out = args.out or "data/raw/readout/pq-eps"


def validate_cli(parser, args):
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
        parser.error("--input is required unless --ident-only is selected")
    if args.reference:
        parser.error("--reference currently applies only to Haldex readout")
    try:
        region_name(args.start, args.end)
    except ValueError as exc:
        parser.error(str(exc))


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
        for address in (args.start, 0xA000, 0x5D000, 0x5E000):
            if args.start <= address <= args.end - 15 and address not in candidates:
                candidates.append(address)
        probe = reader.probe(candidates, requested=args.readout_method)
        report["probe"] = probe
        chunk = (MAX_READ_MEMORY_BLOCK if probe["method"] == "read-memory"
                 else min(args.readout_window, 0xFFFFFF))
        report["capture"] = capture_eps(
            reader, output, args.start, length, probe["method"], chunk=chunk,
            record=events.append,
            progress=lambda done, total: runtime.progress(
                "EPS READ", 100 * done / total, f"{done}/{total} bytes"))
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


def run_flash(args, runtime):
    prepared = prepare_image(args.input, args.start, args.end)
    if args.dry_run:
        print(json.dumps(
            dict(prepared["metadata"], status="validated", dry_run=True,
                 recovery_mode=args.recovery), indent=2, sort_keys=True))
        print("No CAN traffic sent.")
        return 0
    print(json.dumps(
        dict(prepared["metadata"], recovery_mode=args.recovery),
        indent=2, sort_keys=True))
    selection = prepared["metadata"]["selection"]
    if not args.yes and input(
            f"Type YES to erase and flash EPS {selection}: ") != "YES":
        print("Cancelled before adapter access.")
        return 1
    device = runtime.open_adapter(args)
    flasher = PQEPSFlasher(
        device=device, module=args.module,
        device_factory=lambda: runtime.open_adapter(args),
        progress_cb=runtime.progress, debug=args.verbose)
    result = flasher.flash_prepared(prepared, recovery=args.recovery)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
