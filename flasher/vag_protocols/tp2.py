"""Canonical TP2.0 transport implementation.

The transport deliberately separates TP2 framing from channel establishment.
Dynamic diagnostic channels use :class:`TP2Transport` directly.  Fixed or
passively opened in-car channels can reuse ``segment_message``, ``build_ack``,
and ``classify_frame`` without pretending that they use the diagnostic C0/D0
channel handshake.
"""
from dataclasses import dataclass
import struct
import time
from typing import Callable, List, Optional, Sequence, Tuple


BROADCAST_ADDR = 0x200
TIMING_UNITS_MS = (0.1, 1.0, 10.0, 100.0)


class TP2Error(RuntimeError):
    """Base class for TP2 protocol failures."""


class MessageTimeoutError(TP2Error, TimeoutError):
    pass


def decode_timing_ms(value: int) -> float:
    """Decode a TP2 timing byte into milliseconds."""
    if not 0 <= value <= 0xFF:
        raise ValueError("TP2 timing value must fit in one byte")
    return TIMING_UNITS_MS[value >> 6] * (value & 0x3F)


def classify_frame(frame: Sequence[int]) -> Tuple[int, int]:
    """Return ``(opcode, sequence)`` for a TP2 data/ACK frame."""
    if not frame:
        raise ValueError("Empty TP2 frame")
    return frame[0] >> 4, frame[0] & 0x0F


def build_ack(received_sequence: int) -> bytes:
    """Build the ACK for a received TP2 sequence number."""
    if not 0 <= received_sequence <= 0x0F:
        raise ValueError("TP2 sequence must be 0..15")
    return bytes([0xB0 | ((received_sequence + 1) & 0x0F)])


def build_data_frame(payload: bytes, sequence: int, opcode: int) -> bytes:
    """Build one TP2 data frame for protocols that manage message boundaries."""
    payload = bytes(payload)
    if not 1 <= len(payload) <= 7:
        raise ValueError("A classic-CAN TP2 frame carries 1..7 payload bytes")
    if not 0 <= sequence <= 0x0F:
        raise ValueError("TP2 sequence must be 0..15")
    if opcode not in (0, 1, 2, 3):
        raise ValueError("TP2 data opcode must be 0, 1, 2, or 3")
    return bytes([(opcode << 4) | sequence]) + payload


def segment_message(payload: bytes, start_sequence: int = 0, *,
                    block_size: int = 0, length_prefixed: bool = True,
                    final_ack: bool = True) -> Tuple[List[bytes], int]:
    """Segment one logical message into classic-CAN TP2 frames.

    ``block_size`` is the number of frames allowed before an intermediate ACK.
    ``length_prefixed=False`` supports fixed-channel protocols such as DIS/DDP,
    whose message boundary is carried only by the final-frame opcode.
    """
    if not 0 <= start_sequence <= 0x0F:
        raise ValueError("TP2 sequence must be 0..15")
    if block_size < 0:
        raise ValueError("TP2 block size cannot be negative")
    if not payload:
        raise ValueError("TP2 messages cannot be empty")
    wire = (struct.pack(">H", len(payload)) + payload) if length_prefixed else payload

    frames: List[bytes] = []
    seq = start_sequence
    frames_in_block = 0
    while wire:
        last = len(wire) <= 7
        frames_in_block += 1
        block_boundary = bool(block_size and frames_in_block >= block_size and not last)
        if last:
            opcode = 0x10 if final_ack else 0x30
        elif block_boundary:
            opcode = 0x00
        else:
            opcode = 0x20
        frames.append(build_data_frame(wire[:7], seq, opcode >> 4))
        seq = (seq + 1) & 0x0F
        wire = wire[7:]
        if block_boundary:
            frames_in_block = 0
    return frames, seq


@dataclass(frozen=True)
class TP2Parameters:
    block_size: int
    t1_ms: float
    t3_ms: float

    @classmethod
    def decode(cls, response: bytes) -> "TP2Parameters":
        if len(response) != 6 or response[0] != 0xA1:
            raise ValueError(f"Invalid TP2 timing response: {response.hex()}")
        return cls(response[1], decode_timing_ms(response[2]),
                   max(1.0, decode_timing_ms(response[4])))


