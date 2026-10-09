"""Value subscriptions and acquisition planning, independent of sockets and TP2.

The planner uses weighted greedy group cover with a redundancy pass. It is
deterministic, but does not claim to find the globally optimal cover. Monotonic
time controls leases, cooldowns and delivery; acquisition timestamps remain UTC
epoch seconds and are never refreshed by publishing a cached value.
"""

import math
import threading
import time
from collections import deque

from .catalog import CATALOG, decode_ican, diagnostic_readings


class VehicleDataBroker:
    def __init__(self, catalog=None, clock=time.monotonic, wall_clock=time.time,
                 diagnostic_hz=2, ican_hz=10, lease_seconds=15):
        self.catalog = CATALOG if catalog is None else catalog
        self.clock, self.wall_clock = clock, wall_clock
        self.diagnostic_hz = self._positive(diagnostic_hz, "diagnostic_hz")
        self.ican_hz = self._positive(ican_hz, "ican_hz")
        self.lease_seconds = self._positive(lease_seconds, "lease_seconds")
        self._lock = threading.RLock()
        self._clients = {}
        self._readings = {}
        self._providers = {p['id']: p for v in self.catalog.values()
                           for p in v.get('providers', [])}
        self._selected, self._delivery = {}, {}
        self._passive_failed = set()
        self._provider_cooldown, self._group_cooldown = {}, {}
        self._group_errors, self._group_stats = {}, {}
        self._group_times = {}
        self._external_groups = {}
        self._diagnostic_status = {}
        self._sequence = 0

    @staticmethod
    def _positive(value, label):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a positive finite number")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label} must be a positive finite number")
        return float(value)

    def sync(self, client_id, values):
        """Atomically replace and renew a client's complete set of interests."""
        with self._lock:
            try:
                if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 128:
                    raise ValueError("client_id must be a nonempty string of at most 128 characters")
                if not isinstance(values, list) or len(values) > 512:
                    raise ValueError("values must be a list of at most 512 subscriptions")
                interests = {}
                for item in values:
                    if not isinstance(item, (str, dict)):
                        raise ValueError("Each subscription must be a value ID or an options object")
                    options = {'id': item} if isinstance(item, str) else dict(item)
                    value_id = options.get('id')
                    if not isinstance(value_id, str) or value_id not in self.catalog:
                        raise ValueError(f"Unknown value: {value_id!r}")
                    if value_id in interests:
                        raise ValueError(f"Duplicate value: {value_id}")
                    if 'period_ms' in options and 'rate_hz' in options:
                        raise ValueError("Specify period_ms or rate_hz, not both")
                    period = None
                    if 'period_ms' in options:
                        period = self._positive(options['period_ms'], 'period_ms')
                    elif 'rate_hz' in options:
                        period = 1000 / self._positive(options['rate_hz'], 'rate_hz')
                    if period is not None and not 1 <= period <= 86400000:
                        raise ValueError("Requested period must be between 1 ms and one day")
                    source = options.get('source', 'auto')
                    providers = self.catalog[value_id].get('providers', [])
                    if source not in ('auto', 'diag', 'ican') and source not in {p['id'] for p in providers}:
                        raise ValueError(f"Unknown source for {value_id}: {source!r}")
                    for name in ('allow_estimated', 'allow_unverified'):
                        if name in options and not isinstance(options[name], bool):
                            raise ValueError(f"{name} must be boolean")
                    interests[value_id] = {
                        'id': value_id, 'period_ms': period, 'source': source,
                        'allow_estimated': options.get('allow_estimated', False),
                        'allow_unverified': options.get('allow_unverified', False),
                    }
            except (TypeError, ValueError) as exc:
                return {'status': 'error', 'error': str(exc)}
            # Reset delivery for changed requests, so the first response uses the
            # new source/rate even if an old publication just occurred.
            previous = self._clients.get(client_id, {}).get('values', {})
            for key in list(self._delivery):
                if key[0] == client_id and previous.get(key[1]) != interests.get(key[1]):
                    self._delivery.pop(key, None)
            self._clients[client_id] = {'values': interests, 'renewed': self.clock()}
            self._passive_failed = {k for k in self._passive_failed
                                    if k[0] != client_id or k[1] in interests}
            return {'status': 'ok', 'client_id': client_id,
                    'values': [dict(v) for v in interests.values()]}

    def remove(self, client_id):
        with self._lock:
            self._clients.pop(client_id, None)
            for table in (self._selected, self._delivery):
                for key in list(table):
                    if key[0] == client_id:
                        table.pop(key, None)
            self._passive_failed = {k for k in self._passive_failed if k[0] != client_id}

    def _expire(self):
        now = self.clock()
        for client_id, client in list(self._clients.items()):
            if now - client['renewed'] >= self.lease_seconds:
                self.remove(client_id)

    def _period(self, request, provider):
        return request['period_ms'] or 1000 / (self.ican_hz if provider['kind'] == 'ican'
                                              else self.diagnostic_hz)

    def _freshness(self, request, provider):
        return max(self._period(request, provider) * 3,
                   provider.get('stale_after_ms', 1000 if provider['kind'] == 'ican' else 2000)) / 1000

    def _healthy(self, request, provider):
        reading = self._readings.get(provider['id'])
        return bool(reading and reading['valid'] and
                    self.clock() - reading['mono'] <= self._freshness(request, provider))

    def _eligible(self, request):
        source = request['source']
        return [p for p in self.catalog[request['id']].get('providers', [])
                if (p.get('verified', False) or request['allow_unverified'])
                and (not p.get('estimated', False) or request['allow_estimated'])
                and (source == 'auto' or source in (p['kind'], p['id']))]

    def _store(self, readings, timestamp=None):
        now, wall = self.clock(), self.wall_clock()
        if timestamp is None:
            timestamp = wall
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            timestamp = wall
            readings = {pid: {'value': None, 'valid': False,
                              'reason': 'invalid acquisition timestamp'} for pid in readings}
        mono = now - max(0, wall - timestamp)
        for pid, sample in readings.items():
            if pid not in self._providers:
                continue
            previous = self._readings.get(pid)
            # Delayed messages may not replace a newer acquisition.
            if previous and mono < previous['mono'] - 1e-6:
                continue
            valid = bool(sample.get('valid', False))
            reason = sample.get('reason')
            if timestamp > wall + 1:
                valid, reason = False, 'acquisition timestamp is in the future'
            continuous = (previous and previous['valid'] and valid and
                          mono - previous['mono'] <= self._providers[pid].get('stale_after_ms', 2000) / 1000)
            self._sequence += 1
            self._readings[pid] = {
                'value': sample.get('value') if valid else None, 'valid': valid,
                'reason': reason, 'timestamp': timestamp, 'mono': mono,
                'unit': sample.get('unit', previous.get('unit') if previous else None),
                'sequence': self._sequence,
                'good_since': previous['good_since'] if continuous else mono,
                'good_count': previous['good_count'] + 1 if continuous else int(valid),
            }
            if valid:
                self._provider_cooldown.pop(pid, None)
            elif self._providers[pid]['kind'] == 'diag':
                self._provider_cooldown[pid] = now + 2

    def ingest_can(self, can_id, data, timestamp=None):
        with self._lock:
            try:
                readings = decode_ican(can_id, data, catalog=self.catalog)
            except (TypeError, ValueError, IndexError) as exc:
                readings = {p['id']: {'value': None, 'valid': False, 'reason': str(exc)}
                            for p in self._providers.values()
                            if p['kind'] == 'ican' and p.get('can_id') == can_id}
            self._store(readings, timestamp)

    def ingest_diagnostic(self, payload):
        with self._lock:
            if not isinstance(payload, dict) or 'group' not in payload or 'module' not in payload:
                return
            if payload.get('error') or payload.get('complete') is False:
                self.ingest_observation({**payload, 'error': payload.get('error') or 'incomplete measuring group'})
                return
            try:
                group = (int(payload['module']), int(payload['group']))
            except (ValueError, TypeError):
                return
            timestamp = payload.get('acquisition_timestamp', payload.get('timestamp'))
            try:
                readings = diagnostic_readings(*group, payload.get('data', []), catalog=self.catalog)
            except (TypeError, ValueError, IndexError) as exc:
                self.ingest_observation({**payload, 'error': f'malformed measuring group: {exc}'})
                return
            self._store(readings, timestamp)
            self._group_cooldown.pop(group, None)
            self._group_errors.pop(group, None)
            times = self._group_times.setdefault(group, deque(maxlen=32))
            stamp = self.wall_clock() if timestamp is None else timestamp
            if isinstance(stamp, (float, int)) and math.isfinite(stamp) and (not times or stamp > times[-1]):
                times.append(stamp)
            stat = self._group_stats.setdefault(group, {})
            stat['observed_count'] = stat.get('observed_count', 0) + 1
            stat['last_successful_acquisition_timestamp'] = stamp
            stat['request_duration_ms'] = payload.get('request_duration_ms', stat.get('request_duration_ms'))
            stat['achieved_hz'] = ((len(times) - 1) / (times[-1] - times[0]) if len(times) >= 2 else None)

    def ingest_observation(self, payload):
        """Accept raw results or worker failures without treating errors as zero."""
        with self._lock:
            if not isinstance(payload, dict) or 'module' not in payload or 'group' not in payload:
                return
            if 'data' in payload and not payload.get('error') and payload.get('complete') is not False:
                self.ingest_diagnostic(payload)
                return
            try:
                group = (int(payload['module']), int(payload['group']))
            except (ValueError, TypeError):
                return
            error = payload.get('error')
            if not error:
                return
            count = self._group_errors.get(group, 0) + 1
            self._group_errors[group] = count
            cooldown = min(30, 0.5 * 2 ** min(count - 1, 6)) if payload.get('transient', True) else 30
            self._group_cooldown[group] = self.clock() + cooldown
            self._group_stats.setdefault(group, {}).update({
                'last_error': str(error), 'request_duration_ms': payload.get('request_duration_ms')})
            self._store({p['id']: {'value': None, 'valid': False, 'reason': str(error)}
                         for p in self._providers.values()
                         if p['kind'] == 'diag' and (p['module'], p['group']) == group},
                        payload.get('acquisition_timestamp'))

    def set_diagnostic_status(self, payload):
        with self._lock:
            if not isinstance(payload, dict):
                return
            self._diagnostic_status.update({k: payload[k] for k in
                ('enabled', 'running', 'ignition', 'diagnostic_owner', 'available', 'flashing', 'quiescent')
                if k in payload})
            # Stream status messages have no sessions. A STATUS response is an
            # authoritative snapshot: disappeared clients/groups must stop
            # influencing planning immediately, not remain a cached free read.
            if 'sessions' in payload:
                self._external_groups = {}
            sessions = payload.get('sessions', [])
            if isinstance(sessions, dict):
                sessions = [dict(s, module=m) for m, s in sessions.items() if isinstance(s, dict)]
            if not isinstance(sessions, list):
                return
            for session in sessions:
                if not isinstance(session, dict):
                    continue
                module = session.get('module')
                if module is None:
                    continue
                try:
                    module = int(module)
                except (TypeError, ValueError):
                    continue
                subscriptions = session.get('client_subs', {})
                if isinstance(subscriptions, dict):
                    for client_id, interest in subscriptions.items():
                        if client_id == 'vehicle_data' or not isinstance(interest, dict):
                            continue
                        renewed = interest.get('last_sync')
                        lease = interest.get('lease_seconds', 15)
                        if (not isinstance(renewed, (int, float)) or not math.isfinite(renewed)
                                or not isinstance(lease, (int, float)) or not math.isfinite(lease)
                                or lease <= 0 or renewed > self.clock() + 1):
                            continue
                        expires = renewed + lease
                        if expires <= self.clock():
                            continue
                        periods = {}
                        low = interest.get('low_groups', [])
                        if isinstance(low, list):
                            for group in low:
                                try:
                                    periods[int(group)] = 60000.0
                                except (TypeError, ValueError):
                                    continue
                        timed = interest.get('group_periods_ms', {})
                        if isinstance(timed, dict):
                            for group, period in timed.items():
                                if (isinstance(period, (int, float)) and math.isfinite(period)
                                        and period > 0):
                                    try:
                                        group = int(group)
                                    except (TypeError, ValueError):
                                        continue
                                    periods[group] = min(periods.get(group, period), period)
                        normal = interest.get('groups', [])
                        if isinstance(normal, list):
                            for group in normal:
                                try:
                                    periods[int(group)] = 0.0
                                except (TypeError, ValueError):
                                    continue
                        for group, period in periods.items():
                            self._external_groups.setdefault((module, group), []).append((period, expires))
                stats = session.get('group_stats', {})
                if not isinstance(stats, dict):
                    continue
                for group, stat in stats.items():
                    if isinstance(stat, dict):
                        try:
                            group_key = (int(module), int(group))
                        except (ValueError, TypeError):
                            continue
                        self._group_stats.setdefault(group_key, {}).update(stat)

    def _external_period(self, group):
        periods = [period for period, expires in self._external_groups.get(group, [])
                   if expires > self.clock()]
        return min(periods) if periods else None

    def _diagnostics_available(self):
        state = self._diagnostic_status
        return (all(state.get(k) is not False for k in ('enabled', 'running', 'ignition', 'available'))
                and not any(state.get(k) for k in ('diagnostic_owner', 'flashing', 'quiescent')))

    def _make_plan(self, requests):
        now = self.clock()
        selected, pending, uncovered = {}, {}, []
        for key, request in requests.items():
            eligible = self._eligible(request)
            passive = [p for p in eligible if p['kind'] == 'ican' and self._healthy(request, p)]
            old = self._selected.get(key)
            if old and old['kind'] == 'ican' and not self._healthy(request, old):
                self._passive_failed.add(key)
            if key in self._passive_failed and request['source'] == 'auto':
                passive = [p for p in passive if self._readings[p['id']]['good_count'] >= 2
                           and now - self._readings[p['id']]['good_since'] >= 0.5]
            if passive:
                selected[key] = min(passive, key=lambda p: (p.get('estimated', False), p['id']))
                self._passive_failed.discard(key)
                continue
            diag = [p for p in eligible if p['kind'] == 'diag'
                    and self._group_cooldown.get((p['module'], p['group']), 0) <= now
                    and self._provider_cooldown.get(p['id'], 0) <= now]
            if diag:
                pending[key] = diag
            else:
                if eligible:
                    selected[key] = next((p for p in eligible if old and p['id'] == old['id']), eligible[0])
                uncovered.append({'client_id': key[0], 'id': key[1],
                                  'reason': 'no eligible providers' if not eligible else
                                  'waiting for passive data or provider cooldown'})

        # Candidate groups cover only requests they can actually satisfy,
        # including per-consumer source pins and estimate permissions.
        candidates = {}
        for key, providers in pending.items():
            for p in providers:
                candidates.setdefault((p['module'], p['group']), {})[key] = p

        def cost(group, keys):
            period = min(self._period(requests[k], candidates[group][k]) for k in keys)
            external_period = self._external_period(group)
            if external_period is not None and external_period <= period:
                # Other TP2 clients already pay for these reads at a sufficient
                # rate. Keep our period subscription anyway: if they disappear,
                # TP2 still provides this consumer's samples while we replan.
                return 1e-9
            stat = self._group_stats.get(group, {})
            duration = stat.get('request_duration_ms')
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
                observed = [s['request_duration_ms'] for (m, _), s in self._group_stats.items()
                            if m == group[0] and isinstance(s.get('request_duration_ms'), (int, float))
                            and math.isfinite(s['request_duration_ms']) and s['request_duration_ms'] > 0]
                # Unknown groups inherit the measured module cost. Otherwise a
                # real 20-ms result would lose to the next unmeasured 10-ms guess
                # on every acquisition, endlessly walking the RPM alternatives.
                duration = sum(observed) / len(observed) if observed else 10
            # Recent legacy reads are useful tie breakers; TP2 merges their
            # subscriptions with ours so choosing them never creates a second read.
            recent = stat.get('last_successful_acquisition_timestamp')
            discount = 0.85 if isinstance(recent, (int, float)) and self.wall_clock() - recent < 2 else 1
            external_cost = duration / external_period if external_period else 0
            return (max(0, duration / period - external_cost) + 0.005) * discount

        remaining, chosen = set(pending), []
        while remaining:
            choices = [(cost(g, set(coverage) & remaining) / len(set(coverage) & remaining), g)
                       for g, coverage in candidates.items() if set(coverage) & remaining]
            if not choices:
                break
            _, group = min(choices)
            chosen.append(group)
            remaining -= set(candidates[group])
        # Remove groups made redundant by subsequent choices.
        for group in reversed(chosen[:]):
            others = set().union(*(set(candidates[g]) for g in chosen if g != group))
            if set(pending) <= others:
                chosen.remove(group)
        assignments = {}
        for key, providers in pending.items():
            possible = [p for p in providers if (p['module'], p['group']) in chosen]
            if possible:
                p = min(possible, key=lambda p: (not self._healthy(requests[key], p),
                                                 p['module'], p['group'], p.get('block', 0)))
                selected[key] = p
                assignments.setdefault((p['module'], p['group']), []).append(key)
        groups = [{'module': m, 'group': g,
                   'period_ms': min(self._period(requests[k], selected[k]) for k in keys)}
                  for (m, g), keys in sorted(assignments.items())]
        explanations = []
        for key, request in requests.items():
            p = selected.get(key)
            external_period = (self._external_period((p['module'], p['group']))
                               if p and p['kind'] == 'diag' else None)
            explanations.append({'client_id': key[0], 'id': key[1],
                'provider_id': p['id'] if p else None, 'source': p['kind'] if p else None,
                'period_ms': self._period(request, p) if p else request['period_ms'],
                'reason': ('healthy passive source' if p and p['kind'] == 'ican' and self._healthy(request, p)
                           else 'shared external diagnostic group' if p and p['kind'] == 'diag'
                           and external_period is not None and external_period <= self._period(request, p)
                           else 'shared diagnostic group' if key in pending else 'no available source')})
        return {'algorithm': 'weighted_greedy_with_redundancy_removal', 'groups': groups,
                'selected': explanations, 'uncovered': uncovered,
                'diagnostics_available': self._diagnostics_available()}, selected

    def _requests(self):
        self._expire()
        return {(client_id, value_id): request for client_id, client in self._clients.items()
                for value_id, request in client['values'].items()}

    def plan(self):
        with self._lock:
            result, self._selected = self._make_plan(self._requests())
            return result

    def _sample(self, key, request, provider):
        value = self.catalog[request['id']]
        reading = self._readings.get(provider['id']) if provider else None
        healthy = bool(provider and self._healthy(request, provider))
        status = ('unavailable' if not reading else 'invalid' if not reading['valid']
                  else 'ok' if healthy else 'stale')
        reason = reading['reason'] if reading else 'no acquired sample'
        if status == 'stale':
            reason = 'source sample is stale'
        if provider and provider['kind'] == 'diag' and not self._diagnostics_available():
            status, reason = 'paused', 'diagnostic acquisition is paused'
        source = ({k: provider[k] for k in ('id', 'kind', 'module', 'group', 'block', 'can_id')
                   if k in provider} if provider else None)
        sample = {'version': 1, 'id': request['id'], 'label': value.get('label', request['id']),
                  'unit': (reading.get('unit') if reading and value.get('unit_policy') == 'reported'
                           else value.get('unit')), 'type': value.get('type', 'number'),
                  'value': reading['value'] if reading else None, 'status': status,
                  'quality': {'valid': status == 'ok', 'fresh': healthy,
                              'verified': bool(provider and provider.get('verified', False)),
                              'estimated': bool(provider and provider.get('estimated', False)), 'reason': reason},
                  'source': source, 'timestamp': reading['timestamp'] if reading else None,
                  'age_ms': max(0, (self.clock() - reading['mono']) * 1000) if reading else None,
                  'max_age_ms': self._freshness(request, provider) * 1000 if provider else None,
                  'sample_sequence': reading['sequence'] if reading else 0}
        if key[0] is not None:
            sample['client_id'] = key[0]
        return sample

    def tick(self):
        with self._lock:
            requests = self._requests()
            _, self._selected = self._make_plan(requests)
            result = []
            for key, request in requests.items():
                provider = self._selected.get(key)
                sample = self._sample(key, request, provider)
                signature = (sample['status'], provider['id'] if provider else None,
                             sample['quality']['reason'])
                previous = self._delivery.get(key)
                changed = not previous or signature != previous['signature']
                new_acquisition = not previous or sample['sample_sequence'] != previous['sequence']
                period = self._period(request, provider) if provider else request['period_ms'] or 500
                due = not previous or (self.clock() - previous['mono']) * 1000 >= period - 1e-6
                if changed or (new_acquisition and due):
                    result.append(sample)
                    self._delivery[key] = {'signature': signature, 'sequence': sample['sample_sequence'],
                                           'mono': self.clock()}
            return result

    def snapshot(self, value_ids=None, client_id=None):
        with self._lock:
            requests = self._requests()
            _, self._selected = self._make_plan(requests)
            if client_id is not None:
                return [self._sample(key, request, self._selected.get(key))
                        for key, request in requests.items()
                        if key[0] == client_id and (value_ids is None or key[1] in value_ids)]
            ids = self.catalog if value_ids is None else value_ids
            defaults = {(None, v): {'id': v, 'period_ms': None, 'source': 'auto',
                                   'allow_estimated': False, 'allow_unverified': False}
                        for v in ids if v in self.catalog}
            _, selected = self._make_plan(defaults)
            return [self._sample(k, r, selected.get(k)) for k, r in defaults.items()]

    def status(self):
        with self._lock:
            plan = self.plan()
            return {'version': 1, 'client_count': len(self._clients),
                    'clients': [{'client_id': c, 'values': list(v['values']),
                                 'lease_remaining_ms': max(0, (self.lease_seconds -
                                                            (self.clock() - v['renewed'])) * 1000)}
                                for c, v in self._clients.items()],
                    'diagnostic_status': dict(self._diagnostic_status), 'plan': plan,
                    'groups': [{'module': m, 'group': g, **stat,
                                'cooldown_remaining_ms': max(0, (self._group_cooldown.get((m, g), 0) -
                                                                 self.clock()) * 1000)}
                               for (m, g), stat in sorted(self._group_stats.items())]}
