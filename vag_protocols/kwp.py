"""Canonical KWP2000 request/response client.

Transport framing is intentionally outside this module.  Any transport with
``send(bytes)`` and ``recv() -> bytes`` can carry KWP, including TP2 and test
fixtures.
"""
from dataclasses import dataclass, field
import logging
import time
from typing import Callable, Dict, FrozenSet, Optional


logger = logging.getLogger(__name__)

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
    0x36: "ExceedNumberOfAttempts",
    0x37: "RequiredTimeDelayNotExpired",
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


class KWPError(RuntimeError):
    pass


class KWPPendingTimeout(KWPError, TimeoutError):
    pass


class KWPNegativeResponse(KWPError):
    def __init__(self, request: bytes, response: bytes):
        self.request = request
        self.response = response
        self.service_id = response[1] if len(response) > 1 else None
        self.code = response[2] if len(response) > 2 else None
        description = KWP_NRC.get(self.code, "Unknown") if self.code is not None else "Malformed"
        code = f"0x{self.code:02X}" if self.code is not None else "missing"
        super().__init__(f"Negative response to {describe_kwp(request)}: NRC {code} ({description})")


def describe_kwp(request: bytes) -> str:
    if not request:
        return "Empty"
    sid = request[0]
    if sid == 0x10 and len(request) >= 2:
        return f"StartDiagnosticSession (0x{request[1]:02X})"
    if sid == 0x27 and len(request) >= 2:
        return f"SecurityAccess ({'seed' if request[1] & 1 else 'key'}, 0x{request[1]:02X})"
    if sid == 0x1A and len(request) >= 2:
        return f"ReadECUIdentification (0x{request[1]:02X})"
    if sid == 0x21 and len(request) >= 2:
        return f"ReadDataByLocalIdentifier (0x{request[1]:02X})"
    if sid == 0x34:
        return "RequestDownload"
    if sid == 0x35:
        return "RequestUpload"
    if sid == 0x36:
        return f"TransferData ({len(request) - 1} bytes)"
    if sid == 0x37:
        return "RequestTransferExit"
    if sid == 0x31 and len(request) >= 2:
        return f"StartRoutine (0x{request[1]:02X})"
    if sid == 0x33 and len(request) >= 2:
        return f"RoutineResults (0x{request[1]:02X})"
    if sid == 0x11:
        return "ECUReset"
    if sid == 0x3E:
        return "TesterPresent"
    return f"SID 0x{sid:02X}"


@dataclass(frozen=True)
class KWPProfile:
    echo_services: FrozenSet[int] = frozenset({0x10, 0x11, 0x1A, 0x27, 0x31, 0x33})
    busy_retry_services: FrozenSet[int] = frozenset()
    busy_retries: int = 0
    busy_delay: float = 0.2
    pending_timeout: float = 30.0
    pending_limit: int = 30
    exact_session_responses: Dict[int, bytes] = field(default_factory=dict)
    exact_routine_responses: Dict[int, bytes] = field(default_factory=dict)
    reject_unprofiled_sessions: bool = False
    reject_unprofiled_routines: bool = False
    exact_key_status: Optional[int] = None
    single_byte_positive_services: FrozenSet[int] = frozenset()
    exact_response_lengths: Dict[int, int] = field(default_factory=dict)


DEFAULT_PROFILE = KWPProfile()


