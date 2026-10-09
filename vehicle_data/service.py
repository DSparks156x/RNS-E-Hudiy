"""Value-oriented telemetry broker. Hardware diagnostic ownership stays in TP2."""
from __future__ import annotations

import json
import logging
import math
import signal
import threading
import time
from pathlib import Path

from .broker import VehicleDataBroker
from .catalog import CATALOG, decode_ican, get_catalog, get_catalog_coverage

logger = logging.getLogger(__name__)

DEFAULT_ADDRESSES = {
    'can_raw_stream': 'ipc:///run/rnse_control/can_stream.ipc',
    'tp2_stream': 'ipc:///run/rnse_control/tp2_stream.ipc',
    'tp2_command': 'ipc:///run/rnse_control/tp2_cmd.ipc',
    'status_stream': 'ipc:///run/rnse_control/status_stream.ipc',
    'vehicle_data_stream': 'ipc:///run/rnse_control/vehicle_data_stream.ipc',
    'vehicle_data_command': 'ipc:///run/rnse_control/vehicle_data_cmd.ipc',
}


def group_plan(groups):
    """Translate a broker plan into the period-only TP2 subscription contract."""
    result = {}
    for group in groups:
        result.setdefault(int(group['module']), {})[str(group['group'])] = group['period_ms']
    return result


class TP2PlanClient:
    """Own REQ sockets on one thread so ECU/command delays cannot stall ICAN RX."""

    def __init__(self, context, address):
        self.context, self.address = context, address
        self.lock = threading.Lock()
        self.desired, self.latest_status = {}, None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name='vehicle-data-tp2', daemon=True)

    def set_plan(self, groups):
        with self.lock:
            self.desired = group_plan(groups)

    def status(self):
        with self.lock:
            return dict(self.latest_status) if self.latest_status is not None else None

    def _run(self):
        import zmq
        sock = None
        applied, next_sync, next_status = {}, 0, 0
        try:
            while not self.stop_event.wait(0.05):
                if sock is None:
                    sock = self.context.socket(zmq.REQ)
                    sock.setsockopt(zmq.LINGER, 0)
                    sock.setsockopt(zmq.RCVTIMEO, 1000)
                    sock.setsockopt(zmq.SNDTIMEO, 1000)
                    sock.connect(self.address)
                with self.lock:
                    desired = {mod: dict(periods) for mod, periods in self.desired.items()}
                now = time.monotonic()
                commands = []
                if now >= next_status:
                    commands.append({'cmd': 'STATUS'})
                    next_status = now + 2
                sync_due = desired != applied or now >= next_sync
                if sync_due:
                    for module in sorted(set(desired) | set(applied)):
                        commands.append({'cmd': 'SYNC', 'client_id': 'vehicle_data',
                                         'module': module, 'groups': [], 'low_priority_groups': [],
                                         'group_periods_ms': desired.get(module, {})})
                try:
                    for command in commands:
                        if self.stop_event.is_set():
                            break
                        sock.send_json(command)
                        response = sock.recv_json()
                        if command['cmd'] == 'STATUS':
                            with self.lock:
                                self.latest_status = {**response, '_received_monotonic': time.monotonic()}
                        elif response.get('status') != 'ok':
                            raise RuntimeError(response.get('message', 'TP2 rejected plan'))
                    if sync_due:
                        applied = desired
                        next_sync = now + 5
                except Exception as exc:
                    logger.debug('TP2 plan unavailable: %s', exc)
                    with self.lock:
                        self.latest_status = {'status': 'error', 'available': False,
                                              'error': str(exc), '_received_monotonic': time.monotonic()}
                    sock.close()
                    sock = None
                    next_sync = 0
        finally:
            if sock is not None:
                sock.close()

    def close(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=3)


