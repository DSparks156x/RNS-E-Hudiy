"""Haldex Gen4 protocol, readout, and flash policy."""
import hashlib
import json
import logging
import struct
import time
from pathlib import Path
from typing import Any, Callable, Optional

from ...engine import (
    PQFlashProfile, PQFlasher, PQMemoryReader, PQReadError, PQReadProfile,
    SecurityAccess, add32, capture_contiguous, encode_vag_flash_date,
    fixed_challenge, parse_vag_identification,
)
from ...socketcan_device import SocketCANDevice
from ...vag_protocols.kwp import KWPClient, KWPError, KWPProfile
from ...vag_protocols.tp2 import TP20Transport
from .patches import (
    APP_SECTORS, DEFAULT_END, DEFAULT_START, application_checksums,
    prepare_image, selected_blocks, validate_image,
)

logger = logging.getLogger("HaldexFlasher")

# Constants
AWD_MODULE_ADDR    = 0x0A
APP_KEY_CONST      = 0x0000BAFB
LOADER_SEED        = bytes([0x11, 0x22, 0x33, 0x44])
LOADER_KEY         = bytes([0x11, 0x22, 0xEE, 0x3F])

SESSION_EXTENDED   = 0x89
SESSION_PROGRAMMING = 0x85
SA_APP_REQUEST_SEED = 0x01
SA_APP_SEND_KEY     = 0x02
SA_LDR_REQUEST_SEED = 0x01
SA_LDR_SEND_KEY     = 0x02
RC_ERASE           = 0xC4
RC_CHECKSUM        = 0xC5
IDENT_ECU_IDENT    = 0x9B
IDENT_STATUS_FLASH = 0x9C

FLASH_TOOL_ID = bytes([0x00, 0x01])
CHUNK_SIZE  = 240


def a3(addr: int) -> bytes:
    """24-bit big-endian address field."""
    return struct.pack(">I", addr)[1:]


def erase_payload(start: int, end: int, metadata: dict) -> bytes:
    flash_date = metadata.get("flash_date")
    if flash_date is None:
        raise RuntimeError("Host system date is unavailable; refusing to write a false flash date")
    return a3(start) + a3(end) + encode_vag_flash_date(flash_date) + FLASH_TOOL_ID


HALDEX_KWP_PROFILE = KWPProfile(
    busy_retry_services=frozenset({0x1A, 0x33}),
    busy_retries=3,
    exact_session_responses={
        SESSION_EXTENDED: b"\x50\x89",
        SESSION_PROGRAMMING: b"\x50\x85\x01",
    },
    exact_routine_responses={
        RC_ERASE: b"\x71\xC4\x01",
        RC_CHECKSUM: b"\x71\xC5",
    },
    reject_unprofiled_sessions=True,
    reject_unprofiled_routines=True,
    exact_key_status=0x34,
    single_byte_positive_services=frozenset({0x20, 0x36, 0x37, 0x82}),
    exact_response_lengths={0x33: 3},
)


class Kwp(KWPClient):
    """Haldex loader policy layered on the shared KWP implementation."""

    def __init__(self, transport, **kwargs):
        kwargs.setdefault("profile", HALDEX_KWP_PROFILE)
        super().__init__(transport, **kwargs)

    def security_seed(self, subfunction: int, *, length=4) -> bytes:
        return super().security_seed(subfunction, length=length)

    sa_seed = security_seed


APP_START, APP_END = 0x18000, 0x50000  # end exclusive
IMAGE_SIZE = 0x50000
UPLOAD_KEY_ADD = 0x762B
MAX_BLOCK = 200



def sha256(data):
    return hashlib.sha256(data).hexdigest().upper()


def validate_range(start, length):
    if length <= 0 or start < APP_START or start + length > APP_END:
        raise ValueError('Only nonempty application ranges 0x018000..0x04FFFF are supported')


def upload_request(start, length):
    validate_range(start, length)
    return b'\x35' + start.to_bytes(3, 'big') + b'\x00' + length.to_bytes(3, 'big')


class ProtocolError(RuntimeError):
    pass


HALDEX_READ_KWP_PROFILE = KWPProfile(
    exact_session_responses={SESSION_EXTENDED: b"\x50\x89", 0x84: b"\x50\x84"},
    exact_key_status=0x34,
    single_byte_positive_services=frozenset({0x20, 0x37}),
)

HALDEX_READ_PROFILE = PQReadProfile(
    name="haldex-gen4",
    module=AWD_MODULE_ADDR,
    image_size=IMAGE_SIZE,
    validate_range=validate_range,
    initial_session=SESSION_EXTENDED,
    privileged_session=0x84,
    security=SecurityAccess(0x03, 0x04, add32(UPLOAD_KEY_ADD), "haldex-read"),
    methods=("upload",),
    upload_block_max=MAX_BLOCK,
    strict_upload_blocks=True,
    mark_upload_before_request=True,
    leave_requests=(b"\x20", b"\x10\x89"),
    key_response=b"\x67\x04\x34",
)