class KWPClient:
    def __init__(self, transport, *, profile: KWPProfile = DEFAULT_PROFILE,
                 debug: bool = True, log_fn: Optional[Callable[[str], None]] = None,
                 clock=time.monotonic, sleeper=time.sleep):
        self.transport = transport
        # Compatibility for existing callers which used ``kwp.tp``.
        self.tp = transport
        self.profile = profile
        self.debug = debug
        self.log_fn = log_fn or logger.info
        self.clock = clock
        self.sleeper = sleeper

    def request(self, request: bytes, *, raise_negative: bool = True,
                validate_positive: bool = True) -> bytes:
        request = bytes(request)
        if not request:
            raise ValueError("KWP request cannot be empty")
        if self.debug:
            self.log_fn(f"[KWP TX] {request.hex()} ({describe_kwp(request)})")
        self.transport.send(request)
        response = self.transport.recv()
        deadline = self.clock() + self.profile.pending_timeout
        pending_count = 0
        busy_count = 0
        while response and response[0] == 0x7F:
            if len(response) != 3 or response[1] != request[0]:
                raise KWPError("Malformed or mismatched KWP negative response")
            if response[2] == 0x78:
                pending_count += 1
                if pending_count > self.profile.pending_limit or self.clock() >= deadline:
                    raise KWPPendingTimeout("KWP pending deadline exceeded")
                response = self.transport.recv()
                continue
            if (response[2] == 0x21
                    and request[0] in self.profile.busy_retry_services
                    and busy_count < self.profile.busy_retries):
                busy_count += 1
                self.sleeper(self.profile.busy_delay)
                self.transport.send(request)
                response = self.transport.recv()
                continue
            break
        if self.debug:
            self.log_fn(f"[KWP RX] {response.hex()}")
        if response and response[0] == 0x7F:
            if raise_negative:
                raise KWPNegativeResponse(request, response)
            return response
        if validate_positive:
            self._validate_positive(request, response)
        return response

    # Historical API name used by the flasher.
    raw = request

    def _validate_positive(self, request: bytes, response: bytes):
        if not response or response[0] != ((request[0] + 0x40) & 0xFF):
            got = response.hex() if response else "<empty>"
            raise KWPError(f"Unexpected positive KWP response: {got}")
        if request[0] in self.profile.echo_services:
            if len(request) < 2 or len(response) < 2 or response[1] != request[1]:
                raise KWPError("KWP subfunction/routine echo mismatch")
        if request[0] == 0x10:
            expected = self.profile.exact_session_responses.get(request[1])
            if expected is None and self.profile.reject_unprofiled_sessions:
                raise KWPError("Diagnostic session is not allowed by this KWP profile")
            if expected is not None and response != expected:
                raise KWPError("Unexpected diagnostic-session response")
        if request[0] == 0x31:
            expected = self.profile.exact_routine_responses.get(request[1])
            if expected is None and self.profile.reject_unprofiled_routines:
                raise KWPError("Routine is not allowed by this KWP profile")
            if expected is not None and response != expected:
                raise KWPError("Unexpected routine-start response/status")
        if request[0] == 0x27:
            if request[1] & 1 and len(response) < 3:
                raise KWPError("Security seed response has no seed")
            if (not request[1] & 1 and self.profile.exact_key_status is not None
                    and response != bytes([0x67, request[1], self.profile.exact_key_status])):
                raise KWPError("Security key was not accepted")
        if request[0] in self.profile.single_byte_positive_services and len(response) != 1:
            raise KWPError("Unexpected KWP response length")
        expected_length = self.profile.exact_response_lengths.get(request[0])
        if expected_length is not None and len(response) != expected_length:
            raise KWPError("Unexpected KWP response length")

    def session(self, session: int) -> bytes:
        return self.request(bytes([0x10, session]))

    def security_seed(self, subfunction: int, *, length: Optional[int] = None) -> bytes:
        seed = self.request(bytes([0x27, subfunction]))[2:]
        if length is not None and len(seed) != length:
            raise KWPError(f"Expected {length} security seed bytes, got {len(seed)}")
        return seed

    sa_seed = security_seed

    def security_key(self, subfunction: int, key: bytes) -> bytes:
        return self.request(bytes([0x27, subfunction]) + bytes(key))

    sa_key = security_key

    def read_ecu_ident(self, identifier: int) -> bytes:
        return self.request(bytes([0x1A, identifier]))

    def read_local_identifier(self, identifier: int) -> bytes:
        return self.request(bytes([0x21, identifier]))

    def request_download(self, address: int, size: int) -> int:
        response = self.request(b"\x34" + address.to_bytes(3, "big")
                                + b"\x00" + size.to_bytes(3, "big"))
        if len(response) != 2 or response[1] < 5:
            raise KWPError("Invalid RequestDownload block limit")
        return response[1]

    def transfer(self, data: bytes) -> bytes:
        return self.request(b"\x36" + bytes(data))

    def transfer_exit(self) -> bytes:
        return self.request(b"\x37")

    def routine(self, identifier: int, data: bytes = b"") -> bytes:
        return self.request(bytes([0x31, identifier]) + bytes(data))

    def routine_result(self, identifier: int) -> bytes:
        return self.request(bytes([0x33, identifier]))

    def ecu_reset(self, subfunction: int = 0x01) -> bytes:
        return self.request(bytes([0x11, subfunction]))

    def tester_present(self, subfunction: Optional[int] = None) -> bytes:
        request = b"\x3E" if subfunction is None else bytes([0x3E, subfunction])
        return self.request(request)
