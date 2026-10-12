"""TP2.0 transport against a scripted ECU that implements the VW TP2.0 spec.

Ground truth: references/tp2diag references/VW-TP-2.0.txt (jazdw.net/tp20).
The fake ECU checks every frame the tester sends (sequence numbers, ACK
values, channel IDs) independently of the code under test, so a regression in
framing shows up as an ECU-side protocol error, not just a changed byte.

Runs the real worker facade (tp2/tp2_protocol.py) over a fake python-can bus
with a fake clock: no hardware, no sleeping.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import can

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flasher.vag_protocols import tp2 as tp2_transport  # noqa: E402
from tp2 import tp2_protocol  # noqa: E402

TESTER_RX = 0x300   # ID the tester asks the ECU to transmit on
ECU_RX = 0x740      # ID the ECU tells the tester to transmit on
# Spec example parameter response: BS=15, T1=0x8A (100 ms), T3=0x4A (10 ms).
SPEC_PARAMS = bytes.fromhex('A10F8AFF4AFF')


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)


class FakeBus:
    """python-can Bus stand-in: timed delivery queue driven by the fake clock."""

    def __init__(self, clock):
        self.clock = clock
        self.sent = []
        self.pending = []
        self.ecu = None

    def deliver(self, can_id, data, delay=0.001, **flags):
        self.pending.append((self.clock.now + delay, can_id, bytes(data), flags))
        self.pending.sort(key=lambda item: item[0])

    def send(self, message, timeout=None):
        frame = (message.arbitration_id, bytes(message.data))
        self.sent.append(frame)
        if self.ecu:
            self.ecu.on_frame(*frame)

    def recv(self, timeout=None):
        if not self.pending or self.pending[0][0] > self.clock.now:
            if not timeout:
                return None
            target = self.clock.now + timeout
            if self.pending:
                target = min(target, self.pending[0][0])
            self.clock.now = target
            if not self.pending or self.pending[0][0] > self.clock.now:
                return None
        _, can_id, data, flags = self.pending.pop(0)
        return can.Message(arbitration_id=can_id, data=data,
                           is_extended_id=flags.get('is_extended_id', False))

    def shutdown(self):
        pass


def frames_for(payload, *, block_size=0):
    """Independent spec segmentation: 2-byte length prefix, 7 bytes per frame."""
    wire = len(payload).to_bytes(2, 'big') + bytes(payload)
    chunks = [wire[i:i + 7] for i in range(0, len(wire), 7)]
    result = []
    for index, chunk in enumerate(chunks):
        last = index == len(chunks) - 1
        if last:
            opcode = 0x1
        elif block_size and (index + 1) % block_size == 0:
            opcode = 0x0
        else:
            opcode = 0x2
        result.append((opcode, chunk))
    return result


class SpecECU:
    """Scripted TP2.0 ECU. Records protocol violations by the tester."""

    def __init__(self, bus, module=0x01, params=SPEC_PARAMS):
        self.bus = bus
        bus.ecu = self
        self.module = module
        self.params = params
        self.errors = []
        self.requests = []
        self.responses = []      # list of lists of (opcode, payload) frames
        self.tx_seq = 0          # ECU -> tester
        self.rx_seq = 0          # tester -> ECU
        self.inbox = bytearray()
        self.expected_acks = []  # ACKs the tester owes us, in order
        self.ack_requests = True
        self.answer_params = True
        self.received_acks = []
        self.disconnected = False

    def queue_response(self, payload=None, frames=None, **kwargs):
        self.responses.append(frames if frames is not None else frames_for(payload, **kwargs))

    def send_frames(self, frames, start_delay=0.002):
        delay = start_delay
        for opcode, chunk in frames:
            byte0 = (opcode << 4) | self.tx_seq
            if opcode in (0x0, 0x1):
                self.expected_acks.append(0xB0 | ((self.tx_seq + 1) & 0x0F))
            self.tx_seq = (self.tx_seq + 1) & 0x0F
            self.bus.deliver(TESTER_RX, bytes([byte0]) + bytes(chunk), delay=delay)
            delay += 0.001

    def on_frame(self, can_id, data):
        if can_id == 0x200:
            # Spec: Dest, 0xC0, RX ID (invalid), TX ID 0x300 (valid), app 0x01.
            if data != bytes([self.module, 0xC0, 0x00, 0x10,
                              TESTER_RX & 0xFF, TESTER_RX >> 8, 0x01]):
                self.errors.append(f'bad channel setup {data.hex()}')
                return
            self.bus.deliver(0x200 + self.module, bytes(
                [0x00, 0xD0, TESTER_RX & 0xFF, TESTER_RX >> 8,
                 ECU_RX & 0xFF, ECU_RX >> 8, 0x01]))
            return
        if can_id != ECU_RX:
            self.errors.append(f'frame on unexpected ID 0x{can_id:03X}: {data.hex()}')
            return
        op = data[0]
        if op == 0xA0:
            if len(data) != 6:
                self.errors.append(f'parameter request must be 6 bytes: {data.hex()}')
            self.tx_seq = self.rx_seq = 0
            if self.answer_params:
                self.bus.deliver(TESTER_RX, self.params)
        elif op == 0xA3:
            self.bus.deliver(TESTER_RX, self.params)
        elif op == 0xA8:
            self.disconnected = True
        elif op >> 4 in (0x9, 0xB):
            self.received_acks.append(op)
            expected = self.expected_acks.pop(0) if self.expected_acks else None
            if op != expected:
                self.errors.append(f'unexpected ACK {op:02X}, expected {expected}')
        elif op >> 4 in (0x0, 0x1, 0x2, 0x3):
            seq = op & 0x0F
            if seq != self.rx_seq:
                self.errors.append(f'tester sequence {seq}, expected {self.rx_seq}')
            self.rx_seq = (seq + 1) & 0x0F
            self.inbox.extend(data[1:])
            if op >> 4 in (0x0, 0x1) and self.ack_requests:
                self.bus.deliver(TESTER_RX, bytes([0xB0 | self.rx_seq]))
            if op >> 4 in (0x1, 0x3):
                length = int.from_bytes(self.inbox[:2], 'big')
                if len(self.inbox) - 2 != length:
                    self.errors.append(f'length {length} but {len(self.inbox) - 2} bytes')
                self.requests.append(bytes(self.inbox[2:2 + length]))
                self.inbox.clear()
                if self.responses:
                    self.send_frames(self.responses.pop(0))
        else:
            self.errors.append(f'unknown opcode {data.hex()}')


class TP2Harness(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        # transmission_guard reads ~/.hudiy; keep it in a private, empty HOME.
        env = patch.dict(os.environ, {'HOME': home.name})
        env.start()
        self.addCleanup(env.stop)
        self.clock = FakeClock()
        for module in (tp2_transport, tp2_protocol):
            patcher = patch.object(module, 'time', self.clock)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.bus = FakeBus(self.clock)
        self.ecu = SpecECU(self.bus)
        self.tester = tp2_protocol.TP2Protocol(channel='vcan0')
        self.tester.bus = self.bus

    def connect(self):
        self.assertTrue(self.tester.connect(0x01))
        self.bus.sent.clear()


class SpecExampleTests(TP2Harness):
    def test_reproduces_spec_example_session_byte_for_byte(self):
        """The whole example table from VW-TP-2.0.txt, both directions."""
        self.ecu.queue_response(frames=[(0x1, bytes.fromhex('00025089'))])
        self.ecu.queue_response(frames=[
            (0x2, bytes.fromhex('001A6101010000')),
            (0x2, bytes.fromhex('2700002200801A')),
            (0x2, bytes.fromhex('324B25027A2500')),
            (0x1, bytes.fromhex('00250000250000')),
        ])

        self.assertTrue(self.tester.connect(0x01))
        self.assertEqual(self.tester.send_kwp_request([0x10, 0x89]), [0x50, 0x89])
        response = self.tester.send_kwp_request([0x21, 0x01])
        self.tester.disconnect()

        self.assertEqual(self.bus.sent, [
            (0x200, bytes.fromhex('01C00010000301')),
            (0x740, bytes.fromhex('A00F8AFF32FF')),
            (0x740, bytes.fromhex('1000021089')),
            (0x740, bytes.fromhex('B1')),
            (0x740, bytes.fromhex('1100022101')),
            (0x740, bytes.fromhex('B5')),
            (0x740, bytes.fromhex('A8')),
        ])
        self.assertEqual(bytes(response), bytes.fromhex(
            '6101010000' '2700002200801A' '324B25027A2500' '00250000250000'))
        self.assertEqual(len(response), 0x1A)
        self.assertEqual(self.ecu.errors, [])
        self.assertTrue(self.ecu.disconnected)
        self.assertFalse(self.tester.connected)

    def test_negotiated_ids_and_timing_are_decoded_from_spec_bytes(self):
        self.assertTrue(self.tester.connect(0x01))
        # Response 00 D0 00 03 40 07 01: tester listens on 0x300, sends on 0x740.
        self.assertEqual((self.tester.rx_id, self.tester.tx_id), (0x300, 0x740))
        self.assertEqual(self.tester.block_size, 0x0F)
        self.assertEqual(self.tester.t1, 100.0)   # 0x8A: 10 ms units x 10
        self.assertEqual(self.tester.t3, 10.0)    # 0x4A: 1 ms units x 10
        self.assertTrue(self.tester.connected)

    def test_timing_byte_units_follow_spec_table(self):
        for value, expected in ((0x0A, 1.0), (0x4A, 10.0), (0x8A, 100.0),
                                (0xCA, 1000.0), (0x3F, 6.3)):
            with self.subTest(value=hex(value)):
                self.assertAlmostEqual(tp2_transport.decode_timing_ms(value), expected)


class SequenceAndAckTests(TP2Harness):
    def test_sequence_numbers_wrap_after_0xF_in_both_directions(self):
        self.connect()
        for index in range(18):
            self.ecu.queue_response(bytes([0x61, index]))
            self.assertEqual(self.tester.send_kwp_request([0x21, index]), [0x61, index])
        data_frames = [d for i, d in self.bus.sent if d[0] >> 4 == 0x1]
        self.assertEqual([d[0] & 0x0F for d in data_frames], [i & 0x0F for i in range(18)])
        tester_acks = [d[0] for i, d in self.bus.sent if d[0] >> 4 == 0xB]
        self.assertEqual(tester_acks, [0xB0 | ((i + 1) & 0x0F) for i in range(18)])
        self.assertEqual(self.ecu.errors, [])

    def test_block_size_requests_intermediate_ack_and_waits_for_it(self):
        self.ecu.params = bytes.fromhex('A1028AFF4AFF')   # BS = 2
        self.connect()
        self.ecu.queue_response(b'\x76\x01')
        payload = bytes([0x36]) + bytes(range(29))       # 30 bytes -> 5 frames
        self.tester.send_kwp_request(payload)
        sent_ops = [d[0] >> 4 for i, d in self.bus.sent if d[0] >> 4 in (0, 1, 2, 3)]
        # Spec: opcode 0 = "waiting for ACK, more to follow" at each block end.
        self.assertEqual(sent_ops, [2, 0, 2, 0, 1])
        self.assertEqual(self.ecu.requests, [payload])
        self.assertEqual(self.ecu.errors, [])

    def test_missing_block_ack_stops_transmission(self):
        """An ECU that never ACKs a block must not be flooded with more frames."""
        self.ecu.params = bytes.fromhex('A1028AFF4AFF')
        self.connect()
        self.ecu.ack_requests = False
        with self.assertRaises(tp2_protocol.TP2Error):
            self.tester.send_kwp_request(bytes(30))
        data = [d for i, d in self.bus.sent if d[0] >> 4 in (0, 1, 2, 3)]
        self.assertEqual(len(data), 2, 'tester kept sending past the block boundary')

    def test_not_ready_ack_extends_wait_beyond_timeout(self):
        """0x9X = ACK, not ready. The tester must keep waiting for the 0xBX."""
        self.connect()
        self.ecu.ack_requests = False
        original = self.ecu.on_frame

        def slow_ack(can_id, data):
            original(can_id, data)
            if data[0] >> 4 == 0x1:
                self.bus.deliver(TESTER_RX, b'\x91', delay=1.5)
                self.bus.deliver(TESTER_RX, b'\xB1', delay=2.5)   # after 2 s timeout
                self.ecu.send_frames(frames_for(b'\x50\x89'), start_delay=2.6)
        self.ecu.on_frame = slow_ack
        self.assertEqual(self.tester.send_kwp_request([0x10, 0x89]), [0x50, 0x89])

    # BUG flasher/vag_protocols/tp2.py:346: wait_for_ack() treats a data frame
    # as an implied ACK and re-queues it with msgs.append(), i.e. BEHIND frames
    # already buffered after it. recv() then reassembles out of order.
    @unittest.expectedFailure
    def test_retransmitted_final_frame_is_reacked_not_duplicated(self):
        """If our ACK is lost the ECU repeats its last frame; it is not new data."""
        self.connect()
        self.ecu.queue_response(b'\x5A\x9B')
        self.assertEqual(self.tester.send_kwp_request([0x1A, 0x9B]), [0x5A, 0x9B])
        self.bus.deliver(TESTER_RX, bytes.fromhex('1000025A9B'))   # repeat, seq 0
        self.ecu.queue_response(b'\x61\x01')
        self.assertEqual(self.tester.send_kwp_request([0x21, 0x01]), [0x61, 0x01])
        # B1 for the original, B1 again for the repeat, then B2 for the new reply.
        acks = [d for _, d in self.bus.sent if d[0] >> 4 == 0xB]
        self.assertEqual(acks, [b'\xB1', b'\xB1', b'\xB2'])
        # Currently the stale repeat stays queued and kills the NEXT request
        # with "sequence mismatch: expected 2, got 0".
        self.ecu.queue_response(b'\x61\x02')
        self.assertEqual(self.tester.send_kwp_request([0x21, 0x02]), [0x61, 0x02])

    @unittest.expectedFailure
    def test_multiframe_reply_without_explicit_ack_keeps_frame_order(self):
        """Code accepts a data frame as an implied ACK; the reply must stay in order.

        Fails today: the first reply frame is moved behind the rest, giving
        'sequence mismatch: expected 0, got 1' and a failed measuring-block read.
        """
        self.connect()
        self.ecu.ack_requests = False
        self.ecu.queue_response(bytes([0x61, 0x01]) + bytes(range(20)))
        self.assertEqual(self.tester.send_kwp_request([0x21, 0x01]),
                         [0x61, 0x01] + list(range(20)))

    def test_response_pending_then_answer_keeps_sequence(self):
        self.connect()
        self.ecu.queue_response(b'\x7F\x21\x78')
        original = self.ecu.send_frames

        def pending_then_answer(frames, start_delay=0.002):
            original(frames, start_delay)
            if frames == frames_for(b'\x7F\x21\x78'):
                original(frames_for(b'\x61\x01\xAA'), start_delay=0.5)
        self.ecu.send_frames = pending_then_answer
        self.assertEqual(self.tester.send_kwp_request([0x21, 0x01]), [0x61, 0x01, 0xAA])
        self.assertEqual(self.ecu.errors, [])
        self.assertEqual(self.ecu.received_acks, [0xB1, 0xB2])

    def test_extended_id_frames_with_same_id_are_ignored(self):
        self.connect()
        self.ecu.queue_response(b'\x61\x01')
        self.bus.deliver(TESTER_RX, b'\x10\x00\x02\x7F\x21', delay=0.0005, is_extended_id=True)
        self.assertEqual(self.tester.send_kwp_request([0x21, 0x01]), [0x61, 0x01])


class ChannelLifecycleTests(TP2Harness):
    def test_keepalive_is_channel_test_answered_by_parameter_response(self):
        self.connect()
        self.assertTrue(self.tester.send_keep_alive())
        self.assertEqual(self.bus.sent, [(0x740, b'\xA3')])

    def test_data_arriving_during_keepalive_is_not_lost(self):
        self.connect()
        # ECU pushes a message that lands before its answer to the A3.
        self.ecu.send_frames(frames_for(b'\x61\x05'), start_delay=0.0005)
        self.assertTrue(self.tester.send_keep_alive())
        self.assertEqual(self.tester._transport.recv(), b'\x61\x05')

    def test_keepalive_without_answer_raises(self):
        self.connect()
        self.ecu.on_frame = lambda can_id, data: None
        with self.assertRaises(tp2_protocol.TP2Error):
            self.tester.send_keep_alive()

    def test_ecu_disconnect_while_waiting_for_response_drops_channel(self):
        self.connect()
        original = self.ecu.on_frame

        def close_after_ack(can_id, data):
            original(can_id, data)
            if data[0] >> 4 == 0x1:
                self.bus.deliver(TESTER_RX, b'\xA8', delay=0.01)
        self.ecu.on_frame = close_after_ack
        with self.assertRaises(tp2_protocol.TP2Error):
            self.tester.send_kwp_request([0x21, 0x01])
        self.assertFalse(self.tester.connected)

    @unittest.expectedFailure
    def test_ecu_disconnect_is_answered_with_disconnect(self):
        """Spec: 0xA8 'Receiver should reply with a disconnect'. Code does not."""
        self.connect()
        original = self.ecu.on_frame

        def close_after_ack(can_id, data):
            original(can_id, data)
            if data[0] >> 4 == 0x1:
                self.bus.deliver(TESTER_RX, b'\xA8', delay=0.01)
        self.ecu.on_frame = close_after_ack
        with self.assertRaises(tp2_protocol.TP2Error):
            self.tester.send_kwp_request([0x21, 0x01])
        self.assertEqual(self.bus.sent[-1], (0x740, b'\xA8'))

    @unittest.expectedFailure
    def test_channel_test_from_ecu_is_answered_with_full_parameter_response(self):
        """Spec: A3 'response is same as parameters response' (6 bytes, A1 BS T1 FF T3 FF).

        flasher/vag_protocols/tp2.py answers with a bare 1-byte A1.
        """
        self.connect()
        self.bus.deliver(TESTER_RX, b'\xA3', delay=0.0005)
        self.ecu.queue_response(b'\x61\x01')
        self.tester.send_kwp_request([0x21, 0x01])
        replies = [d for i, d in self.bus.sent if d[:1] == b'\xA1']
        self.assertEqual(len(replies), 1)
        self.assertEqual(len(replies[0]), 6)

    def test_missing_parameter_response_fails_connect_and_closes_channel(self):
        self.ecu.answer_params = False
        started = self.clock.now
        self.assertFalse(self.tester.connect(0x01))
        self.assertFalse(self.tester.connected)
        # The half-open channel is torn down so the ECU does not keep it.
        self.assertEqual(self.bus.sent[-1], (0x740, b'\xA8'))
        self.assertGreaterEqual(self.clock.now - started, 2.0)

    def test_negative_channel_setup_response_does_not_open_channel(self):
        self.ecu.on_frame = lambda can_id, data: self.bus.deliver(
            0x201, bytes.fromhex('00D60003400701'))
        self.assertFalse(self.tester.connect(0x01))
        self.assertEqual([i for i, d in self.bus.sent], [0x200])

    def test_request_without_channel_is_refused_without_bus_traffic(self):
        with self.assertRaises(tp2_protocol.TP2Error):
            self.tester.send_kwp_request([0x21, 0x01])
        self.assertEqual(self.bus.sent, [])


class ReassemblyBoundaryTests(unittest.TestCase):
    def test_spec_length_prefix_and_opcode_table(self):
        frames, next_seq = tp2_transport.segment_message(b'\x10\x89', 0)
        self.assertEqual(frames, [bytes.fromhex('1000021089')])
        self.assertEqual(next_seq, 1)
        frames, _ = tp2_transport.segment_message(bytes(13), 15)
        # 15 wire bytes -> 3 frames; seq wraps 15 -> 0 -> 1.
        self.assertEqual([f[0] for f in frames], [0x2F, 0x20, 0x11])

    def test_out_of_sequence_frame_is_rejected(self):
        reassembler = tp2_transport.TP2MessageReassembler(0)
        reassembler.feed(bytes.fromhex('20001A61010100'))
        with self.assertRaisesRegex(ValueError, 'sequence mismatch'):
            reassembler.feed(bytes.fromhex('222700002200801A'))


if __name__ == '__main__':
    unittest.main()
