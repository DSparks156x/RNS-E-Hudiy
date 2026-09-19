"""Compatibility API over the canonical :mod:`vag_protocols.kwp` client.

New code should import ``KWPClient`` directly from ``vag_protocols``. The
historical enums and stripped-payload convention remain for simulator and
third-party callers without maintaining a second KWP implementation.
"""
import struct
from enum import IntEnum

from .vag_protocols.kwp import KWPClient, KWPError, KWPNegativeResponse, KWPProfile


class NegativeResponseError(Exception):
    def __init__(self, message, service_id, error_code):
        super().__init__(message)
        self.message = message
        self.service_id = service_id
        self.error_code = error_code

    def __str__(self):
        return self.message


class InvalidServiceIdError(Exception):
    pass


class InvalidSubFunctionError(Exception):
    pass


class SERVICE_TYPE(IntEnum):
    DIAGNOSTIC_SESSION_CONTROL = 0x10
    ECU_RESET = 0x11
    READ_FREEZE_FRAME_DATA = 0x12
    READ_DIAGNOSTIC_TROUBLE_CODES = 0x13
    CLEAR_DIAGNOSTIC_INFORMATION = 0x14
    READ_STATUS_OF_DIAGNOSTIC_TROUBLE_CODES = 0x17
    READ_DIAGNOSTIC_TROUBLE_CODES_BY_STATUS = 0x18
    READ_ECU_IDENTIFICATION = 0x1A
    STOP_DIAGNOSTIC_SESSION = 0x20
    READ_DATA_BY_LOCAL_IDENTIFIER = 0x21
    READ_DATA_BY_COMMON_IDENTIFIER = 0x22
    READ_MEMORY_BY_ADDRESS = 0x23
    SECURITY_ACCESS = 0x27
    REQUEST_DOWNLOAD = 0x34
    REQUEST_UPLOAD = 0x35
    TRANSFER_DATA = 0x36
    REQUEST_TRANSFER_EXIT = 0x37
    WRITE_MEMORY_BY_ADDRESS = 0x3D
    TESTER_PRESENT = 0x3E


class ECU_IDENTIFICATION_TYPE(IntEnum):
    IDENT_ORIGINAL = 0x80
    IDENT_SCALING = 0x81
    IDENT_CURRENT = 0x82
    ECU_IDENT = 0x9B
    STATUS_FLASH = 0x9C
    SYSTEM_NAME = 0x97
    VIN = 0x90


class SESSION_TYPE(IntEnum):
    DEFAULT = 0x81
    PROGRAMMING = 0x85
    ENGINEERING_MODE = 0x86
    DIAGNOSTIC = 0x89
    EXTENDED = 0x92


class ACCESS_TYPE(IntEnum):
    PROGRAMMING_REQUEST_SEED = 1
    PROGRAMMING_SEND_KEY = 2
    REQUEST_SEED = 3
    SEND_KEY = 4
    MANUFACTURE_REQUEST_SEED = 0x9
    MANUFACTURE_SEND_KEY = 0xA


_COMPAT_PROFILE = KWPProfile(
    echo_services=frozenset({0x10, 0x11, 0x1A, 0x21, 0x22, 0x27, 0x3E}),
)


class KWP2000Client:
    """Historical API backed by ``vag_protocols.KWPClient``."""

    def __init__(self, transport, debug=False):
        self.transport = transport
        self.debug = debug
        self._client = KWPClient(
            transport,
            profile=_COMPAT_PROFILE,
            debug=debug,
            log_fn=print,
        )

    def _kwp(self, service_type, subfunction=None, data=None):
        sid = int(service_type)
        request = bytes([sid])
        if subfunction is not None:
            request += bytes([int(subfunction)])
        if data is not None:
            request += bytes(data)
        try:
            response = self._client.request(request, validate_positive=False)
        except KWPNegativeResponse as exc:
            code = exc.code if exc.code is not None else -1
            service_id = exc.service_id if exc.service_id is not None else -1
            raise NegativeResponseError(str(exc), service_id, code) from exc
        expected_sid = (sid + 0x40) & 0xFF
        actual_sid = response[0] if response else None
        if actual_sid != expected_sid:
            got = "<empty>" if actual_sid is None else f"0x{actual_sid:02X}"
            raise InvalidServiceIdError(f"Invalid response service ID: {got}")
        if subfunction is not None:
            actual_subfunction = response[1] if len(response) > 1 else None
            if actual_subfunction != int(subfunction):
                got = "<missing>" if actual_subfunction is None else f"0x{actual_subfunction:02X}"
                raise InvalidSubFunctionError(f"Invalid response subfunction: {got}")
        return response[1 if subfunction is None else 2:]

    def diagnostic_session_control(self, session_type):
        return self._kwp(SERVICE_TYPE.DIAGNOSTIC_SESSION_CONTROL, subfunction=session_type)

    def security_access(self, access_type, security_key=b""):
        request_seed = int(access_type) % 2 != 0
        if request_seed and security_key:
            raise ValueError("security_key not allowed when requesting seed")
        if not request_seed and not security_key:
            raise ValueError("security_key is missing when sending key")
        return self._kwp(SERVICE_TYPE.SECURITY_ACCESS, subfunction=access_type, data=security_key)

    def read_ecu_identification(self, data_identifier_type):
        return self._kwp(SERVICE_TYPE.READ_ECU_IDENTIFICATION, data_identifier_type)

    def read_memory_by_address(self, address, size):
        address_bytes = struct.pack(">I", address)[1:]
        size_bytes = struct.pack(">B", size) if size <= 255 else struct.pack(">H", size)
        return self._kwp(SERVICE_TYPE.READ_MEMORY_BY_ADDRESS, data=address_bytes + size_bytes)

    def tester_present(self, subfunction=0x00):
        return self._kwp(SERVICE_TYPE.TESTER_PRESENT, subfunction=subfunction)
