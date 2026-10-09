import argparse
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import inspect_measuring_groups as inspector


class InspectorParsingAndAnalysisTests(unittest.TestCase):
    def test_explicit_targets_merge_decimal_and_hex(self):
        targets = [inspector.parse_target("01:011,118,118"),
                   inspector.parse_target("0x01:0x73"), inspector.parse_target("0x22:1,3")]
        self.assertEqual(inspector.merge_targets(targets), {1: [11, 115, 118], 34: [1, 3]})
        for invalid in ["1", "1:", "0:1", "256:1", "1:256", "1:-1", "1:1,", "1:*"]:
            with self.subTest(invalid=invalid), self.assertRaises(argparse.ArgumentTypeError):
                inspector.parse_target(invalid)

    def test_defaults_and_opt_in_unlimited_polling(self):
        args = inspector.argument_parser().parse_args(["--target", "1:11"])
        self.assertEqual(args.duration, 30)
        self.assertEqual(args.rate, 2)
        self.assertFalse(args.as_fast)
        normal = inspector.sync_message("mine", 1, [11, 118])
        self.assertEqual(normal["groups"], [])
        self.assertEqual(normal["group_periods_ms"], {"11": 500, "118": 500})
        unlimited = inspector.sync_message("mine", 1, [11], as_fast=True)
        self.assertEqual(unlimited["groups"], [11])
        self.assertEqual(unlimited["group_periods_ms"], {})
        for invalid in ["0", "-1", "nan", "inf"]:
            with self.subTest(invalid=invalid), self.assertRaises(argparse.ArgumentTypeError):
                inspector.positive_number(invalid)

    def test_availability_requires_explicit_worker_confirmation(self):
        ready = {"status": "ok", "available": True, "enabled": True, "running": True}
        self.assertTrue(inspector.diagnostic_available(ready))
        for change in [{"available": False}, {"enabled": False}, {"running": False},
                       {"ignition": False}, {"diagnostic_owner": "flash"}, {"flashing": True},
                       {"status": "error"}]:
            with self.subTest(change=change):
                self.assertFalse(inspector.diagnostic_available(dict(ready, **change)))
        self.assertFalse(inspector.diagnostic_available({"enabled": True, "running": True}))

    def test_eight_fields_and_raw_bytes_are_preserved_without_guessing(self):
        analysis = inspector.CaptureAnalysis({1: [11]})
        data = [{"value": index * .125, "unit": "V", "type": 6} for index in range(8)]
        payload = {"module": 1, "group": 11, "data": data, "raw_data_hex": "0632fa" * 8,
                   "acquisition_timestamp": 123.45, "request_duration_ms": 12.3,
                   "block_count": 8, "trailing_bytes": 0, "complete": True}
        record = analysis.consume("HUDIY_DIAG", payload, 1, 124)
        self.assertEqual(record["data"], data)
        self.assertEqual(record["raw_data_hex"], payload["raw_data_hex"])
        self.assertEqual(record["acquisition_timestamp"], 123.45)
        self.assertEqual([field["block"] for field in record["fields"]], list(range(1, 9)))
        self.assertEqual(record["fields"][7]["label"], "Field 8")
        self.assertTrue(all(field["meaning_status"] == "unconfirmed" for field in record["fields"]))
        self.assertNotIn("block", payload["data"][0])

    def test_rates_and_percentiles_count_only_complete_selected_groups(self):
        analysis = inspector.CaptureAnalysis({1: [11, 118]})
        payload = {"module": 1, "group": 11, "data": [{"value": 1, "unit": "V", "type": 6}],
                   "complete": True}
        for received, duration in [(1, 10), (1.5, 20), (2, 30)]:
            analysis.consume("HUDIY_DIAG", dict(payload, request_duration_ms=duration), received, 100 + received)
        analysis.consume("HUDIY_DIAG", dict(payload, complete=False), 2.1, 102.1)
        analysis.consume("HUDIY_DIAG_OBSERVATION", {"module": 1, "group": 11, "error": "timeout"}, 2.2, 102.2)
        self.assertIsNone(analysis.consume("HUDIY_DIAG", dict(payload, group=3), 2.3, 102.3))
        self.assertIsNone(analysis.consume("HUDIY_DIAG", dict(payload, data=[None]), 2.3, 102.3))
        self.assertIsNone(analysis.consume("HUDIY_DIAG", dict(payload, module=[]), 2.3, 102.3))
        summary = analysis.summary(3)["groups"]
        self.assertEqual(summary[0]["successful_updates"], 3)
        self.assertEqual(summary[0]["achieved_hz"], 2)
        self.assertEqual(summary[0]["request_duration_mean_ms"], 20)
        self.assertEqual(summary[0]["request_duration_p95_ms"], 29)
        self.assertEqual(summary[0]["incomplete_updates"], 1)
        self.assertEqual(summary[0]["failure_observations"], 1)
        self.assertEqual(summary[1]["successful_updates"], 0)
        self.assertIsNone(summary[1]["achieved_hz"])


class InspectorCaptureLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.context = Mock()
        self.subscriber = Mock()
        self.context.socket.return_value = self.subscriber
        self.Again = type("Again", (Exception,), {})
        self.zmq = SimpleNamespace(Context=lambda: self.context, SUB=1, REQ=2, LINGER=3,
                                   RCVTIMEO=4, SNDTIMEO=5, Again=self.Again)
        self.args = SimpleNamespace(config="unused", command=None, stream=None, duration=30,
                                    rate=2, as_fast=False, output=None, quiet=True)
        self.ready = {"status": "ok", "available": True, "enabled": True, "running": True}

    def capture(self, request, targets=None):
        with patch.dict("sys.modules", {"zmq": self.zmq}), \
                patch.object(inspector, "load_addresses", return_value=("command", "stream")), \
                patch.object(inspector, "request", side_effect=request) as requests, \
                patch("sys.stdout", new_callable=io.StringIO), \
                patch("sys.stderr", new_callable=io.StringIO):
            result = inspector.capture(self.args, targets or {1: [11]})
        return result, [call.args[3] for call in requests.call_args_list]

    def test_disabled_worker_never_receives_sync(self):
        result, commands = self.capture(lambda *args: dict(self.ready, available=False))
        self.assertEqual(result, 1)
        self.assertEqual(commands, [{"cmd": "STATUS"}])
        self.context.socket.assert_not_called()
        self.context.term.assert_called_once()

    def test_partial_subscription_failure_releases_only_own_client(self):
        def request(*args):
            message = args[3]
            if message["cmd"] == "STATUS":
                return self.ready
            if message["module"] == 34 and message["group_periods_ms"]:
                raise TimeoutError("reply lost after acceptance")
            return {"status": "ok"}
        result, commands = self.capture(request, {1: [11], 34: [1]})
        self.assertEqual(result, 1)
        releases = [command for command in commands if command["cmd"] == "SYNC" and not command["group_periods_ms"]]
        self.assertEqual([release["module"] for release in releases], [1, 34])
        clients = {command["client_id"] for command in commands if command["cmd"] == "SYNC"}
        self.assertEqual(len(clients), 1)
        self.assertTrue(next(iter(clients)).startswith("group_inspector_"))
        self.assertTrue(all(command["cmd"] in ("STATUS", "SYNC") for command in commands))
        self.context.term.assert_called_once()

    def test_ndjson_retains_eight_fields_then_stops_on_pause(self):
        payload = {"module": 1, "group": 11, "data": [{"value": 12.5, "unit": "V", "type": 6}] * 8,
                   "raw_data_hex": "0632fa" * 8, "complete": True,
                   "acquisition_timestamp": 123, "request_duration_ms": 25}
        self.subscriber.recv_multipart.side_effect = [
            [b"HUDIY_DIAG", json.dumps(payload).encode()],
            [b"HUDIY_TP2_STATUS", json.dumps(dict(self.ready, available=False)).encode()]]
        with tempfile.TemporaryDirectory() as directory:
            self.args.output = str(Path(directory) / "capture.ndjson")
            result, commands = self.capture(lambda *args: self.ready)
            records = [json.loads(line) for line in Path(self.args.output).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(result, 1)
        group = next(record for record in records if record["record_type"] == "group")
        self.assertEqual(len(group["fields"]), 8)
        self.assertEqual(group["raw_data_hex"], payload["raw_data_hex"])
        self.assertEqual(records[-1]["groups"][0]["successful_updates"], 1)
        self.assertEqual(commands[-1]["group_periods_ms"], {})

    def test_five_second_heartbeats_and_final_release(self):
        self.args.duration = 11
        clock = SimpleNamespace(now=0)
        def receive():
            clock.now += 1
            raise self.Again()
        self.subscriber.recv_multipart.side_effect = receive
        with patch.object(inspector.time, "monotonic", side_effect=lambda: clock.now):
            result, commands = self.capture(lambda *args: self.ready)
        self.assertEqual(result, 0)
        syncs = [message for message in commands if message["cmd"] == "SYNC"]
        self.assertEqual(len(syncs), 4)  # Start, 5 s, 10 s, release.
        self.assertTrue(all(message["group_periods_ms"] == {"11": 500} for message in syncs[:-1]))
        self.assertEqual(syncs[-1]["groups"], [])
        self.assertEqual(syncs[-1]["group_periods_ms"], {})

    def test_interrupt_releases_subscriptions(self):
        self.subscriber.recv_multipart.side_effect = KeyboardInterrupt()
        result, commands = self.capture(lambda *args: self.ready)
        self.assertEqual(result, 130)
        self.assertEqual(commands[-1]["group_periods_ms"], {})
        self.subscriber.close.assert_called_once_with(linger=0)
        self.context.term.assert_called_once()

    def test_command_timeout_closes_socket_and_next_request_uses_fresh_socket(self):
        first, second = Mock(), Mock()
        first.recv_json.side_effect = TimeoutError("timeout")
        second.recv_json.return_value = self.ready
        self.context.socket.side_effect = [first, second]
        with self.assertRaises(TimeoutError):
            inspector.request(self.context, self.zmq, "command", {"cmd": "STATUS"})
        self.assertEqual(inspector.request(self.context, self.zmq, "command", {"cmd": "STATUS"}), self.ready)
        first.close.assert_called_once_with(linger=0)
        second.close.assert_called_once_with(linger=0)
        first.setsockopt.assert_any_call(self.zmq.SNDTIMEO, 2000)
        first.setsockopt.assert_any_call(self.zmq.RCVTIMEO, 2000)


if __name__ == "__main__":
    unittest.main()
