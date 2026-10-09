"""Observed initialization traces and content requests are separate from READY."""
from collections import deque
import unittest
from test_ddp_state import ddp


class InitProfileTests(unittest.TestCase):
    def driver(self, mode=ddp.DisMode.WHITE):
        driver = ddp.DDPProtocol.__new__(ddp.DDPProtocol)
        driver.state = ddp.DDPState.INITIALIZING
        driver.dis_mode = mode
        driver.PL = driver._get_init_payloads()
        self.sent = []
        driver.send_data_packet = lambda payload: self.sent.append(list(payload))
        return driver

    def test_white_long_profile_preserves_wire_order_and_variant_records(self):
        driver = self.driver()
        incoming = deque([
            [0x10, 0x30, 0x39, 0, 0x32, 0],
            [0x11, 9, 32, 11, 80, 8, 11, 80],
            [0x12, 0x30, 0x39, 0, 0x30, 0],
            [0x13, 0x21, 0x3b, 0xa0, 0],
            [0x14, 0x21, 0x3b, 0xa0, 0],
        ])
        driver._recv_and_ack_data = lambda timeout: incoming.popleft()
        driver._init_path_c_white()
        self.assertEqual(self.sent, [[1, 1, 0], [8], [0x20, 0x3b, 0xa0, 0],
                                    [0x20, 0x3b, 0xa0, 0], [0x33], [0x33]])
        self.assertEqual(driver.capability_record, [9, 32, 11, 80, 8, 11, 80])
        self.assertFalse(incoming)

    def test_receive_mismatch_stops_before_later_commands(self):
        driver = self.driver()
        driver._recv_and_ack_data = lambda timeout: [0x10, 0x99]
        with self.assertRaises(ddp.DDPHandshakeError):
            driver._init_path_c_white()
        self.assertEqual(self.sent, [[1, 1, 0]])

    def test_closed_session_does_not_continue_profile(self):
        driver = self.driver()
        driver.state = ddp.DDPState.DISCONNECTED
        with self.assertRaises(ddp.DDPHandshakeError):
            driver._init_path_b_white()
        self.assertEqual(self.sent, [])

    def test_red_profile_keeps_short_wire_sequence(self):
        driver = self.driver(ddp.DisMode.RED)
        incoming = deque([[0x10, *driver.PL['PL_LOG_14']],
                          [0x11, *driver.PL['PL_LOG_23']]])
        driver._recv_and_ack_data = lambda timeout: incoming.popleft()
        driver._init_path_red()
        self.assertEqual(self.sent, [[0x20, 0x3b, 0xa0, 0], [0x33]])

    def test_truncated_capability_is_a_handshake_error(self):
        driver = self.driver()
        driver._recv_and_ack_data = lambda timeout: [0x10]
        with self.assertRaises(ddp.DDPHandshakeError):
            driver._init_common_start()


class PresentationRequestTests(unittest.TestCase):
    def driver(self):
        driver = ddp.DDPProtocol.__new__(ddp.DDPProtocol)
        driver.state = ddp.DDPState.PAUSED
        driver.dis_mode = ddp.DisMode.WHITE
        driver.presentation_request_generation = 0
        driver._last_screen_status = None
        driver._last_received_ack = driver._last_received_data = None
        driver._data_inbox = deque([[0x10, 0x2e]])
        driver.screen_released_by_cluster = False
        driver._flashing_inhibited = lambda: False
        driver._recv = lambda timeout: None
        self.sent = []
        driver.send_data_packet = lambda payload: self.sent.append(list(payload))
        return driver

    def test_confirmed_request_signals_once_without_claiming(self):
        driver = self.driver()
        driver.poll_bus_events()
        self.assertEqual(driver.presentation_request_generation, 1)
        self.assertEqual(self.sent, [[0x2f]])
        self.assertEqual(driver.state, ddp.DDPState.READY)
        driver.poll_bus_events()
        self.assertEqual(driver.presentation_request_generation, 1)

    def test_failed_confirmation_is_not_selection(self):
        driver = self.driver()
        def fail(payload):
            raise ddp.DDPAckTimeoutError('timeout')
        driver.send_data_packet = fail
        driver.poll_bus_events()
        self.assertEqual(driver.presentation_request_generation, 0)
        self.assertEqual(driver.state, ddp.DDPState.PAUSED)

    def test_content_request_does_not_override_busy_region(self):
        driver = self.driver()
        driver._last_screen_status = 0x84
        driver.poll_bus_events()
        self.assertEqual(driver.presentation_request_generation, 1)
        self.assertEqual(driver.state, ddp.DDPState.PAUSED)

    def test_ready_transition_alone_is_not_selection(self):
        driver = self.driver()
        driver._data_inbox.clear()
        driver._set_state(ddp.DDPState.READY)
        driver.poll_bus_events()
        self.assertEqual(driver.presentation_request_generation, 0)


if __name__ == '__main__':
    unittest.main()
