"""Real retained-FREE ACK waits stop graphics without opening a CAN bus."""
import unittest
from collections import deque
from unittest.mock import Mock

from test_ddp_state import ddp


FREE = (0x05, 0x0A)


class FreeDuringAckTests(unittest.TestCase):
    def driver(self, incoming):
        d = ddp.DDPProtocol.__new__(ddp.DDPProtocol)
        d.state, d.dis_mode = ddp.DDPState.READY, ddp.DisMode.WHITE
        d.bus = None
        d.tx_id, d.send_seq_num = 0x6C0, 0
        d.i_am_opener = True
        d.screen_released_by_cluster = False
        d._last_screen_status = None
        d._data_inbox = deque()
        d._flashing_inhibited = Mock(return_value=False)
        d.send_can = Mock()
        d.transport_profile = ddp.DDPTransportProfile(frame_gap_s=0,
            white_post_message_delay_s=0)
        queue = deque(incoming)
        d._recv = lambda timeout: queue.popleft() if queue else None
        return d

    def graphics_frames(self, d):
        return [call.args[1] for call in d.send_can.call_args_list
                if call.args[1][0] >> 4 in (0, 1, 2)]

    def assert_released(self, d, status):
        self.assertEqual(d.state, ddp.DDPState.PAUSED)
        self.assertTrue(d.screen_released_by_cluster)
        self.assertEqual(d._last_screen_status, status)
        self.assertEqual(d.state_generation, 1)

    def test_free_before_continuation_ack_stops_remaining_graphics(self):
        for status in FREE:
            with self.subTest(status=status):
                record = [0x13, 0x53, status]
                d = self.driver([record, [0xB6], [0xB8]])
                self.assertFalse(d.send_ddp_frame(list(range(52))))
                self.assert_released(d, status)
                graphics = self.graphics_frames(d)
                self.assertEqual(len(graphics), 6)
                self.assertEqual(graphics[-1][0] >> 4, 0)
                self.assertFalse(any(frame[0] >> 4 == 1 for frame in graphics))
                self.assertEqual(list(d._data_inbox), [record])
                self.assertEqual([call.args[1] for call in d.send_can.call_args_list].count([0xB4]), 1)
                # Dispatch is idempotent: no second application ACK or state epoch.
                d.poll_bus_events()
                self.assert_released(d, status)
                self.assertEqual(d.send_can.call_count, 7)
                self.assertFalse(d.send_ddp_frame([0x39]))
                self.assertEqual(d.send_can.call_count, 7)

    def test_free_before_final_ack_does_not_report_success(self):
        for status in FREE:
            with self.subTest(status=status):
                d = self.driver([[0x13, 0x53, status], [0xB1]])
                self.assertFalse(d.send_ddp_frame([0x39]))
                self.assert_released(d, status)
                self.assertEqual(self.graphics_frames(d), [[0x10, 0x39]])

    def test_claim_grants_are_not_reinterpreted_as_free(self):
        for status in (0x85, 0x8A):
            with self.subTest(status=status):
                d = self.driver([[0x13, 0x53, status], [0xB1]])
                self.assertTrue(d.send_ddp_frame([0x39]))
                self.assertEqual(d.state, ddp.DDPState.READY)
                self.assertFalse(d.screen_released_by_cluster)
                self.assertEqual(getattr(d, 'state_generation', 0), 0)

    def test_free_remains_asynchronous_during_initialization(self):
        for status in FREE:
            with self.subTest(status=status):
                d = self.driver([[0x13, 0x53, status], [0x14, 0, 1]])
                d.state = ddp.DDPState.INITIALIZING
                self.assertEqual(d._recv_and_ack_data(50), [0x14, 0, 1])
                self.assertEqual(d.state, ddp.DDPState.INITIALIZING)
                self.assertEqual(d._last_screen_status, status)
                self.assertEqual(getattr(d, 'state_generation', 0), 0)

    def test_repeated_free_while_paused_marks_release_without_new_generation(self):
        d = self.driver([])
        d.state = ddp.DDPState.PAUSED
        d.state_generation = 4
        for status in FREE:
            d._retain_data([0x13, 0x53, status])
            self.assertTrue(d.screen_released_by_cluster)
            self.assertEqual(d._last_screen_status, status)
            self.assertEqual(d.state_generation, 4)


if __name__ == '__main__':
    unittest.main()