class TP2MessageReassembler:
    """Stateful, length-prefixed TP2 receive reassembler."""

    def __init__(self, start_sequence: int = 0,
                 last_acked_frame: Optional[bytes] = None):
        self.expected_sequence = start_sequence
        self.last_acked_frame = last_acked_frame
        self.wire = bytearray()
        self.expected_length: Optional[int] = None

    def clear_partial(self):
        self.wire.clear()
        self.expected_length = None

    def feed(self, frame: bytes) -> Tuple[Optional[bytes], Optional[bytes]]:
        """Consume a data frame and return ``(message, ack_to_send)``."""
        frame = bytes(frame)
        opcode, sequence = classify_frame(frame)
        if opcode not in (0, 1, 2, 3):
            raise ValueError(f"Not a TP2 data frame: {frame.hex()}")
        if sequence != self.expected_sequence:
            previous = (self.expected_sequence - 1) & 0x0F
            if (opcode in (0, 1) and sequence == previous
                    and frame == self.last_acked_frame):
                return None, build_ack(sequence)
            raise ValueError(
                f"TP2 sequence mismatch: expected {self.expected_sequence}, got {sequence}")
        self.expected_sequence = (sequence + 1) & 0x0F
        self.wire.extend(frame[1:])
        if self.expected_length is None and len(self.wire) >= 2:
            self.expected_length = struct.unpack(">H", self.wire[:2])[0]
            if not 1 <= self.expected_length <= 0xFFFF:
                raise ValueError("Unsupported TP2 payload length")
        final = opcode in (1, 3)
        ack = build_ack(sequence) if opcode in (0, 1) else None
        if ack is not None:
            self.last_acked_frame = frame
        if final:
            if self.expected_length is None or len(self.wire) != self.expected_length + 2:
                raise ValueError("TP2 final frame length mismatch")
            message = bytes(self.wire[2:self.expected_length + 2])
            self.clear_partial()
            return message, ack
        if self.expected_length is not None and len(self.wire) >= self.expected_length + 2:
            raise ValueError("TP2 payload completed without final frame")
        return None, ack


