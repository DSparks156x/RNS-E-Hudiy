"""Per-browser value subscriptions and unsmoothed telemetry relay."""
import json
import logging
import queue
import threading
import time

import zmq

logger = logging.getLogger(__name__)


class ValueBridge:
    def __init__(self, addresses, emit):
        self.emit = emit
        self.stream = addresses.get('vehicle_data_stream', 'ipc:///run/rnse_control/vehicle_data_stream.ipc')
        self.command = addresses.get('vehicle_data_command', 'ipc:///run/rnse_control/vehicle_data_cmd.ipc')
        self.context = zmq.Context()
        self.clients = {}
        self.generations = {}
        self.lock = threading.Lock()
        self.queue = queue.Queue(maxsize=256)

    @staticmethod
    def client_id(sid):
        return 'dataview_values:' + sid

    def request(self, command, wait=True):
        response = queue.Queue(maxsize=1)
        try:
            self.queue.put_nowait((command, response))
        except queue.Full:
            return {'status': 'error', 'message': 'Values command queue is full'}
        if not wait:
            return {'status': 'queued'}
        try:
            return response.get(timeout=3)
        except queue.Empty:
            return {'status': 'error', 'message': 'Values service did not respond'}

    def replace(self, sid, values):
        with self.lock:
            generation = self.generations.get(sid, 0) + 1
            self.generations[sid] = generation
        result = self.request({'cmd': 'SYNC_VALUES', 'client_id': self.client_id(sid),
                               'values': values, '_generation': generation})
        if result.get('status') == 'ok':
            with self.lock:
                if self.generations.get(sid) != generation:
                    return {'status': 'error', 'message': 'Subscription superseded or disconnected'}
                self.clients[sid] = values
            cached = self.request({'cmd': 'SNAPSHOT', 'client_id': self.client_id(sid)})
            with self.lock:
                current = self.generations.get(sid) == generation and sid in self.clients
            if current and cached.get('status') == 'ok':
                self.emit('values_batch', cached.get('values', []), to=sid)
        return result

    def release(self, sid):
        with self.lock:
            self.generations[sid] = self.generations.get(sid, 0) + 1
            self.clients.pop(sid, None)
        self.request({'cmd': 'UNSUBSCRIBE', 'client_id': self.client_id(sid)}, wait=False)

    def start(self):
        for target in (self._commands, self._receive):
            threading.Thread(target=target, daemon=True).start()

    def _commands(self):
        socket, next_heartbeat = None, 0
        while True:
            if socket is None:
                socket = self.context.socket(zmq.REQ)
                socket.setsockopt(zmq.LINGER, 0)
                socket.setsockopt(zmq.RCVTIMEO, 1000)
                socket.setsockopt(zmq.SNDTIMEO, 1000)
                socket.connect(self.command)
            now = time.monotonic()
            if now >= next_heartbeat:
                next_heartbeat = now + 5
                with self.lock:
                    clients = list(self.clients.items())
                for sid, values in clients:
                    self.request({'cmd': 'SYNC_VALUES', 'client_id': self.client_id(sid),
                                  'values': values, '_heartbeat': True}, wait=False)
            try:
                command, result = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if command['cmd'] == 'SYNC_VALUES' and command.get('_heartbeat'):
                sid = command['client_id'].split(':', 1)[1]
                with self.lock:
                    current = self.clients.get(sid)
                if current is None:
                    result.put({'status': 'ok'})
                    continue
                command['values'] = current
            if '_generation' in command:
                sid = command['client_id'].split(':', 1)[1]
                with self.lock:
                    current_generation = self.generations.get(sid)
                if current_generation != command['_generation']:
                    result.put({'status': 'error', 'message': 'Subscription superseded or disconnected'})
                    continue
                command.pop('_generation')
            command.pop('_heartbeat', None)
            try:
                socket.send_json(command)
                result.put(socket.recv_json())
            except Exception as exc:
                result.put({'status': 'error', 'message': str(exc)})
                socket.close()
                socket = None

    def _receive(self):
        socket = self.context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(self.stream)
        socket.subscribe(b'HUDIY_VALUES')
        while True:
            try:
                _topic, encoded = socket.recv_multipart()
                payload = json.loads(encoded)
                client_id = payload.get('client_id', '')
                if not client_id.startswith('dataview_values:'):
                    continue
                sid = client_id.split(':', 1)[1]
                with self.lock:
                    active = sid in self.clients
                if active:
                    self.emit('values_batch', payload.get('values', []), to=sid)
            except Exception:
                logger.exception('Invalid values message')
