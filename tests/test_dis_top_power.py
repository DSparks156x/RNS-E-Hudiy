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
import zmq
from dis_top_display_service import CANWatcher, LineController, OEM_RESPONSE_N, POWER_STALE


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


class TopDisplayWithoutRnseTextTests(unittest.TestCase):
    """Some RNS-E firmware never writes 0x363/0x365 (at least in TV). The top
    lines must run on 0x661 + POWER_STATUS alone, and still answer the RNS-E
    with a burst when it does write."""

    def setUp(self):
        self.now = 100.0
        patcher = patch('dis_top_display_service.time.monotonic', lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.watcher = CANWatcher(Mock(), '', '', 0x661, SimpleNamespace(running=True), 0x37,
                                  power_addr='ipc:///unused')
        self.watcher.tv_active = True
        self.watcher._on_power_status(status(True))

    def make_line(self, text):
        line = LineController(0x363, Mock(), 'inproc://unused-test', 'L1', .35, 0, 0, 0,
                              False, 3, False, SimpleNamespace(running=True), watcher=self.watcher)
        line._send = Mock(return_value=True)
        line.set_text(text)
        self.watcher._lines = {0x363: line, 0x365: None}
        return line

    def test_heartbeat_writes_and_scrolls_with_no_rnse_text(self):
        line = self.make_line('Long scrolling title')
        steps = iter(range(20))
        def sleep(_):
            self.now += .4
            if next(steps) == 19:
                line.ctrl.running = False
        with patch('dis_top_display_service.time.sleep', side_effect=sleep):
            line.run()
        sent = [c.args[0] for c in line._send.call_args_list]
        self.assertTrue(sent, 'no 0x363 seen, still writes')
        self.assertGreater(len(set(sent)), 1, 'scroll never froze waiting on the RNS-E')

    def test_rnse_text_still_gets_burst_reply(self):
        line = self.make_line('Title')
        frame = [b'CAN_363', json.dumps({'data_hex': '2020202020202020'}).encode()]
        def recv(flags=0):
            if frame:
                return [frame.pop(0), frame.pop(0)]
            self.watcher._dis.running = False
            raise zmq.Again()
        sub, push = Mock(), Mock()
        sub.recv_multipart.side_effect = recv
        self.watcher._zmq_ctx.socket.side_effect = [sub, push]
        with patch('dis_top_display_service.zmq.Poller') as poller:
            poller.return_value.poll.return_value = [(sub, zmq.POLLIN)]
            self.watcher.run()
        snap = line.snapshot().hex().encode()
        self.assertEqual(push.send_multipart.call_args_list,
                         [((([str(0x363).encode(), snap],), {'flags': zmq.NOBLOCK}))] * OEM_RESPONSE_N)
        self.assertTrue(line.scroller._frozen, 'held until the next heartbeat')


if __name__ == '__main__':
    unittest.main()