class LegacyCANAdapter:
    """Retain module-0 group layout for existing consumers, with explicit nulls."""

    GROUPS = {
        0: [('engine.oil_temperature', 'C'), ('ambient.filtered_temperature', 'C'),
            ('engine.coolant_temperature', 'C'), ('engine.intake_temperature', 'C')],
        1: [('engine.rpm', 'RPM'), ('engine.boost.actual_absolute', 'mbar'),
            ('engine.load.spec', '%'), ('engine.load.actual', '%')],
        2: [('vehicle.battery_voltage', 'V'), (None, 'L'), ('vehicle.speed', 'km/h')],
    }

    def __init__(self, clock=time.monotonic, wall_clock=time.time):
        self.clock, self.wall_clock, self.readings = clock, wall_clock, {}
        self.providers = {p['id']: (value_id, p) for value_id, entry in CATALOG.items()
                          for p in entry['providers'] if p['kind'] == 'ican'}

    def ingest(self, can_id, data, timestamp):
        now = self.clock()
        for provider_id, reading in decode_ican(can_id, data).items():
            if provider_id in self.providers:
                value_id, provider = self.providers[provider_id]
                self.readings[value_id] = (reading, now, timestamp, provider)

    def value(self, value_id):
        reading = self.readings.get(value_id)
        if reading is None:
            return {'value': None, 'timestamp': None, 'valid': False}
        sample, received, timestamp, provider = reading
        valid_timestamp = (not isinstance(timestamp, bool) and isinstance(timestamp, (int, float))
                           and math.isfinite(timestamp) and timestamp <= self.wall_clock() + 1)
        acquisition_age = max(0, self.wall_clock() - timestamp) if valid_timestamp else float('inf')
        valid = sample['valid'] and self.clock() - received <= 1.5 and acquisition_age <= 1.5
        return {'value': sample['value'] if valid else None, 'timestamp': timestamp if valid_timestamp else None,
                'valid': valid, 'source': provider['id'],
                'estimated': provider.get('estimated', False)}

    def groups(self):
        messages = []
        for group, fields in self.GROUPS.items():
            data = [{**self.value(value_id), 'unit': unit} for value_id, unit in fields]
            if any(item['timestamp'] is not None for item in data):
                messages.append({'module': 0, 'group': group, 'data': data})
        return messages


