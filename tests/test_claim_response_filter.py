"""Exercise the real DisService.claim_nav_screen against a real DDPProtocol.

No CAN: the driver comes from make_driver() and peer frames are fed through
its _recv, so sequence checks, ACKs and window-status observation are real.
"""
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_ddp_state import ddp, make_driver
import dis_service

GRANT = [0x53, 0x85]
CENTRAL_CLAIM = [0x52, 5, 0x82, 0, 0x1B, 0x40, 0x30]
# A stale setup reply: retained and handed to the claim loop, but unrelated.
UNRELATED = [0x21, 0x3B, 0xA0, 0]
# The production claim methods, without DisService's ZMQ/status side effects.
Service = type('Service', (), {name: getattr(dis_service.DisService, name) for name in
               ('claim_nav_screen', '_native_7a_ready', '_native_7a_context')})


class ClaimResponseTests(unittest.TestCase):
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
        self.d.send_data_packet = Mock()
        self.incoming = deque()
        self.timeouts = []
        self.peer_seq = 0
        def recv(timeout):
            self.timeouts.append(timeout)
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
        s.claim_retry_count = 5
        self.s = s

    def peer(self, *payloads):
        """Queue single-frame peer records with consecutive TP sequence numbers."""
        frames = []
        for payload in payloads:
            frames.append([0x10 | self.peer_seq] + list(payload))
            self.peer_seq = (self.peer_seq + 1) & 15
        self.incoming.extend(frames)
        return frames

    def claim(self):
        return self.s.claim_nav_screen()

    def test_grant_marks_screen_active(self):
        self.peer(GRANT)
        self.assertTrue(self.claim())
        self.assertTrue(self.s.screen_is_active)
        self.assertEqual(self.s.claim_retry_count, 0)
        self.assertEqual(self.d.state, ddp.DDPState.READY)
        self.d.send_data_packet.assert_called_once_with(CENTRAL_CLAIM)

    def test_unrelated_retained_record_does_not_hide_ownership_grant(self):
        self.peer(UNRELATED, GRANT)
        self.assertTrue(self.claim())
        self.assertTrue(self.s.screen_is_active)
        self.d.send_data_packet.assert_called_once()

    def test_full_ownership_grant_is_accepted_after_ignored_record(self):
        self.peer([0x57, 0], [0x53, 0x8a])
        self.assertTrue(self.claim())

    def test_status_received_before_claim_is_not_a_grant(self):
        # Already observed before this claim was sent: must not grant it.
        self.d._retain_data(self.peer(GRANT)[0])
        self.incoming.clear()
        self.assertFalse(self.claim())
        self.assertFalse(self.s.screen_is_active)

    def test_busy_free_and_reinit_stop_claim_and_preserve_protocol_event(self):
        for payload in ([0x53, 0x84], [0x53, 0x04], [0x53, 0x88],
                        [0x53, 0x08], [0x53, 0x05], [0x53, 0x0a], [0x2e]):
            with self.subTest(payload=payload):
                self.setUp()
                packet, _ = self.peer(payload, GRANT)
                self.assertFalse(self.claim())
                self.assertEqual(self.d.state, ddp.DDPState.PAUSED)
                self.assertEqual(list(self.d._data_inbox), [packet])
                self.assertFalse(self.s.screen_is_active)
                self.assertEqual(len(self.incoming), 1)
                self.d.send_data_packet.assert_called_once()

    def test_fault_status_does_not_mark_screen_active(self):
        self.peer([0x53, 0xff])
        self.assertFalse(self.claim())
        self.assertFalse(self.s.screen_is_active)
        self.assertEqual(self.d.state, ddp.DDPState.PAUSED)

    def test_no_response_waits_paused(self):
        self.assertFalse(self.claim())
        self.assertFalse(self.s.screen_is_active)
        self.assertEqual(self.d.state, ddp.DDPState.PAUSED)
        self.assertLessEqual(self.now, 1.1)

    def test_unrelated_records_share_one_bounded_deadline(self):
        self.peer(*([UNRELATED] * 10))
        self.assertFalse(self.claim())
        self.assertLessEqual(self.now, 1.1)
        self.assertLess(self.timeouts[-1], self.timeouts[0])
        self.assertEqual(self.d.state, ddp.DDPState.PAUSED)

    def test_disconnect_does_not_become_paused(self):
        self.incoming.append(list(self.d.KA_CLOSE))
        self.assertFalse(self.claim())
        self.assertEqual(self.d.state, ddp.DDPState.DISCONNECTED)

    def test_disabled_presentation_never_sends_claim(self):
        self.s.presentation_requested = False
        self.assertFalse(self.claim())
        self.d.send_data_packet.assert_not_called()

    def test_unverified_renderer_never_sends_claim(self):
        self.d._application_setup_pending = True
        self.assertFalse(self.claim())
        self.d.send_data_packet.assert_not_called()


if __name__ == '__main__':
    unittest.main()
