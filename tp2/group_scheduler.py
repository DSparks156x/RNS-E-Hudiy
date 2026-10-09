"""Rate-aware measuring-group scheduling and acquisition observations.

All scheduling uses a monotonic clock. Wall timestamps describe host receipt,
not an ECU-generated timestamp. No field-count limit is imposed on responses.
"""
from collections import deque
import math

from tp2.tp2_coding import TP2Coding


def parse_group_periods(raw):
    if not isinstance(raw, dict):
        raise ValueError("group_periods_ms must be an object")
    periods = {}
    for group, period in raw.items():
        if isinstance(group, bool) or not isinstance(group, (str, int)):
            raise ValueError("Measuring group must be an integer between 0 and 255")
        group = int(group)
        if not 0 <= group <= 255:
            raise ValueError("Measuring group must be between 0 and 255")
        if isinstance(period, bool) or not isinstance(period, (int, float)):
            raise ValueError("Group periods must be positive finite milliseconds")
        if not math.isfinite(period) or period <= 0:
            raise ValueError("Group periods must be positive finite milliseconds")
        periods[group] = float(period)
    return periods


class GroupScheduler:
    def __init__(self):
        self.periods = {}
        self.next_due = {}
        self.last_started = {}
        self.stats = {}
        self.cursor = 0

    def configure(self, normal, low, timed, now):
        periods = {group: 60000.0 for group in low}
        for group, period in timed.items():
            periods[group] = min(periods.get(group, period), period)
        periods.update({group: 0.0 for group in normal})
        for group, period in periods.items():
            if group not in self.periods:
                self.next_due[group] = now
            elif period != self.periods[group]:
                self.next_due[group] = self.last_started.get(group, now) + period / 1000
        self.periods = periods
        self.next_due = {group: self.next_due[group] for group in periods}
        self.last_started = {group: value for group, value in self.last_started.items() if group in periods}

    def select(self, now, blocked=(), advance=True):
        """Round-robin due groups so unlimited legacy polling cannot starve others."""
        groups = sorted(self.periods)
        blocked = set(blocked)
        for step in range(len(groups)):
            index = (self.cursor + step) % len(groups)
            group = groups[index]
            if group not in blocked and now >= self.next_due[group]:
                if advance:
                    self.cursor = (index + 1) % len(groups)
                return group
        return None

    def started(self, group, now):
        self.last_started[group] = now
        self.next_due[group] = now + self.periods.get(group, 0) / 1000

    def completed(self, group, now, timestamp, duration_ms, success):
        period = self.periods.get(group, 0) / 1000
        if group in self.next_due and period and now >= self.next_due[group]:
            # Skip missed deadlines; never queue catch-up requests.
            self.next_due[group] = now + period
        stat = self.stats.setdefault(group, {"observed_count": 0, "success_times": deque(maxlen=32)})
        stat["request_duration_ms"] = duration_ms
        if success:
            stat["observed_count"] += 1
            stat["last_successful_acquisition_timestamp"] = timestamp
            stat["success_times"].append(now)

    def snapshot(self, now):
        result = {}
        for group, period in self.periods.items():
            stat = self.stats.get(group, {})
            successes = stat.get("success_times", ())
            rate = None
            if len(successes) > 1:
                # Include current idle age: a stopped source must not retain its peak rate.
                elapsed = max(now, successes[-1]) - successes[0]
                if elapsed > 0:
                    rate = (len(successes) - 1) / elapsed
            overdue = (period > 0 and group in self.last_started
                       and now > self.next_due[group] + period / 1000)
            result[str(group)] = {
                "requested_period_ms": period,
                "observed_count": stat.get("observed_count", 0),
                "last_successful_acquisition_timestamp": stat.get("last_successful_acquisition_timestamp"),
                "request_duration_ms": stat.get("request_duration_ms"),
                "achieved_hz": rate,
                "overrun": bool(period and (overdue
                    or stat.get("request_duration_ms", 0) > period
                    or (len(successes) >= 3 and rate is not None and rate < 900 / period))),
            }
        return result


def group_observation(module, group, response, timestamp, duration_ms, error=None):
    """Return a legacy-compatible group payload and/or a failure observation."""
    common = {"module": module, "group": group, "acquisition_timestamp": timestamp,
              "request_duration_ms": duration_ms}
    response = list(response or [])
    payload = None
    nrc = None
    transient = True
    kind = "transport"
    if error is None and len(response) >= 2 and response[:2] == [0x61, group]:
        raw = response[2:]
        decoded = TP2Coding.decode_block(raw)
        complete = bool(decoded) and len(raw) % 3 == 0
        payload = dict(common, data=decoded, raw_data_hex=bytes(raw).hex(),
                       block_count=len(decoded), trailing_bytes=len(raw) % 3,
                       complete=complete)
        if complete:
            return payload, None
        error, kind = "Incomplete or empty measuring-group payload", "malformed"
    elif error is None and response and response[0] == 0x7F:
        nrc = response[2] if len(response) >= 3 else None
        kind = "negative_response" if nrc is not None else "malformed"
        error = "Request rejected" if nrc is not None else "Malformed negative response"
        # Busy/conditions/security can change; unsupported service/group require
        # another provider rather than fast retries. Broker still sets retry policy.
        transient = nrc not in (0x11, 0x12, 0x31)
    elif error is None:
        kind = "malformed" if response else "transport"
        error = "Unexpected measuring-group response" if response else "No measuring-group response"
    failure = dict(common, error=str(error), error_kind=kind, nrc=nrc,
                   transient=transient, complete=False, raw_response_hex=bytes(response).hex())
    return payload, failure
