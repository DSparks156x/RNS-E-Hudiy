"""Real retained-FREE ACK waits stop graphics without opening a CAN bus."""
import unittest
from collections import deque
from unittest.mock import Mock, patch

from test_ddp_state import ddp, make_driver


FREE = (0x05, 0x0A)


class FreeDuringAckTests(unittest.TestCase):
    def setUp(self):
        sleep = patch.object(ddp.time, 'sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def driver(self, incoming, *, owned=True):
        d = make_driver()
        d.send_can = Mock()
        d._receive_seq_num = 3  # Peer records below continue at sequence 3.
        if owned:
            # Graphics are only sent while the cluster has granted the window.
            d._last_window_status = ddp.WindowStatus.parse([0x53, 0x85])
        queue = deque(incoming)
        d._recv = lambda timeout: queue.popleft() if queue else None
        return d

    def graphics_frames(self, d):
        return [call.args[1] for call in d.send_can.call_args_list
                if call.args[1][0] >> 4 in (0, 1, 2)]

    def assert_abandoned(self, d):
        # A release mid-message leaves unknown peer progress; the driver
        # closes (A8) and reopens rather than finishing or resuming it.
        self.assertEqual(d.state, ddp.DDPState.DISCONNECTED)
        self.assertTrue(d.screen_released_by_cluster)
        self.assertEqual([c.args[1] for c in d.send_can.call_args_list][-1], d.KA_CLOSE)

    def test_free_before_continuation_ack_stops_remaining_graphics(self):
        for status in FREE:
            with self.subTest(status=status):
                record = [0x13, 0x53, status]
                d = self.driver([record, [0xB6], [0xB8]])
                self.assertFalse(d.send_ddp_frame(list(range(52))))
                self.assert_abandoned(d)
                graphics = self.graphics_frames(d)
                self.assertEqual(len(graphics), 6)
                self.assertEqual(graphics[-1][0] >> 4, 0)
                self.assertFalse(any(frame[0] >> 4 == 1 for frame in graphics))
                self.assertEqual([call.args[1] for call in d.send_can.call_args_list].count([0xB4]), 1)
                sent = d.send_can.call_count
                self.assertFalse(d.send_ddp_frame([0x39]))
                self.assertEqual(d.send_can.call_count, sent)

    def test_free_before_final_ack_does_not_report_success(self):
        for status in FREE:
            with self.subTest(status=status):
                d = self.driver([[0x13, 0x53, status], [0xB1]])
                self.assertFalse(d.send_ddp_frame([0x39]))
                self.assert_abandoned(d)
                self.assertEqual(self.graphics_frames(d), [[0x10, 0x39]])

    def test_claim_grants_are_not_reinterpreted_as_free(self):
        for status in (0x85, 0x8A):
            with self.subTest(status=status):
                d = self.driver([[0x13, 0x53, status], [0xB1]])
                self.assertTrue(d.send_ddp_frame([0x39]))
                self.assertEqual(d.state, ddp.DDPState.READY)
                self.assertFalse(d.screen_released_by_cluster)
                self.assertEqual(d.state_generation, 0)

    def test_free_remains_asynchronous_during_initialization(self):
        for status in FREE:
            with self.subTest(status=status):
                d = self.driver([[0x13, 0x53, status], [0x14, 0x21, 0x3B, 0xA0, 0]], owned=False)
                d.state = ddp.DDPState.INITIALIZING
                self.assertEqual(d._recv_and_ack_data(50), [0x14, 0x21, 0x3B, 0xA0, 0])
                self.assertEqual(d.state, ddp.DDPState.INITIALIZING)
                self.assertEqual(d._last_screen_status, status)
                self.assertEqual(d.state_generation, 0)

    def test_repeated_free_while_setup_pending_stays_paused_without_new_generation(self):
        d = self.driver([], owned=False)
        d.state = ddp.DDPState.PAUSED
        d._application_setup_pending = True
        d.state_generation = 4
        for record in ([0x13, 0x53, 0x05], [0x14, 0x53, 0x0A]):
            d._retain_data(record)
            self.assertTrue(d.screen_released_by_cluster)
            self.assertEqual(d._last_screen_status, record[2])
            self.assertEqual(d.state, ddp.DDPState.PAUSED)
            self.assertEqual(d.state_generation, 4)

    def test_free_while_paused_and_configured_resumes_once(self):
        d = self.driver([], owned=False)
        d.state = ddp.DDPState.PAUSED
        d.state_generation = 4
        for record in ([0x13, 0x53, 0x05], [0x14, 0x53, 0x0A]):
            d._retain_data(record)
            self.assertEqual(d.state, ddp.DDPState.READY)
            self.assertEqual(d.state_generation, 5)


if __name__ == '__main__':
    unittest.main()
