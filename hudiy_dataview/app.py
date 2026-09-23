import os
import sys
import json
import time
import threading
import queue
import hashlib
import uuid
import logging
import zmq
from flask import Flask, render_template, request, abort, send_file
from flask_socketio import SocketIO, emit
try:
    from .data_logger import DataLogger
    from .file_portal import register_file_portal
except ImportError:  # Direct execution on the installed Pi.
    from data_logger import DataLogger
    from file_portal import register_file_portal

# Compatibility fix for Flask 3.1.3+ with older Flask-SocketIO:
# Flask 3.1.3 made RequestContext.session a property without a setter.
try:
    from flask.ctx import RequestContext
    if hasattr(RequestContext, "session") and (not hasattr(RequestContext.session, "fset") or RequestContext.session.fset is None):
        def _set_session(self, val):
            self._session = val
        RequestContext.session = RequestContext.session.setter(_set_session)
except Exception:
    pass

# Configuration — load ZMQ addresses from config.json (same as tp2_worker)
_DEFAULT_TP2_STREAM  = 'ipc:///run/rnse_control/tp2_stream.ipc'
_DEFAULT_TP2_COMMAND = 'ipc:///run/rnse_control/tp2_cmd.ipc'
try:
    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _package_root = _base_dir
    if _package_root not in sys.path:
        sys.path.insert(0, _package_root)
    from flasher.controllers.haldex_gen4 import HaldexFlasher
    from flasher.controllers.pq_eps.protocol import PQEPSFlasher
    from flasher.traffic import flashing_operation, set_flashing_mode

    with open(os.path.join(_base_dir, 'config.json')) as _f:
        _cfg = json.load(_f)
    _zmq = _cfg.get('interfaces', {}).get('zmq', {})
    if not _zmq:
        _zmq = _cfg.get('zmq', {})
        
    ZMQ_PUB_ADDR = _zmq.get('tp2_stream',  _DEFAULT_TP2_STREAM)
    ZMQ_REQ_ADDR = _zmq.get('tp2_command', _DEFAULT_TP2_COMMAND)
    ZMQ_CAN_ADDR = _zmq.get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc')
    ZMQ_STATUS_STREAM = _zmq.get('status_stream', 'ipc:///run/rnse_control/status_stream.ipc')
    ZMQ_HALDEX_CMD = _zmq.get('haldex_command', 'ipc:///run/rnse_control/haldex_cmd.ipc')
    ZMQ_HALDEX_STATUS = _zmq.get('haldex_status', 'ipc:///run/rnse_control/haldex_status.ipc')
except Exception as _e:
    logging.warning(f"Could not load config.json, using default ZMQ addresses: {_e}")
    _cfg = {}
    ZMQ_PUB_ADDR = _DEFAULT_TP2_STREAM
    ZMQ_REQ_ADDR = _DEFAULT_TP2_COMMAND
    ZMQ_CAN_ADDR = 'ipc:///run/rnse_control/can_stream.ipc'
    ZMQ_STATUS_STREAM = 'ipc:///run/rnse_control/status_stream.ipc'
    ZMQ_HALDEX_CMD = 'ipc:///run/rnse_control/haldex_cmd.ipc'
    ZMQ_HALDEX_STATUS = 'ipc:///run/rnse_control/haldex_status.ipc'
    try:
        _package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _package_root not in sys.path:
            sys.path.insert(0, _package_root)
        from flasher.controllers.haldex_gen4 import HaldexFlasher
        from flasher.controllers.pq_eps.protocol import PQEPSFlasher
        from flasher.traffic import flashing_operation, set_flashing_mode
    except Exception:
        HaldexFlasher = None
        PQEPSFlasher = None

# --- Setup Flask & SocketIO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'hudiy_secret'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*',
                    ping_interval=60, ping_timeout=120)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (DataView) %(message)s')
logger = logging.getLogger(__name__)
data_logger = DataLogger(_cfg)


def _validate_vehicle_portal_upload(path):
    errors = []
    for flasher in (HaldexFlasher, PQEPSFlasher):
        if flasher is None:
            continue
        try:
            return flasher.prepare_image(path)
        except Exception as error:
            errors.append(str(error))
            if flasher is PQEPSFlasher:
                try:
                    return flasher.prepare_image(
                        path, start_addr=0x5e000, end_addr=0x5efff)
                except Exception as dataset_error:
                    errors.append(str(dataset_error))
    raise ValueError('File is not a supported Haldex or PQ EPS image: ' + '; '.join(errors))


register_file_portal(app, _cfg, validators={'haldex': _validate_vehicle_portal_upload})

# Cache Busting
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# --- Global State ---
SMOOTHING_ENABLED = True  # default on

# --- Server-Side Interpolator ---
EMIT_INTERVAL = 0.25    # 4Hz broadcast rate
EMA_ALPHA     = 0.98    # applied to incoming source values before linear interp

