#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
socketcan_device.py
SocketCAN adapter implementing the device interface required by TP20Transport and HaldexFlasher.
Compatible with standard Linux SocketCAN (can0).
"""
import time
import logging
from typing import List, Tuple, Optional

try:
    import can
except ImportError:
    can = None

logger = logging.getLogger("SocketCANDevice")


class SocketCANDevice:
    """
    Duck-typed CAN device interface matching the methods expected by TP20Transport:
      - can_send(addr, dat, bus=0)
      - can_recv(timeout_ms=20) -> List[Tuple[addr, dat, bus]]
      - can_clear(mask=0xFFFF)
      - write_frame(addr, dat)
      - close()
    """
    def __init__(self, channel: str = "can0", bitrate: int = 500000, bus: Optional[object] = None):
        self.channel = channel
        self.bitrate = bitrate
        self.bus_num = 0
        if bus is not None:
            self.bus = bus
        else:
            if can is None:
                raise RuntimeError("python-can is not installed. Please install with 'pip install python-can'.")
            try:
                self.bus = can.Bus(interface="socketcan", channel=channel)
                logger.info(f"SocketCAN device opened on channel {channel}")
            except Exception as e:
                logger.error(f"Failed to open SocketCAN on {channel}: {e}")
                raise

    def can_send(self, addr: int, data: bytes, bus: int = 0):
        """Send a standard 11-bit CAN frame."""
        if not isinstance(addr, int) or not 0 <= addr <= 0x7FF or not 1 <= len(data) <= 8:
            raise ValueError("Expected a classic 11-bit CAN frame with 1..8 bytes")
        if bus != self.bus_num:
            raise ValueError("Unexpected CAN bus number")
        if not self.bus:
            raise RuntimeError("CAN bus not open")
        if can is not None:
            msg = can.Message(
                arbitration_id=addr,
                data=data,
                is_extended_id=False
            )
        else:
            # Lightweight duck-typed container if python-can not installed
            class _DuckCanMsg:
                def __init__(self, aid, d):
                    self.arbitration_id = aid
                    self.data = d
                    self.is_extended_id = False
            msg = _DuckCanMsg(addr, data)
        self.bus.send(msg)

    def write_frame(self, addr: int, data: bytes):
        """Helper alias matching J2534Device interface."""
        self.can_send(addr, data, self.bus_num)

    def can_recv(self, timeout_ms: int = 20) -> List[Tuple[int, bytes, int]]:
        """
        Receive pending CAN messages within timeout_ms.
        Returns list of (arbitration_id, data_bytes, bus_number).
        """
        if not self.bus:
            return []

        results: List[Tuple[int, bytes, int]] = []
        timeout_sec = max(0.001, timeout_ms / 1000.0)
        start = time.monotonic()

        # Get at least one message if available within timeout
        msg = self.bus.recv(timeout=timeout_sec)
        if msg is not None:
            if self._valid_message(msg):
                results.append((msg.arbitration_id, bytes(msg.data), self.bus_num))

            # Drain any additional queued messages without waiting
            while time.monotonic() - start < timeout_sec:
                extra = self.bus.recv(timeout=0.0)
                if extra is not None:
                    if self._valid_message(extra):
                        results.append((extra.arbitration_id, bytes(extra.data), self.bus_num))
                else:
                    break

        return results

    @staticmethod
    def _valid_message(msg):
        return (not any(getattr(msg, flag, False) for flag in
                        ('is_extended_id', 'is_error_frame', 'is_remote_frame', 'is_fd'))
                and 0 <= msg.arbitration_id <= 0x7FF and 1 <= len(msg.data) <= 8)

    def can_clear(self, mask: int = 0xFFFF):
        """Drain any unread messages from socket buffer."""
        if not self.bus:
            return
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            msg = self.bus.recv(timeout=0.0)
            if msg is None:
                return
        raise RuntimeError("CAN receive queue did not drain within 100ms")

    def close(self):
        """Shut down the CAN bus interface."""
        if self.bus:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            self.bus = None