class VehicleDataService:
    def __init__(self, config=None, context=None):
        import zmq
        self.zmq = zmq
        if config is None:
            config = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text())
        addresses = config.get('interfaces', {}).get('zmq') or config.get('zmq', {})
        self.addresses = {key: addresses.get(key, value) for key, value in DEFAULT_ADDRESSES.items()}
        settings = config.get('diagnostics', {}).get('values', {})
        self.broker = VehicleDataBroker(diagnostic_hz=settings.get('diagnostic_hz', 2),
                                       ican_hz=settings.get('ican_hz', 10),
                                       lease_seconds=settings.get('lease_seconds', 15))
        self.context = context or zmq.Context()
        self.owns_context = context is None
        self.running = True
        self.legacy = LegacyCANAdapter()
        self.tp2 = TP2PlanClient(self.context, self.addresses['tp2_command'])
        self.sockets = []
        self.observations = {}

    def _socket(self, kind):
        socket = self.context.socket(kind)
        socket.setsockopt(self.zmq.LINGER, 0)
        self.sockets.append(socket)
        return socket

    def command(self, request):
        if not isinstance(request, dict):
            raise ValueError('Command must be an object')
        cmd = request.get('cmd')
        if cmd == 'CATALOG':
            return {'status': 'ok', 'version': 1, 'values': get_catalog(), 'coverage': get_catalog_coverage()}
        if cmd == 'SYNC_VALUES':
            return self.broker.sync(request.get('client_id'), request.get('values', []))
        if cmd == 'UNSUBSCRIBE':
            client_id = request.get('client_id')
            if not isinstance(client_id, str) or not client_id:
                raise ValueError('Missing client_id')
            self.broker.remove(client_id)
            return {'status': 'ok'}
        if cmd == 'SNAPSHOT':
            return {'status': 'ok', 'values': self.broker.snapshot(request.get('values'), request.get('client_id'))}
        if cmd == 'PLAN':
            return {'status': 'ok', 'plan': self.broker.plan()}
        if cmd == 'STATUS':
            return {'status': 'ok', 'broker': self.broker.status(), 'tp2': self.tp2.status(),
                    'observed_groups': list(self.observations.values())}
        return {'status': 'error', 'message': 'Unknown command'}

    def run(self):
        zmq = self.zmq
        raw, diag = self._socket(zmq.SUB), self._socket(zmq.SUB)
        raw.connect(self.addresses['can_raw_stream'])
        raw.subscribe(b'CAN_')
        diag.connect(self.addresses['tp2_stream'])
        for topic in (b'HUDIY_DIAG', b'HUDIY_DIAG_OBSERVATION', b'HUDIY_TP2_STATUS'):
            diag.subscribe(topic)
        pub, legacy_pub, rep = self._socket(zmq.PUB), self._socket(zmq.PUB), self._socket(zmq.REP)
        pub.bind(self.addresses['vehicle_data_stream'])
        legacy_pub.bind(self.addresses['status_stream'])
        rep.bind(self.addresses['vehicle_data_command'])
        poller = zmq.Poller()
        for socket in (raw, diag, rep):
            poller.register(socket, zmq.POLLIN)
        self.tp2.thread.start()
        last_status, last_legacy, last_legacy_payload = None, 0, None
        logger.info('Vehicle values service running at %s', self.addresses['vehicle_data_command'])
        try:
            while self.running:
                events = dict(poller.poll(10))
                # Bounded drains leave time for leases, commands and freshness transitions.
                for socket in (raw, diag):
                    if socket not in events:
                        continue
                    for _ in range(200):
                        try:
                            frames = socket.recv_multipart(flags=zmq.NOBLOCK)
                        except zmq.Again:
                            break
                        try:
                            topic, encoded = frames
                            payload = json.loads(encoded)
                            if not isinstance(payload, dict):
                                raise ValueError('Telemetry must be an object')
                            if socket is raw:
                                can_id = payload.get('arbitration_id')
                                if can_id is None:
                                    can_id = int(topic.decode().removeprefix('CAN_'), 16)
                                data = bytes.fromhex(payload['data_hex'])
                                timestamp = payload.get('timestamp', time.time())
                                self.broker.ingest_can(int(can_id), data, timestamp)
                                self.legacy.ingest(int(can_id), data, timestamp)
                            elif topic == b'HUDIY_DIAG' and 'group' in payload:
                                self.broker.ingest_diagnostic(payload)
                                self.observations[(payload['module'], payload['group'])] = {
                                    key: payload.get(key) for key in ('module', 'group', 'block_count',
                                    'raw_data_hex', 'trailing_bytes', 'complete', 'acquisition_timestamp')}
                            elif topic == b'HUDIY_DIAG_OBSERVATION':
                                self.broker.ingest_observation(payload)
                            elif topic == b'HUDIY_TP2_STATUS':
                                self.broker.set_diagnostic_status(payload)
                        except (ValueError, TypeError, KeyError) as exc:
                            logger.debug('Discarded malformed telemetry: %s', exc)
                if rep in events:
                    try:
                        response = self.command(rep.recv_json())
                    except Exception as exc:
                        response = {'status': 'error', 'message': str(exc)}
                    rep.send_json(response)
                status = self.tp2.status()
                if status is not None and status != last_status:
                    self.broker.set_diagnostic_status(status)
                    last_status = status
                batches = {}
                for sample in self.broker.tick():
                    batches.setdefault(sample.get('client_id'), []).append(sample)
                for client_id, values in batches.items():
                    pub.send_multipart([b'HUDIY_VALUES', json.dumps(
                        {'version': 1, 'client_id': client_id, 'values': values}).encode()])
                self.tp2.set_plan(self.broker.plan().get('groups', []))
                now = time.monotonic()
                if now - last_legacy >= 0.25:
                    last_legacy = now
                    groups = self.legacy.groups()
                    encoded = json.dumps(groups)
                    if encoded != last_legacy_payload:
                        for payload in groups:
                            legacy_pub.send_multipart([b'HUDIY_DIAG', json.dumps(payload).encode()])
                        last_legacy_payload = encoded
        finally:
            self.tp2.close()
            for socket in self.sockets:
                socket.close()
            if self.owns_context:
                self.context.term()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    service = VehicleDataService()
    def stop(_signum, _frame):
        service.running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    service.run()


if __name__ == '__main__':
    main()
