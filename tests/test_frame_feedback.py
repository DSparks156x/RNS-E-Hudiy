import ast
import logging
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent
SERVICE = ROOT / 'service_feedback_candidate.py'
GIF = ROOT / 'gif_feedback_candidate.py'
if not SERVICE.exists():
    SERVICE = ROOT.parent / 'dis_client/dis_service.py'
    GIF = ROOT.parent / 'dis_client/dis_tests/test_gif_ipc.py'


def load_methods(path, names):
    tree = ast.parse(path.read_text())
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    namespace = {'time': time, 'logger': logging.getLogger(__name__),
                 'DDPError': RuntimeError, 'zmq': SimpleNamespace(NOBLOCK=1, ZMQError=RuntimeError)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class ServiceFeedbackTests(unittest.TestCase):
    def setUp(self):
        names = {'_send_graphics', '_finish_frame', '_expand_draw_command',
                 '_reject_draw_commands', '_publish_frame_result', 'commit_frame'}
        ns = load_methods(SERVICE, names)
        cls = type('Service', (), {name: ns[name] for name in names})
        self.service = cls()
        self.service.ddp = SimpleNamespace(send_ddp_frame=Mock(return_value=True))
        self.service.status_pub = SimpleNamespace(send_string=Mock())

    def result(self):
        return self.service.status_pub.send_string.call_args.args[0]

    def test_successful_graphics_and_commit_ack(self):
        self.service._send_graphics([55])
        self.assertTrue(self.service._finish_frame(42))
        self.assertEqual(self.result(), 'DRAW_ACK 42')
        self.assertEqual(self.service.ddp.send_ddp_frame.call_args.args[0], [0x39])

    def test_failed_payload_cannot_be_hidden_by_successful_commit(self):
        self.service.ddp.send_ddp_frame.return_value = False
        self.service._send_graphics([55])
        self.service.ddp.send_ddp_frame.return_value = True
        self.assertFalse(self.service._finish_frame(43))
        self.assertEqual(self.result(), 'DRAW_NACK 43')
        self.assertEqual(self.service.ddp.send_ddp_frame.call_count, 1)
        self.assertTrue(self.service._finish_frame(44))
        self.assertEqual(self.result(), 'DRAW_ACK 44')

    def test_failed_commit_nacks(self):
        self.service.ddp.send_ddp_frame.return_value = False
        self.assertFalse(self.service._finish_frame(45))
        self.assertEqual(self.result(), 'DRAW_NACK 45')

    def test_failure_is_retained_between_ipc_batches(self):
        self.service.ddp.send_ddp_frame.side_effect = RuntimeError('ACK timeout')
        self.assertFalse(self.service._send_graphics([55]))
        self.assertFalse(self.service._send_graphics([57]))
        self.service._finish_frame(46)
        self.assertEqual(self.result(), 'DRAW_NACK 46')
        self.assertEqual(self.service.ddp.send_ddp_frame.call_count, 1)

    def test_unowned_frame_gets_nack(self):
        self.service._reject_draw_commands([{'command': 'draw_raw_bitmap'}, {'command': 'commit', 'seq': 47}])
        self.assertEqual(self.result(), 'DRAW_NACK 47')
        self.service._reject_draw_commands([{'command': 'frame', 'seq': 48}])
        self.assertEqual(self.result(), 'DRAW_NACK 48')

    def test_frame_envelope_has_one_final_commit(self):
        commands = [{'command': 'clear_area'}, {'command': 'draw_raw_bitmap'}]
        self.assertEqual(self.service._expand_draw_command({'command': 'frame', 'commands': commands, 'seq': 49}),
                         commands + [{'command': 'commit', 'seq': 49}])
        self.assertEqual(len(commands), 2)

    def test_nested_or_invalid_commands_are_rejected(self):
        for commands in ({}, [None], [{'command': 'frame'}], [{'command': 'commit'}]):
            self.assertEqual(self.service._expand_draw_command({'command': 'frame', 'commands': commands, 'seq': 50}), [])
            self.assertEqual(self.result(), 'DRAW_NACK 50')


class CowFlowTests(unittest.TestCase):
    def setUp(self):
        self.ns = load_methods(GIF, {'FrameRejected', 'FrameSender', 'playback_indices'})
        self.draw = SimpleNamespace(send_json=Mock())
        self.now = 0.0
        self.messages = []
        self.status = SimpleNamespace(poll=self.poll, recv_string=lambda: self.messages.pop(0))
        self.sender = self.ns['FrameSender'](self.draw, self.status, timeout=1, clock=lambda: self.now)
        self.sender.seq = 100

    def poll(self, timeout):
        self.now += .1
        return bool(self.messages)

    def test_only_matching_ack_advances(self):
        self.messages = ['DRAW_ACK 99', 'DRAW_ACK 102', 'DIS_STATE READY', 'DRAW_ACK nope', 'DRAW_ACK 101']
        self.assertAlmostEqual(self.sender.submit([{'command': 'draw_raw_bitmap'}]), .5)
        self.assertEqual(self.draw.send_json.call_count, 1)
        self.assertFalse(self.sender.pending)
        self.assertEqual(self.draw.send_json.call_args.args[0]['command'], 'frame')

    def test_rejected_frame_stops_and_cannot_send_another_delta(self):
        self.messages = ['DRAW_NACK 101']
        with self.assertRaises(self.ns['FrameRejected']):
            self.sender.submit([])
        with self.assertRaises(RuntimeError):
            self.sender.submit([])
        self.assertEqual(self.draw.send_json.call_count, 1)

    def test_timeout_never_queues_another_frame(self):
        with self.assertRaises(TimeoutError):
            self.sender.submit([])
        with self.assertRaises(RuntimeError):
            self.sender.submit([])
        self.assertEqual(self.draw.send_json.call_count, 1)

    def test_initial_and_wraparound_frame_order(self):
        indices = self.ns['playback_indices'](3)
        self.assertEqual([next(indices) for _ in range(6)], [1, 2, 0, 1, 2, 0])


if __name__ == '__main__':
    unittest.main()
