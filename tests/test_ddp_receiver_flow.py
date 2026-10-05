"""Offline tests of the actual DDP receiver-flow methods; never open CAN."""
import ast
import logging
import os
import struct
import unittest
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Sequence, Tuple
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SOURCE = Path(os.environ.get('DDP_RECEIVER_SOURCE', str(REPO / 'dis_client/ddp_protocol.py')))


def load_actual(clock, guard):
    ns = dict(List=List, Optional=Optional, Sequence=Sequence, Tuple=Tuple,
              struct=struct, deque=deque, dataclass=dataclass, Enum=Enum, auto=auto,
              logger=logging.getLogger(__name__), time=clock,
              transmission_guard=guard,
              can=SimpleNamespace(Message=lambda **kw: SimpleNamespace(**kw)))
    tp_tree = ast.parse((REPO / 'flasher/vag_protocols/tp2.py').read_text())
    wanted = {'classify_frame', 'build_ack', 'build_data_frame', 'segment_message'}
    exec(compile(ast.Module(body=[n for n in tp_tree.body
        if isinstance(n, ast.FunctionDef) and n.name in wanted], type_ignores=[]),
        '<actual TP2 framing>', 'exec'), ns)
    tree = ast.parse(SOURCE.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == 'DEFAULT_DDP_TRANSPORT' for t in n.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), ns)
    return ns


class ReceiverFlowTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.physical = []
        self.guard_allowed = True
        self.guard_events = []
        clock = SimpleNamespace(monotonic=lambda: self.now, time=lambda: self.now,
                                perf_counter=lambda: self.now,
                                sleep=lambda s: setattr(self, 'now', self.now + s))
        @contextmanager
        def guard():
            self.guard_events.append('enter')
            try:
                yield self.guard_allowed
            finally:
                self.guard_events.append('exit')
        self.ns = load_actual(clock, guard)
        self.State, self.Mode = self.ns['DDPState'], self.ns['DisMode']
        self.cls = self.ns['DDPProtocol']
        self.d = self.cls.__new__(self.cls)
        self.d.state, self.d.dis_mode = self.State.READY, self.Mode.WHITE
        self.d.send_seq_num = 8
        self.d.tx_id, self.d.rx_id = 0x6c0, 0x6c1
        self.d.i_am_opener = True
        self.d._data_inbox = deque()
        self.d._last_received_ack = None
        self.d._last_screen_status = None
        self.d.screen_released_by_cluster = False
        self.d._flashing_inhibited = Mock(return_value=False)
        self.d.transport_profile = self.ns['DDPTransportProfile'](
            frame_gap_s=0, max_message_bytes=105, max_unacked_frames=15,
            white_post_message_delay_s=0, receiver_not_ready_wait_s=.1,
            max_not_ready_retries=5, max_ack_retries=2)
        self.sent, self.delays = [], []
        self.d.send_can = lambda cid, frame: self.sent.append((self.now, cid, bytes(frame)))
        self.d.close_session = Mock(side_effect=lambda: setattr(self.d, 'state', self.State.DISCONNECTED))
        def delay(seconds):
            self.delays.append(seconds)
            self.now += seconds
            return True
        self.d._wait_receiver_delay = delay
        self.block, self.next_sequence = self.ns['segment_message'](
            bytes(range(105)), 8, block_size=15, length_prefixed=False)

    def replies(self, *items):
        self.responses = deque(items)
        self.d._recv_specific = Mock(side_effect=lambda expected, timeout:
            self.responses.popleft() if self.responses else None)

    def packets(self):
        return [item[2] for item in self.sent]

    def incoming(self, *items):
        queue = deque(items)
        def recv(timeout):
            self.now += min(timeout, .001) if queue else timeout
            return queue.popleft() if queue else None
        self.d._recv = recv

    def test_live_rejected_wrapped_block_replays_identical_bytes_after_wait(self):
        self.replies([0x98], [0xb7])
        self.assertTrue(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block + self.block)
        self.assertEqual(self.delays, [.1])
        self.assertGreaterEqual(self.sent[15][0] - self.sent[14][0], .1)
        self.assertEqual(self.d.send_seq_num, 7)
        self.assertEqual(self.d.state, self.State.READY)
        self.d.close_session.assert_not_called()

    def test_matching_not_ready_accepts_without_replay_or_ready_notification(self):
        self.replies([0x97])
        self.assertTrue(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block)
        self.assertEqual(self.delays, [.1])
        self.assertEqual(self.d.send_seq_num, 7)
        self.assertEqual(self.d._recv_specific.call_count, 1)
        self.assertEqual(self.d.state, self.State.READY)

    def test_not_ready_partial_retry_replays_only_requested_wrapped_suffix(self):
        self.replies([0x9c], [0xb7])
        self.assertTrue(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block + self.block[4:])
        self.assertEqual(self.delays, [.1])

    def test_ready_partial_retry_does_not_apply_not_ready_delay(self):
        self.replies([0xbc], [0xb7])
        self.assertTrue(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block + self.block[4:])
        self.assertEqual(self.delays, [])

    def test_ready_sequence_retry_has_block_allowance_independent_of_timeout(self):
        self.replies([0xb8], [0xb8], [0xb8], None, None, [0xb7])
        self.assertTrue(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block * 4 + [self.block[-1]] * 2)
        self.assertEqual(self.delays, [])
        self.d.close_session.assert_not_called()

    def test_ready_sequence_rejection_is_bounded_by_block_retry_limit(self):
        self.replies(*([[0xb8]] * 6))
        self.assertFalse(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block * 6)
        self.assertEqual(self.delays, [])
        self.d.close_session.assert_called_once()

    def test_continuation_retry_preserves_message_end_and_next_block(self):
        frames, final_sequence = self.ns['segment_message'](
            bytes(range(119)), 8, block_size=15, length_prefixed=False)
        self.replies([0x98], [0xb7], [0xb9])
        self.assertTrue(self.d.send_ddp_frame(list(range(119)), pacing=False))
        self.assertEqual(self.packets(), frames[:15] * 2 + frames[15:])
        self.assertEqual(self.packets()[14][0], 0x06)
        self.assertEqual(self.packets()[29][0], 0x06)
        self.assertEqual(sum(frame[0] >> 4 == 1 for frame in self.packets()), 1)
        self.assertEqual(self.d.send_seq_num, final_sequence)

    def test_persistent_rejection_is_bounded_and_closes_instead_of_pausing(self):
        self.replies(*([[0x98]] * 6))
        self.assertFalse(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block * 6)
        self.assertEqual(len(self.delays), 5)
        self.d.close_session.assert_called_once()
        self.assertEqual(self.d.state, self.State.DISCONNECTED)

    def test_missing_ack_retries_final_only_with_unchanged_sequence(self):
        self.replies(None, None, [0xb7])
        self.assertTrue(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block + [self.block[-1]] * 2)
        self.assertEqual(self.delays, [])
        self.assertEqual(self.d.send_seq_num, 7)

    def test_missing_ack_exhaustion_is_bounded(self):
        self.replies(None, None, None)
        self.assertFalse(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block + [self.block[-1]] * 2)
        self.d.close_session.assert_called_once()

    def test_sequence_outside_retained_block_fails_without_invented_replay(self):
        self.d.send_seq_num = 8
        self.replies([0x9a])
        self.assertFalse(self.d.send_ddp_frame([0x39], pacing=False))
        self.assertEqual(self.packets(), [b'\x18\x39'])
        self.d.close_session.assert_called_once()

    def test_single_command_not_ready_retry_works_during_initialization(self):
        self.d.state = self.State.INITIALIZING
        self.replies([0x98], [0xb9])
        self.d.send_data_packet([0x39])
        self.assertEqual(self.packets(), [b'\x18\x39'] * 2)
        self.assertEqual(self.delays, [.1])
        self.assertEqual(self.d.send_seq_num, 9)
        self.assertEqual(self.d.state, self.State.INITIALIZING)

    def test_unsolicited_not_ready_does_not_change_display_ownership(self):
        self.assertTrue(self.d._handle_incoming_packet([0x98]))
        self.assertEqual(self.d.state, self.State.READY)
        self.assertEqual(self.d._last_received_ack, [0x98])

    def test_ack_wait_returns_receiver_flow_and_retains_unrelated_data_once(self):
        self.incoming([0xa3], [0x13, 0x30, 0, 0, 64, 48], [0x98])
        result = self.cls._recv_specific(self.d, [0xb7], 1000)
        self.assertEqual(result, [0x98])
        self.assertEqual(list(self.d._data_inbox), [[0x13, 0x30, 0, 0, 64, 48]])
        self.assertEqual(self.packets(), [bytes(self.d.KA_WHITE_ACCEPT), b'\xb4'])
        self.assertEqual(self.d.state, self.State.READY)

    def test_session_wait_does_not_mistake_not_ready_for_expected_session_reply(self):
        self.incoming([0x98], self.d.KA_WHITE_ACCEPT)
        result = self.cls._recv_specific(self.d, self.d.KA_WHITE_ACCEPT, 1000)
        self.assertEqual(result, self.d.KA_WHITE_ACCEPT)
        self.assertEqual(self.d.state, self.State.READY)

    def test_cooperative_receiver_delay_handles_keepalive_and_retains_data(self):
        self.incoming([0xa3], [0x13, 0x30, 0, 0, 64, 48])
        self.cls._wait_receiver_delay(self.d, .1)
        self.assertGreaterEqual(self.now, .1)
        self.assertEqual(list(self.d._data_inbox), [[0x13, 0x30, 0, 0, 64, 48]])
        self.assertEqual(self.packets(), [bytes(self.d.KA_WHITE_ACCEPT), b'\xb4'])

    def test_ownership_busy_or_reinit_during_wait_prevents_retransmission(self):
        for application in ([0x53, 0x84], [0x53, 0x04], [0x2e]):
            with self.subTest(application=application):
                self.setUp()
                self.replies([0x98], [0xb7])
                self.incoming([0x13] + application)
                self.d._wait_receiver_delay = lambda s: self.cls._wait_receiver_delay(self.d, s)
                self.assertFalse(self.d.send_ddp_frame(list(range(105)), pacing=False))
                self.assertEqual(self.packets()[:15], self.block)
                self.assertFalse(any(frame in self.block for frame in self.packets()[15:]))
                self.assertEqual(list(self.d._data_inbox), [[0x13] + application])

    def test_disconnect_during_wait_prevents_retransmission(self):
        self.replies([0x98], [0xb7])
        self.incoming([0xa8])
        self.d._wait_receiver_delay = lambda s: self.cls._wait_receiver_delay(self.d, s)
        self.assertFalse(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.packets(), self.block)
        self.assertEqual(self.d.state, self.State.DISCONNECTED)

    def test_flash_guard_rejects_every_physical_retry(self):
        def bus_send(message, timeout):
            self.assertEqual(self.guard_events[-1], 'enter')
            self.physical.append(bytes(message.data))
        self.d.bus = SimpleNamespace(send=bus_send, shutdown=Mock())
        self.d._flashing_inhibited = Mock(return_value=False)
        self.d._reset_for_flashing = Mock(side_effect=lambda: setattr(self.d, 'state', self.State.DISCONNECTED))
        self.d.send_can = lambda cid, frame: self.cls.send_can(self.d, cid, frame)
        def arm_flash(seconds):
            self.now += seconds
            self.guard_allowed = False
            return True
        self.d._wait_receiver_delay = arm_flash
        self.replies([0x98], [0xb7])
        self.assertFalse(self.d.send_ddp_frame(list(range(105)), pacing=False))
        self.assertEqual(self.physical, self.block)
        self.d._reset_for_flashing.assert_called_once()
        self.assertEqual(len(self.guard_events), 32)


if __name__ == '__main__':
    unittest.main()
