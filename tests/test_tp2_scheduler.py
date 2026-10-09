import unittest
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tp2.group_scheduler import GroupScheduler, parse_group_periods
from tp2 import tp2_coding


def load_offline_worker():
    """Replace only I/O imports; run the worker's real command/main-loop code."""
    class ContextTerminated(Exception):
        pass
    spec = importlib.util.spec_from_file_location(
        "offline_tp2_worker", Path(__file__).resolve().parents[1] / "tp2" / "tp2_worker.py")
    worker = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {
        "zmq": SimpleNamespace(ContextTerminated=ContextTerminated),
        "tp2_protocol": SimpleNamespace(TP2Protocol=lambda **kwargs: Mock(), TP2Error=RuntimeError),
        "tp2_coding": tp2_coding,
        "openpilot_receiver": SimpleNamespace(OpenpilotReceiver=Mock(),
            OPENPILOT_TRANSPORT_ENABLED=False, OPENPILOT_DISABLED_REASON="offline"),
    }):
        spec.loader.exec_module(worker)
    return worker


class GroupSchedulerTests(unittest.TestCase):
    def test_fastest_demand_wins_and_legacy_modes_survive(self):
        scheduler = GroupScheduler()
        scheduler.configure([3], [4, 5], {3: 500, 4: 2000, 6: 500}, 10)
        self.assertEqual(scheduler.periods, {3: 0, 4: 2000, 5: 60000, 6: 500})

    def test_normal_polling_does_not_starve_timed_groups(self):
        scheduler = GroupScheduler()
        scheduler.configure([1, 2], [], {3: 500, 4: 500}, 0)
        selected = []
        for index in range(4):
            now = index * 0.01
            group = scheduler.select(now)
            selected.append(group)
            scheduler.started(group, now)
            scheduler.completed(group, now + .001, 100 + now, 1, True)
        self.assertEqual(selected, [1, 2, 3, 4])

    def test_five_groups_can_each_get_two_hz_when_capacity_permits(self):
        scheduler = GroupScheduler()
        scheduler.configure([], [], {group: 500 for group in range(5)}, 0)
        counts = {group: 0 for group in range(5)}
        for step in range(200):
            now = step / 100
            group = scheduler.select(now)
            if group is not None:
                counts[group] += 1
                scheduler.started(group, now)
                scheduler.completed(group, now + .001, 100 + now, 1, True)
        self.assertEqual(counts, dict.fromkeys(range(5), 4))

    def test_refresh_does_not_reset_deadlines_and_reduced_rate_waits(self):
        scheduler = GroupScheduler()
        scheduler.configure([], [], {3: 500}, 0)
        scheduler.started(3, 0)
        scheduler.configure([], [], {3: 500}, .2)
        self.assertIsNone(scheduler.select(.2))
        scheduler.configure([], [], {3: 2000}, .3)
        self.assertIsNone(scheduler.select(.5))
        self.assertEqual(scheduler.select(2), 3)

    def test_no_catchup_burst_after_slow_request(self):
        scheduler = GroupScheduler()
        scheduler.configure([], [], {3: 500}, 0)
        scheduler.started(3, 0)
        scheduler.completed(3, 2, 102, 2000, True)
        self.assertIsNone(scheduler.select(2))
        self.assertEqual(scheduler.select(2.5), 3)
        self.assertTrue(scheduler.snapshot(2)["3"]["overrun"])

    def test_low_priority_interval_and_cooldown_exclusion(self):
        scheduler = GroupScheduler()
        scheduler.configure([], [1, 2], {}, 0)
        self.assertEqual(scheduler.select(0, blocked=[1]), 2)
        scheduler.started(2, 0)
        scheduler.completed(2, .1, 100, 100, True)
        self.assertIsNone(scheduler.select(59, blocked=[1]))
        self.assertEqual(scheduler.select(60, blocked=[1]), 2)

    def test_removing_all_subscriptions_removes_due_work(self):
        scheduler = GroupScheduler()
        scheduler.configure([], [], {3: 500}, 0)
        scheduler.configure([], [], {}, .1)
        self.assertIsNone(scheduler.select(100))
        self.assertEqual(scheduler.snapshot(100), {})

    def test_peeking_does_not_change_fair_selection(self):
        scheduler = GroupScheduler()
        scheduler.configure([1, 2, 3], [], {}, 0)
        for expected in [1, 2, 3, 1]:
            self.assertEqual(scheduler.select(0, advance=False), expected)
            self.assertEqual(scheduler.select(0), expected)

    def test_observed_rate_and_receipt_timestamp(self):
        scheduler = GroupScheduler()
        scheduler.configure([], [], {3: 500}, 0)
        for now in [0, .5, 1]:
            scheduler.started(3, now)
            scheduler.completed(3, now + .01, 100 + now, 10, True)
        info = scheduler.snapshot(1.01)["3"]
        self.assertEqual(info["observed_count"], 3)
        self.assertEqual(info["last_successful_acquisition_timestamp"], 101)
        self.assertAlmostEqual(info["achieved_hz"], 2)
        self.assertFalse(info["overrun"])
        self.assertTrue(scheduler.snapshot(3)["3"]["overrun"])
        scheduler.completed(3, 3, 103, 20, False)
        self.assertEqual(scheduler.snapshot(3)["3"]["observed_count"], 3)

    def test_period_wire_validation(self):
        self.assertEqual(parse_group_periods({"3": 500}), {3: 500})
        for bad in [[], {"3": True}, {"3": 0}, {"3": -1}, {"3": float("nan")},
                    {"3": "500"}, {"256": 500}]:
            with self.subTest(bad=bad), self.assertRaises((ValueError, TypeError)):
                parse_group_periods(bad)


class WorkerSchedulingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worker = load_offline_worker()

    def setUp(self):
        flashing = patch.object(self.worker, "flashing_mode_enabled", return_value=False)
        flashing.start()
        self.addCleanup(flashing.stop)
        self.service = self.worker.TP2Service.__new__(self.worker.TP2Service)
        self.service.lock = threading.Lock()
        self.service.sessions = {}
        self.service._tester_id_pool = list(range(0x300, 0x307))
        self.service.can_interface = "offline"
        self.service.shutdown_event = threading.Event()
        self.service.diagnostic_owner = None
        self.service.quiescent = threading.Event()
        self.service.running = self.service.user_enabled = True
        self.service.last_ignition_state = True
        self.service.config = {}
        self.service.pub = Mock()

    def commands(self, *messages):
        rep = Mock()
        rep.recv_json.side_effect = [*messages, self.worker.zmq.ContextTerminated()]
        self.service.rep = rep
        self.service.command_thread_func()
        return [call.args[0] for call in rep.send_json.call_args_list]

    def test_sync_merges_clients_and_expires_period_only_lease(self):
        with patch.object(self.worker.time, "monotonic", return_value=100):
            results = self.commands(
                {"cmd": "SYNC", "client_id": "broker", "module": 1,
                 "group_periods_ms": {"3": 500, "4": 1000}},
                {"cmd": "SYNC", "client_id": "another", "module": 1,
                 "group_periods_ms": {"3": 250}},
                {"cmd": "STATUS"})
        session = self.service.sessions[1]
        self.assertTrue(session["active"])
        self.assertEqual(session["scheduler"].periods, {3: 250, 4: 1000})
        self.assertEqual(results[-1]["sessions"][0]["group_stats"]["3"]["requested_period_ms"], 250)
        self.assertTrue(results[-1]["available"])
        with patch.object(self.worker.time, "monotonic", return_value=115):
            self.service._rebuild_groups_list(session)
        self.assertFalse(session["active"])
        self.assertEqual(session["client_subs"], {})

    def test_status_exposes_owner_and_flashing_pause(self):
        self.service.diagnostic_owner = "flash-owner"
        with patch.object(self.worker, "flashing_mode_enabled", return_value=True):
            result = self.commands({"cmd": "STATUS"})[0]
            self.service._publish_status()
        self.assertFalse(result["available"])
        self.assertEqual(result["diagnostic_owner"], "flash-owner")
        self.assertTrue(result["flashing"])
        published = json.loads(self.service.pub.send_multipart.call_args.args[0][1])
        self.assertFalse(published["available"])

    def run_one_iteration(self):
        # Stop after the main loop's first iteration; command thread is inert.
        def stop_after_ignition():
            self.service.shutdown_event.set()
        self.service.process_ignition = stop_after_ignition
        with patch.object(self.worker.threading, "Thread"), patch.object(self.worker.time, "sleep"):
            self.service.run()

    def test_inhibited_main_loop_never_polls_and_acknowledges_owner(self):
        with patch.object(self.worker.time, "monotonic", return_value=100):
            self.commands({"cmd": "SYNC", "client_id": "broker", "module": 1,
                           "group_periods_ms": {"3": 500}})
        proto = self.service.sessions[1]["protocol"]
        self.service.diagnostic_owner = "flasher"
        self.run_one_iteration()
        proto.send_kvp_request.assert_not_called()
        self.assertTrue(self.service.quiescent.is_set())

    def test_period_only_main_loop_publishes_complete_eight_field_response(self):
        with patch.object(self.worker.time, "monotonic", return_value=100):
            self.commands({"cmd": "SYNC", "client_id": "broker", "module": 1,
                           "group_periods_ms": {"11": 500}})
            session = self.service.sessions[1]
            session["connected"] = True
            session["protocol"].send_kvp_request.return_value = [0x61, 11] + [6, 50, 250] * 8
            with patch.object(self.worker, "flashing_mode_enabled", return_value=False):
                self.run_one_iteration()
        session["protocol"].send_kvp_request.assert_called_once_with([0x21, 11])
        topic, encoded = self.service.pub.send_multipart.call_args.args[0]
        self.assertEqual(topic, b"HUDIY_DIAG")
        payload = json.loads(encoded)
        self.assertEqual(payload["block_count"], 8)
        self.assertTrue(payload["complete"])

    def test_dtc_read_retains_priority_over_due_groups(self):
        with patch.object(self.worker.time, "monotonic", return_value=100):
            self.commands({"cmd": "SYNC", "client_id": "broker", "module": 1,
                           "group_periods_ms": {"3": 500}})
            session = self.service.sessions[1]
            session["connected"] = True
            session["pending_dtc_req"] = True
            session["protocol"].send_kvp_request.side_effect = [[0x58, 0], [0x61, 3, 6, 50, 250]]
            self.run_one_iteration()
        requests = [call.args[0] for call in session["protocol"].send_kvp_request.call_args_list]
        self.assertEqual(requests, [[0x18, 0x02, 0xFF, 0x00], [0x21, 3]])

    def test_disabled_or_flashing_main_loop_never_polls(self):
        for enabled, flashing in [(False, False), (True, True)]:
            with self.subTest(enabled=enabled, flashing=flashing):
                self.service.shutdown_event.clear()
                self.service.running = enabled
                with patch.object(self.worker.time, "monotonic", return_value=100):
                    self.commands({"cmd": "SYNC", "client_id": "broker", "module": 1,
                                   "group_periods_ms": {"3": 500}})
                proto = self.service.sessions[1]["protocol"]
                proto.reset_mock()
                with patch.object(self.worker, "flashing_mode_enabled", return_value=flashing):
                    self.run_one_iteration()
                proto.send_kvp_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
