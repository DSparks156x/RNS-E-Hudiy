"""Haldex mode commands, telemetry-driven reconciliation and persistence.

Runs the real rns-e_can/haldex_manager.py (not AST extracts) with fake ZMQ
sockets and a fake clock. Wire format ground truth:
references/HALDEX_LOGGING_SPEC.md - five identical 0x67A frames 20 ms apart,
bytes 0-1 select the mode (5A A5 Stock, A5 5A Performance, 3C C3 Competition),
bytes 2-7 zero; applied mode is read back from the 0x6DA status byte.
"""
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import zmq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flasher import traffic  # noqa: E402


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    with patch.object(logging, 'FileHandler', lambda *a, **k: logging.NullHandler()):
        spec.loader.exec_module(module)
    return module


HM = load('haldex_manager_under_test', 'rns-e_can/haldex_manager.py')

SPEC_HEADERS = {0: '5aa5', 1: 'a55a', 2: '3cc3'}


class FakeTime:
    """Fake clock for the module; stops a worker loop after `loop_sleeps` 0.5 s naps."""

    def __init__(self, manager=None, loop_sleeps=None):
        self.now = 50_000.0
        self.manager = manager
        self.loop_sleeps = loop_sleeps
        self.naps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.naps.append(seconds)
        self.now += seconds
        if seconds == 0.5 and self.loop_sleeps is not None:
            self.loop_sleeps -= 1
            if self.loop_sleeps <= 0:
                self.manager.running = False


class CapturePush:
    def __init__(self, clock):
        self.clock = clock
        self.frames = []

    def send_multipart(self, parts, flags=0):
        self.frames.append((self.clock.now, parts[0], parts[1]))

    def connect(self, address):
        pass

    bind = connect