class TP2Transport:
    """TP2 transport over a duck-typed classic CAN device.

    The device must provide ``can_send(id, bytes, bus)`` and
    ``can_recv(timeout_ms) -> [(id, bytes, bus)]``.
    """

    def __init__(self, device, module: int = 0x0A, bus: int = 0,
                 timeout: float = 2.0, debug: bool = False, log_fn=None,
                 intercept: bool = False, tester_id: int = 0x300,
                 auto_open: bool = True):
        self.device = device
        self.module = module
        self.bus = bus
        self.timeout = timeout
        self.tester_id = tester_id
        self.keepalive_after_response = False
        self.keepalive_interval = 1.0
        self.last_keepalive = time.monotonic()
        self.last_request_at = 0.0
        self.msgs: List[Tuple[int, bytes]] = []
        self.tx_seq = 0
        self.rx_seq = 0
        self.block_size = 0
        self.t1_ms = timeout * 1000.0
        self.time_between_packets = 0.005
        self.last_acked_rx_frame: Optional[bytes] = None
        self.rx_addr = 0
        self.tx_addr = 0
        self.connected = False
        self.debug = debug
        self.log_fn = log_fn or print

        if auto_open:
            try:
                if intercept:
                    self.intercept_channel(module)
                else:
                    self.open_channel(module)
            except Exception:
                if self.tx_addr:
                    self.disconnect()
                raise

    @classmethod
    def fixed_channel(cls, device, *, tx_addr: int, rx_addr: int,
                      bus: int = 0, timeout: float = 2.0,
                      block_size: int = 0, t3_ms: float = 1.0,
                      debug: bool = False, log_fn=None):
        """Create an already-open transport for a predefined internal channel."""
        obj = cls(device, bus=bus, timeout=timeout, debug=debug,
                  log_fn=log_fn, auto_open=False)
        obj.tx_addr = tx_addr
        obj.rx_addr = rx_addr
        obj.block_size = block_size
        obj.time_between_packets = max(1.0, t3_ms) / 1000.0
        obj.connected = True
        return obj

    def log(self, message: str):
        if self.debug:
            self.log_fn(message)

    def can_recv(self, addr: Optional[int] = None) -> bytes:
        addr = self.rx_addr if addr is None else addr
        started = time.monotonic()
        while time.monotonic() - started < self.timeout:
            for index, (queued_addr, data) in enumerate(self.msgs):
                if queued_addr == addr:
                    return self.msgs.pop(index)[1]
            for received_addr, data, bus in self.device.can_recv(10):
                if bus != self.bus:
                    continue
                relevant = (addr, BROADCAST_ADDR, BROADCAST_ADDR + self.module,
                            self.rx_addr, self.tx_addr)
                if received_addr in relevant:
                    data = bytes(data)
                    self.log(f"  [TP2 CAN RX] 0x{received_addr:03X} -> {data.hex()}")
                    self.msgs.append((received_addr, data))
        detail = f"Timed out waiting for message on ID 0x{addr:X} (timeout={self.timeout}s)."
        if self.msgs:
            detail += f" Currently queued: {[(hex(a), d.hex()) for a, d in self.msgs]}"
        raise MessageTimeoutError(detail)

    def can_send(self, data: bytes, addr: Optional[int] = None):
        addr = self.tx_addr if addr is None else addr
        self.log(f"  [TP2 CAN TX] 0x{addr:03X} <- {bytes(data).hex()}")
        self.device.can_send(addr, bytes(data), self.bus)
        time.sleep(self.time_between_packets)

    def _apply_parameters(self, response: bytes):
        parameters = TP2Parameters.decode(response)
        self.block_size = parameters.block_size
        self.t1_ms = parameters.t1_ms
        self.time_between_packets = parameters.t3_ms / 1000.0
        self.log(f"[TP2] Timing: BS={self.block_size}, T1={self.t1_ms:.1f} ms, "
                 f"T3={parameters.t3_ms:.1f} ms")
        self.tx_seq = self.rx_seq = 0
        self.last_acked_rx_frame = None
        self.connected = True

    def _setup_payload(self, module: int) -> bytes:
        if not 0 <= self.tester_id <= 0x7FF:
            raise ValueError("Tester CAN ID must be an 11-bit identifier")
        return bytes([module, 0xC0, 0x00, 0x10,
                      self.tester_id & 0xFF, (self.tester_id >> 8) & 0xFF, 0x01])

    def open_channel(self, module: int):
        self.module = module
        self.can_send(self._setup_payload(module), BROADCAST_ADDR)
        deadline = time.monotonic() + self.timeout
        response = None
        while time.monotonic() < deadline:
            for address, data, bus in self.device.can_recv(20):
                if (address == BROADCAST_ADDR + module and bus == self.bus
                        and len(data) == 7 and data[1] == 0xD0):
                    response = bytes(data)
                    break
            if response is not None:
                break
        if response is None:
            raise MessageTimeoutError(
                f"Timed out waiting for channel setup response from module 0x{module:02X}")
        status, rx_addr, tx_addr, _ = struct.unpack("<xBHHB", response)
        if status != 0xD0:
            raise TP2Error(f"Channel setup failed: {response.hex()}")
        self.rx_addr, self.tx_addr = rx_addr, tx_addr
        if not (0 < rx_addr <= 0x7FF and 0 < tx_addr <= 0x7FF and rx_addr != tx_addr):
            raise ValueError("Invalid TP2 channel addresses")
        self.can_send(b"\xA0\x0F\x8A\xFF\x32\xFF")
        self._apply_parameters(self.can_recv())

    def intercept_channel(self, module: int, timeout: float = 30.0):
        self.module = module
        request = self._setup_payload(module)
        deadline = time.monotonic() + timeout
        response = None
        while time.monotonic() < deadline and response is None:
            self.device.can_send(BROADCAST_ADDR, request, self.bus)
            attempt_deadline = time.monotonic() + 0.010
            while time.monotonic() < attempt_deadline:
                for address, data, bus in self.device.can_recv(10):
                    if (address == BROADCAST_ADDR + module and bus == self.bus
                            and len(data) == 7 and data[1] == 0xD0):
                        response = bytes(data)
                        break
                if response is not None:
                    break
                time.sleep(0.002)
        if response is None:
            raise MessageTimeoutError(
                f"Timed out intercepting module 0x{module:02X} after {timeout}s")
        status, self.rx_addr, self.tx_addr, _ = struct.unpack("<xBHHB", response)
        if status != 0xD0 or not (0 < self.rx_addr <= 0x7FF
                                  and 0 < self.tx_addr <= 0x7FF
                                  and self.rx_addr != self.tx_addr):
            raise ValueError("Invalid TP2 channel response")
        self.can_send(b"\xA0\x0F\x8A\xFF\x32\xFF")
        self._apply_parameters(self.can_recv())

    def wait_for_ack(self, sent_sequence: int):
        expected = 0xB0 | ((sent_sequence + 1) & 0x0F)
        started = time.monotonic()
        deadline = started + self.timeout
        hard_deadline = started + 30.0
        while time.monotonic() < deadline:
            try:
                data = self.can_recv()
            except MessageTimeoutError:
                break
            if not data:
                continue
            if (data[0] & 0xF0) == 0x90:
                deadline = min(deadline + 1.0, hard_deadline)
            elif data[0] == 0xA8:
                self.connected = False
                raise ConnectionError("Controller closed TP2 channel while waiting for ACK")
            elif data[0] == 0xA3:
                self.can_send(b"\xA1")
            elif data[0] == expected:
                return
            elif data[0] >> 4 in (0, 1, 2, 3):
                self.msgs.append((self.rx_addr, data))
                return
        raise TP2Error(f"Did not receive expected ACK 0x{expected:02X}")

    def send(self, payload: bytes):
        payload = bytes(payload)
        if len(payload) > 0xFFFF:
            raise ValueError("TP2 payload exceeds 65535 bytes")
        self.last_request_at = time.monotonic()
        self.msgs = [(a, d) for a, d in self.msgs
                     if d and (d[0] & 0xF0) != 0xB0]
        frames, next_sequence = segment_message(
            payload, self.tx_seq, block_size=self.block_size, length_prefixed=True)
        for frame in frames:
            self.can_send(frame)
            if frame[0] >> 4 in (0, 1):
                self.wait_for_ack(frame[0] & 0x0F)
        self.tx_seq = next_sequence

    def send_ack(self, received_sequence: Optional[int] = None):
        # ``rx_seq`` always points at the *next* expected frame.
        sequence = ((self.rx_seq - 1) & 0x0F
                    if received_sequence is None else received_sequence)
        self.can_send(build_ack(sequence))

    def recv(self) -> bytes:
        reassembler = TP2MessageReassembler(self.rx_seq, self.last_acked_rx_frame)
        started = time.monotonic()
        deadline = started + self.timeout
        hard_deadline = started + 30.0
        while time.monotonic() < deadline:
            try:
                data = self.can_recv()
            except MessageTimeoutError:
                break
            if not data:
                continue
            if (data[0] & 0xF0) == 0x90:
                deadline = min(deadline + 1.0, hard_deadline)
                continue
            opcode, sequence = classify_frame(data)
            if opcode == 0xA:
                if data[0] == 0xA8:
                    self.connected = False
                    raise ConnectionError("Controller closed the TP2.0 channel")
                if data[0] == 0xA3:
                    self.can_send(b"\xA1")
                continue
            if opcode == 0xB:
                continue
            if opcode not in (0, 1, 2, 3):
                continue
            result, ack = reassembler.feed(data)
            self.rx_seq = reassembler.expected_sequence
            self.last_acked_rx_frame = reassembler.last_acked_frame
            if ack is not None:
                self.can_send(ack)
            if result is not None:
                if getattr(self, "keepalive_after_response", False):
                    self.maybe_send_keep_alive()
                return result
        raise MessageTimeoutError(
            f"TP2 receive timed out; expected {reassembler.expected_length}, "
            f"got {len(reassembler.wire)} wire bytes")

    def maybe_send_keep_alive(self, force: bool = False):
        if force or time.monotonic() - self.last_keepalive >= self.keepalive_interval:
            return self.send_keep_alive()
        return True

    def send_keep_alive(self):
        self.can_send(b"\xA3")
        started = time.monotonic()
        deadline = started + self.timeout
        hard_deadline = started + 30.0
        deferred: List[Tuple[int, bytes]] = []
        try:
            while time.monotonic() < deadline:
                data = self.can_recv()
                if not data:
                    continue
                if data[0] in (0xA1, 0x93):
                    self.last_keepalive = time.monotonic()
                    return True
                if data[0] == 0xA3:
                    self.can_send(b"\xA1")
                elif data[0] == 0xA8:
                    self.connected = False
                    raise ConnectionError("Controller closed TP2 channel during keepalive")
                elif (data[0] & 0xF0) == 0x90:
                    deadline = min(deadline + 1.0, hard_deadline)
                elif data[0] >> 4 in (0, 1, 2, 3):
                    deferred.append((self.rx_addr, data))
            raise MessageTimeoutError("TP2 keepalive response timed out")
        finally:
            self.msgs[0:0] = deferred

    def disconnect(self):
        try:
            if self.tx_addr:
                self.can_send(b"\xA8")
        finally:
            self.connected = False


# Historical spelling retained for callers and third-party scripts.
TP20Transport = TP2Transport
