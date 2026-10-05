"""Exercise the actual claim method without CAN or service dependencies."""
import ast
import logging
import unittest
from collections import deque
from enum import Enum, auto
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parent.parent / 'dis_client/dis_service.py'
TREE = ast.parse(SOURCE.read_text())
METHOD = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == 'claim_nav_screen')

class State(Enum):
    READY = auto()
    PAUSED = auto()
    DISCONNECTED = auto()

class ClaimResponseTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        def monotonic():
            self.now += .001
            return self.now
        ns = {'DDPState': State, 'DDPError': RuntimeError,
              'DDPMessages': SimpleNamespace(CMD_REINIT_REQ=[0x2e],
                  STAT_BUSY_HALF=[0x53, 0x84], STAT_BUSY_WARN_HALF=[0x53, 0x04],
                  STAT_BUSY_FULL=[0x53, 0x88], STAT_BUSY_WARN_FULL=[0x53, 0x08],
                  STAT_FREE_HALF=[0x53, 0x05], STAT_FREE_FULL=[0x53, 0x0a]),
              'time': SimpleNamespace(monotonic=monotonic, time=lambda: self.now),
              'logger': logging.getLogger(__name__)}
        exec(compile(ast.Module(body=[METHOD], type_ignores=[]), str(SOURCE), 'exec'), ns)
        self.claim = ns['claim_nav_screen']
        self.responses = deque()
        self.timeouts = []
        self.d = SimpleNamespace(state=State.READY, _data_inbox=deque(),
                                 send_data_packet=Mock())
        self.d._set_state = lambda state: setattr(self.d, 'state', state)
        def receive(timeout):
            self.timeouts.append(timeout)
            if self.responses:
                response = self.responses.popleft()
                if response == 'disconnect':
                    self.d.state = State.DISCONNECTED
                    return None
                return response
            self.now += timeout / 1000
            return None
        self.d._recv_and_ack_data = receive
        self.s = SimpleNamespace(ddp=self.d, presentation_requested=True,
                                 region_name='central', region_height=48,
                                 screen_is_active=False, claim_retry_count=5)

    def test_unrelated_retained_record_does_not_hide_ownership_grant(self):
        self.responses.extend(([0x10, 0x30, 0, 0, 64, 48], [0x11, 0x53, 0x85]))
        self.assertTrue(self.claim(self.s))
        self.assertTrue(self.s.screen_is_active)
        self.assertEqual(self.d.state, State.READY)
        self.d.send_data_packet.assert_called_once()

    def test_full_ownership_grant_is_accepted_after_unrelated_data(self):
        self.responses.extend(([0x10, 0x57, 0], [0x11, 0x53, 0x8a]))
        self.assertTrue(self.claim(self.s))

    def test_busy_free_and_reinit_stop_claim_and_preserve_protocol_event(self):
        for payload in ([0x53, 0x84], [0x53, 0x04], [0x53, 0x88],
                        [0x53, 0x08], [0x53, 0x05], [0x53, 0x0a], [0x2e]):
            with self.subTest(payload=payload):
                self.setUp()
                packet = [0x10] + payload
                self.responses.extend((packet, [0x11, 0x53, 0x85]))
                self.assertFalse(self.claim(self.s))
                self.assertEqual(self.d.state, State.PAUSED)
                self.assertEqual(list(self.d._data_inbox), [packet])
                self.assertFalse(self.s.screen_is_active)
                self.assertEqual(len(self.responses), 1)
                self.d.send_data_packet.assert_called_once()

    def test_unrelated_records_share_one_bounded_deadline(self):
        self.responses.extend([[0x10, 0x57, 0]] * 10)
        self.assertFalse(self.claim(self.s))
        self.assertLessEqual(self.now, 1.01)
        self.assertLess(self.timeouts[-1], self.timeouts[0])
        self.assertEqual(self.d.state, State.PAUSED)

    def test_disconnect_does_not_become_paused(self):
        self.responses.append('disconnect')
        self.assertFalse(self.claim(self.s))
        self.assertEqual(self.d.state, State.DISCONNECTED)

    def test_disabled_presentation_never_sends_claim(self):
        self.s.presentation_requested = False
        self.assertFalse(self.claim(self.s))
        self.d.send_data_packet.assert_not_called()

if __name__ == '__main__':
    unittest.main()