class ApplicationReader(PQMemoryReader):
    """Haldex profile of the common PQ reader."""

    def __init__(self, transport, record=lambda event: None):
        super().__init__(
            transport, HALDEX_READ_PROFILE, record=record,
            kwp_factory=lambda tp, **kwargs: KWPClient(
                tp, profile=HALDEX_READ_KWP_PROFILE, debug=False),
        )

    @property
    def special_session(self):
        return self.privileged_active

    def exchange(self, request, prefix):
        try:
            response = self._exchange(request)
        except (KWPError, PQReadError) as exc:
            raise ProtocolError(str(exc)) from exc
        if not response.startswith(prefix):
            raise ProtocolError(f'Expected {prefix.hex()}, received {response.hex()}')
        return response[len(prefix):]

    def identify(self):
        try:
            return super().identify()
        except (KWPError, PQReadError) as exc:
            raise ProtocolError(str(exc)) from exc

    def enter(self):
        try:
            return super().enter()
        except (KWPError, PQReadError) as exc:
            raise ProtocolError(str(exc)) from exc

    def read_window(self, start, length):
        try:
            return super().read_window(start, length, "upload")
        except (KWPError, PQReadError) as exc:
            raise ProtocolError(str(exc)) from exc

    def leave(self):
        return super().leave()


def compare_reference(data, start, path):
    reference = Path(path).read_bytes()
    validate_image(reference)
    expected = reference[start:start+len(data)]
    differences = [i for i, (a, b) in enumerate(zip(data, expected)) if a != b]
    sectors = []
    for low, high in APP_SECTORS:
        lo, hi = max(low, start), min(high, start+len(data))
        if lo < hi:
            actual_slice = data[lo-start:hi-start]
            reference_slice = reference[lo:hi]
            sectors.append({'start': lo, 'end_exclusive': hi,
                            'whole_sector': (lo, hi) == (low, high),
                            'equal': actual_slice == reference_slice,
                            'captured_sha256': sha256(actual_slice),
                            'reference_sha256': sha256(reference_slice)})
    return {'path': str(Path(path).resolve()), 'reference_sha256': sha256(reference),
            'equal': not differences, 'different_bytes': len(differences),
            'first_difference_addresses': [start+i for i in differences[:32]],
            'sectors': sectors}


def capture(reader, output, start, length, passes, window, record, progress,
            recover=None, max_window_retries=2):
    try:
        return capture_contiguous(
            reader, output, start, length, passes, window, record, progress,
            image_size=IMAGE_SIZE, validate_selection=selected_blocks,
            recover=recover, max_window_retries=max_window_retries,
            protocol_errors=(PQReadError, ProtocolError),
        )
    except PQReadError as exc:
        raise ProtocolError(str(exc)) from exc





# --- Haldex flash target ---


def make_haldex_profile(*, kwp_factory, prepare_image, device_factory,
                        transport_factory, identify):
    def verify_loader(tp):
        if tp.tx_addr == 0x764:
            raise RuntimeError("Programming transition did not enter loader")

    def validate_application(info):
        if (info["in_bootloader"] or not info["sw_version"].strip()
                or not info["part_number"].strip() or info["flash_status"] not in (0, 1)):
            raise RuntimeError("Fresh expected application boot was not verified")

    def validate_controller(info, metadata):
        if info.get("in_bootloader"):
            raise RuntimeError(
                "Module is already in the bootloader; retry with --recovery")
        part = info.get("software_part_number", info.get("part_number", "")).upper()
        if not part.startswith(("0BR", "0AY", "0BS")):
            raise RuntimeError(
                f"Identification {part or '<empty>'} is not a recognized Haldex Gen4 family")

    return PQFlashProfile(
        name="haldex-gen4",
        module=AWD_MODULE_ADDR,
        kwp_factory=kwp_factory,
        prepare_image=prepare_image,
        device_factory=device_factory,
        transport_factory=transport_factory,
        identify=identify,
        validate_controller=validate_controller,
        is_application_channel=lambda tp: tp.tx_addr == 0x764,
        initial_session=SESSION_EXTENDED,
        programming_session=SESSION_PROGRAMMING,
        pre_programming_security=SecurityAccess(
            SA_APP_REQUEST_SEED, SA_APP_SEND_KEY, add32(APP_KEY_CONST),
            "haldex-application"),
        programming_security=SecurityAccess(
            SA_LDR_REQUEST_SEED, SA_LDR_SEND_KEY,
            fixed_challenge(LOADER_SEED, LOADER_KEY), "haldex-loader"),
        verify_programming_channel=verify_loader,
        chunk_size=CHUNK_SIZE,
        erase_routine=RC_ERASE,
        checksum_routine=RC_CHECKSUM,
        erase_payload=erase_payload,
        checksum_payload=lambda start, end, metadata:
            a3(start) + a3(end) + struct.pack(">H", metadata["checksum"]),
        validate_fresh_application=validate_application,
    )

