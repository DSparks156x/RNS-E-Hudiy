#!/usr/bin/env python3
"""Capture explicitly selected TP2 groups, including unconfirmed extra fields.

Importing this module does not open sockets. The CLI subscribes through the
existing worker and never enables diagnostics or acquires diagnostic ownership.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics
import sys
import time
import uuid


DEFAULT_COMMAND = "ipc:///run/rnse_control/tp2_cmd.ipc"
DEFAULT_STREAM = "ipc:///run/rnse_control/tp2_stream.ipc"
HEARTBEAT_SECONDS = 5.0


def positive_number(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("Must be a positive finite number")
    return value


def parse_target(value):
    """MODULE:GROUP,GROUP; decimal and explicit 0x hexadecimal are supported."""
    def number(text):
        text = text.strip()
        return int(text, 16 if text.lower().startswith("0x") else 10)
    try:
        module_text, groups_text = value.split(":")
        module = number(module_text)
        groups = sorted({number(group) for group in groups_text.split(",")})
        if not 1 <= module <= 255 or not groups or any(not 0 <= group <= 255 for group in groups):
            raise ValueError()
        return module, groups
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Expected MODULE:GROUP,GROUP; module 1..255, groups 0..255") from None


def merge_targets(targets):
    merged = {}
    for module, groups in targets:
        merged.setdefault(module, set()).update(groups)
    return {module: sorted(groups) for module, groups in sorted(merged.items())}


def diagnostic_available(status):
    """Fail closed when the worker does not explicitly report availability."""
    return (status.get("status", "ok") == "ok" and status.get("available") is True
            and status.get("enabled") is not False and status.get("running") is not False
            and status.get("ignition") is not False and not status.get("diagnostic_owner")
            and not status.get("flashing"))


def sync_message(client_id, module, groups, rate_hz=2.0, as_fast=False):
    return {"cmd": "SYNC", "client_id": client_id, "module": module,
            "groups": list(groups) if as_fast else [], "low_priority_groups": [],
            "group_periods_ms": {} if as_fast else {str(group): 1000 / rate_hz for group in groups}}


def describe_fields(data):
    # A decoded unit/formula does not establish a field's semantic meaning.
    # Keep every field, including fields 5..8 or beyond, explicitly unconfirmed.
    return [dict(field, block=index, label=f"Field {index}", meaning_status="unconfirmed")
            for index, field in enumerate(data, 1)]


def percentile(values, percentile_value):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * percentile_value / 100
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


class CaptureAnalysis:
    """Compute rates from unsmoothed successful arrivals; retain failure counts."""
    def __init__(self, targets):
        self.targets = {(module, group) for module, groups in targets.items() for group in groups}
        self.groups = {key: {"success_times": [], "durations": [], "field_counts": Counter(),
                             "failures": 0, "incomplete": 0} for key in self.targets}

    def consume(self, topic, payload, received_monotonic, received_timestamp):
        key = (payload.get("module"), payload.get("group"))
        if any(not isinstance(part, int) or isinstance(part, bool) for part in key):
            return None
        if key not in self.targets:
            return None
        stat = self.groups[key]
        record = dict(payload, topic=topic, received_timestamp=received_timestamp,
                      received_monotonic=received_monotonic)
        if topic == "HUDIY_DIAG_OBSERVATION":
            record["record_type"] = "failure"
            stat["failures"] += 1
        elif (topic == "HUDIY_DIAG" and isinstance(payload.get("data"), list)
              and all(isinstance(field, dict) for field in payload["data"])):
            record["record_type"] = "group"
            record["fields"] = describe_fields(payload["data"])
            stat["field_counts"][len(payload["data"])] += 1
            if payload.get("complete") is True:
                stat["success_times"].append(received_monotonic)
                duration = payload.get("request_duration_ms")
                if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration >= 0:
                    stat["durations"].append(duration)
            else:
                stat["incomplete"] += 1
        else:
            return None
        return record

    def summary(self, elapsed_seconds):
        groups = []
        for (module, group), stat in sorted(self.groups.items()):
            times = stat["success_times"]
            span = times[-1] - times[0] if len(times) > 1 else 0
            groups.append({"module": module, "group": group, "successful_updates": len(times),
                "achieved_hz": (len(times) - 1) / span if span > 0 else None,
                "updates_per_second_over_capture": len(times) / elapsed_seconds if elapsed_seconds > 0 else None,
                "request_duration_mean_ms": statistics.mean(stat["durations"]) if stat["durations"] else None,
                "request_duration_p95_ms": percentile(stat["durations"], 95),
                "observed_field_counts": dict(sorted(stat["field_counts"].items())),
                "failure_observations": stat["failures"], "incomplete_updates": stat["incomplete"]})
        return {"record_type": "summary", "elapsed_seconds": elapsed_seconds, "groups": groups}


def load_addresses(config_path):
    with Path(config_path).open(encoding="utf-8") as source:
        config = json.load(source)
    addresses = config.get("interfaces", {}).get("zmq", {}) or config.get("zmq", {})
    return addresses.get("tp2_command", DEFAULT_COMMAND), addresses.get("tp2_stream", DEFAULT_STREAM)


def request(context, zmq, address, message, timeout_ms=2000):
    # Fresh socket per command avoids a REQ socket stuck awaiting a timed-out reply.
    socket = context.socket(zmq.REQ)
    try:
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
        socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        socket.connect(address)
        socket.send_json(message)
        reply = socket.recv_json()
        if reply.get("status") != "ok":
            raise RuntimeError(reply.get("message", "TP2 command rejected"))
        return reply
    finally:
        socket.close(linger=0)


def capture(args, targets):
    import zmq  # Runtime-only dependency; parsing/analysis/tests are offlineable.
    command, stream = load_addresses(args.config)
    command, stream = args.command or command, args.stream or stream
    client_id = f"group_inspector_{uuid.uuid4().hex}"
    context = zmq.Context()
    subscribed_modules = set()
    subscriber = None
    output = None
    analysis = CaptureAnalysis(targets)
    started = time.monotonic()
    exit_code = 0

    def emit(record):
        if output is not None:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()

    try:
        status = request(context, zmq, command, {"cmd": "STATUS"})
        if not diagnostic_available(status):
            raise RuntimeError("Diagnostics unavailable or paused; enable/resume them separately before capturing")
        subscriber = context.socket(zmq.SUB)
        subscriber.setsockopt(zmq.LINGER, 0)
        subscriber.setsockopt(zmq.RCVTIMEO, 250)
        subscriber.subscribe(b"HUDIY_DIAG")
        subscriber.subscribe(b"HUDIY_TP2_STATUS")
        subscriber.connect(stream)
        if args.output:
            output = Path(args.output).open("w", encoding="utf-8")
        emit({"record_type": "capture", "client_id": client_id, "targets": targets,
              "rate_hz": None if args.as_fast else args.rate, "as_fast": args.as_fast,
              "started_timestamp": time.time(), "initial_status": status})

        def sync_all():
            for module, groups in targets.items():
                # A timeout may occur after the worker accepted the request.
                subscribed_modules.add(module)
                request(context, zmq, command, sync_message(client_id, module, groups, args.rate, args.as_fast))

        sync_all()
        started = time.monotonic()
        deadline, heartbeat = started + args.duration, started + HEARTBEAT_SECONDS
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= heartbeat:
                status = request(context, zmq, command, {"cmd": "STATUS"})
                if not diagnostic_available(status):
                    raise RuntimeError("Diagnostics became unavailable or paused; stopping capture")
                sync_all()
                heartbeat = time.monotonic() + HEARTBEAT_SECONDS
            try:
                parts = subscriber.recv_multipart()
            except zmq.Again:
                continue
            if len(parts) != 2:
                continue
            topic = parts[0].decode("ascii", errors="replace")
            try:
                payload = json.loads(parts[1])
                if not isinstance(payload, dict):
                    continue
            except (ValueError, UnicodeDecodeError):
                continue
            if topic == "HUDIY_TP2_STATUS":
                if not diagnostic_available(payload):
                    raise RuntimeError("Diagnostics became unavailable or paused; stopping capture")
                continue
            record = analysis.consume(topic, payload, time.monotonic(), time.time())
            if record is not None:
                emit(record)
                if not args.quiet:
                    print(json.dumps(record, ensure_ascii=False))
    except KeyboardInterrupt:
        exit_code = 130
    except Exception as error:
        print(f"Capture stopped: {error}", file=sys.stderr)
        emit({"record_type": "capture_error", "error": str(error), "timestamp": time.time()})
        exit_code = 1
    finally:
        try:
            summary = analysis.summary(max(0, time.monotonic() - started))
            emit(summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        finally:
            # Release leases even when writing the report/output fails.
            try:
                for module in sorted(subscribed_modules):
                    try:
                        request(context, zmq, command, sync_message(client_id, module, []))
                    except Exception as error:
                        print(f"Could not release own module {module} lease: {error}; expires after 15 seconds", file=sys.stderr)
            finally:
                if subscriber is not None:
                    subscriber.close(linger=0)
                context.term()
                if output is not None:
                    output.close()
    return exit_code


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", type=parse_target, required=True,
                        help="Repeatable MODULE:GROUP,GROUP, e.g. 01:11,118 --target 0x22:1,3")
    parser.add_argument("--duration", type=positive_number, default=30.0, help="Capture seconds (default 30)")
    parser.add_argument("--rate", type=positive_number, default=2.0, help="Requested Hz per group (default 2)")
    parser.add_argument("--as-fast", action="store_true", help="Opt in to unlimited legacy group polling")
    parser.add_argument("--output", help="Write raw observations and summary as NDJSON (replaces file)")
    parser.add_argument("--quiet", action="store_true", help="Only print summary; NDJSON still includes each observation")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config.json"))
    parser.add_argument("--command", help="Override configured TP2 command socket address")
    parser.add_argument("--stream", help="Override configured TP2 stream socket address")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    return capture(args, merge_targets(args.target))


if __name__ == "__main__":
    raise SystemExit(main())
