import ctypes
from ctypes import wintypes
import struct
import time
import os
import winreg
from typing import List, Tuple, Optional

# Protocol IDs
J1850VPW = 1
J1850PWM = 2
ISO9141 = 3
ISO14230 = 4
CAN = 5
ISO15765 = 6
SCI_A_ENGINE = 7
SCI_A_TRANS = 8
SCI_B_ENGINE = 9
SCI_B_TRANS = 10

# Filter Types
PASSTHRU_FILTER_MASK = 1
PASSTHRU_FILTER_PATTERN = 2
PASSTHRU_FILTER_FLOW_CONTROL = 3

# Flags
CAN_29BIT_ID = 0x00000100
ISO15765_FRAME_PAD = 0x00000040

# Errors
STATUS_NOERROR = 0
ERR_BUFFER_EMPTY = 0x0000000E
ERR_BUFFER_FULL = 0x00000007
ERR_BUFFER_OVERFLOW = 0x00000008

class PASSTHRU_MSG(ctypes.Structure):
    _fields_ = [
        ("ProtocolID", wintypes.DWORD),
        ("RxStatus", wintypes.DWORD),
        ("TxFlags", wintypes.DWORD),
        ("Timestamp", wintypes.DWORD),
        ("DataSize", wintypes.DWORD),
        ("ExtraDataIndex", wintypes.DWORD),
        ("Data", ctypes.c_ubyte * 4128),
    ]


def find_sm2_dll() -> str:
    """Finds Scanmatik J2534 DLL from registry or standard location."""
    reg_paths = [
        r"SOFTWARE\WOW6432Node\PassThruSupport.04.04\Scanmatik - SM2 USB",
        r"SOFTWARE\PassThruSupport.04.04\Scanmatik - SM2 USB",
        r"SOFTWARE\WOW6432Node\PassThruSupport.04.04\Scanmatik - SM3 USB",
        r"SOFTWARE\PassThruSupport.04.04\Scanmatik - SM3 USB",
    ]
    for rp in reg_paths:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rp) as key:
                val, _ = winreg.QueryValueEx(key, "FunctionLibrary")
                if os.path.isfile(val):
                    return val
        except OSError:
            pass

    default_path = r"C:\Program Files (x86)\Scanmatik\smj2534.dll"
    if os.path.isfile(default_path):
        return default_path

    return default_path


