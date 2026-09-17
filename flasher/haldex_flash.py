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
from .tp20 import TP20Transport
from .haldex_patcher import application_checksums, APP_SECTORS, validate_image, selected_blocks
from vag_protocols.kwp import KWPClient, KWPError, KWPProfile
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


class ApplicationReader:
    def __init__(self, transport, record=lambda event: None):
        self.transport = transport
        self.kwp = KWPClient(transport, debug=False)
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
        try:
            response = self.kwp.request(request)
        except KWPError as exc:
            raise ProtocolError(str(exc)) from exc
        self.record({'event': 'response', 'hex': response.hex()})
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


