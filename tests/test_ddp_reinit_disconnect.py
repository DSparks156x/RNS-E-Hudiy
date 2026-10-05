"""Re-init confirmation must not resurrect a closed DDP session. No CAN bus."""
import unittest
from collections import deque
from unittest.mock import Mock, patch

from test_ddp_state import ddp


class ReinitDisconnectTests(unittest.TestCase):
    def driver(self):
        d = ddp.DDPProtocol.__new__(ddp.DDPProtocol)
        d.state = ddp.DDPState.PAUSED
        d.dis_mode = ddp.DisMode.WHITE
        d.bus = None
        d.tx_id = 0x6C0
        d.send_seq_num = 0
        d.i_am_opener = True
        d.screen_released_by_cluster = True
        d._last_screen_status = None
        d._data_inbox = deque([[0x10, 0x2E]])  # Already ACKed by the receive path.
        d._flashing_inhibited = Mock(return_value=False)
        d.send_can = Mock()  # Entire transport is in-memory, no bus construction.
        d._recv = Mock(return_value=None)
        return d

    def setUp(self):
        sleep = patch.object(ddp.time, 'sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def assert_closed(self, d):
        self.assertEqual(d.state, ddp.DDPState.DISCONNECTED)
        self.assertEqual(d.dis_mode, ddp.DisMode.UNKNOWN)
        self.assertIsNone(d.bus)
        self.assertFalse(d.i_am_opener)

    def test_cluster_a8_during_actual_2f_ack_wait_stays_disconnected(self):
        d = self.driver()
        d._recv.side_effect = [[0xA8]]
        d.poll_bus_events()
        self.assert_closed(d)
        d.send_can.assert_called_once_with(d.tx_id, [0x10, 0x2F])

    def test_exhausted_2f_ack_retries_stay_disconnected(self):
        d = self.driver()
        d._recv_specific = Mock(return_value=None)
        d.poll_bus_events()
        self.assert_closed(d)
        self.assertEqual(d._recv_specific.call_count, 3)
        self.assertEqual(d.send_can.call_args_list[-1].args, (d.tx_id, [0xA8]))

    def test_error_without_session_close_remains_paused(self):
        d = self.driver()
        d.send_data_packet = Mock(side_effect=ddp.DDPAckTimeoutError('interrupted'))
        d.poll_bus_events()
        self.assertEqual(d.state, ddp.DDPState.PAUSED)
        self.assertEqual(d.dis_mode, ddp.DisMode.WHITE)

    def test_successful_confirmation_still_resumes(self):
        d = self.driver()
        d._recv_specific = Mock(return_value=[0xB1])
        d.poll_bus_events()
        self.assertEqual(d.state, ddp.DDPState.READY)
        d.send_can.assert_called_once_with(d.tx_id, [0x10, 0x2F])

    def test_generation_increments_on_real_transitions_only(self):
        d = self.driver()
        d._set_state(ddp.DDPState.PAUSED)
        self.assertEqual(getattr(d, 'state_generation', 0), 0)
        for expected, state in enumerate((ddp.DDPState.READY,
                ddp.DDPState.PAUSED, ddp.DDPState.DISCONNECTED), start=1):
            d._set_state(state)
            self.assertEqual(d.state_generation, expected)
            d._set_state(state)
            self.assertEqual(d.state_generation, expected)

    def test_flashing_reset_counts_once_without_duplicate_transitions(self):
        d = self.driver()
        d._reset_for_flashing()
        self.assertEqual(d.state_generation, 1)
        d._reset_for_flashing()
        self.assertEqual(d.state_generation, 1)

    def test_closed_confirmation_does_not_add_a_paused_generation(self):
        d = self.driver()
        d._recv.side_effect = [[0xA8]]
        d.poll_bus_events()
        self.assert_closed(d)
        self.assertEqual(d.state_generation, 1)


if __name__ == '__main__':
    unittest.main()