class J2534Device:
    def __init__(self, dll_path: Optional[str] = None):
        if not dll_path:
            dll_path = find_sm2_dll()

        if not os.path.isfile(dll_path):
            raise FileNotFoundError(f"J2534 DLL not found at: {dll_path}")

        self.dll_path = dll_path
        self.dll = ctypes.WinDLL(dll_path)
        self.device_id = wintypes.DWORD(0)
        self.channel_id = wintypes.DWORD(0)
        self.filter_id = wintypes.DWORD(0)

        # Setup prototypes
        self._setup_prototypes()

    def _setup_prototypes(self):
        self.dll.PassThruOpen.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        self.dll.PassThruOpen.restype = wintypes.DWORD

        self.dll.PassThruClose.argtypes = [wintypes.DWORD]
        self.dll.PassThruClose.restype = wintypes.DWORD

        self.dll.PassThruConnect.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        self.dll.PassThruConnect.restype = wintypes.DWORD

        self.dll.PassThruDisconnect.argtypes = [wintypes.DWORD]
        self.dll.PassThruDisconnect.restype = wintypes.DWORD

        self.dll.PassThruReadMsgs.argtypes = [wintypes.DWORD, ctypes.POINTER(PASSTHRU_MSG), ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
        self.dll.PassThruReadMsgs.restype = wintypes.DWORD

        self.dll.PassThruWriteMsgs.argtypes = [wintypes.DWORD, ctypes.POINTER(PASSTHRU_MSG), ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
        self.dll.PassThruWriteMsgs.restype = wintypes.DWORD

        self.dll.PassThruStartMsgFilter.argtypes = [wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(PASSTHRU_MSG), ctypes.POINTER(PASSTHRU_MSG), ctypes.POINTER(PASSTHRU_MSG), ctypes.POINTER(wintypes.DWORD)]
        self.dll.PassThruStartMsgFilter.restype = wintypes.DWORD

        self.dll.PassThruStopMsgFilter.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.dll.PassThruStopMsgFilter.restype = wintypes.DWORD

        self.dll.PassThruIoctl.argtypes = [wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        self.dll.PassThruIoctl.restype = wintypes.DWORD

        if hasattr(self.dll, "PassThruSetProgrammingVoltage"):
            self.dll.PassThruSetProgrammingVoltage.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
            self.dll.PassThruSetProgrammingVoltage.restype = wintypes.DWORD

    def open(self):
        res = self.dll.PassThruOpen(None, ctypes.byref(self.device_id))
        if res != STATUS_NOERROR:
            raise RuntimeError(f"PassThruOpen failed with error code: 0x{res:08X}")
        print(f"[J2534] Device opened, DeviceID: {self.device_id.value}")

    def set_ignition(self, on: bool, pin: int = 15):
        """Controls Scanmatik 2 ignition/power pin (Pin 15 on bench cable, 12V on / 0V off)"""
        voltage = 12000 if on else 0  # 12,000 mV = 12V
        if hasattr(self.dll, "PassThruSetProgrammingVoltage"):
            res = self.dll.PassThruSetProgrammingVoltage(self.device_id, pin, voltage)
            return res
        return -1

    def close(self):
        if self.device_id.value != 0:
            self.dll.PassThruClose(self.device_id)
            self.device_id.value = 0

    def connect_can(self, baudrate: int = 500000):
        # Protocol: CAN (5), Flags: 0, Baudrate: 500000
        res = self.dll.PassThruConnect(self.device_id, CAN, 0, baudrate, ctypes.byref(self.channel_id))
        if res != STATUS_NOERROR:
            raise RuntimeError(f"PassThruConnect (CAN) failed with error code: 0x{res:08X}")
        print(f"[J2534] Connected to CAN @ {baudrate} bps, ChannelID: {self.channel_id.value}")

        # Setup Pass-all filter for standard 11-bit CAN IDs
        mask_msg = PASSTHRU_MSG()
        mask_msg.ProtocolID = CAN
        mask_msg.DataSize = 4
        mask_msg.Data[0] = 0
        mask_msg.Data[1] = 0
        mask_msg.Data[2] = 0
        mask_msg.Data[3] = 0

        pattern_msg = PASSTHRU_MSG()
        pattern_msg.ProtocolID = CAN
        pattern_msg.DataSize = 4
        pattern_msg.Data[0] = 0
        pattern_msg.Data[1] = 0
        pattern_msg.Data[2] = 0
        pattern_msg.Data[3] = 0

        res = self.dll.PassThruStartMsgFilter(self.channel_id, PASSTHRU_FILTER_MASK, ctypes.byref(mask_msg), ctypes.byref(pattern_msg), None, ctypes.byref(self.filter_id))
        if res != STATUS_NOERROR:
            raise RuntimeError(f"PassThruStartMsgFilter failed with error code: 0x{res:08X}")
        print(f"[J2534] Filter started, FilterID: {self.filter_id.value}")

        # Clear TX/RX buffers (Ioctl CLEAR_TX_BUFFER=7, CLEAR_RX_BUFFER=8)
        self.dll.PassThruIoctl(self.channel_id, 7, None, None)
        self.dll.PassThruIoctl(self.channel_id, 8, None, None)

    def disconnect(self):
        if self.channel_id.value != 0:
            if self.filter_id.value != 0:
                try:
                    self.dll.PassThruStopMsgFilter(self.channel_id, self.filter_id)
                except Exception:
                    pass
                self.filter_id.value = 0
            try:
                self.dll.PassThruDisconnect(self.channel_id)
            except Exception:
                pass
            self.channel_id.value = 0

    def can_send(self, can_id: int, data: bytes, bus: int = 0, timeout_ms: int = 50) -> int:
        """Sends a CAN frame. Returns J2534 status code (0 = success, 9 = timeout/no ACK, 7 = buffer full)."""
        msg = PASSTHRU_MSG()
        msg.ProtocolID = CAN
        msg.TxFlags = 0
        msg.DataSize = 4 + len(data)
        msg.Data[0] = (can_id >> 24) & 0xFF
        msg.Data[1] = (can_id >> 16) & 0xFF
        msg.Data[2] = (can_id >> 8) & 0xFF
        msg.Data[3] = can_id & 0xFF
        for i, b in enumerate(data):
            msg.Data[4 + i] = b

        num_msgs = wintypes.DWORD(1)
        res = self.dll.PassThruWriteMsgs(self.channel_id, ctypes.byref(msg), ctypes.byref(num_msgs), timeout_ms)
        if res in (ERR_BUFFER_FULL, ERR_BUFFER_OVERFLOW):
            # Clear TX buffer so subsequent sends don't lock up
            self.dll.PassThruIoctl(self.channel_id, 7, None, None)
        return res

    def write_frame(self, can_id: int, data: bytes, bus: int = 0, timeout_ms: int = 50) -> int:
        """Alias for can_send for CAN API compatibility."""
        return self.can_send(can_id, data, bus=bus, timeout_ms=timeout_ms)

    def can_recv_ts(self, timeout_ms: int = 10) -> List[Tuple[int, bytes, int, int]]:
        """
        Returns list of (can_id, payload_bytes, bus=0, timestamp_us).

        The timestamp is the J2534 driver's own hardware receive stamp in
        microseconds, not a host-side time.time(). That distinction matters for
        any rate measurement: host stamps are taken when Python happened to
        drain the queue, so a slow reader makes a 50 Hz stream look slower.
        Hardware stamps stay correct under arbitrary reader lag, and inter-frame
        deltas remain valid even when frames are dropped in between.

        The DWORD wraps roughly every 71.6 minutes; callers taking differences
        should mask to 32 bits.
        """
        msgs = (PASSTHRU_MSG * 32)()
        num_msgs = wintypes.DWORD(32)
        res = self.dll.PassThruReadMsgs(self.channel_id, msgs, ctypes.byref(num_msgs), timeout_ms)
        if res != STATUS_NOERROR and res != ERR_BUFFER_EMPTY:
            # Buffer empty is normal when polling
            pass

        results = []
        for i in range(num_msgs.value):
            m = msgs[i]
            if m.DataSize >= 4:
                can_id = (m.Data[0] << 24) | (m.Data[1] << 16) | (m.Data[2] << 8) | m.Data[3]
                data = bytes([m.Data[j] for j in range(4, m.DataSize)])
                results.append((can_id, data, 0, int(m.Timestamp)))
        return results

    def can_recv(self, timeout_ms: int = 10) -> List[Tuple[int, bytes, int]]:
        """Returns list of (can_id, payload_bytes, bus=0)"""
        return [(cid, data, bus)
                for cid, data, bus, _ts in self.can_recv_ts(timeout_ms)]

    # Panda-compatible interface methods
    def can_clear(self, flags: int = 0xFFFF):
        if self.channel_id.value != 0:
            self.dll.PassThruIoctl(self.channel_id, 7, None, None)
            self.dll.PassThruIoctl(self.channel_id, 8, None, None)

    def set_safety_mode(self, mode: int):
        pass
