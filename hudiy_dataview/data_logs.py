"""Named-value recordings, shared DIS controls and DataView HTTP endpoints.

Raw CAN/debug profiles remain in data_logger.py. This recorder subscribes only
through the vehicle broker, keeping acquisition metadata instead of resampling.
"""
import csv
import io
import json
import logging
import math
import os
import queue
import re
import threading
import time
import uuid
import sys
from pathlib import Path
from copy import deepcopy

try:
    from vehicle_data.catalog import CATALOG
    from vehicle_data.workspace import WorkspaceStore, data_logs_directory
except ModuleNotFoundError:  # Direct installed hudiy_dataview/app.py execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vehicle_data.catalog import CATALOG
    from vehicle_data.workspace import WorkspaceStore, data_logs_directory

log = logging.getLogger(__name__)


class DataLogs:
    CLIENT_ID = 'dataview_recording'

    def __init__(self, config=None, request_values=None, emit=None):
        self.config = config or {}
        self.workspace = WorkspaceStore(self.config)
        self.directory = data_logs_directory(self.config) / 'sessions'
        self.request_values = request_values
        self.emit = emit or (lambda *args, **kwargs: None)
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.active = None
        self.last_session = None
        self.last_error = ''
        self.running = False
        self.worker = None
        self.control_worker = None
        self.seen = {}
        self.latest = {}
        self.addresses = self.config.get('interfaces', {}).get('zmq') or self.config.get('zmq', {})

    def _path(self, session_id):
        if not isinstance(session_id, str) or not re.fullmatch(r'[a-f0-9]{32}', session_id):
            raise ValueError('Invalid session ID')
        path = self.directory / session_id
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise ValueError('Invalid session path')
        if any((path / name).is_symlink() for name in ('session.json', 'samples.ndjson', '.session.tmp')):
            raise ValueError('Invalid recording file')
        return path

    @staticmethod
    def _requests(profile):
        values = []
        for value in profile['values']:
            spec = {'id': value} if isinstance(value, str) else dict(value)
            for key in ('allow_estimated', 'allow_unverified'):
                if profile.get(key):
                    spec.setdefault(key, True)
            values.append(spec)
        return values

    def _broker(self, cmd, **kwargs):
        if self.request_values is None:
            return {'status': 'ok'}
        result = self.request_values({'cmd': cmd, 'client_id': self.CLIENT_ID, **kwargs})
        if result.get('status') != 'ok':
            raise RuntimeError(result.get('message', 'Vehicle values service unavailable'))
        return result

    def status(self):
        with self.lock:
            session = self.active or self.last_session or {}
            return {'recording': self.active is not None,
                    'session_id': session.get('id'), 'profile_id': session.get('profile_id'),
                    'elapsed_sec': round(time.time()-session['started_at'], 2) if self.active else session.get('duration_sec', 0),
                    'samples': session.get('samples', 0), 'markers': session.get('markers', 0),
                    'dropped_rows': session.get('dropped_rows', 0), 'last_error': self.last_error}

    def sessions(self):
        result = []
        if self.directory.exists():
            for path in self.directory.iterdir():
                if not path.is_dir() or path.is_symlink() or not re.fullmatch(r'[a-f0-9]{32}', path.name):
                    continue
                try:
                    path = self._path(path.name)
                    metadata = json.loads((path / 'session.json').read_text(encoding='utf-8'))
                    if metadata.get('id') != path.name:
                        continue
                    if metadata.get('recording') and (not self.active or self.active['id'] != path.name):
                        metadata['recording'] = False
                        metadata['interrupted'] = True
                    result.append(metadata)
                except (OSError, ValueError):
                    log.warning('Ignoring unreadable recording metadata %s', path.name)
        with self.lock:
            if self.active:
                result = [entry for entry in result if entry['id'] != self.active['id']]
                result.append(deepcopy(self.active))
        return sorted(result, key=lambda item: item['started_at'], reverse=True)

    def state(self):
        config = self.workspace.load()
        return {**config, 'catalog': list(deepcopy(CATALOG).values()),
                'sessions': self.sessions(), 'recording': self.status()}

    def broadcast(self):
        self.emit('data_logs_status', self.status())
        self.emit('data_logs_state', self.state())

    def save_config(self, document):
        clean = self.workspace.save(document)
        self.emit('data_logs_config', clean)
        self.broadcast()
        return clean

    def _metadata(self):
        path = self._path(self.active['id'])
        temporary = path / '.session.tmp'
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(self.active, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path / 'session.json')

    def start_recording(self, profile_id):
        with self.operation_lock:
            return self._start_recording(profile_id)

    def _start_recording(self, profile_id):
        with self.lock:
            if self.active:
                raise ValueError('A recording is already running')
            profile = next((p for p in self.workspace.load()['profiles'] if p['id'] == profile_id), None)
            if profile is None:
                raise ValueError('Unknown recording profile')
            requests = self._requests(profile)
            self._broker('SYNC_VALUES', values=requests)
            session_id = uuid.uuid4().hex
            path = self._path(session_id)
            handle = None
            try:
                path.mkdir(parents=True, exist_ok=False)
                handle = (path / 'samples.ndjson').open('x', encoding='utf-8')
                self.active = {'id': session_id, 'name': profile['name'], 'profile_id': profile_id,
                               'started_at': time.time(), 'duration_sec': 0, 'recording': True,
                               'values': [value['id'] for value in requests], 'requests': requests,
                               'catalog': [deepcopy(CATALOG[value['id']]) for value in requests],
                               'samples': 0, 'markers': 0, 'dropped_rows': 0}
                self.last_error = ''
                self.seen, self.latest = {}, {}
                self.write_queue = queue.Queue(maxsize=max(100, int(self.config.get('data_logs', {}).get('queue_size', 10000))))
                self._metadata()
                self.writer = threading.Thread(target=self._write, args=(handle, self.write_queue), daemon=True)
                self.writer.start()
                for value in requests:
                    self._enqueue({'kind': 'sample', 'id': value['id'], 'value': None,
                                   'status': 'unavailable', 'unit': CATALOG[value['id']].get('unit'),
                                   'timestamp': None, 'received_at': self.active['started_at'],
                                   'event_at': self.active['started_at'], 'sample_sequence': None})
            except Exception:
                if handle is not None:
                    handle.close()
                self.active = None
                self._broker('UNSUBSCRIBE')
                raise
        self.broadcast()
        try:
            cached = self._broker('SNAPSHOT')
            self.ingest({'client_id': self.CLIENT_ID, 'values': cached.get('values', [])})
        except RuntimeError as error:
            self.last_error = str(error)
        return self.status()

    def _enqueue(self, row):
        try:
            self.write_queue.put_nowait(row)
        except queue.Full:
            self.active['dropped_rows'] += 1

    def ingest(self, envelope):
        if envelope.get('client_id') != self.CLIENT_ID:
            return
        with self.lock:
            if not self.active or not self.active['recording']:
                return
            allowed = set(self.active['values'])
            for sample in envelope.get('values', []):
                if not isinstance(sample, dict) or sample.get('id') not in allowed:
                    continue
                row = deepcopy(sample)
                signature = (row.get('sample_sequence'), row.get('timestamp'), row.get('status'),
                             json.dumps(row.get('source'), sort_keys=True), json.dumps(row.get('value'), sort_keys=True))
                if self.seen.get(row['id']) == signature:
                    continue
                # Reject corrupt transport numbers; strings/statuses/bitfields are retained.
                if isinstance(row.get('value'), float) and not math.isfinite(row['value']):
                    row['value'], row['status'] = None, 'invalid'
                if row.get('status') != 'ok':
                    row['raw_value'] = row.get('value')
                    row['value'] = None
                self.seen[row['id']] = signature
                self.latest[row['id']] = row
                row.update(kind='sample', received_at=time.time())
                row['event_at'] = row.get('timestamp') if row.get('status') == 'ok' else row['received_at']
                self._enqueue(row)

    def expire(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if not self.active:
                return
            stale = []
            for sample in self.latest.values():
                timestamp, max_age = sample.get('timestamp'), sample.get('max_age_ms', 2000)
                # A null age limit means this value does not expire (for example,
                # ECU identification). It must not stop the subscriber loop.
                if (sample.get('status') == 'ok' and isinstance(timestamp, (int, float))
                        and isinstance(max_age, (int, float)) and math.isfinite(max_age)
                        and now-timestamp > max_age/1000):
                    stale.append({**sample, 'status': 'stale', 'raw_value': sample.get('value'), 'value': None})
            if stale:
                self.ingest({'client_id': self.CLIENT_ID, 'values': stale})

    def _write(self, handle, pending):
        row_pending = False
        try:
            with handle:
                last_flush = time.monotonic()
                while True:
                    try:
                        row = pending.get(timeout=0.5)
                    except queue.Empty:
                        handle.flush()
                        continue
                    if row is None:
                        break
                    row_pending = True
                    handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                    with self.lock:
                        if self.active:
                            self.active['markers' if row['kind'] == 'marker' else 'samples'] += 1
                    row_pending = False
                    if time.monotonic()-last_flush >= 1:
                        handle.flush()
                        with self.lock:
                            if self.active:
                                self._metadata()
                        last_flush = time.monotonic()
                handle.flush()
                os.fsync(handle.fileno())
        except Exception as error:
            with self.lock:
                self.last_error = str(error)
                if self.active:
                    self.active['write_failed'] = True
                    self.active['recording'] = False
                    if row_pending:
                        self.active['dropped_rows'] += 1
            log.exception('Named-value recording writer failed')

    def marker(self, note='Mark'):
        note = str(note).strip()
        if not note or len(note) > 256:
            raise ValueError('Marker must contain 1–256 characters')
        with self.lock:
            if not self.active or not self.active['recording']:
                raise ValueError('No recording is running')
            now = time.time()
            self._enqueue({'kind': 'marker', 'timestamp': now, 'event_at': now, 'note': note, 'label': note})
        self.broadcast()
        return self.status()

    def stop_recording(self):
        with self.operation_lock:
            return self._stop_recording()

    def _stop_recording(self):
        with self.lock:
            if not self.active:
                return self.status()
            self.active['recording'] = False
            writer, pending = self.writer, self.write_queue
        # Drain all accepted samples before finalizing metadata.
        if writer.is_alive():
            try:
                pending.put(None, timeout=2)
            except queue.Full:
                raise RuntimeError('Recording writer queue did not drain')
        writer.join(timeout=10)
        with self.lock:
            if writer.is_alive():
                raise RuntimeError('Recording writer has not finished; retry Stop')
            self.active.update(recording=False, stopped_at=time.time(),
                               duration_sec=time.time()-self.active['started_at'], last_error=self.last_error)
            if self.active.get('write_failed'):
                self.active['dropped_rows'] += pending.qsize()
            self._metadata()
            self.last_session, self.active = self.active, None
            self.latest, self.seen = {}, {}
        try:
            self._broker('UNSUBSCRIBE')
        except RuntimeError as error:
            self.last_error = str(error)
        self.broadcast()
        return self.status()

    def read_session(self, session_id, limit=100000, offset=0, window_sec=None, since=None, until=None):
        path = self._path(session_id)
        if not (path / 'session.json').is_file():
            raise FileNotFoundError('Recording not found')
        limit, offset = min(max(int(limit), 1), 100000), max(int(offset), 0)
        metadata = next((s for s in self.sessions() if s['id'] == session_id), None)
        since = None if since is None else float(since)
        until = None if until is None else float(until)
        if window_sec is not None:
            window_sec = float(window_sec)
            if not math.isfinite(window_sec) or window_sec <= 0:
                raise ValueError('Review window must be positive and finite')
            until = until if until is not None else metadata.get('stopped_at', time.time())
            since = until-window_sec
        if any(value is not None and not math.isfinite(value) for value in (since, until)):
            raise ValueError('Review bounds must be finite')
        samples, markers, count, truncated = [], [], 0, False
        with (path / 'samples.ndjson').open(encoding='utf-8') as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # Recover the complete prefix after an interrupted write.
                timestamp = row.get('event_at', row.get('received_at') if row.get('timestamp') is None else row.get('timestamp'))
                if ((since is not None and (timestamp is None or timestamp < since)) or
                        (until is not None and (timestamp is None or timestamp > until))):
                    continue
                if row.get('kind') == 'marker':
                    if len(markers) < 10000:
                        markers.append(row)
                else:
                    if count >= offset:
                        if len(samples) < limit:
                            samples.append(row)
                        else:
                            truncated = True
                    count += 1
        return {'session': metadata, 'samples': samples, 'markers': markers,
                'offset': offset, 'next_offset': offset+len(samples) if truncated else None,
                'truncated': truncated, 'total_samples': count}

    def delete_session(self, session_id):
        with self.lock:
            if self.active and self.active['id'] == session_id:
                raise ValueError('Stop the recording before deleting it')
            path = self._path(session_id)
            if not path.exists():
                raise FileNotFoundError('Recording not found')
            for name in ('samples.ndjson', 'session.json', '.session.tmp'):
                target = path / name
                if target.is_symlink():
                    raise ValueError('Invalid recording file')
            for name in ('samples.ndjson', 'session.json', '.session.tmp'):
                (path / name).unlink(missing_ok=True)
            path.rmdir()
        self.broadcast()

    def export_csv(self, session_id):
        path = self._path(session_id)
        if not (path / 'session.json').exists():
            raise FileNotFoundError('Recording not found')
        columns = ['kind', 'id', 'timestamp', 'received_at', 'event_at', 'value', 'raw_value', 'unit', 'status',
                   'sample_sequence', 'source', 'quality', 'max_age_ms', 'note']
        def generate():
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            yield buffer.getvalue()
            with (path / 'samples.ndjson').open(encoding='utf-8') as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    for key in ('source', 'quality'):
                        if isinstance(row.get(key), (dict, list)):
                            row[key] = json.dumps(row[key], separators=(',', ':'))
                    buffer.seek(0)
                    buffer.truncate()
                    writer.writerow(row)
                    yield buffer.getvalue()
        return generate()

    def command(self, payload):
        try:
            if not isinstance(payload, dict):
                raise ValueError('Expected command object')
            command_name = payload.get('cmd', '')
            if not isinstance(command_name, str):
                raise ValueError('Command name must be a string')
            cmd = command_name.upper()
            if cmd == 'START':
                recording = self.start_recording(payload.get('profile_id'))
            elif cmd == 'STOP':
                recording = self.stop_recording()
            elif cmd == 'MARK':
                recording = self.marker(payload.get('note', payload.get('label', 'Mark')))
            elif cmd == 'STATUS':
                recording = self.status()
            else:
                raise ValueError('Unknown logging command')
            return {'status': 'ok', 'recording': recording}
        except (ValueError, TypeError, RuntimeError, OSError) as error:
            return {'status': 'error', 'message': str(error), 'recording': self.status()}

    def start(self):
        if self.running:
            return
        self.running = True
        self.worker = threading.Thread(target=self._receive, name='DataLogs-Values', daemon=True)
        self.worker.start()
        self.control_worker = threading.Thread(target=self._controls, name='DataLogs-Controls', daemon=True)
        self.control_worker.start()

    def close(self):
        self.stop_recording()
        self.running = False
        if self.worker:
            self.worker.join(timeout=2)
        if self.control_worker:
            self.control_worker.join(timeout=2)

    def _receive(self):
        import zmq
        context = zmq.Context()
        sock = context.socket(zmq.SUB)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(self.addresses.get('vehicle_data_stream', 'ipc:///run/rnse_control/vehicle_data_stream.ipc'))
        sock.subscribe(b'HUDIY_VALUES')
        heartbeat = 0
        try:
            while self.running:
                if sock.poll(200):
                    try:
                        _, encoded = sock.recv_multipart()
                        self.ingest(json.loads(encoded))
                    except (ValueError, TypeError):
                        log.warning('Discarding malformed value recording message')
                self.expire()
                with self.lock:
                    write_failed = bool(self.active and self.active.get('write_failed'))
                if write_failed:
                    try:
                        self.stop_recording()
                    except OSError:
                        log.exception('Could not finalize failed recording metadata')
                if time.monotonic() >= heartbeat:
                    heartbeat = time.monotonic()+5
                    with self.lock:
                        if self.active and self.active['recording']:
                            try:
                                self._broker('SYNC_VALUES', values=self.active['requests'])
                            except RuntimeError as error:
                                self.last_error = str(error)
                    self.emit('data_logs_status', self.status())
        finally:
            sock.close()
            context.term()

    def _controls(self):
        import zmq
        context = zmq.Context()
        sock = context.socket(zmq.REP)
        sock.setsockopt(zmq.LINGER, 0)
        try:
            sock.bind(self.addresses.get('data_logs_command', 'ipc:///run/rnse_control/data_logs_cmd.ipc'))
            while self.running:
                if sock.poll(200):
                    try:
                        payload = sock.recv_json()
                        result = self.command(payload) if isinstance(payload, dict) else {'status': 'error', 'message': 'Expected command object'}
                    except ValueError:
                        result = {'status': 'error', 'message': 'Invalid JSON command'}
                    sock.send_json(result)
        except Exception:
            log.exception('DIS logging control endpoint failed')
        finally:
            sock.close()
            context.term()


def register_data_logs(app, socketio, config=None, request_values=None):
    from flask import Response, jsonify, request, stream_with_context
    service = DataLogs(config, request_values, socketio.emit)
    app.extensions['data_logs'] = service

    def object_payload():
        payload = request.get_json(silent=True)
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ValueError('Expected request object')
        return payload

    def guarded(action):
        try:
            return jsonify(action())
        except FileNotFoundError as error:
            return jsonify({'status': 'error', 'message': str(error)}), 404
        except (ValueError, TypeError, RuntimeError, OSError) as error:
            return jsonify({'status': 'error', 'message': str(error)}), 400

    @app.get('/api/data-logs')
    def data_logs_state():
        return guarded(service.state)

    @app.route('/api/data-logs/config', methods=['GET', 'PUT'])
    def data_logs_config():
        return guarded(lambda: service.workspace.load() if request.method == 'GET' else
                       service.save_config(request.get_json(silent=True)))

    @app.get('/api/data-logs/status')
    def data_logs_status():
        return jsonify(service.status())

    @app.post('/api/data-logs/start')
    def data_logs_start():
        return guarded(lambda: service.start_recording(object_payload().get('profile_id')))

    @app.post('/api/data-logs/stop')
    def data_logs_stop():
        return guarded(service.stop_recording)

    @app.post('/api/data-logs/marker')
    @app.post('/api/data-logs/mark')
    def data_logs_marker():
        return guarded(lambda: service.marker(object_payload().get('note', object_payload().get('label', 'Mark'))))

    @app.get('/api/data-logs/sessions')
    def data_logs_sessions():
        return guarded(lambda: {'sessions': service.sessions()})

    @app.route('/api/data-logs/sessions/<session_id>', methods=['GET', 'DELETE'])
    def data_logs_session(session_id):
        return guarded(lambda: service.read_session(session_id, request.args.get('limit', 100000), request.args.get('offset', 0),
                       request.args.get('window_sec'), request.args.get('since'), request.args.get('until'))
                       if request.method == 'GET' else (service.delete_session(session_id) or {'status': 'ok'}))

    @app.get('/api/data-logs/sessions/<session_id>/export')
    def data_logs_export(session_id):
        try:
            rows = service.export_csv(session_id)
            return Response(stream_with_context(rows), mimetype='text/csv',
                            headers={'Content-Disposition': 'attachment; filename="'+session_id+'.csv"'})
        except (ValueError, FileNotFoundError) as error:
            return jsonify({'status': 'error', 'message': str(error)}), 404

    return service