class Interpolator:
    """
    Receives raw diagnostic messages at low rate (~0.5 Hz).
    Re-emits linearly interpolated values to all SocketIO clients at ~4 Hz.

    When smoothing is disabled, it just passes raw values through at the
    natural data rate without the 4Hz loop.
    """
    def __init__(self):
        self._lock = threading.Lock()
        # key = (module, group, value_index)
        # value = {'prev': float, 'target': float, 'ema': float,
        #          't_update': float, 'source_interval': float}
        self._state: dict = {}
        # latest raw message per (module, group)
        self._latest_msg: dict = {}

    def _make_key(self, module, group, idx):
        return (module, group, idx)

    def update(self, module, group, data):
        """Called when a new raw message arrives from the TP2 source."""
        now = time.monotonic()
        with self._lock:
            for i, dv in enumerate(data):
                raw = dv.get('value')
                if not isinstance(raw, (int, float)):
                    continue  # skip strings

                key = self._make_key(module, group, i)
                prev_state = self._state.get(key)

                if prev_state is None:
                    # First ever sample — seed everything
                    self._state[key] = {
                        'prev': float(raw),
                        'target': float(raw),
                        'ema': float(raw),
                        't_update': now,
                        'source_interval': 0.6,
                    }
                else:
                    # EMA filter the new target to smooth out noise
                    ema = prev_state['ema'] + EMA_ALPHA * (float(raw) - prev_state['ema'])
                    # Source interval — how long between real updates
                    src_ivl = now - prev_state['t_update']

                    # The 'prev' for the next lerp segment starts at the
                    # CURRENT displayed position (not the old target) so
                    # we don't snap on mid-segment updates.
                    current_t = min(1.0, (now - prev_state['t_update']) / max(prev_state['source_interval'], 0.05))
                    current_display = prev_state['prev'] + (prev_state['target'] - prev_state['prev']) * current_t

                    self._state[key] = {
                        'prev': current_display,
                        'target': ema,
                        'ema': ema,
                        't_update': now,
                        'source_interval': max(0.05, src_ivl),
                    }

            # Store the full message structure for re-broadcasting
            self._latest_msg[(module, group)] = {
                'module': module,
                'group': group,
                'data': data,
            }

    def get_interpolated(self, module, group):
        """Return a copy of the latest message with linearly interpolated numeric values."""
        key_base = (module, group)
        with self._lock:
            msg = self._latest_msg.get(key_base)
            if not msg:
                return None
            now = time.monotonic()
            out_data = []
            for i, dv in enumerate(msg['data']):
                raw = dv.get('value')
                if not isinstance(raw, (int, float)):
                    out_data.append(dv)
                    continue
                key = self._make_key(module, group, i)
                s = self._state.get(key)
                if s is None:
                    out_data.append(dv)
                    continue
                t = min(1.0, (now - s['t_update']) / max(s['source_interval'], 0.05))
                interp = s['prev'] + (s['target'] - s['prev']) * t
                out_data.append({**dv, 'value': round(interp, 3)})
            return {'module': module, 'group': group, 'data': out_data}

    def get_raw(self, module, group):
        with self._lock:
            return self._latest_msg.get((module, group))


interpolator = Interpolator()

# Track when each (module, group) last received a real data update so the
# broadcast loop only fires for groups with fresh data, not stale ones.
_last_update_time: dict = {}
_last_update_lock = threading.Lock()

def interpolation_broadcast_loop():
    """Background task: runs at ~4Hz, emits interpolated data to clients.
    Batches all fresh group updates into a single emit to minimise WebSocket
    frame overhead."""
    while True:
        socketio.sleep(EMIT_INTERVAL)
        if not SMOOTHING_ENABLED:
            continue  # raw mode: data is emitted directly in ingest()
        now = time.monotonic()
        with _last_update_lock:
            fresh_keys = [k for k, t in _last_update_time.items() if now - t < 5.0]
        if not fresh_keys:
            continue
        batch = []
        for (module, group) in fresh_keys:
            msg = interpolator.get_interpolated(module, group)
            if msg:
                batch.append(msg)
        if batch:
            socketio.emit('diagnostic_batch', batch, namespace='/')


# --- ZMQ Worker ---
class ZMQWorker:
    def __init__(self):
        self.context = zmq.Context()
        self.running = True
        self.sub_sock = None
        self.status_sock = None
        self._cmd_queue = queue.Queue()
        self._cmd_thread = threading.Thread(target=self._command_loop, daemon=True)
        self._cmd_thread.start()
        self._last_ambient = 0

    def _new_req_sock(self):
        s = self.context.socket(zmq.REQ)
        s.connect(ZMQ_REQ_ADDR)
        s.setsockopt(zmq.RCVTIMEO, 15000)
        s.setsockopt(zmq.LINGER, 0)
        return s

    def _command_loop(self):
        logger.info("ZMQ command thread started")
        req_sock = self._new_req_sock()
        while self.running:
            try:
                msg, result_q = self._cmd_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                req_sock.send_json(msg)
                resp = req_sock.recv_json()
                result_q.put(resp)
            except Exception as e:
                logger.warning(f"ZMQ REQ error: {e}. Rebuilding socket...")
                try:
                    req_sock.close()
                except Exception:
                    pass
                req_sock = self._new_req_sock()
                result_q.put({"status": "error", "message": str(e)})

    def connect(self):
        try:
            self.sub_sock = self.context.socket(zmq.SUB)
            self.sub_sock.connect(ZMQ_PUB_ADDR)
            self.sub_sock.subscribe(b"HUDIY_DIAG")
            logger.info(f"Connected to ZMQ PUB at {ZMQ_PUB_ADDR}")
            
            self.status_sock = self.context.socket(zmq.SUB)
            self.status_sock.connect(ZMQ_STATUS_STREAM)
            self.status_sock.subscribe(b"HUDIY_DIAG")
            logger.info(f"Connected to ZMQ STATUS at {ZMQ_STATUS_STREAM}")
            return True
        except Exception as e:
            logger.error(f"ZMQ Connection Failed: {e}")
            return False

    def send_command(self, cmd, module=None, group=None, fire_and_forget=False, **kwargs):
        """Send a command to tp2_worker.
        fire_and_forget=True: queues the message and returns immediately without
        waiting for the ZMQ reply.
        """
        msg = {"cmd": cmd}
        if module is not None: msg['module'] = module
        if group is not None: msg['group'] = group
        msg.update(kwargs)
        result_q = queue.Queue(maxsize=1)
        self._cmd_queue.put((msg, result_q))
        if fire_and_forget:
            return {"status": "queued"}
        try:
            return result_q.get(timeout=20.0)
        except queue.Empty:
            return {"status": "error", "message": "Command queue timeout"}

    def run(self):
        if not self.connect():
            logger.error("Failed to connect ZMQ sockets. Worker stopping.")
            return

        logger.info("Starting ZMQ Subscriber Loop...")
        poller = zmq.Poller()
        if self.sub_sock:
            poller.register(self.sub_sock, zmq.POLLIN)
        if self.status_sock:
            poller.register(self.status_sock, zmq.POLLIN)

        while self.running:
            try:
                drained = 0
                now = time.monotonic()
                
                socks = dict(poller.poll(10))
                
                if self.sub_sock in socks:
                    while self.sub_sock.poll(0):
                        topic, msg = self.sub_sock.recv_multipart()
                        if topic == b'HUDIY_DIAG':
                            payload = json.loads(msg)
                            
                            if payload.get('type') == 'dtc_report':
                                socketio.emit('dtc_report', payload, namespace='/')
                                continue
                                
                            mod = payload.get('module')
                            grp = payload.get('group')
                            data = payload.get('data')
                            self.ingest(mod, grp, data)
                
                if self.status_sock in socks:
                    while self.status_sock.poll(0):
                        topic, msg = self.status_sock.recv_multipart()
                        payload = json.loads(msg)
                        mod = payload.get('module')
                        grp = payload.get('group')
                        data = payload.get('data')
                        self.ingest(mod, grp, data)
                            
                if drained > 0:
                    now = time.monotonic()
                    if now - _recv_log_time >= 5.0:
                        logger.info(f"ZMQ RX rate: {_recv_count} msgs in last 5s")
                        _recv_count = 0
                        _recv_log_time = now
                
                socketio.sleep(0.01)
            except Exception as e:
                logger.error(f"ZMQ Sub Error: {e}")
                socketio.sleep(1)

    def ingest(self, module, group, data):
        """Feed new raw data into the interpolator; emit directly if smoothing is off."""
        interpolator.update(module, group, data)
        # Record arrival time so the broadcast loop knows this group is fresh.
        with _last_update_lock:
            _last_update_time[(module, group)] = time.monotonic()
        if not SMOOTHING_ENABLED:
            socketio.emit('diagnostic_update', {
                'module': module,
                'group': group,
                'data': data
            }, namespace='/')