class HaldexTestCase(unittest.TestCase):
    haldex_cfg = {}

    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        env = patch.dict(os.environ, {'HOME': home.name})
        env.start()
        self.addCleanup(env.stop)
        self.home = Path(home.name)
        self.clock = FakeTime()
        patcher = patch.object(HM, 'time', self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config_path = self.home / 'config.json'
        self.write_config(self.haldex_cfg)

    def write_config(self, haldex):
        haldex = dict(haldex)
        haldex.setdefault('persistence_file', str(self.home / '.hudiy' / 'haldex_mode.json'))
        self.config_path.write_text(json.dumps({'haldex': haldex}))

    def manager(self):
        manager = HM.HaldexManager(str(self.config_path))
        self.addCleanup(manager.context.term)
        manager.can_push_sock = CapturePush(self.clock)
        self.clock.manager = manager
        return manager

    def telemetry(self, manager, *frames):
        """Feed (topic, data_hex) through the real CAN listener worker."""
        sub = Mock()
        queue = [[topic.encode(), json.dumps({'data_hex': data}).encode()]
                 for topic, data in frames]

        def recv_multipart(flags=0):
            if queue:
                return queue.pop(0)
            raise zmq.Again()
        sub.recv_multipart.side_effect = recv_multipart

        class Poller:
            def register(self, *args):
                pass

            def poll(self, timeout):
                if queue:
                    return [(sub, zmq.POLLIN)]
                manager.running = False
                return []
        manager.running = True
        with patch.object(manager, 'context', Mock(socket=Mock(return_value=sub))), \
                patch.object(HM.zmq, 'Poller', Poller):
            manager._can_listener_worker()
        manager.running = True
        return sub


class ModeCommandWireTests(HaldexTestCase):
    def test_set_mode_sends_five_spaced_spec_frames_on_0x67a(self):
        manager = self.manager()
        for mode, header in SPEC_HEADERS.items():
            with self.subTest(mode=mode):
                manager.can_push_sock.frames.clear()
                self.clock.naps.clear()
                manager.set_mode(mode)
                frames = manager.can_push_sock.frames
                self.assertEqual(len(frames), 5)
                # Gateway contract: decimal ID, hex payload (see test_can_handler).
                self.assertEqual({(int(i), bytes.fromhex(d.decode())) for _, i, d in frames},
                                 {(0x67A, bytes.fromhex(header) + bytes(6))})
                self.assertEqual(self.clock.naps, [0.02] * 5)

    def test_cycle_goes_stock_performance_competition_and_wraps_on_7316(self):
        manager = self.manager()
        self.telemetry(manager, ('CAN_6DA', 'd040000000000000'))   # 7316 page 0, Stock
        sent = []
        for _ in range(4):
            manager.can_push_sock.frames.clear()
            manager.cycle_mode()
            sent.append(manager.can_push_sock.frames[0][2].decode()[:4])
        self.assertEqual(sent, ['a55a', '3cc3', '5aa5', 'a55a'])

    def test_flashing_mode_blocks_bursts_but_keeps_the_request(self):
        manager = self.manager()
        traffic.set_flashing_mode(True)
        status = manager.set_mode(2)
        self.assertEqual(manager.can_push_sock.frames, [])
        self.assertEqual(status['desired_mode'], 2)

    def test_incomplete_flash_marker_inhibits_from_startup(self):
        (self.home / '.hudiy').mkdir()
        (self.home / '.hudiy' / 'haldex_recovery_required.json').write_text('{}')
        manager = self.manager()
        self.assertTrue(manager.inhibited)
        manager.send_mode_burst(1)
        self.assertEqual(manager.can_push_sock.frames, [])


class TelemetryStatusTests(HaldexTestCase):
    def test_mode_reported_by_0x6da_drives_status(self):
        manager = self.manager()
        manager.desired_mode = 1
        manager.last_switch_time = self.clock.now - 10
        # 7316 frame: byte0 0xD0|page, byte1 mode bits 1:0 = 1, token bit 6.
        self.telemetry(manager, ('CAN_6DA', 'd041100020003000'),
                       ('CAN_679', '12008806370b371b'))
        status = manager.get_status()
        self.assertEqual((status['active_mode'], status['image_modes']), (1, 3))
        self.assertEqual(status['status'], 'synced')
        self.assertTrue(status['token_ok'])
        self.assertEqual(status['available_modes'], [0, 1, 2])
        self.assertEqual(status['b08_torque_nm'], round(0x1B37 * 0.0625, 2))
        self.clock.now += 2.1
        self.assertEqual(manager.get_status()['status'], 'offline')

    def test_bad_frames_do_not_change_the_reported_mode(self):
        manager = self.manager()
        self.telemetry(manager, ('CAN_6DA', 'd041100020003000'))
        self.telemetry(manager,
                       ('CAN_6DA', 'd742000000000000'),   # 7316 has no page 7
                       ('CAN_6DA', '1002000000000000'),   # pre-7316 layout
                       ('CAN_6DA', 'd042'),               # short
                       ('CAN_6DA', 'zz'))
        self.assertEqual(manager.get_status()['active_mode'], 1)

    def test_unsupported_saved_mode_is_reported_not_spammed(self):
        manager = self.manager()
        manager.desired_mode = 3   # Snow Drift saved from a five-mode image
        self.telemetry(manager, ('CAN_6DA', 'd040000000000000'))
        self.assertEqual(manager.get_status()['status'], 'unsupported')
        with self.assertRaisesRegex(ValueError, 'five-mode'):
            manager.set_mode(4)


class ReconciliationTests(HaldexTestCase):
    def reconcile(self, manager, seconds):
        self.clock.loop_sleeps = int(seconds / 0.5)
        manager.running = True
        manager._reconciliation_worker()

    def bursts(self, manager):
        frames = manager.can_push_sock.frames
        return [frames[i] for i in range(0, len(frames), 5)]

    def test_mismatch_is_resent_at_most_once_per_second(self):
        manager = self.manager()
        manager.desired_mode = 2
        manager.last_switch_time = self.clock.now
        self.telemetry(manager, ('CAN_6DA', 'd040000000000000'))   # ECU says Stock
        self.reconcile(manager, 5.0)
        bursts = self.bursts(manager)
        self.assertGreaterEqual(len(bursts), 4)
        self.assertLessEqual(len(bursts), 5)
        times = [t for t, _, _ in bursts]
        self.assertTrue(all(b - a >= 1.0 for a, b in zip(times, times[1:])), times)
        self.assertEqual({d[:4] for _, _, d in bursts}, {b'3cc3'})

    def test_no_resend_when_synced_inhibited_or_unsupported(self):
        manager = self.manager()
        manager.desired_mode = 0
        self.telemetry(manager, ('CAN_6DA', 'd040000000000000'))
        self.reconcile(manager, 3.0)
        self.assertEqual(manager.can_push_sock.frames, [])

        manager.desired_mode = 1
        manager.inhibited = True
        self.reconcile(manager, 3.0)
        self.assertEqual(manager.can_push_sock.frames, [])

        manager.inhibited = False
        manager.desired_mode = 3   # not available on a 7316
        self.reconcile(manager, 3.0)
        self.assertEqual(manager.can_push_sock.frames, [])

    def test_no_resend_before_any_telemetry(self):
        manager = self.manager()
        manager.desired_mode = 2
        self.reconcile(manager, 3.0)
        self.assertEqual(manager.can_push_sock.frames, [])


class PersistenceTests(HaldexTestCase):
    def test_last_mode_restored_when_no_default(self):
        self.manager().set_mode(2)
        self.assertEqual(self.manager().desired_mode, 2)

    def test_configured_default_wins_and_is_not_overwritten(self):
        self.manager().set_mode(2)
        self.write_config({'default_mode': 0})
        manager = self.manager()
        self.assertEqual(manager.desired_mode, 0)
        manager.set_mode(1)
        self.write_config({})
        self.assertEqual(self.manager().desired_mode, 2)

    def test_corrupt_or_invalid_saved_mode_falls_back_to_stock(self):
        path = self.home / '.hudiy' / 'haldex_mode.json'
        path.parent.mkdir()
        for content in ('{"saved_mode": 9}', '{not json', '{"saved_mode": "2"}'):
            with self.subTest(content=content):
                path.write_text(content)
                self.assertEqual(self.manager().desired_mode, 0)

    def test_startup_burst_uses_restored_mode(self):
        self.manager().set_mode(1)
        manager = self.manager()
        push, pub = CapturePush(self.clock), CapturePush(self.clock)
        with patch.object(HM.threading, 'Thread'), \
                patch.object(manager, 'context', Mock(socket=Mock(side_effect=[push, pub]))):
            manager.start()
        pushed = push.frames
        self.assertEqual(len(pushed), 5)
        self.assertEqual(pushed[0][2], b'a55a000000000000')


if __name__ == '__main__':
    unittest.main()
