"""Regression tests for the shared TP2/KWP core and DDP compatibility profile."""
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

# ddp_protocol imports its siblings as top-level modules, as it does on the Pi.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dis_client'))

try:
    import can  # noqa: F401
except ImportError:
    sys.modules['can'] = SimpleNamespace(
        CanError=RuntimeError,
        Message=lambda **kwargs: SimpleNamespace(**kwargs),
    )

from dis_client.ddp_protocol import DDPProtocol, DDPState, DisMode
from flasher.controllers.haldex_gen4.protocol import Kwp
from flasher.vag_protocols.kwp import KWPClient, KWPError, KWPNegativeResponse
from flasher.vag_protocols.tp2 import (
    TP2MessageReassembler, build_ack, decode_timing_ms, segment_message,
)


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.sent = []

    def send(self, payload):
        self.sent.append(bytes(payload))

    def recv(self):
        return next(self.responses)


class SharedTP2Tests(unittest.TestCase):
    def test_encoded_timing_and_length_prefixed_segmentation(self):
        self.assertEqual(decode_timing_ms(0x4A), 10.0)
        frames, next_sequence = segment_message(
            bytes(range(100)), 14, block_size=15, length_prefixed=True)
        self.assertEqual(len(frames), 15)
        self.assertEqual(frames[-1][0] >> 4, 1)
        self.assertEqual(next_sequence, 13)
        self.assertEqual(b''.join(frame[1:] for frame in frames)[:2], b'\x00\x64')

    def test_intermediate_block_uses_ack_more_opcode(self):
        frames, _ = segment_message(bytes(range(120)), block_size=6)
        self.assertEqual(frames[5][0] >> 4, 0)
        self.assertEqual(frames[11][0] >> 4, 0)
        self.assertEqual(frames[-1][0] >> 4, 1)

    def test_raw_ddp_segmentation_has_no_kwp_length(self):
        frames, _ = segment_message(b'12345678', 3, length_prefixed=False)
        self.assertEqual(frames, [b'#1234567', b'\x148'])
        self.assertEqual(build_ack(4), b'\xB5')

    def test_reassembler_acks_block_boundaries_and_returns_one_message(self):
        frames, _ = segment_message(bytes(range(50)), 14, block_size=3)
        reassembler = TP2MessageReassembler(14)
        acknowledgements = []
        result = None
        for frame in frames:
            result, ack = reassembler.feed(frame)
            if ack:
                acknowledgements.append(ack)
        self.assertEqual(result, bytes(range(50)))
        self.assertEqual(acknowledgements, [b'\xB1', b'\xB4', b'\xB6'])

    def test_reassembler_ignores_length_flag_bit(self):
        # Airbag 0x05 sets bit 15 of the length: 0x8030 is 48 bytes.
        payload = b'\x5A\x9B' + bytes(46)
        frames, _ = segment_message(payload, 0)
        frames[0] = frames[0][:1] + b'\x80' + frames[0][2:]
        reassembler = TP2MessageReassembler(0)
        for frame in frames:
            result, _ = reassembler.feed(frame)
        self.assertEqual(result, payload)

    def test_reassembler_rejects_short_final_frame(self):
        reassembler = TP2MessageReassembler(0)
        with self.assertRaisesRegex(ValueError, 'declared 9, got 3'):
            reassembler.feed(b'\x10\x00\x09\x5A\x9B\x00')

    def test_reassembler_ignores_padding_in_final_frame(self):
        frames, _ = segment_message(b'\x5A\x9B' + bytes(10), 0)
        frames[-1] = frames[-1] + b'\x55' * (8 - len(frames[-1]))
        reassembler = TP2MessageReassembler(0)
        for frame in frames:
            result, _ = reassembler.feed(frame)
        self.assertEqual(result, b'\x5A\x9B' + bytes(10))


class SharedKWPTests(unittest.TestCase):
    def test_pending_is_received_without_resending(self):
        transport = ScriptedTransport([b'\x7f\x21\x78', b'\x61\x03data'])
        response = KWPClient(transport, debug=False).read_local_identifier(3)
        self.assertEqual(response, b'\x61\x03data')
        self.assertEqual(transport.sent, [b'\x21\x03'])

    def test_negative_response_can_be_raised_or_returned(self):
        negative = b'\x7f\x21\x31'
        with self.assertRaises(KWPNegativeResponse):
            KWPClient(ScriptedTransport([negative]), debug=False).request(b'\x21\x03')
        transport = ScriptedTransport([negative])
        self.assertEqual(
            KWPClient(transport, debug=False).request(b'\x21\x03', raise_negative=False),
            negative)

    def test_haldex_profile_rejects_unapproved_programming_session(self):
        transport = ScriptedTransport([b'\x50\x86'])
        with self.assertRaises(KWPError):
            Kwp(transport, debug=False).session(0x86)

    def test_pq_download_accepts_one_or_two_byte_block_limits(self):
        for response, expected in ((b'\x74\x91', 0x91), (b'\x74\x01\x00', 0x100)):
            with self.subTest(response=response):
                transport = ScriptedTransport([response])
                actual = KWPClient(transport, debug=False).request_download(0xA000, 0x10000)
                self.assertEqual(actual, expected)
                self.assertEqual(transport.sent, [bytes.fromhex('3400a00000010000')])

    def test_pq_memory_read_and_upload_wire_formats(self):
        transport = ScriptedTransport([b'\x63ABCD', b'\x75\x01\x00'])
        client = KWPClient(transport, debug=False)
        self.assertEqual(client.read_memory_by_address(0x123456, 4), b'ABCD')
        self.assertEqual(client.request_upload(0xA000, 0x10000), 0x100)
        self.assertEqual(
            transport.sent,
            [bytes.fromhex('2312345604'), bytes.fromhex('3500a00000010000')],
        )


class DDPSharedFramingTests(unittest.TestCase):
    def test_ddp_42_byte_profile_uses_shared_raw_framing(self):
        protocol = DDPProtocol.__new__(DDPProtocol)
        protocol.state = DDPState.READY
        protocol.dis_mode = DisMode.RED
        protocol.tx_id = 0x6C0
        protocol.send_seq_num = 0
        sent = []
        acknowledgements = []
        protocol.send_can = lambda address, data: sent.append((address, bytes(data)))
        protocol._recv_specific = lambda expected, timeout: acknowledgements.append(bytes(expected)) or expected

        self.assertTrue(protocol.send_ddp_frame(list(range(50))))
        self.assertEqual(len(sent), 8)
        self.assertEqual([frame[1][0] >> 4 for frame in sent], [2, 2, 2, 2, 2, 0, 2, 1])
        # Six-frame ACK boundaries continue the same application message:
        # opcode0 requests an intermediate ACK, opcode1 terminates it.
        self.assertEqual(b''.join(frame[1][1:] for frame in sent), bytes(range(50)))
        self.assertEqual(acknowledgements, [b'\xB6', b'\xB8'])
        self.assertEqual(protocol.send_seq_num, 8)


if __name__ == '__main__':
    unittest.main()
