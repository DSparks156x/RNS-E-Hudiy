"""Content requests remain separate from successful native control setup."""
from collections import deque
import unittest
from test_ddp_state import ddp


class PresentationRequestTests(unittest.TestCase):
    def driver(self):
        driver = ddp.DDPProtocol.__new__(ddp.DDPProtocol)
        driver.state = ddp.DDPState.PAUSED
        driver.dis_mode = ddp.DisMode.WHITE
        driver.presentation_request_generation = 0
        driver.application_setup_record = (0x21, 0x3B, 0xA0, 0)
        driver._application_mode = 1
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
        driver._last_window_status = ddp.WindowStatus.parse([0x53, 0x84])
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