# Initialize Worker
worker = ZMQWorker()

current_subscriptions = {}
logger_subscriptions = {}


def set_logger_subscriptions(groups):
    """Give the logger its own TP2 subscriptions, independent of the visible tab."""
    global logger_subscriptions
    desired = {}
    for item in groups:
        module = int(item['module'])
        group = int(item['group'])
        entry = desired.setdefault(module, {'normal': set(), 'low': set()})
        entry['low' if item.get('priority') == 'low' else 'normal'].add(group)

    for module in set(logger_subscriptions) | set(desired):
        entry = desired.get(module, {'normal': set(), 'low': set()})
        worker.send_command(
            "SYNC", module=module, groups=sorted(entry['normal']),
            low_priority_groups=sorted(entry['low']), client_id="dataview_logger",
            fire_and_forget=True)
    logger_subscriptions = desired

def sync_subscriptions():
    """Background task: periodically re-asserts subscriptions as a heartbeat.
    Uses fire_and_forget so it never competes with UI commands for the queue."""
    while True:
        socketio.sleep(10.0)
        for mod, groups_dict in list(current_subscriptions.items()):
            worker.send_command("SYNC", module=mod, groups=list(groups_dict['normal']), low_priority_groups=list(groups_dict['low']), client_id="dataview", fire_and_forget=True)
        for mod, groups_dict in list(logger_subscriptions.items()):
            worker.send_command("SYNC", module=mod, groups=list(groups_dict['normal']), low_priority_groups=list(groups_dict['low']), client_id="dataview_logger", fire_and_forget=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/files')
def file_portal_page():
    return render_template('files.html')

@socketio.on('connect')
def handle_connect():
    logger.info(f"Client Connected (sid={request.sid})")
    emit('status', {'mock_mode': False, 'smoothing': SMOOTHING_ENABLED})

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client Disconnected (sid={request.sid})")

@socketio.on('toggle_group')
def handle_toggle(data):
    mod = data.get('module')
    grp = data.get('group')
    action = data.get('action')
    priority = data.get('priority', 'normal')

    if mod is not None and grp is not None:
        mod = int(mod)
        grp = int(grp)
        if mod not in current_subscriptions:
            current_subscriptions[mod] = {'normal': set(), 'low': set()}

        if action == 'add':
            if priority == 'low':
                current_subscriptions[mod]['low'].add(grp)
                current_subscriptions[mod]['normal'].discard(grp)
            else:
                current_subscriptions[mod]['normal'].add(grp)
                current_subscriptions[mod]['low'].discard(grp)
        elif action == 'remove':
            current_subscriptions[mod]['normal'].discard(grp)
            current_subscriptions[mod]['low'].discard(grp)

        mod_entry = current_subscriptions.get(mod)
        if mod_entry is None:
            return  # Another thread already cleaned it up
        normal_now = set(mod_entry['normal'])
        low_now = set(mod_entry['low'])

        worker.send_command("SYNC", module=mod, groups=list(normal_now), low_priority_groups=list(low_now), client_id="dataview", fire_and_forget=True)

        if not normal_now and not low_now:
            current_subscriptions.pop(mod, None)  # safe even if already removed

        # Snapshot push: immediately send whatever cached data we have for this
        if action == 'add':
            if SMOOTHING_ENABLED:
                snap = interpolator.get_interpolated(mod, grp)
            else:
                snap = interpolator.get_raw(mod, grp)
            if snap:
                emit('diagnostic_batch', [snap])

    emit('command_response', {"status": "ok", "action": action, "module": mod, "group": grp, "priority": priority})

@socketio.on('set_smoothing')
def handle_set_smoothing(data):
    global SMOOTHING_ENABLED
    SMOOTHING_ENABLED = bool(data.get('enabled', True))
    logger.info(f"Smoothing {'enabled' if SMOOTHING_ENABLED else 'disabled'}")
    emit('status', {'smoothing': SMOOTHING_ENABLED})

    if not SMOOTHING_ENABLED:
        with interpolator._lock:
            keys = list(interpolator._latest_msg.keys())
        for (module, group) in keys:
            msg = interpolator.get_raw(module, group)
            if msg:
                emit('diagnostic_update', msg)

@socketio.on('request_dtcs')
def handle_request_dtcs(data):
    mod = data.get('module')
    if mod is not None:
        logger.info(f"Client requested DTCs for module {mod}")
        worker.send_command("READ_DTC", module=int(mod), fire_and_forget=True)
        emit('command_response', {"status": "ok", "action": "request_dtcs", "module": mod})
    else:
        emit('command_response', {"status": "error", "message": "Missing module"})

@socketio.on('clear_dtcs')
def handle_clear_dtcs(data):
    mod = data.get('module')
    if mod is not None:
        logger.info(f"Client requested CLEAR DTCs for module {mod}")
        worker.send_command("CLEAR_DTC", module=int(mod), fire_and_forget=True)
        emit('command_response', {"status": "ok", "action": "clear_dtcs", "module": mod})
    else:
        emit('command_response', {"status": "error", "message": "Missing module"})

@socketio.on('log_theme')
def handle_log_theme(theme_data):
    logger.info("=== HUDIY THEME PAYLOAD ===")
    try:
        formatted = json.dumps(theme_data, indent=2)
        for line in formatted.split('\n'):
            logger.info(line)
    except Exception as e:
        logger.error(f"Failed to parse theme data: {theme_data} - {e}")
    logger.info("===========================")

@socketio.on('client_log')
def handle_client_log(data):
    level = data.get('level', 'info')
    args = data.get('args', [])
    
    msg = " ".join(str(a) for a in args)
    if level == 'error':
        logger.error(f"[JS Console] {msg}")
    elif level == 'warn':
        logger.warning(f"[JS Console] {msg}")
    else:
        logger.info(f"[JS Console] {msg}")

# --- Haldex & Logger Helpers & Handlers ---
def send_haldex_command(cmd_dict, timeout_ms=1000):
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.LINGER, 0)
    try:
        sock.connect(ZMQ_HALDEX_CMD)
        sock.send_json(cmd_dict)
        return sock.recv_json()
    except Exception as e:
        logger.debug(f"Haldex command error: {e}")
        return None
    finally:
        sock.close()
        ctx.term()

