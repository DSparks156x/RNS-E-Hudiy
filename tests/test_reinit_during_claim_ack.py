"""2E landing inside the center claim's ACK wait (car log 2026-10-13 00:34:18).

The claim 1E 52 05 82.. was sent, the cluster sent 12 2E, then ACKed the
claim with BF. The old driver sent A8 and the reopened session never got
the window back. Real DisService.claim_nav_screen + DDPProtocol, no CAN.
"""
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

from test_ddp_state import ddp, make_driver
import dis_service

CENTRAL_CLAIM = [0x52, 5, 0x82, 0, 0x1B, 0x40, 0x30]
Service = type('Service', (), {name: getattr(dis_service.DisService, name) for name in
               ('claim_nav_screen', '_native_7a_ready', '_native_7a_context')})


class ReinitDuringClaimAckTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        def monotonic():
            self.now += .001
            return self.now
        def sleep(seconds):
            self.now += seconds
        clock = SimpleNamespace(monotonic=monotonic, time=lambda: self.now,
                                perf_counter=monotonic, sleep=sleep)
        for module in (ddp, dis_service):
            patcher = patch.object(module, 'time', clock)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.d = make_driver()
        self.d.send_seq_num = 0xE
        self.d._receive_seq_num = 2
        self.sent = []
        self.d.send_can = lambda cid, payload: self.sent.append(list(payload))
        self.incoming = deque()
        def recv(timeout):
            if self.incoming:
                return self.incoming.popleft()
            self.now += timeout
            return None
        self.d._recv = recv
        s = Service()
        s.ddp = self.d
        s.presentation_requested = True
        s.region_name, s.region_y_offset, s.region_height = 'central', 27, 48
        s.screen_is_active = False
        s.claim_retry_count = 0
        self.s = s

    def test_acked_claim_survives_reinit_and_2e_gets_2f(self):
        self.incoming.extend([[0x12, 0x2E], [0xBF]])
        self.assertFalse(self.s.claim_nav_screen())
        self.assertIn([0x1E] + CENTRAL_CLAIM, self.sent)
        self.assertNotIn(self.d.KA_CLOSE, self.sent)
        self.assertEqual(self.d.state, ddp.DDPState.PAUSED)
        self.assertEqual(list(self.d._data_inbox), [[0x12, 0x2E]])

        self.incoming.append([0xB0])  # ACK for our 2F.
        self.d.poll_bus_events()
        self.assertIn([0x1F, 0x2F], self.sent)
        self.assertNotIn(self.d.KA_CLOSE, self.sent)
        self.assertEqual(self.d.state, ddp.DDPState.READY)
        self.assertEqual(self.d.presentation_request_generation, 1)

    def test_reinit_without_claim_ack_still_reopens(self):
        self.incoming.append([0x12, 0x2E])
        self.assertFalse(self.s.claim_nav_screen())
        self.assertEqual(self.sent[-1], self.d.KA_CLOSE)
        self.assertEqual(self.d.state, ddp.DDPState.DISCONNECTED)

    def test_reinit_during_continuation_block_ack_still_reopens(self):
        # A graphics prefix ACK leaves the message unfinished at the peer.
        block = [bytes([0x0E, 1, 2, 3, 4, 5, 6, 7])]
        self.incoming.extend([[0x12, 0x2E], [0xBF]])
        with self.assertRaises(ddp.DDPAckTimeoutError):
            self.d._send_acknowledged_block(block)
        self.assertEqual(self.sent[-1], self.d.KA_CLOSE)
        self.assertEqual(self.d.state, ddp.DDPState.DISCONNECTED)


if __name__ == '__main__':
    unittest.main()
