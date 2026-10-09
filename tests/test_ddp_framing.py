"""Verify one message end and bounded ACK blocks in the actual DIS driver."""
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parent
repo = root.parent
sys.path.insert(0, str(repo))
if 'can' not in sys.modules:
    fake = types.ModuleType('can')
    fake.CanError = RuntimeError
    # Preserve the message interface used by other offline adapter fixtures.
    fake.Message = lambda **kwargs: types.SimpleNamespace(**kwargs)
    sys.modules['can'] = fake
source = Path(os.environ.get('DDP_FRAMING_SOURCE', str(repo / 'dis_client/ddp_protocol.py')))
spec = importlib.util.spec_from_file_location('ddp_framing_under_test', source)
ddp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ddp
spec.loader.exec_module(ddp)

class FramingTests(unittest.TestCase):
    def driver(self, sequence=0, byte_budget=42, frame_budget=6):
        d = ddp.DDPProtocol.__new__(ddp.DDPProtocol)
        d.state, d.dis_mode = ddp.DDPState.READY, ddp.DisMode.WHITE
        d.tx_id, d.send_seq_num = 0x6c0, sequence
        d.transport_profile = ddp.DDPTransportProfile(max_message_bytes=byte_budget,
            max_unacked_frames=frame_budget, white_post_message_delay_s=0)
        self.sent, self.acks = [], []
        d.send_can = lambda cid, frame: self.sent.append(list(frame))
        def ack(expected, timeout):
            self.acks.append(list(expected))
            return expected
        d._recv_specific = ack
        d.bus = None
        d.close_session = lambda: setattr(d, 'state', ddp.DDPState.DISCONNECTED)
        return d
    def test_52_bytes_have_one_message_end_and_continuation_ack(self):
        d = self.driver()
        payload = list(range(52))
        self.assertTrue(d.send_ddp_frame(payload))
        self.assertEqual([f[0] >> 4 for f in self.sent], [2, 2, 2, 2, 2, 0, 2, 1])
        self.assertEqual([b for f in self.sent for b in f[1:]], payload)
        self.assertEqual(self.acks, [[0xb6], [0xb8]])
    def test_sequence_wrap_does_not_end_message(self):
        d = self.driver(sequence=14)
        self.assertTrue(d.send_ddp_frame(list(range(52))))
        self.assertEqual([f[0] & 15 for f in self.sent], [14, 15, 0, 1, 2, 3, 4, 5])
        self.assertEqual(self.acks, [[0xb4], [0xb6]])
        self.assertEqual(d.send_seq_num, 6)
        self.assertEqual(sum(f[0] >> 4 == 1 for f in self.sent), 1)
    def test_ack_budget_can_be_reduced_without_splitting_message(self):
        d = self.driver(frame_budget=3)
        self.assertTrue(d.send_ddp_frame(list(range(52))))
        self.assertEqual([f[0] >> 4 for f in self.sent], [2, 2, 0, 2, 2, 0, 2, 1])
    def test_byte_budget_still_limits_unacknowledged_frames(self):
        d = self.driver(byte_budget=21)
        self.assertTrue(d.send_ddp_frame(list(range(52))))
        self.assertEqual([f[0] >> 4 for f in self.sent], [2, 2, 0, 2, 2, 0, 2, 1])
    def test_busy_during_continuation_ack_stops_remaining_frames(self):
        d = self.driver()
        def busy(expected, timeout):
            d.state = ddp.DDPState.PAUSED
            return expected
        d._recv_specific = busy
        self.assertFalse(d.send_ddp_frame(list(range(52))))
        self.assertEqual(len(self.sent), 6)
        self.assertEqual(self.sent[-1][0] >> 4, 0)
    def test_missing_continuation_ack_stops_remaining_frames(self):
        d = self.driver()
        d._recv_specific = lambda expected, timeout: None
        self.assertFalse(d.send_ddp_frame(list(range(52))))
        self.assertEqual(len(self.sent), 8)
        self.assertEqual(self.sent[-2:], [self.sent[5], self.sent[5]])
        self.assertEqual(d.state, ddp.DDPState.DISCONNECTED)
    def test_single_frame_and_empty_payload(self):
        d = self.driver()
        self.assertTrue(d.send_ddp_frame([]))
        self.assertEqual(self.sent, [])
        self.assertTrue(d.send_ddp_frame([0x39]))
        self.assertEqual(self.sent, [[0x10, 0x39]])
    def test_multiple_ack_blocks_have_only_one_final_frame(self):
        d = self.driver()
        self.assertTrue(d.send_ddp_frame(list(range(100))))
        self.assertEqual([i for i, f in enumerate(self.sent) if f[0] >> 4 in (0, 1)], [5, 11, 14])
        self.assertEqual(sum(f[0] >> 4 == 1 for f in self.sent), 1)

if __name__ == '__main__':
    unittest.main()