@socketio.on('get_haldex_status')
def handle_get_haldex_status():
    resp = send_haldex_command({"cmd": "GET_STATUS"})
    if resp and resp.get("status") == "ok":
        emit('haldex_update', resp.get("data", {}))

@socketio.on('set_haldex_mode')
def handle_set_haldex_mode(data):
    mode = data.get('mode', 0)
    resp = send_haldex_command({"cmd": "SET_MODE", "mode": mode})
    if resp and resp.get("status") == "ok":
        socketio.emit('haldex_update', resp.get("data", {}))

@socketio.on('cycle_haldex_mode')
def handle_cycle_haldex_mode():
    resp = send_haldex_command({"cmd": "CYCLE"})
    if resp and resp.get("status") == "ok":
        socketio.emit('haldex_update', resp.get("data", {}))

@socketio.on('get_logger_status')
def handle_get_logger_status():
    emit('logger_update', data_logger.get_status())

@socketio.on('start_logger')
def handle_start_logger(data):
    out = data.get('output') if data else None
    profile = data.get('profile') if data else None
    try:
        status = data_logger.start_recording(profile_name=profile, output_path=out)
        set_logger_subscriptions(status.get('measuring_groups', []))
        socketio.emit('logger_update', status)
    except (ValueError, RuntimeError) as error:
        emit('logger_error', {'message': str(error)})

@socketio.on('stop_logger')
def handle_stop_logger():
    status = data_logger.stop_recording()
    set_logger_subscriptions([])
    socketio.emit('logger_update', status)

@socketio.on('add_logger_marker')
def handle_add_logger_marker(data):
    note = data.get('note', 'Driver Event') if data else 'Driver Event'
    try:
        added = data_logger.add_marker(note)
    except ValueError as error:
        emit('logger_error', {'message': str(error)})
        return
    if added:
        socketio.emit('logger_marker_added', {"note": note, "timestamp": time.time()})

# --- Haldex Flashing Handlers ---
def get_firmware_dir():
    return os.path.abspath(os.path.expanduser(
        _cfg.get('haldex', {}).get('firmware_dir') or '~/haldexfw'))


def get_tunes_dirs():
    # Keep existing tune locations readable during upgrades; create only the new root.
    root = get_firmware_dir()
    os.makedirs(root, exist_ok=True)
    legacy = _cfg.get('haldex', {}).get('tunes_dir')
    dirs = [root] + ([os.path.expanduser(legacy)] if legacy else []) + [
        os.path.expanduser('~/tunes'),
        os.path.join(_base_dir, 'tunes'),
        os.path.join(_base_dir, 'flasher', 'tunes')]
    return list(dict.fromkeys(os.path.abspath(d) for d in dirs if os.path.isdir(d)))


