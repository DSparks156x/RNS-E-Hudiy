"""Top display stops writing 0x363/0x365 once the RNS-E sleeps.

A frame sent after the NM ring acks sleep wakes the bus again, which keeps
the RNS-E (and its amp-wake line, which powers the Pi) up.
"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
from dis_top_display_service import CANWatcher, LineController, POWER_STALE


def status(radio_active):
    return json.dumps({'kl15': False, 'bus_active': radio_active,
                       'radio_active': radio_active}).encode()


class TopDisplayPowerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        patcher = patch('dis_top_display_service.time.monotonic', lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.line = SimpleNamespace(_next_write=50.0)
        self.watcher = CANWatcher(Mock(), '', '', 0x661, SimpleNamespace(running=False), 0x37,
                                  power_addr='ipc:///unused')
        self.watcher._lines = {0x363: self.line, 0x365: None}
        self.watcher.tv_active = True

    def test_no_writes_before_power_status_or_while_radio_asleep(self):
        self.assertFalse(self.watcher.can_transmit, 'RNS-E state unknown at start')
        self.watcher._on_power_status(status(False))
        self.assertFalse(self.watcher.can_transmit)
        self.watcher._on_power_status(status(True))
        self.assertTrue(self.watcher.can_transmit)
        self.assertEqual(self.line._next_write, 0.0, 'wake writes the line at once')
        self.watcher.tv_active = False
        self.assertFalse(self.watcher.can_transmit)

    def test_radio_sleep_stops_writes_even_with_tv_source_latched(self):
        self.watcher._on_power_status(status(True))
        self.watcher._on_power_status(status(False))   # 0x661 stops, tv_active stays True
        self.assertTrue(self.watcher.tv_active)
        self.assertFalse(self.watcher.can_transmit)

    def test_stale_power_status_stops_writes(self):
        self.watcher._on_power_status(status(True))
        self.now += POWER_STALE
        self.assertFalse(self.watcher.can_transmit, 'base function gone: state unknown')

    def test_garbage_status_keeps_last_state(self):
        self.watcher._on_power_status(status(True))
        self.watcher._on_power_status(b'not json')
        self.assertTrue(self.watcher.can_transmit)

    def test_heartbeat_loop_sends_nothing_while_gated(self):
        line = LineController.__new__(LineController)
        line._zmq_ctx = Mock()
        line._can_send_addr = 'inproc://unused-test'
        line.ctrl = SimpleNamespace(running=True)
        line._watcher = self.watcher            # tv_active, but no POWER_STATUS yet
        line.no_scroll = True
        line.hb_interval = .1
        line._last_sent = b''
        line._last_force = 0
        line._next_write = 0
        line._send = Mock(return_value=True)
        def sleep(_):
            line.ctrl.running = False
        with patch('dis_top_display_service.time.sleep', side_effect=sleep):
            line.run()
        line._send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
