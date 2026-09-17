#!/usr/bin/env python3
"""Compatibility façade for the shared TP2 and KWP libraries.

The worker API historically exposed ``TP2Protocol.send_kvp_request``.  Keeping
that API here avoids a flag-day migration while all framing and KWP response
handling live in :mod:`vag_protocols`.
"""
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import can
from flasher.traffic import transmission_guard
from vag_protocols.kwp import KWPClient
from vag_protocols.tp2 import TP2Transport


logger = logging.getLogger(__name__)


class TP2Error(RuntimeError):
    """Diagnostic-service compatibility error."""


class _WorkerCANDevice:
    """Adapt a worker-owned python-can socket to the shared transport API."""

    def __init__(self, owner):
        self.owner = owner

    def can_send(self, address, data, bus=0):
        if bus != 0:
            raise ValueError("Unexpected CAN bus number")
        self.owner._send(address, data, pace=False)

    def can_recv(self, timeout_ms=20):
        if self.owner.bus is None:
            return []
        first = self.owner.bus.recv(max(0.001, timeout_ms / 1000.0))
        if first is None:
            return []
        messages = [(first.arbitration_id, bytes(first.data), 0)]
        while True:
            extra = self.owner.bus.recv(0.0)
            if extra is None:
                break
            messages.append((extra.arbitration_id, bytes(extra.data), 0))
        return messages


class TP2Protocol:
    """Legacy diagnostic API backed by the canonical TP2/KWP implementation."""

    T1_TIMEOUT = 2000
    T3_INTERVAL = 12

    def __init__(self, channel='can0', tester_id=0x300):
        self.channel = channel
        self.tester_id = tester_id
        self.bus = None
        self.tx_id = 0
        self.rx_id = 0
        self.block_size = 0
        self.t1 = 100.0
        self.t3 = 10.0
        self.seq_tx = 0
        self.seq_rx = 0
        self.connected = False
        self.last_kwp_req = 0.0
        self._transport = None
        self._kwp = None

    def open(self):
        try:
            self.bus = can.Bus(interface='socketcan', channel=self.channel, bitrate=100000)
            logger.info("TP2: CAN bus %s opened.", self.channel)
        except Exception as exc:
            raise TP2Error(str(exc)) from exc

    def close(self):
        if self.connected:
            self.disconnect()
        if self.bus is not None:
            self.bus.shutdown()
            self.bus = None

    def _send(self, arbitration_id, data, pace=True):
        message = can.Message(arbitration_id=arbitration_id,
                              data=bytes(data), is_extended_id=False)
        try:
            with transmission_guard() as allowed:
                if not allowed:
                    self.connected = False
                    raise TP2Error("Flashing Mode inhibits diagnostic transmissions")
                self.bus.send(message, timeout=0.5)
            if pace:
                delay_ms = self.t3 if self.connected else self.T3_INTERVAL
                time.sleep(delay_ms / 1000.0)
        except TP2Error:
            raise
        except Exception as exc:
            raise TP2Error(str(exc)) from exc

    def _sync_state(self):
        if self._transport is None:
            return
        self.tx_id = self._transport.tx_addr
        self.rx_id = self._transport.rx_addr
        self.block_size = self._transport.block_size
        self.t1 = self._transport.t1_ms
        self.t3 = self._transport.time_between_packets * 1000.0
        self.seq_tx = self._transport.tx_seq
        self.seq_rx = self._transport.rx_seq
        self.connected = self._transport.connected

    def connect(self, target_module_id: int) -> bool:
        if self.bus is None:
            raise TP2Error("CAN bus is not open")
        try:
            self._transport = TP2Transport(
                _WorkerCANDevice(self), module=target_module_id,
                tester_id=self.tester_id, timeout=self.T1_TIMEOUT / 1000.0,
                debug=False)
            self._kwp = KWPClient(self._transport, debug=False)
            self._sync_state()
            return True
        except Exception as exc:
            self.connected = False
            logger.error("TP2: connection failed: %s", exc)
            return False

    def disconnect(self):
        try:
            if self._transport is not None:
                self._transport.disconnect()
        except Exception as exc:
            logger.debug("TP2 disconnect failed: %s", exc)
        finally:
            self.connected = False

    def send_kvp_request(self, payload):
        """Send one KWP request; retained misspelling for API compatibility."""
        if not self.connected or self._kwp is None:
            raise TP2Error("Not connected")
        self.last_kwp_req = time.time()
        try:
            response = self._kwp.request(bytes(payload), raise_negative=False)
            self._sync_state()
            return list(response)
        except Exception as exc:
            self._sync_state()
            raise TP2Error(str(exc)) from exc

    # Correct spelling for new code.
    send_kwp_request = send_kvp_request

    def send_keep_alive(self):
        if self._transport is None:
            return False
        try:
            result = self._transport.send_keep_alive()
            self._sync_state()
            return bool(result)
        except Exception as exc:
            self._sync_state()
            raise TP2Error(str(exc)) from exc

    def maybe_send_keep_alive(self, force=False):
        if self._transport is None:
            return False
        try:
            result = self._transport.maybe_send_keep_alive(force=force)
            self._sync_state()
            return bool(result)
        except Exception as exc:
            self._sync_state()
            raise TP2Error(str(exc)) from exc
