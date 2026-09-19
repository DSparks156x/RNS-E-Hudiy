"""Offline regression tests; no hardware access."""
import struct
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch
from flasher.socketcan_device import SocketCANDevice
from flasher.vag_protocols.tp2 import TP20Transport, decode_timing_ms, MessageTimeoutError
from flasher.controllers.haldex_gen4.protocol import Kwp


def frame(addr, data, **flags):
    return SimpleNamespace(arbitration_id=addr, data=data, **flags)


class Endpoint:
    def __init__(self):
        self.queue = deque()
        self.sent = []
        self.request = b''
        self.rx_seq = 0
        self.shutdown_count = 0
        self.reply = b'\x5a\x9b' + bytes(range(30))

    def send(self, msg):
        data = bytes(msg.data)
        self.sent.append((msg.arbitration_id, data))
        if msg.arbitration_id == 0x200:
            # Unrelated ECU cannot satisfy the requested module's setup.
            self.queue.append(frame(0x203, b'\x00\xd0\x00\x03\x65\x07\x01'))
            self.queue.append(frame(0x20A, b'\x00\xd0\x00\x03\x65\x07\x01'))
        elif data[0] == 0xA0:
            self.queue.append(frame(0x300, b'\xa1\x0f\x8a\xff\x0a\xff'))
        elif data[0] >> 4 in (0, 1, 2):
            self.request += data[1:]
            if data[0] >> 4 in (0, 1):
                self.queue.append(frame(0x300, bytes([0xB0 | ((data[0] + 1) & 15)])))
            if data[0] >> 4 == 1:
                wire = struct.pack('>H', len(self.reply)) + self.reply
                while wire:
                    last = len(wire) <= 7
                    self.queue.append(frame(0x300, bytes([(0x10 if last else 0x20) | self.rx_seq]) + wire[:7]))
                    self.rx_seq = (self.rx_seq + 1) & 15
                    wire = wire[7:]

    def recv(self, timeout=0):
        return self.queue.popleft() if self.queue else None

    def shutdown(self):
        self.shutdown_count += 1


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch('flasher.vag_protocols.tp2.time.sleep')
        self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.endpoint = Endpoint()
        self.device = SocketCANDevice(bus=self.endpoint)
        self.addCleanup(self.device.close)

    def test_segmented_roundtrip_and_sequence_wrap(self):
        tp = TP20Transport(self.device, timeout=0.02)
        for _ in range(6):
            tp.send(b'\x36' + bytes(range(144)))
            self.assertEqual(tp.recv(), self.endpoint.reply)
        tp.disconnect()
        self.assertEqual(self.endpoint.sent[-1], (0x765, b'\xa8'))
        self.device.close()
        self.device.close()
        self.assertEqual(self.endpoint.shutdown_count, 1)

    def test_long_request_honors_negotiated_transmit_block_size(self):
        tp = TP20Transport(self.device, timeout=0.02)
        tp.send(b'\x36' + bytes(range(239)))
        request_frames = [data for address, data in self.endpoint.sent
                          if address == tp.tx_addr and data[0] >> 4 in (0, 1, 2)]
        self.assertGreater(len(request_frames), 30)
        self.assertEqual(request_frames[14][0] >> 4, 0)
        self.assertEqual(request_frames[29][0] >> 4, 0)
        self.assertEqual(request_frames[-1][0] >> 4, 1)
        self.assertEqual(self.endpoint.request[2:], b'\x36' + bytes(range(239)))

    def test_kwp_ident_through_adapter_and_transport(self):
        tp = TP20Transport(self.device, timeout=0.02)
        self.assertEqual(Kwp(tp, debug=False).read_ecu_ident(0x9b), self.endpoint.reply)
        self.endpoint.reply = b'\x00'
        with self.assertRaises(RuntimeError):
            Kwp(tp, debug=False).transfer(b'abcd')
        # Failed validation does not duplicate the destructive request.
        writes = [data for _, data in self.endpoint.sent if b'\x36abcd' in data]
        self.assertEqual(len(writes), 1)

    def test_out_of_sequence_and_truncated_final_rejected(self):
        for data in (b'\x11\x00\x01\x76', b'\x10\x00\x02\x76'):
            with self.subTest(data=data):
                tp = TP20Transport(self.device, timeout=0.02)
                self.endpoint.queue.append(frame(0x300, data))
                with self.assertRaises(ValueError):
                    tp.recv()

    def test_bad_timing_response_fails(self):
        original = self.endpoint.send
        def send(msg):
            original(msg)
            if bytes(msg.data)[0] == 0xA0:
                self.endpoint.queue.clear()
                self.endpoint.queue.append(frame(0x300, b'\xa3'))
        self.endpoint.send = send
        with self.assertRaises(ValueError):
            TP20Transport(self.device, timeout=0.02)

    def test_adapter_filters_non_classic_data(self):
        for flag in ('is_extended_id', 'is_error_frame', 'is_remote_frame', 'is_fd'):
            self.endpoint.queue.append(frame(0x300, b'\x76', **{flag: True}))
        self.endpoint.queue.append(frame(0x300, b''))
        self.endpoint.queue.append(frame(0x300, b'\x76'))
        self.assertEqual(self.device.can_recv(), [(0x300, b'\x76', 0)])

    def test_adapter_rejects_invalid_transmits(self):
        for addr, data in ((0x800, b'1'), (0x300, b''), (0x300, b'123456789')):
            with self.assertRaises(ValueError):
                self.device.can_send(addr, data)
        self.assertEqual(self.endpoint.sent, [])

    def test_tp2_encoded_timing_units(self):
        self.assertEqual(decode_timing_ms(0x0A), 1.0)
        self.assertEqual(decode_timing_ms(0x4A), 10.0)
        self.assertEqual(decode_timing_ms(0x8A), 100.0)