def firmware_paths(directory):
    for current, subdirs, names in os.walk(directory, followlinks=False):
        subdirs[:] = sorted(d for d in subdirs if not d.startswith('.'))
        # A capture directory can contain incomplete pass files. Only its completed
        # image is eligible, even when a failed capture happens to be 320 KiB.
        if 'report.json' in names:
            try:
                with open(os.path.join(current, 'report.json'), encoding='utf-8') as stream:
                    report = json.load(stream)
                names = [report['filename']] if report.get('status') == 'ok' else []
                names = [name for name in names if isinstance(name, str)
                         and name == os.path.basename(name) and not any(c in name for c in '/\\:')]
            except (OSError, ValueError, KeyError, TypeError):
                names = []
        for name in sorted(names):
            path = os.path.join(current, name)
            if name.lower().endswith('.bin') and os.path.isfile(path):
                yield os.path.relpath(path, directory), path


def _flasher_for_module(module):
    if module in (None, 'haldex-gen4', 'haldex', 'awd'):
        if HaldexFlasher is None:
            raise RuntimeError('Haldex flasher is unavailable')
        return HaldexFlasher
    if module in ('pq-eps', 'eps', 'steering'):
        if PQEPSFlasher is None:
            raise RuntimeError('PQ EPS flasher is unavailable')
        return PQEPSFlasher
    raise ValueError('Unknown flash module')


def _validated_artifacts(module='haldex-gen4'):
    """Only controller-policy-validated installed images enter the vehicle workflow."""
    artifacts = {}
    try:
        flasher_class = _flasher_for_module(module)
    except (RuntimeError, ValueError):
        return artifacts
    for directory in get_tunes_dirs():
        for name, path in firmware_paths(directory):
            try:
                prepared = flasher_class.prepare_image(path)
                with open(path, 'rb') as source:
                    artifact_id = hashlib.sha256(source.read()).hexdigest()
                metadata = prepared['metadata']
                artifacts[artifact_id] = {
                    'artifact_id': artifact_id, 'name': name, '_path': path,
                    'size_bytes': os.path.getsize(path),
                    'type': metadata.get('source_kind', '320 KiB firmware image'),
                    'module': 'pq-eps' if flasher_class is PQEPSFlasher else 'haldex-gen4',
                    'modified': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))
                }
            except Exception as error:
                logger.debug('Rejected %s artifact %s: %s', module, name, error)
    return artifacts


def list_available_tunes(module='haldex-gen4'):
    return [{k: v for k, v in artifact.items() if k != '_path'}
            for artifact in _validated_artifacts(module).values()]


_flasher_lock = threading.Lock()
_active_flasher = None
_active_operation = None
_flasher_running = False
_flasher_thread = None
_diagnostic_lock = threading.Lock()
_recovery_file = os.path.expanduser('~/.hudiy/haldex_recovery_required.json')
_readout_root = os.path.join(get_firmware_dir(), 'readouts')


def _readout_download(capture_id, report=False):
    # Only server-generated capture IDs and basenames from our report are allowed.
    if len(capture_id) != 32 or any(c not in '0123456789abcdef' for c in capture_id):
        abort(404)
    directory = os.path.realpath(os.path.join(_readout_root, capture_id))
    if os.path.dirname(directory) != os.path.realpath(_readout_root):
        abort(404)
    report_path = os.path.join(directory, 'report.json')
    try:
        with open(report_path, encoding='utf-8') as handle:
            metadata = json.load(handle)
        if report:
            path = report_path
            filename = capture_id + '_report.json'
        else:
            if metadata.get('status') != 'ok':
                abort(404)
            filename = metadata['filename']
            if not isinstance(filename, str) or not filename or any(c in filename for c in '/\\:') or filename in ('.', '..'):
                abort(404)
            path = os.path.join(directory, filename)
        if os.path.dirname(os.path.realpath(path)) != directory or not os.path.isfile(path):
            abort(404)
    except (OSError, ValueError, KeyError, TypeError):
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename)


@app.route('/haldex/readouts/<capture_id>/image')
def download_haldex_readout(capture_id):
    return _readout_download(capture_id)


@app.route('/haldex/readouts/<capture_id>/report')
def download_haldex_readout_report(capture_id):
    return _readout_download(capture_id, report=True)


class DiagnosticOwnership:
    """Single lease shared by identification and flash/reset sessions.

    Services acknowledge closure, not just receipt of an enable/disable command.
    A lost acknowledgement deliberately retains their inhibit (fail closed).
    """
    def __init__(self):
        self.token = uuid.uuid4().hex
        self.acquired = False

    def acquire(self, allow_incomplete_flash=False):
        resuming_recovery = os.path.exists(_recovery_file)
        if resuming_recovery and not allow_incomplete_flash:
            raise RuntimeError('Controller is in bootloader after an incomplete flash; flash firmware to resume normal diagnostics')
        if not _diagnostic_lock.acquire(blocking=False):
            raise RuntimeError('Another diagnostic operation is in progress')
        try:
            for service, response in (
                ('Haldex mode sender', send_haldex_command({
                    'cmd': 'QUIESCE', 'owner': self.token,
                    'recovery_resume': resuming_recovery}, timeout_ms=12000)),
                ('TP2 worker', worker.send_command(
                    'QUIESCE', owner=self.token,
                    recovery_resume=resuming_recovery)),
            ):
                if not response or response.get('status') != 'ok' or response.get('quiescent') is not True or response.get('owner') != self.token:
                    detail = response.get('message', 'invalid acknowledgement') if isinstance(response, dict) else 'no reply'
                    raise RuntimeError(f'{service} did not acknowledge diagnostic pause: {detail}')
            self.acquired = True
        except Exception:
            # A failed second handshake must not strand the first service under
            # this token. Mismatched RELEASE requests are safely rejected.
            try:
                worker.send_command('RELEASE', owner=self.token,
                                    recovery_required=resuming_recovery)
            except Exception:
                pass
            try:
                send_haldex_command({'cmd': 'RELEASE', 'owner': self.token,
                                     'recovery_required': resuming_recovery})
            except Exception:
                pass
            _diagnostic_lock.release()
            raise

    def release(self, recovery_required=False):
        if not self.acquired:
            return
        try:
            for response in (worker.send_command(
                    'RELEASE', owner=self.token,
                    recovery_required=recovery_required),
                    send_haldex_command({
                        'cmd': 'RELEASE', 'owner': self.token,
                        'recovery_required': recovery_required})):
                if not response or response.get('status') != 'ok':
                    logger.error('Diagnostic ownership release failed: %s', response)
        finally:
            self.acquired = False
            _diagnostic_lock.release()


