import os
import sys
import json
import time
import threading
import queue
import logging
import zmq
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

# Configuration — load ZMQ addresses from config.json (same as tp2_worker)
_DEFAULT_TP2_STREAM  = 'ipc:///run/rnse_control/tp2_stream.ipc'
_DEFAULT_TP2_COMMAND = 'ipc:///run/rnse_control/tp2_cmd.ipc'
try:
    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(_base_dir, 'config.json')) as _f:
        _cfg = json.load(_f)
    ZMQ_PUB_ADDR = _cfg['zmq'].get('tp2_stream',  _DEFAULT_TP2_STREAM)
    ZMQ_REQ_ADDR = _cfg['zmq'].get('tp2_command', _DEFAULT_TP2_COMMAND)
    ZMQ_CAN_ADDR = _cfg['zmq'].get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc')
except Exception as _e:
    logging.warning(f"Could not load config.json, using default ZMQ addresses: {_e}")
    ZMQ_PUB_ADDR = _DEFAULT_TP2_STREAM
    ZMQ_REQ_ADDR = _DEFAULT_TP2_COMMAND
    ZMQ_CAN_ADDR = 'ipc:///run/rnse_control/can_stream.ipc'

# --- Setup Flask & SocketIO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'hudiy_secret'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*',
                    ping_interval=60, ping_timeout=120)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (DataView) %(message)s')
logger = logging.getLogger(__name__)

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
        self.can_sock = None
        self._cmd_queue = queue.Queue()
        self._cmd_thread = threading.Thread(target=self._command_loop, daemon=True)
        self._cmd_thread.start()
        self._last_ambient = 0

    def _new_req_sock(self):
        s = self.context.socket(zmq.REQ)
        s.connect(ZMQ_REQ_ADDR)
        s.setsockopt(zmq.RCVTIMEO, 2000)
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
            
            self.can_sock = self.context.socket(zmq.SUB)
            self.can_sock.connect(ZMQ_CAN_ADDR)
            for t in [b"CAN_35B", b"CAN_0x35B", b"CAN_555", b"CAN_0x555", b"CAN_527", b"CAN_0x527"]:
                self.can_sock.subscribe(t)
            logger.info(f"Connected to ZMQ CAN at {ZMQ_CAN_ADDR}")
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
            return result_q.get(timeout=5.0)
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
        if self.can_sock:
            poller.register(self.can_sock, zmq.POLLIN)

        while self.running:
            try:
                drained = 0
                now = time.monotonic()
                
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
                    
                if self.can_sock in socks:
                    while self.can_sock.poll(0):
                        topic, msg = self.can_sock.recv_multipart()
                        t_str = topic.decode()
                        
                        try:
                            payload = bytes.fromhex(json.loads(msg)['data_hex'])
                            if '35B' in t_str and len(payload) >= 4:
                                rpm = (payload[2] * 256 + payload[1]) / 4.0
                                coolant = (payload[3] * 0.75) - 64
                                # logger.info(f"[CAN] 35B -> RPM: {rpm}, Coolant: {coolant}")
                                
                            if '555' in t_str and len(payload) >= 8:
                                boost = (payload[3] + payload[4] * 256) * 0.08
                                oil_temp = payload[7] - 60
                                # logger.info(f"[CAN] 555 -> Boost: {boost}, Oil: {oil_temp}")
                                self.ingest(0, 0, [
                                    {'value': oil_temp, 'unit': 'C'},
                                    {'value': getattr(self, '_last_ambient', 0), 'unit': 'C'}
                                ])
                                
                            if '527' in t_str and len(payload) >= 6:
                                ambient = (payload[5] * 0.5) - 50
                                self._last_ambient = ambient
                                oil_now = 0
                                with interpolator._lock:
                                    msg_obj = interpolator.get_raw(0, 0)
                                    if msg_obj and len(msg_obj['data']) > 0:
                                        oil_now = msg_obj['data'][0]['value']
                                self.ingest(0, 0, [
                                    {'value': oil_now, 'unit': 'C'},
                                    {'value': ambient, 'unit': 'C'}
                                ])
                        except Exception as e:
                            logger.debug(f"Error parsing CAN message {t_str}: {e}")
                            
                # Check CAN Socket
                if self.can_sock:
                    while True:
                        try:
                            topic, msg = self.can_sock.recv_multipart(flags=zmq.NOBLOCK)
                            t_str = topic.decode()
                            
                            try:
                                payload = bytes.fromhex(json.loads(msg)['data_hex'])
                                if '35B' in t_str and len(payload) >= 4:
                                    rpm = (payload[2] * 256 + payload[1]) / 4.0
                                    coolant = (payload[3] * 0.75) - 64
                                    # logger.info(f"[CAN] 35B -> RPM: {rpm}, Coolant: {coolant}")
                                    
                                if '555' in t_str and len(payload) >= 8:
                                    boost = (payload[3] + payload[4] * 256) * 0.08
                                    oil_temp = payload[7] - 60
                                    # logger.info(f"[CAN] 555 -> Boost: {boost}, Oil: {oil_temp}")
                                    self.ingest(0, 0, [
                                        {'value': oil_temp, 'unit': 'C'},
                                        {'value': getattr(self, '_last_ambient', 0), 'unit': 'C'}
                                    ])
                                
                                if '527' in t_str and len(payload) >= 6:
                                    ambient = (payload[5] * 0.5) - 50
                                    self._last_ambient = ambient
                                    # logger.info(f"[CAN] 527 -> Ambient: {ambient}")
                                    oil_now = 0
                                    with interpolator._lock:
                                        msg = interpolator.get_raw(0, 0)
                                        if msg and len(msg['data']) > 0:
                                            oil_now = msg['data'][0]['value']
                                    self.ingest(0, 0, [
                                        {'value': oil_now, 'unit': 'C'},
                                        {'value': ambient, 'unit': 'C'}
                                    ])
                            except Exception as e:
                                logger.debug(f"Error parsing CAN message {t_str}: {e}")
                        except zmq.Again:
                            break
                    
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

def sync_subscriptions():
    """Background task: periodically re-asserts subscriptions as a heartbeat.
    Uses fire_and_forget so it never competes with UI commands for the queue."""
    while True:
        socketio.sleep(10.0)
        for mod, groups_dict in list(current_subscriptions.items()):
            worker.send_command("SYNC", module=mod, groups=list(groups_dict['normal']), low_priority_groups=list(groups_dict['low']), client_id="dataview", fire_and_forget=True)

@app.route('/')
def index():
    return render_template('index.html')

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


if __name__ == '__main__':
    socketio.start_background_task(worker.run)

    logger.info("Starting Flask-SocketIO Server on port 5003")
    socketio.start_background_task(sync_subscriptions)
    socketio.start_background_task(interpolation_broadcast_loop)
    socketio.run(app, host='0.0.0.0', port=5003, allow_unsafe_werkzeug=True)
