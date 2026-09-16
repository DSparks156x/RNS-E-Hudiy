"""Shared Haldex protocol and application readout.

Adapted from HaldexRE/flasher/haldex_flash.py (2026-09-16 refactor).
The vehicle lifecycle (progress, cancellation, verified boot) lives in
haldex_flasher.py; no duplicate adapter-specific flash/CLI flow is retained.
"""
import time
import os
import struct
import logging
import hashlib
from pathlib import Path
from typing import Optional, Callable
from .tp20 import TP20Transport, MessageTimeoutError
from .haldex_patcher import application_checksums, APP_SECTORS, validate_image, selected_blocks
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

ERASE_STAMP = bytes([0x20, 0x26, 0x01, 0x01, 0x00, 0x01])
CHUNK_SIZE  = 240


KWP_NRC = {
    0x10: "GeneralReject",
    0x11: "ServiceNotSupported / MovingLockout",
    0x12: "SubFunctionNotSupported / InvalidFormat",
    0x21: "Busy - RepeatRequest",
    0x22: "ConditionsNotCorrect or RequestSequenceError",
    0x23: "RoutineNotComplete",
    0x31: "RequestOutOfRange",
    0x33: "SecurityAccessDenied",
    0x35: "InvalidKey",
    0x36: "ExceedNumberOfAttempts (Lockout Active)",
    0x37: "RequiredTimeDelayNotExpired (Penalty Timer Running)",
    0x40: "DownloadNotAccepted",
    0x42: "CantDownloadToSpecifiedAddress",
    0x43: "CantDownloadNumberOfBytesRequested",
    0x71: "TransferSuspended",
    0x72: "TransferAborted",
    0x74: "IllegalAddressInBlockTransfer",
    0x75: "IllegalByteCountInBlockTransfer",
    0x77: "BlockTransferDataChecksumError",
    0x78: "RequestCorrectlyReceived - ResponsePending",
}


def describe_kwp(req: bytes) -> str:
    """Returns human-readable description for KWP request"""
    if not req:
        return "Empty"
    sid = req[0]
    if sid == 0x10 and len(req) >= 2:
        return f"StartDiagSession (0x{req[1]:02X})"
    elif sid == 0x27 and len(req) >= 2:
        sub = req[1]
        desc = "RequestSeed" if sub % 2 != 0 else "SendKey"
        return f"SecurityAccess {desc} (sub=0x{sub:02X})"
    elif sid == 0x1A and len(req) >= 2:
        sub = req[1]
        sub_name = {
            0x9B: "ECU_IDENT (0x9B)",
            0x9C: "STATUS_FLASH (0x9C)",
            0x90: "VIN (0x90)",
            0x97: "SYSTEM_NAME (0x97)",
        }.get(sub, f"id=0x{sub:02X}")
        return f"ReadEcuIdent ({sub_name})"
    elif sid == 0x34:
        return "RequestDownload"
    elif sid == 0x36:
        return f"TransferData ({len(req)-1} bytes)"
    elif sid == 0x37:
        return "RequestTransferExit"
    elif sid == 0x31 and len(req) >= 2:
        return f"StartRoutine (0x{req[1]:02X})"
    elif sid == 0x33 and len(req) >= 2:
        return f"RoutineResults (0x{req[1]:02X})"
    elif sid == 0x11:
        return "ECUReset"
    elif sid == 0x3E:
        return "TesterPresent"
    return f"SID 0x{sid:02X}"


def a3(addr: int) -> bytes:
    """24-bit big-endian address field."""
    return struct.pack(">I", addr)[1:]


