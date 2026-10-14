"""Haldex mode select over KWP, reconciliation and persistence.

Runs the real rns-e_can/haldex_manager.py (not AST extracts) with a fake clock
and a fake ECU in place of the TP2 worker. Protocol ground truth:
HaldexRE artifacts/7716/README.md - `3B F0 b0 b1` sets, `3B F0` queries, the
answer is `7B F0 applied a48 candidate reason`, and a pre-7716 image answers the
query with `7F 3B 12`. The ECU applies a set on its 10th 20 ms tick.
"""
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
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

CODEWORDS = {0: '5aa5', 1: 'a55a', 2: '3cc3', 3: '6996', 4: '9669'}


class FakeTime:
    def __init__(self):
        self.now = 50_000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeEcu:
    """A 7716 image's mode latch, debounce and query, as seen through the worker."""

    def __init__(self, clock, supported=True):
        self.clock = clock
        self.supported = supported
        self.applied = 0
        self.candidate = 0xFF
        self.reason = 6
        self.set_at = None
        self.accepts = True
        self.link_down = False
        self.requests = []

    def reset(self):
        self.applied, self.candidate, self.reason, self.set_at = 0, 0xFF, 6, None

    def _tick(self):
        if self.set_at is not None and self.clock.now - self.set_at >= 0.2:
            self.applied, self.reason, self.set_at = self.candidate, 3, None

    def kwp(self, payload):
        self.requests.append((self.clock.now, payload.hex()))
        if self.link_down:
            raise RuntimeError('No answer from module 0x0A')
        if not self.supported:
            return bytes.fromhex('7f3b12') if len(payload) == 2 else bytes.fromhex('7b9a')
        self._tick()
        answer = bytes((0x7B, 0xF0, self.applied, self.applied, self.candidate, self.reason))
        if len(payload) == 4:
            mode = {v: k for k, v in CODEWORDS.items()}[payload[2:].hex()]
            if self.accepts and mode != self.applied:
                self.candidate, self.reason, self.set_at = mode, 1, self.clock.now
            elif self.accepts:
                self.candidate = mode
        return answer

    def sets(self):
        return [p[4:] for _, p in self.requests if len(p) == 8]


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

    def manager(self, ecu=None):
        manager = HM.HaldexManager(str(self.config_path))
        self.addCleanup(manager.context.term)
        self.ecu = ecu or FakeEcu(self.clock)
        manager._kwp = self.ecu.kwp
        return manager

    def drive(self, manager, seconds, step=0.05):
        for _ in range(int(seconds / step)):
            manager._mode_step()
            self.clock.now += step

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


class ModeSelectTests(HaldexTestCase):
    def test_queries_before_the_first_set_and_confirms_it(self):
        self.manager().set_mode(2)
        manager = self.manager()        # restored Competition
        self.drive(manager, 1.0)
        payloads = [p for _, p in self.ecu.requests]
        self.assertEqual(payloads[:3], ['3bf0', '3bf03cc3', '3bf0'])
        (t_set, _), (t_confirm, _) = self.ecu.requests[1:3]
        self.assertAlmostEqual(t_confirm - t_set, 0.3, delta=0.06)
        status = manager.get_status()
        self.assertEqual((status['status'], status['active_mode']), ('synced', 2))
        self.assertEqual(status['ecu']['reason'], 3)
        self.assertEqual((status['last_set']['mode'], status['last_set']['time']), (2, t_set))
        self.assertEqual(len(payloads), 3)   # quiet until the next reconcile

    def test_every_mode_codeword(self):
        manager = self.manager()
        for mode in (1, 2, 3, 4, 0):
            word = CODEWORDS[mode]
            with self.subTest(mode=mode):
                manager.set_mode(mode)
                self.drive(manager, 1.0)
                self.assertEqual(self.ecu.sets()[-1], word)
                self.assertEqual(manager.get_status()['status'], 'synced')

    def test_stock_on_a_fresh_ecu_needs_no_set(self):
        manager = self.manager()
        self.drive(manager, 1.0)
        self.assertEqual(self.ecu.sets(), [])
        self.assertEqual(manager.get_status()['status'], 'synced')

    def test_image_without_the_handler_never_gets_a_set(self):
        manager = self.manager(FakeEcu(self.clock, supported=False))
        manager.set_mode(1)
        self.drive(manager, 25.0)
        self.assertEqual(self.ecu.sets(), [])
        self.assertEqual({p for _, p in self.ecu.requests}, {'3bf0'})
        self.assertEqual(len(self.ecu.requests), 3)   # once per reconcile interval
        self.assertEqual(manager.get_status()['status'], 'unsupported')

    def test_cycle_covers_all_five_and_wraps(self):
        manager = self.manager()
        self.assertEqual([manager.cycle_mode()['desired_mode'] for _ in range(6)],
                         [1, 2, 3, 4, 0, 1])

    def test_set_mode_returns_without_waiting_for_the_ecu(self):
        manager = self.manager()
        status = manager.set_mode(3)
        self.assertEqual(self.ecu.requests, [])
        self.assertEqual(status['desired_mode'], 3)