def transport_for(frames):
    t = TP20Transport.__new__(TP20Transport)
    t.timeout = 0.1
    t.debug = False
    t.rx_seq = 0
    t.last_acked_rx_frame = None
    t.sent = []
    pending = list(frames)
    def receive():
        if not pending:
            raise MessageTimeoutError('no more frames')
        return pending.pop(0)
    t.can_recv = receive
    t.can_send = t.sent.append
    return t


class UploadReceiveTests(unittest.TestCase):
    def test_200_byte_reply_requires_intermediate_ack_and_sequence_wrap(self):
        response = b'\x76'+bytes(range(200))
        wire = len(response).to_bytes(2, 'big')+response
        frames = []
        for i, start in enumerate(range(0, len(wire), 7)):
            last = start+7 >= len(wire)
            opcode = 1 if last else (0 if (i+1) % 15 == 0 else 2)
            frames.append(bytes([(opcode << 4) | (i & 15)])+wire[start:start+7])
        t = transport_for(frames)
        self.assertEqual(t.recv(), response)
        self.assertEqual(t.sent, [b'\xbf', b'\xbd'])

    def test_short_ack_final_reply(self):
        t = transport_for([bytes.fromhex('170003750020')])
        t.rx_seq = 7
        self.assertEqual(t.recv(), bytes.fromhex('750020'))
        self.assertEqual(t.sent, [b'\xb8'])

    def test_exact_final_retransmission_is_reacked_without_duplicate_payload(self):
        previous = bytes.fromhex('170003750020')
        current = bytes.fromhex('1800025089')
        t = transport_for([previous, current])
        t.rx_seq = 8
        t.last_acked_rx_frame = previous
        self.assertEqual(t.recv(), bytes.fromhex('5089'))
        self.assertEqual(t.sent, [b'\xb8', b'\xb9'])

    def test_final_without_ack(self):
        t = transport_for([bytes.fromhex('33000177')])
        t.rx_seq = 3
        self.assertEqual(t.recv(), b'\x77')
        self.assertEqual(t.sent, [])

    def test_missing_frame_rejected(self):
        t = transport_for([bytes.fromhex('200008760102030405'), bytes.fromhex('120607')])
        with self.assertRaisesRegex(ValueError, 'sequence mismatch'):
            t.recv()

    def test_premature_final_rejected(self):
        t = transport_for([bytes.fromhex('100010760102')])
        with self.assertRaises(ValueError):
            t.recv()

    def test_nonfinal_cannot_complete_message(self):
        t = transport_for([bytes.fromhex('20000177')])
        with self.assertRaisesRegex(ValueError, 'without final'):
            t.recv()

    def test_disconnect_is_reported_immediately(self):
        t = transport_for([b'\xa8'])
        with self.assertRaisesRegex(ConnectionError, 'closed the TP2.0 channel'):
            t.recv()


if __name__ == "__main__":
    unittest.main()