class HaldexFlasher(PQFlasher):
    """Haldex Gen4 binding backed by the controller-neutral PQ lifecycle."""

    def __init__(self, channel: str = "can0", module: int = AWD_MODULE_ADDR,
                 device: Optional[Any] = None,
                 device_factory: Optional[Callable[[], Any]] = None,
                 progress_cb: Optional[Callable[..., None]] = None,
                 log_cb: Optional[Callable[[str], None]] = None,
                 debug: bool = False):
        # Resolve module globals at call time so tests and applications can
        # replace the adapter or artifact preparation boundary explicitly.
        profile = make_haldex_profile(
            kwp_factory=lambda tp, log, debug: Kwp(tp, log_fn=log, debug=debug),
            prepare_image=lambda *args, **kwargs: prepare_image(*args, **kwargs),
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
        ident = kwp.read_ecu_ident(IDENT_ECU_IDENT)
        status = kwp.read_ecu_ident(IDENT_STATUS_FLASH)
        if len(status) < 12:
            raise RuntimeError("Truncated Controller identification/status")
        result = parse_vag_identification(ident, status)
        result.update({
            "connected": True,
            "in_bootloader": tp.tx_addr != 0x764 or b"B_111545" in ident[2:],
        })
        return result

    def reset_ecu(self, to_bootloader=False):
        raise RuntimeError("Standalone reset is disabled; start a flash to enter programming")

    def flash_binary(self, binary_data_or_path, start_addr=DEFAULT_START,
                     end_addr=DEFAULT_END, file_off=None, dry_run=False,
                     simulator_mode=False, recovery=False):
        return super().flash_binary(binary_data_or_path, start_addr, end_addr,
                                    file_off=file_off, dry_run=dry_run,
                                    simulator_mode=simulator_mode,
                                    recovery=recovery)


# --- Command-line controller interface ---


def add_cli_arguments(parser):
    parser.add_argument("--simulator-mode", action="store_true", help="Internal bench-only patch set")


def apply_defaults(args):
    args.start = DEFAULT_START if args.start is None else args.start
    args.end = DEFAULT_END if args.end is None else args.end
    args.out = args.out or "data/raw/readout/haldex"


def validate_cli(parser, args):
    if args.readout:
        if args.input or args.recovery or args.simulator_mode:
            parser.error("--readout cannot be combined with flash, recovery, or simulator options")
        selected_blocks(args.start, args.end)
        if args.reference:
            validate_image(Path(args.reference).read_bytes())
        return
    if args.ident_only:
        if args.input or args.dry_run or args.simulator_mode:
            parser.error("--ident-only cannot be combined with flash or dry-run options")
        return
    if not args.input:
        parser.error("--input is required unless --readout or --ident-only is selected")
    selected_blocks(args.start, args.end)


def run_flash(args, runtime):
    prepared = prepare_image(args.input, args.start, args.end,
                             simulator_mode=args.simulator_mode)
    if args.dry_run:
        print(json.dumps(dict(prepared["metadata"], status="validated", dry_run=True,
                              recovery_mode=args.recovery), indent=2, sort_keys=True))
        print("No CAN traffic sent.")
        return 0
    print(json.dumps(dict(prepared["metadata"], recovery_mode=args.recovery),
                     indent=2, sort_keys=True))
    if not args.yes and input("Type YES to erase and flash the selected sectors: ") != "YES":
        print("Cancelled before adapter access.")
        return 1
    device = runtime.open_adapter(args)
    flasher = HaldexFlasher(
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
        "module": args.module, "adapter": args.adapter, "start": args.start,
        "end": args.end, "length": length, "passes": args.readout_passes,
        "window": args.readout_window, "hardware_access": not args.dry_run,
        "firmware_writes": False,
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
        reader = ApplicationReader(tp, events.append)
        report["controller"] = reader.identification()
        args.family.validate_identification(report["controller"])
        reader.enter()
        captures = capture(
            reader, output, args.start, length, args.readout_passes,
            args.readout_window, events.append,
            lambda p, done, total: runtime.progress(
                f"READ {p}", 100 * done / total, f"{done}/{total} bytes"),
        )
        report["captures"] = captures
        report["saved_ranges"] = {
            item["path"]: {"start": args.start, "end_exclusive": args.end + 1}
            for item in captures
        }
        captured = (output / captures[0]["path"]).read_bytes()[args.start:args.end + 1]
        checksums = application_checksums(captured, args.start)
        report["application_checksums"] = checksums
        if args.reference:
            report["comparisons"] = [compare_reference(captured, args.start, args.reference)]
        invalid = any(row["valid"] is False for row in checksums)
        report["status"] = "checksum_mismatch" if invalid else "captured_checksums_valid"
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
    return 0 if report["status"] == "captured_checksums_valid" else 1