class ReconciliationTests(HaldexTestCase):
    def test_ecu_reset_is_detected_and_resent(self):
        manager = self.manager()
        manager.set_mode(2)
        self.drive(manager, 1.0)
        self.ecu.reset()                       # key cycle / ECU reset: back to Stock
        self.drive(manager, HM.RECONCILE_INTERVAL_S + 1.0)
        self.assertEqual(self.ecu.sets(), ['3cc3', '3cc3'])
        self.assertEqual(manager.get_status()['status'], 'synced')

    def test_ecu_that_never_applies_is_reported_and_resent_once_per_interval(self):
        manager = self.manager()
        self.ecu.accepts = False
        manager.set_mode(1)
        self.drive(manager, 2.0)
        self.assertEqual(len(self.ecu.sets()), HM.MAX_QUICK_SETS)
        self.assertEqual(manager.get_status()['status'], 'failed')
        self.drive(manager, 2 * HM.RECONCILE_INTERVAL_S)
        self.assertEqual(len(self.ecu.sets()), HM.MAX_QUICK_SETS + 2)
        self.ecu.accepts = True
        self.drive(manager, HM.RECONCILE_INTERVAL_S + 1.0)
        self.assertEqual(manager.get_status()['status'], 'synced')

    def test_link_loss_reports_offline_and_reprobes(self):
        manager = self.manager()
        manager.set_mode(4)
        self.drive(manager, 1.0)
        self.ecu.link_down = True
        self.drive(manager, HM.RECONCILE_INTERVAL_S + 6.0)
        status = manager.get_status()
        self.assertEqual(status['status'], 'offline')
        self.assertIn('No answer', status['message'])
        attempts = [t for t, _ in self.ecu.requests[3:]]
        self.assertTrue(all(b - a >= HM.LINK_RETRY_S - 0.01 for a, b in zip(attempts, attempts[1:])))
        self.ecu.link_down = False
        self.ecu.reset()
        before = len(self.ecu.requests)
        self.drive(manager, 3.0)
        self.assertEqual([p for _, p in self.ecu.requests[before:before + 2]], ['3bf0', '3bf09669'])
        self.assertEqual(manager.get_status()['status'], 'synced')

    def test_nothing_is_sent_while_inhibited_or_flashing(self):
        manager = self.manager()
        manager.inhibited = True
        manager.set_mode(2)
        self.drive(manager, 2.0)
        manager.inhibited = False
        traffic.set_flashing_mode(True)
        self.addCleanup(traffic.set_flashing_mode, False)
        self.drive(manager, 2.0)
        self.assertEqual(self.ecu.requests, [])
        self.assertEqual(manager.get_status()['desired_mode'], 2)

    def test_incomplete_flash_marker_inhibits_from_startup(self):
        (self.home / '.hudiy').mkdir()
        (self.home / '.hudiy' / 'haldex_recovery_required.json').write_text('{}')
        manager = self.manager()
        self.assertTrue(manager.inhibited)
        self.drive(manager, 1.0)
        self.assertEqual(self.ecu.requests, [])

    def test_release_after_a_flash_reprobes_and_resends(self):
        manager = self.manager()
        manager.set_mode(1)
        self.drive(manager, 1.0)
        token = 'b' * 32
        with patch.object(manager, '_drain_can_queue'):
            manager.quiesce(token)
        self.ecu.reset()                       # the flash reset the ECU
        self.drive(manager, 1.0)
        sent = len(self.ecu.requests)
        manager.release(token)
        self.drive(manager, 1.0)
        self.assertEqual([p for _, p in self.ecu.requests[sent:sent + 2]], ['3bf0', '3bf0a55a'])

    def test_inflight_request_finishes_before_quiesce_acknowledges(self):
        manager = self.manager()
        started, finish, acknowledged = threading.Event(), threading.Event(), threading.Event()
        sent = []

        def kwp(payload):
            started.set()
            self.assertTrue(finish.wait(2))
            sent.append(payload)
            return bytes.fromhex('7bf00000ff06')
        manager._kwp = kwp
        worker = threading.Thread(target=manager._mode_step)
        worker.start()
        self.assertTrue(started.wait(2))
        with patch.object(manager, '_drain_can_queue'):
            pause = threading.Thread(target=lambda: (manager.quiesce('a' * 32), acknowledged.set()))
            pause.start()
            self.assertFalse(acknowledged.wait(0.05))
            finish.set()
            worker.join(2)
            pause.join(2)
        self.assertTrue(acknowledged.is_set())
        manager.next_action = 0
        manager._mode_step()
        self.assertEqual(len(sent), 1)


class TelemetryStatusTests(HaldexTestCase):
    def test_telemetry_fills_signals_but_not_the_mode(self):
        manager = self.manager()
        self.telemetry(manager, ('CAN_6DA', 'e8c1100020003000'),
                       ('CAN_679', '12008806370b371b'))
        status = manager.get_status()
        self.assertIsNone(status['active_mode'])
        self.assertEqual(status['status'], 'offline')
        self.assertTrue(status['token_ok'])
        self.assertEqual(status['b08_torque_nm'], round(0x1B37 * 0.0625, 2))
        self.assertEqual(status['available_modes'], [0, 1, 2, 3, 4])


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


if __name__ == '__main__':
    unittest.main()