def parse_flash_date(raw: bytes) -> str:
    """Decode 4-byte flash date stamp (e.g. bytes([0x20, 0x26, 0x01, 0x01])) to YYYY-MM-DD."""
    if len(raw) < 4:
        return raw.hex()
    if raw[:4] in (b'\x00\x00\x00\x00', b'\xff\xff\xff\xff'):
        return "None (unprogrammed)"
    if all((b >> 4) <= 9 and (b & 0x0F) <= 9 for b in raw[:4]):
        yyyy = f"{raw[0]:02x}{raw[1]:02x}"
        mm = f"{raw[2]:02x}"
        dd = f"{raw[3]:02x}"
        return f"{yyyy}-{mm}-{dd}"
    return raw[:4].hex()


class Kwp:
    def __init__(self, tp: TP20Transport, debug: bool = True, log_fn: Optional[Callable[[str], None]] = None):
        self.tp = tp
        self.debug = debug
        self.log_fn = log_fn or logger.info

    def raw(self, req: bytes) -> bytes:
        desc = describe_kwp(req)
        if self.debug:
            self.log_fn(f"[KWP TX] {req.hex()} ({desc})")
        self.tp.send(req)
        resp = self.tp.recv()
        deadline = time.monotonic() + 30.0
        busy_count = 0
        pending_count = 0
        while resp and resp[0] == 0x7f:
            if len(resp) != 3 or resp[1] != req[0]:
                raise RuntimeError('Malformed or mismatched KWP negative response')
            if resp[2] == 0x78:
                pending_count += 1
                if time.monotonic() >= deadline or pending_count > 30:
                    raise TimeoutError('KWP pending deadline exceeded')
                resp = self.tp.recv()  # pending means wait, never resend
                continue
            if resp[2] == 0x21 and req[0] in (0x1a, 0x33) and busy_count < 3:
                busy_count += 1
                time.sleep(0.2)
                self.tp.send(req)
                resp = self.tp.recv()
                continue
            break
        if self.debug:
            self.log_fn(f"[KWP RX] {resp.hex()}")

        if resp and resp[0] == 0x7F:
            service_id = resp[1] if len(resp) > 1 else -1
            nrc = resp[2] if len(resp) > 2 else -1
            nrc_desc = KWP_NRC.get(nrc, f"Unknown (0x{nrc:02X})")
            err_msg = f"Negative response to {desc} (SID 0x{service_id:02X}): NRC 0x{nrc:02X} ({nrc_desc})"
            logger.error(f"[KWP NEGATIVE RESPONSE] {err_msg}")
            raise RuntimeError(err_msg)

        if not resp or resp[0] != ((req[0] + 0x40) & 0xff):
            raise RuntimeError(f'Unexpected positive KWP response: {resp.hex()}')
        if req[0] in (0x10, 0x27, 0x1a, 0x31, 0x33, 0x11):
            if len(resp) < 2 or resp[1] != req[1]:
                raise RuntimeError('KWP subfunction/routine echo mismatch')
        if req[0] == 0x27:
            if req[1] & 1 and len(resp) != 6:
                raise RuntimeError('Security seed must be four bytes')
            if not req[1] & 1 and resp != bytes([0x67, req[1], 0x34]):
                raise RuntimeError('Security key was not accepted (expected status 0x34)')
        if req[0] == 0x33 and len(resp) != 3:
            raise RuntimeError('Routine result must contain exactly one status byte')
        if req[0] == 0x31:
            expected = {RC_ERASE: b'\x71\xc4\x01', RC_CHECKSUM: b'\x71\xc5'}.get(req[1])
            if expected is None or resp != expected:
                raise RuntimeError('Unexpected routine-start response/status')
        if req[0] == 0x10:
            expected = {SESSION_EXTENDED: b'\x50\x89', SESSION_PROGRAMMING: b'\x50\x85\x01'}.get(req[1])
            if expected is None or resp != expected:
                raise RuntimeError('Unexpected session response/status')
        if req[0] in (0x36, 0x37, 0x20, 0x82) and len(resp) != 1:
            raise RuntimeError('Unexpected KWP response length')
        return resp

    def session(self, s: int) -> bytes:
        return self.raw(bytes([0x10, s]))

    def sa_seed(self, sub: int) -> bytes:
        return self.raw(bytes([0x27, sub]))[2:]

    def sa_key(self, sub: int, key: bytes) -> bytes:
        return self.raw(bytes([0x27, sub]) + key)

    def read_ecu_ident(self, ident: int) -> bytes:
        return self.raw(bytes([0x1A, ident]))

    def request_download(self, addr: int, size: int) -> int:
        a = struct.pack(">I", addr)[1:]
        s = struct.pack(">I", size)[1:]
        r = self.raw(bytes([0x34]) + a + b"\x00" + s)
        if len(r) != 2 or r[1] < 5:
            raise RuntimeError('Invalid RequestDownload block limit')
        return r[1]

    def transfer(self, data: bytes) -> bytes:
        return self.raw(bytes([0x36]) + data)

    def transfer_exit(self) -> bytes:
        return self.raw(bytes([0x37]))

    def routine(self, rid: int, data: bytes = b"") -> bytes:
        return self.raw(bytes([0x31, rid]) + data)

    def routine_result(self, rid: int) -> bytes:
        return self.raw(bytes([0x33, rid]))

    def ecu_reset(self) -> bytes:
        return self.raw(bytes([0x11, 0x01]))

    def tester_present(self):
        try:
            self.tp.can_send(b"\xa3")
            self.tp.can_recv()
        except Exception:
            pass


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