def _recovery_marker(active):
    if active:
        os.makedirs(os.path.dirname(_recovery_file), exist_ok=True)
        temporary = _recovery_file + '.tmp'
        with open(temporary, 'w') as handle:
            json.dump({'recovery_required': True, 'time': time.time()}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, _recovery_file)
        if hasattr(os, 'O_DIRECTORY'):
            directory_fd = os.open(os.path.dirname(_recovery_file), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    elif os.path.exists(_recovery_file):
        os.unlink(_recovery_file)


class FlashOperationLog:
    RETAIN_OPERATIONS = 2

    def __init__(self):
        directory = os.path.expanduser('~/.hudiy/flash_logs')
        os.makedirs(directory, exist_ok=True)
        self._prune(directory, keep=self.RETAIN_OPERATIONS - 1)
        self.path = os.path.join(directory, uuid.uuid4().hex + '.log')
        self.handle = open(self.path, 'x', encoding='utf-8', buffering=1)
        self.write('Operation log opened before diagnostic ownership')
        os.fsync(self.handle.fileno())

    @staticmethod
    def _prune(directory, keep):
        """Keep only the newest complete operation logs before opening a new one."""
        try:
            logs = []
            for name in os.listdir(directory):
                stem, extension = os.path.splitext(name)
                if extension != '.log' or len(stem) != 32 or any(c not in '0123456789abcdef' for c in stem):
                    continue
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    logs.append((os.path.getmtime(path), path))
            logs.sort(reverse=True)
            for _, path in logs[keep:]:
                for target in (path, path + '.json'):
                    try:
                        os.unlink(target)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            logger.warning('Could not prune old flash logs: %s', exc)

    def write(self, message):
        self.handle.write(time.strftime('%Y-%m-%dT%H:%M:%S') + ' ' + str(message) + '\n')

    def finish(self, result):
        self.write('TERMINAL ' + json.dumps(result, default=str, sort_keys=True))
        self.handle.flush()
        os.fsync(self.handle.fileno())
        with open(self.path + '.json', 'w', encoding='utf-8') as terminal:
            json.dump(result, terminal, default=str, indent=2)
            terminal.flush()
            os.fsync(terminal.fileno())

    def close(self):
        self.handle.close()


@socketio.on('get_tunes_list')
def handle_get_tunes_list(data=None):
    module = data.get('module', 'haldex-gen4') if isinstance(data, dict) else 'haldex-gen4'
    try:
        _flasher_for_module(module)
        emit('tunes_list', list_available_tunes(module))
    except Exception as error:
        emit('tunes_list', [])
        emit('haldex_flash_error', {'message': str(error), 'stopped': True})


@socketio.on('get_ecu_flash_info')
def handle_get_ecu_flash_info(data=None):
    module = data.get('module', 'haldex-gen4') if isinstance(data, dict) else 'haldex-gen4'
    def read_info():
        owner = DiagnosticOwnership()
        flasher = None
        try:
            flasher_class = _flasher_for_module(module)
            owner.acquire()
            flasher = flasher_class(
                channel=_cfg.get('interfaces', {}).get('can', {}).get('diagnostic', 'can0'))
            result = flasher.read_ecu_info()
            result['module'] = 'pq-eps' if flasher_class is PQEPSFlasher else 'haldex-gen4'
            socketio.emit('ecu_flash_info', result)
        except Exception as error:
            socketio.emit('ecu_flash_info', {'error': str(error), 'connected': False})
        finally:
            try:
                if flasher:
                    flasher.close()
            finally:
                owner.release()
    socketio.start_background_task(read_info)


@socketio.on('start_haldex_flash')
def handle_start_haldex_flash(data):
    global _flasher_running, _flasher_thread
    try:
        if not isinstance(data, dict) or set(data) - {'artifact_id', 'dry_run', 'start_addr', 'end_addr', 'module'}:
            raise ValueError('Only module, artifact_id, dry_run and region bounds are accepted')
        module = data.get('module', 'haldex-gen4')
        if module in (None, 'haldex-gen4', 'haldex', 'awd'):
            flasher_class = HaldexFlasher
        elif module in ('pq-eps', 'eps', 'steering'):
            flasher_class = PQEPSFlasher
        else:
            raise ValueError('Unknown flash module')
        if flasher_class is None:
            raise RuntimeError(f'{module} flasher is unavailable')
        artifact_id = data.get('artifact_id')
        dry_run = data.get('dry_run', False)
        if not isinstance(artifact_id, str) or len(artifact_id) != 64:
            raise ValueError('A validated artifact_id is required')
        if type(dry_run) is not bool:
            raise ValueError('dry_run must be boolean')
        artifact = (_validated_artifacts() if module in (None, 'haldex-gen4', 'haldex', 'awd')
                    else _validated_artifacts(module)).get(artifact_id)
        if artifact is None:
            raise ValueError('Artifact is not an installed validated vehicle image')
        default_bounds = ((0x0a000, 0x5ffff) if module in ('pq-eps', 'eps', 'steering')
                          else (0x18000, 0x4ffff))
        start_addr = data.get('start_addr', default_bounds[0])
        end_addr = data.get('end_addr', default_bounds[1])
        flasher_class.prepare_image(
            artifact['_path'], start_addr=start_addr, end_addr=end_addr)
    except Exception as error:
        emit('haldex_flash_error', {'message': str(error), 'recovery_required': os.path.exists(_recovery_file), 'stopped': not _flasher_running})
        return
    with _flasher_lock:
        if _flasher_running:
            emit('haldex_flash_error', {'message': 'A flash operation is already in progress', 'stopped': False})
            return
        _flasher_running = True

    def progress(stage, percent, detail, speed, eta_sec=0.0):
        logger.info('Flash %s %.1f%% %s', stage, percent, detail)
        socketio.emit('haldex_flash_progress', {'stage': stage, 'percent': round(percent, 1),
                      'detail': detail, 'speed': round(speed, 1), 'eta_sec': round(eta_sec, 1)})

    def flash_worker():
        global _flasher_running, _active_flasher, _active_operation
        owner = DiagnosticOwnership()
        flasher = None
        recovery = False
        marked = False
        operation_log = None
        traffic_operation = None
        try:
            operation_log = FlashOperationLog()
            flasher = flasher_class(channel=_cfg.get('interfaces', {}).get('can', {}).get('diagnostic', 'can0'), progress_cb=progress, log_cb=operation_log.write)
            with _flasher_lock:
                _active_flasher = flasher
                _active_operation = 'flash'
            # Offline preparation occurs before services change or hardware opens.
            flasher_class.prepare_image(artifact['_path'], start_addr=start_addr, end_addr=end_addr)
            if not dry_run:
                traffic_operation = flashing_operation()
                traffic_operation.__enter__()
                # An incomplete prior attempt deliberately leaves normal traffic
                # inhibited, but the normal flasher is the path that completes it.
                owner.acquire(allow_incomplete_flash=True)
                set_flashing_mode(True)
                _recovery_marker(True)  # Crash during flashing must not restart polling.
                marked = True
            result = flasher.flash_binary(artifact['_path'], start_addr=start_addr, end_addr=end_addr, dry_run=dry_run)
            recovery = bool(result.get('recovery_required', False))
            if not dry_run and not result.get('application_verified', result.get('boot_verified', False)):
                recovery = bool(getattr(flasher, 'destructive_started', False))
            result['recovery_required'] = recovery
            result['stopped'] = True
            result['log_path'] = operation_log.path
            operation_log.finish(result)
            logger.info('Flash terminal result: %s', json.dumps(result, default=str))
            socketio.emit('haldex_flash_complete', result)
        except Exception as error:
            recovery = bool(flasher and (getattr(flasher, 'destructive_started', False) or getattr(flasher, 'recovery_required', False)))
            logger.exception('%s flash stopped', module)
            failure = dict(getattr(flasher, 'last_result', {}) if flasher else {},
                           message=str(error), recovery_required=recovery, stopped=True,
                           log_path=operation_log.path if operation_log else None)
            if operation_log:
                try:
                    operation_log.finish(failure)
                except Exception:
                    logger.exception('Could not persist terminal flash result')
            socketio.emit('haldex_flash_error', failure)
        finally:
            try:
                if flasher:
                    flasher.close()
            finally:
                try:
                    if marked and not recovery:
                        _recovery_marker(False)
                    owner.release(recovery_required=recovery)
                finally:
                    try:
                        if operation_log:
                            operation_log.close()
                    finally:
                        try:
                            if traffic_operation:
                                traffic_operation.__exit__(None, None, None)
                        finally:
                            with _flasher_lock:
                                _flasher_running = False
                                _active_flasher = None
                                _active_operation = None

    _flasher_thread = threading.Thread(target=flash_worker, daemon=True)
    socketio.emit('haldex_flash_started', {
        'artifact_id': artifact_id, 'dry_run': dry_run, 'module': module})
    try:
        _flasher_thread.start()
    except Exception as error:
        with _flasher_lock:
            _flasher_running = False
        socketio.emit('haldex_flash_error', {'message': str(error), 'stopped': True})



@socketio.on('start_haldex_readout')
def handle_start_haldex_readout(data):
    global _flasher_running, _flasher_thread
    try:
        from flasher.readout import HaldexReadout, validate_selection
        from flasher.controllers.pq_eps.protocol import validate_eps_range
        if not isinstance(data, dict) or set(data) - {'start_addr', 'end_addr', 'module', 'readout_kind'}:
            raise ValueError('Only module, readout kind and readout bounds are accepted')
        module = data.get('module', 'haldex-gen4')
        readout_kind = data.get('readout_kind', 'firmware')
        if module in (None, 'haldex-gen4', 'haldex', 'awd'):
            if readout_kind != 'firmware':
                raise ValueError('Haldex only supports firmware readout')
            reader_class = HaldexReadout
            start_addr = data.get('start_addr', 0x18000)
            end_addr = data.get('end_addr', 0x4ffff)
            validate_selection(start_addr, end_addr)
            readout_kwargs = {'start_addr': start_addr, 'end_addr': end_addr}
        elif module in ('pq-eps', 'eps', 'steering'):
            if readout_kind == 'eeprom':
                if 'start_addr' in data or 'end_addr' in data:
                    raise ValueError('EPS EEPROM readout has a fixed 1 KiB range')
                from flasher.readout import PQEPSEepromReadout
                reader_class = PQEPSEepromReadout
                start_addr = end_addr = None
                readout_kwargs = {}
            elif readout_kind == 'firmware':
                from flasher.readout import PQEPSReadout
                reader_class = PQEPSReadout
                start_addr = data.get('start_addr', 0x5e000)
                end_addr = data.get('end_addr', 0x5efff)
                validate_eps_range(start_addr, end_addr - start_addr + 1)
                readout_kwargs = {'start_addr': start_addr, 'end_addr': end_addr}
            else:
                raise ValueError('Unknown EPS readout kind')
        else:
            raise ValueError('Unknown readout module')
    except Exception as error:
        emit('haldex_readout_error', {'message': str(error), 'recovery_required': False, 'stopped': not _flasher_running})
        return
    with _flasher_lock:
        if _flasher_running:
            emit('haldex_readout_error', {'message': 'A flash or readout operation is already in progress', 'stopped': False})
            return
        _flasher_running = True

    def progress(stage, percent, detail, speed, eta_sec=0.0):
        socketio.emit('haldex_readout_progress', {'stage': stage, 'percent': round(percent, 1),
                      'detail': detail, 'speed': round(speed, 1), 'eta_sec': round(eta_sec, 1)})

    def readout_worker():
        global _flasher_running, _active_flasher, _active_operation
        owner = DiagnosticOwnership()
        reader = None
        operation_log = None
        traffic_operation = None
        traffic_entered = False
        event = 'haldex_readout_error'
        result = {'recovery_required': False, 'stopped': True}
        try:
            operation_log = FlashOperationLog()
            reader = reader_class(channel=_cfg.get('interfaces', {}).get('can', {}).get('diagnostic', 'can0'),
                                  progress_cb=progress, log_cb=operation_log.write)
            with _flasher_lock:
                _active_flasher = reader
                _active_operation = 'readout'
            traffic_operation = flashing_operation()
            traffic_operation.__enter__()
            traffic_entered = True
            owner.acquire()
            set_flashing_mode(True)
            result.update(reader.readout(_readout_root, **readout_kwargs))
            event = 'haldex_readout_complete'
        except Exception as error:
            logger.exception('%s readout stopped', module)
            result.update(getattr(reader, 'last_result', {}) if reader else {})
            result['message'] = str(error)
        finally:
            # Cleanup failures must still release the busy flag and be visible to UI.
            for cleanup in (lambda: reader.close() if reader else None,
                            lambda: owner.release(),
                            lambda: traffic_operation.__exit__(None, None, None) if traffic_entered else None):
                try:
                    cleanup()
                except Exception as error:
                    logger.exception('Readout cleanup failed')
                    result.update(cleanup_attention=True, message=str(error))
                    event = 'haldex_readout_error'
            result.update(recovery_required=False, stopped=True)
            capture_id = result.get('capture_id')
            if isinstance(capture_id, str) and len(capture_id) == 32 and all(c in '0123456789abcdef' for c in capture_id):
                result['report_url'] = '/haldex/readouts/' + capture_id + '/report'
                if event == 'haldex_readout_complete' and result.get('status') == 'ok':
                    result['download_url'] = '/haldex/readouts/' + capture_id + '/image'
            if operation_log:
                result['log_path'] = operation_log.path
                try:
                    operation_log.finish(result)
                except Exception:
                    logger.exception('Could not persist terminal readout log')
                finally:
                    try:
                        operation_log.close()
                    except Exception:
                        logger.exception('Could not close readout log')
            with _flasher_lock:
                _flasher_running = False
                _active_flasher = None
                _active_operation = None
            socketio.emit(event, result)

    _flasher_thread = threading.Thread(target=readout_worker, daemon=True)
    socketio.emit('haldex_readout_started', {
        'module': module, 'readout_kind': readout_kind,
        'start_addr': start_addr, 'end_addr': end_addr})
    try:
        _flasher_thread.start()
    except Exception as error:
        with _flasher_lock:
            _flasher_running = False
        socketio.emit('haldex_readout_error', {'message': str(error), 'recovery_required': False, 'stopped': True})


@socketio.on('cancel_haldex_flash')
def handle_cancel_haldex_flash():
    with _flasher_lock:
        # Firmware flashing is intentionally non-cancellable. Interrupting it
        # after erase begins only leaves an incomplete controller. Readout is
        # non-destructive and remains safe to cancel.
        if _active_flasher and _active_operation == 'readout':
            _active_flasher.abort_requested = True
            emit('haldex_flash_cancel_requested', {'message': 'Cancellation requested; waiting for operation to stop', 'stopped': False})


def haldex_status_subscriber_loop():
    """Background loop listening for haldex status updates and emitting to clients."""
    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.set_hwm(100)
    try:
        sub.connect(ZMQ_HALDEX_STATUS)
        sub.subscribe(b"HALDEX_STATUS")
        logger.info(f"Connected to Haldex status stream {ZMQ_HALDEX_STATUS}")
    except Exception as e:
        logger.warning(f"Could not connect to Haldex status stream: {e}")
        return

    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    while True:
        try:
            events = dict(poller.poll(500))
            if sub in events:
                topic, msg_bytes = sub.recv_multipart(flags=zmq.NOBLOCK)
                status_dict = json.loads(msg_bytes.decode('utf-8'))
                socketio.emit('haldex_update', status_dict)
            else:
                socketio.sleep(0.1)
        except Exception:
            socketio.sleep(0.5)

if __name__ == '__main__':
    data_logger.start()
    socketio.start_background_task(worker.run)

    logger.info("Starting Flask-SocketIO Server on port 5003")
    socketio.start_background_task(sync_subscriptions)
    socketio.start_background_task(interpolation_broadcast_loop)
    socketio.start_background_task(haldex_status_subscriber_loop)
    try:
        socketio.run(app, host='0.0.0.0', port=5003, allow_unsafe_werkzeug=True)
    finally:
        data_logger.close()
