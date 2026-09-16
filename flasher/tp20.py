import time
import struct
from typing import Optional, List, Tuple, Callable

BROADCAST_ADDR = 0x200

TIMING_UNITS_MS = (0.1, 1.0, 10.0, 100.0)


def decode_timing_ms(value: int) -> float:
    """Decode a TP2 timing byte: high 2 bits select units, low 6 bits scale."""
    return TIMING_UNITS_MS[value >> 6] * (value & 0x3F)

class MessageTimeoutError(TimeoutError):
    pass

class TP20Transport:
    def __init__(self, device, module: int = 0x0A, bus: int = 0, timeout: float = 2.0, debug: bool = False, log_fn=None, intercept: bool = False):
        self.device = device
        self.module = module
        self.bus = bus
        self.timeout = timeout
        self.keepalive_after_response = False
        self.keepalive_interval = 1.0
        self.last_keepalive = time.monotonic()
        self.msgs: List[Tuple[int, bytes]] = []

        self.tx_seq = 0
        self.rx_seq = 0
        self.block_size = 0
        self.last_acked_rx_frame: Optional[bytes] = None
        self.time_between_packets = 0.005

        self.rx_addr = 0
        self.tx_addr = 0
        self.debug = debug
        self.log_fn = log_fn or print

        try:
            if intercept:
                self.intercept_channel(module)
            else:
                self.open_channel(module)
        except Exception:
            if self.tx_addr:
                self.disconnect()
            raise

    def log(self, msg: str):
        if self.debug:
            self.log_fn(msg)

    def can_recv(self, addr: Optional[int] = None) -> bytes:
        if addr is None:
            addr = self.rx_addr

        start_time = time.monotonic()
        while time.monotonic() - start_time < self.timeout:
            for idx, (a, dat) in enumerate(self.msgs):
                if a == addr:
                    return self.msgs.pop(idx)[1]

            raw_msgs = self.device.can_recv(10)
            for a, dat, bus in raw_msgs:
                if bus != self.bus:
                    continue
                # Only queue TP2.0 relevant messages, ignore broadcast bus chatter (e.g. 0x2C0)
                if a == addr or a in (BROADCAST_ADDR, BROADCAST_ADDR + self.module, self.rx_addr, self.tx_addr):
                    self.log(f"  [TP20 CAN RX] 0x{a:03X} -> {dat.hex()}")
                    self.msgs.append((a, dat))

            for idx, (a, dat) in enumerate(self.msgs):
                if a == addr:
                    return self.msgs.pop(idx)[1]

        err_info = f"Timed out waiting for message on ID 0x{addr:X} (timeout={self.timeout}s)."
        if self.msgs:
            err_info += f" Currently queued: {[(hex(a), d.hex()) for a, d in self.msgs]}"
        self.log(f"  [TP20 TIMEOUT] {err_info}")
        raise MessageTimeoutError(err_info)

    def can_send(self, dat: bytes, addr: Optional[int] = None):
        if addr is None:
            addr = self.tx_addr

        self.log(f"  [TP20 CAN TX] 0x{addr:03X} <- {dat.hex()}")
        self.device.can_send(addr, dat, self.bus)
        time.sleep(self.time_between_packets)

    def open_channel(self, module: int):
        # Dest: <module> (0x0A for Haldex AWD)
        # Opcode 0xc0 (setup)
        # RX ID: V = 1 (invalid), 0x1000
        # TX ID: 0x300 + V = 0 (valid), 0x0300
        # Application type: 0x01 (KWP2000)
        setup_payload = bytes([module]) + b"\xc0\x00\x10\x00\x03\x01"
        self.log(f"[TP20] Establishing channel to module 0x{module:02X} via broadcast 0x{BROADCAST_ADDR:03X}...")
        self.can_send(setup_payload, BROADCAST_ADDR)

        # Channel setup response (Controller responds on 0x200 + logical ID, e.g. 0x20A)
        start_time = time.monotonic()
        dat = None
        while time.monotonic() - start_time < self.timeout:
            msgs = self.device.can_recv(20)
            for a, payload, bus in msgs:
                if a == BROADCAST_ADDR + module and bus == self.bus and len(payload) == 7 and payload[1] == 0xD0:
                    dat = payload
                    self.log(f"[TP20] Received setup response from 0x{a:03X}: {dat.hex()}")
                    break
            if dat is not None:
                break

        if dat is None:
            raise MessageTimeoutError(f"Timed out waiting for channel setup response from module 0x{module:02X}")

        status, rx, tx, _ = struct.unpack("<xBHHB", dat)
        if status != 0xD0:
            raise RuntimeError(f"Failed to setup channel, got status 0x{status:02X}: {dat.hex()}")

        self.rx_addr = rx
        self.tx_addr = tx
        if not (0 < rx <= 0x7FF and 0 < tx <= 0x7FF and rx != tx):
            raise ValueError('Invalid TP2 channel addresses')
        self.log(f"[TP20] Channel open! Controller listens on 0x{tx:03X}, transmits on 0x{rx:03X}")

        # Set timing parameters
        # Opcode: 0xa0 (Parameters request)
        # Block size: 0x0f
        # T1: 0x8a (100ms timeout)
        # T2: 0xff
        # T3: 0x32 (same request as the main TP2 service)
        # T4: 0xff
        self.can_send(b"\xa0\x0f\x8a\xff\x32\xff")

        dat = self.can_recv()
        self.log(f"[TP20] Timing params response: {dat.hex()}")
        if len(dat) != 6 or dat[0] != 0xA1:
            raise ValueError(f'Invalid TP2 timing response: {dat.hex()}')

        self.block_size = dat[1]
        self.time_between_packets = max(1.0, decode_timing_ms(dat[4])) / 1000.0
        self.log(f"[TP20] Negotiated frame gap: {self.time_between_packets * 1000:.1f} ms")
        self.tx_seq = 0
        self.rx_seq = 0
        self.last_acked_rx_frame = None

    def intercept_channel(self, module: int, timeout: float = 30.0):
        setup_payload = bytes([module]) + b"\xc0\x00\x10\x00\x03\x01"
        self.log(f"[TP20] Intercept active: rapidly broadcasting 0x{BROADCAST_ADDR:03X} every 10ms for module 0x{module:02X}...")
        start_time = time.monotonic()
        dat = None
        while time.monotonic() - start_time < timeout:
            self.device.can_send(BROADCAST_ADDR, setup_payload, self.bus)
            t_chk = time.monotonic()
            while time.monotonic() - t_chk < 0.010:
                msgs = self.device.can_recv(10)
                for a, payload, bus in msgs:
                    if a == BROADCAST_ADDR + module and bus == self.bus and len(payload) == 7 and payload[1] == 0xD0:
                        dat = payload
                        self.log(f"[TP20] INTERCEPTED setup response from 0x{a:03X}: {dat.hex()}")
                        break
                if dat is not None:
                    break
                time.sleep(0.002)
            if dat is not None:
                break

        if dat is None:
            raise MessageTimeoutError(f"Timed out waiting for channel setup response from module 0x{module:02X} after {timeout}s")

        status, rx, tx, _ = struct.unpack("<xBHHB", dat)
        self.rx_addr = rx
        self.tx_addr = tx
        if not (0 < rx <= 0x7FF and 0 < tx <= 0x7FF and rx != tx):
            raise ValueError('Invalid TP2 channel addresses')
        self.log(f"[TP20] Intercept established! Controller listens on 0x{tx:03X}, transmits on 0x{rx:03X}")

        # Send timing parameters immediately (zero delay)
        self.can_send(b"\xa0\x0f\x8a\xff\x32\xff")
        dat = self.can_recv()
        self.log(f"[TP20] Timing params response: {dat.hex()}")
        if len(dat) != 6 or dat[0] != 0xA1:
            raise ValueError(f'Invalid TP2 timing response: {dat.hex()}')

        self.block_size = dat[1]
        self.time_between_packets = max(1.0, decode_timing_ms(dat[4])) / 1000.0
        self.tx_seq = 0
        self.rx_seq = 0
        self.last_acked_rx_frame = None

    def wait_for_ack(self):
        expected_seq = (self.tx_seq + 1) & 0xF
        expected_ack = 0xB0 | expected_seq
        start_time = time.monotonic()
        deadline = start_time + self.timeout
        hard_deadline = start_time + 30.0
        while time.monotonic() < deadline:
            try:
                dat = self.can_recv()
            except MessageTimeoutError:
                break

            if not dat:
                continue
            if (dat[0] & 0xF0) == 0x90:
                deadline = min(deadline + 1.0, hard_deadline)
                self.log(f'[TP20] Wait frame {dat.hex()}; extending response wait')
                continue

            if dat[0] == 0xA8:
                raise ConnectionError('Controller closed the TP2.0 channel (A8) while waiting for ACK')
            if dat[0] == 0xA3:
                self.log('  [TP20] Keepalive received while waiting for ACK; responding')
                self.can_send(b'\xa1')
                continue

            if dat[0] == expected_ack:
                return

            # If it's a data packet, queue it for later (implicit ACK)
            if (dat[0] >> 4) in (0, 1, 2, 3):
                self.msgs.append((self.rx_addr, dat))
                return

            if (dat[0] & 0xF0) == 0xB0:
                self.log(f"  [TP20] Discarding stale ACK 0x{dat.hex()}, expected 0x{expected_ack:02X}")
                continue

        raise RuntimeError(f"Did not receive expected ACK 0x{expected_ack:02X}")

    def send_ack(self):
        seq = (self.rx_seq + 1) & 0xF
        self.can_send(bytes([0xB0 | seq]))

    def send(self, dat: bytes):
        if len(dat) > 0xFF:
            raise ValueError("Packet longer than 255 bytes not supported")

        # Discard stale ACKs, but retain channel-control frames for processing.
        self.msgs = [(a, d) for a, d in self.msgs if d and (d[0] & 0xF0) != 0xB0]
        payload = struct.pack(">H", len(dat)) + dat
        frames_in_block = 0

        while payload:
            last = len(payload) <= 7
            frames_in_block += 1
            block_boundary = bool(self.block_size and frames_in_block >= self.block_size)
            ack_required = last or block_boundary

            # Type 0 is a non-final frame that requests an ACK. A negotiated
            # block size of 15 therefore requires an ACK on frames 15, 30, ...
            # Long TransferData requests cross these boundaries; read requests
            # generally do not.
            frame_type = 0x10 if last else (0x00 if ack_required else 0x20)
            to_send = bytes([frame_type | self.tx_seq])
            to_send += payload[:7]

            self.can_send(to_send)

            if ack_required:
                self.wait_for_ack()
                frames_in_block = 0

            self.tx_seq = (self.tx_seq + 1) & 0xF
            payload = payload[7:]

    def recv(self) -> bytes:
        payload = b""
        expected_len: Optional[int] = None
        expected_seq = self.rx_seq
        start_time = time.monotonic()
        deadline = start_time + self.timeout
        hard_deadline = start_time + 30.0

        while time.monotonic() < deadline:
            try:
                dat = self.can_recv()
            except MessageTimeoutError:
                break

            if not dat:
                continue
            if (dat[0] & 0xF0) == 0x90:
                deadline = min(deadline + 1.0, hard_deadline)
                self.log(f'[TP20] Wait frame {dat.hex()}; extending response wait')
                continue

            typ, seq = (dat[0] >> 4), (dat[0] & 0xF)

            # Handle keepalive / test frame (0xA3)
            if (dat[0] & 0xF0) == 0xA0:
                if dat[0] == 0xA8:
                    raise ConnectionError('Controller closed the TP2.0 channel (A8) during receive')
                if dat[0] == 0xA3:
                    self.log("  [TP20] Keepalive frame 0xA3 received, responding...")
                    self.can_send(b"\xa1")
                continue

            # Stray ACK packet (0xB0..0xBF)
            if typ == 0xB:
                self.log(f"  [TP20] Ignoring unexpected ACK packet 0x{dat.hex()}")
                continue

            # Data types 0/1 require an ACK; 1/3 terminate the message.
            if typ not in (0, 1, 2, 3):
                self.log(f"  [TP20] Ignoring unknown frame type 0x{dat[0]:02X}")
                continue

            if seq != expected_seq:
                # An ACK can be lost on CAN. TP2 then retransmits the exact
                # ACK-requiring frame with the preceding sequence number.
                # Re-ACK that frame without appending its payload twice.
                previous_seq = (expected_seq - 1) & 0xF
                if (typ in (0, 1) and seq == previous_seq
                        and dat == getattr(self, 'last_acked_rx_frame', None)):
                    self.log(
                        f"  [TP20] Re-ACKing retransmitted frame seq {seq}; "
                        f"still expecting seq {expected_seq}"
                    )
                    self.rx_seq = seq
                    self.send_ack()
                    self.rx_seq = expected_seq
                    continue
                raise ValueError(f'TP2 sequence mismatch: expected {expected_seq}, got {seq}')
            expected_seq = (seq + 1) & 0xF
            self.rx_seq = seq
            payload += dat[1:]

            if expected_len is None and len(payload) >= 2:
                expected_len = struct.unpack(">H", payload[:2])[0]
                if not 1 <= expected_len <= 0xFF:
                    raise ValueError('Unsupported TP2 payload length')

            if typ in (1, 3) and (expected_len is None or len(payload) != expected_len + 2):
                raise ValueError('TP2 final frame length mismatch')
            if typ in (0, 1):
                self.send_ack()
                self.last_acked_rx_frame = dat

            if typ in (1, 3):
                self.rx_seq = expected_seq
                break
            if expected_len is not None and len(payload) >= expected_len + 2:
                raise ValueError('TP2 payload completed without final frame')

        if expected_len is None or len(payload) < expected_len + 2:
            err_msg = (
                f"TP2.0 recv timed out. Expected length: {expected_len}, "
                f"Received payload: {payload.hex()} ({len(payload)} bytes)"
            )
            self.log(f"  [TP20 ERROR] {err_msg}")
            raise MessageTimeoutError(err_msg)

        data = payload[2 : expected_len + 2]
        if getattr(self, 'keepalive_after_response', False):
            self.maybe_send_keep_alive()
        return data

    def maybe_send_keep_alive(self, force: bool = False):
        if force or time.monotonic() - self.last_keepalive >= self.keepalive_interval:
            self.send_keep_alive()

    def send_keep_alive(self):
        """Send one channel heartbeat between complete KWP transactions."""
        self.can_send(b'\xa3')
        started = time.monotonic()
        deadline = started + self.timeout
        hard_deadline = started + 30.0
        deferred = []
        try:
            while time.monotonic() < deadline:
                dat = self.can_recv()
                if not dat:
                    continue
                if dat[0] in (0xA1, 0x93):
                    self.last_keepalive = time.monotonic()
                    return
                if dat[0] == 0xA3:
                    self.can_send(b'\xa1')
                elif dat[0] == 0xA8:
                    raise ConnectionError('Controller closed TP2 channel during keepalive')
                elif (dat[0] & 0xF0) == 0x90:
                    deadline = min(deadline + 1.0, hard_deadline)
                    self.log(f'[TP20] Wait frame {dat.hex()} during keepalive')
                elif (dat[0] >> 4) in (0, 1, 2, 3):
                    # Preserve an early next response (e.g. after KWP pending).
                    deferred.append((self.rx_addr, dat))
            raise MessageTimeoutError('TP2 keepalive response timed out')
        finally:
            self.msgs[0:0] = deferred

    def disconnect(self):
        # Disconnect channel: Opcode 0xa8
        try:
            self.log(f"[TP20] Disconnecting channel (opcode 0xa8)...")
            self.can_send(b"\xa8")
        except Exception:
            pass