class ApplicationReader:
    def __init__(self, transport, record=lambda event: None):
        self.transport = transport
        self.record = record
        self.special_session = False
        self.upload_active = False

    def exchange(self, request, prefix):
        # An allowlist guards against accidentally reusing flash/programming code.
        allowed = (request in (b'\x10\x89', b'\x10\x84', b'\x27\x03',
                               b'\x36', b'\x37', b'\x20', b'\x1a\x9b')
                   or (request[:2] == b'\x27\x04' and len(request) == 6)
                   or (request[:1] == b'\x35' and len(request) == 8))
        if not allowed:
            raise ValueError('Request is outside readout allowlist: ' + request.hex())
        if request[:1] == b'\x35':
            if request[4] != 0:
                raise ValueError('Only uncompressed upload is supported')
            validate_range(int.from_bytes(request[1:4], 'big'),
                           int.from_bytes(request[5:8], 'big'))
        self.record({'event': 'request', 'hex': request.hex()})
        self.transport.send(request)
        response = self.transport.recv()
        self.record({'event': 'response', 'hex': response.hex()})
        deadline = time.monotonic() + 30
        pending = 0
        while response == bytes([0x7f, request[0], 0x78]):
            pending += 1
            if pending > 30 or time.monotonic() >= deadline:
                raise ProtocolError('Readout response-pending deadline exceeded')
            # Pending means await completion, never repeat an upload transfer.
            response = self.transport.recv()
            self.record({'event': 'response', 'hex': response.hex()})
        if response[:1] == b'\x7f':
            raise ProtocolError('Negative response: ' + response.hex(' '))
        if not response.startswith(prefix):
            raise ProtocolError(f'Expected {prefix.hex()}, received {response.hex()}')
        if request in (b'\x10\x89', b'\x10\x84', b'\x37', b'\x20') and response != prefix:
            raise ProtocolError('Unexpected readout service response length')
        if request[:2] == b'\x27\x04' and response != b'\x67\x04\x34':
            raise ProtocolError('Readout security key was not accepted')
        return response[len(prefix):]

    def identify(self):
        return self.exchange(b'\x1a\x9b', b'\x5a\x9b')

    def enter(self):
        self.exchange(b'\x10\x89', b'\x50\x89')
        seed_bytes = self.exchange(b'\x27\x03', b'\x67\x03')
        if len(seed_bytes) != 4:
            raise ProtocolError('Expected exactly four seed bytes; refusing to guess')
        seed = int.from_bytes(seed_bytes, 'big')
        key = ((seed + UPLOAD_KEY_ADD) & 0xffffffff).to_bytes(4, 'big')
        # One calculated key attempt only. No brute force or automatic retries.
        self.exchange(b'\x27\x04' + key, b'\x67\x04')
        # Set before sending so an uncertain reply still causes cleanup.
        self.special_session = True
        self.exchange(b'\x10\x84', b'\x50\x84')

    def read_window(self, start, length):
        request = upload_request(start, length)
        self.upload_active = True
        answer = self.exchange(request, b'\x75')
        expected_limit = min(MAX_BLOCK, length)
        if answer != bytes([expected_limit]):
            raise ProtocolError(f'Unexpected upload block limit {answer.hex()}; expected {expected_limit}')
        data = bytearray()
        while len(data) < length:
            # Request has NO data and NO sequence byte on this KWP implementation.
            # Never retry an ambiguous 36: the Controller may already have advanced.
            block = self.exchange(b'\x36', b'\x76')
            expected = min(MAX_BLOCK, length - len(data))
            if len(block) != expected:
                raise ProtocolError(f'Upload at 0x{start+len(data):06X}: expected {expected} bytes, got {len(block)}')
            data.extend(block)
            self.record({'event': 'block_received', 'address': start + len(data) - len(block),
                         'length': len(block), 'end_exclusive': start + len(data)})
        self.exchange(b'\x37', b'\x77')
        self.upload_active = False
        return bytes(data)

    def leave(self):
        errors = []
        if self.upload_active:
            try:
                self.exchange(b'\x37', b'\x77')
                self.upload_active = False
            except Exception as exc:
                errors.append('transfer exit: ' + str(exc))
        if self.special_session:
            try:
                self.exchange(b'\x20', b'\x60')
                self.exchange(b'\x10\x89', b'\x50\x89')
                self.special_session = False
            except Exception as exc:
                errors.append('session exit: ' + str(exc))
        return errors


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
    selected_blocks(start, start+length-1)
    if passes not in (1, 2) or not 1 <= window <= 65536:
        raise ValueError('passes must be 1 or 2; window must be 1..65536')
    output = Path(output)
    results = []
    for pass_index in range(1, passes+1):
        path = output / f'pass{pass_index}.bin'
        with path.open('xb') as stream:
            # CPU addresses are file offsets, matching the flasher's 320 KiB input.
            # Unread bytes are padding, not captured flash contents.
            stream.write(b'\xff' * IMAGE_SIZE)
            stream.flush()
            for offset in range(0, length, window):
                size = min(window, length-offset)
                for attempt in range(max_window_retries+1):
                    try:
                        block = reader.read_window(start+offset, size)
                        break
                    except (TimeoutError, ConnectionError, RuntimeError) as exc:
                        # NRCs, changed protocol, and invalid lengths are not
                        # transient transport failures; don't hide them.
                        if isinstance(exc, ProtocolError) or recover is None or attempt == max_window_retries:
                            raise
                        record({'event': 'window_restart', 'pass': pass_index,
                                'address': start+offset, 'length': size,
                                'attempt': attempt+1, 'error': str(exc)})
                        recover(exc)
                if len(block) != size:
                    raise ProtocolError('Incomplete window')
                stream.seek(start+offset)
                stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
                record({'event': 'window_saved', 'pass': pass_index,
                        'address': start+offset, 'length': size, 'sha256': sha256(block)})
                progress(pass_index, offset+size, length)
        data = path.read_bytes()
        results.append({'path': path.name, 'length': len(data), 'sha256': sha256(data),
                        'captured_start': start, 'captured_end_exclusive': start+length,
                        'captured_length': length,
                        'captured_sha256': sha256(data[start:start+length])})
    if passes == 2 and (output/'pass1.bin').read_bytes() != (output/'pass2.bin').read_bytes():
        raise ProtocolError('Independent captures differ; do not treat this as a verified dump')
    return results


