import os
import sys
import json
import time
import threading
import queue
import logging
import random
import zmq
from flask import Flask, render_template, jsonify, request
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
except Exception as _e:
    logging.warning(f"Could not load config.json, using default ZMQ addresses: {_e}")
    ZMQ_PUB_ADDR = _DEFAULT_TP2_STREAM
    ZMQ_REQ_ADDR = _DEFAULT_TP2_COMMAND

# --- Setup Flask & SocketIO ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'hudiy_secret'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*')

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
MOCK_MODE = False
SMOOTHING_ENABLED = True  # default on

# --- Server-Side Interpolator ---
EMIT_INTERVAL = 0.05    # 20Hz broadcast rate
EMA_ALPHA     = 0.92     # applied to incoming source values before linear interp (0=frozen, 1=raw)

class Interpolator:
    """
    Receives raw diagnostic messages at low rate (~0.5 Hz).
    Re-emits linearly interpolated values to all SocketIO clients at ~20 Hz.

    When smoothing is disabled, it just passes raw values through at the
    natural data rate without the 20Hz loop.
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
        """Called when a new raw message arrives from the TP2 / mock source."""
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


def interpolation_broadcast_loop():
    """Background task: runs at 20Hz, emits interpolated data to all clients."""
    while True:
        socketio.sleep(EMIT_INTERVAL)
        if not SMOOTHING_ENABLED:
            continue  # raw mode: data is emitted directly in update()
        with interpolator._lock:
            keys = list(interpolator._latest_msg.keys())
        for (module, group) in keys:
            msg = interpolator.get_interpolated(module, group)
            if msg:
                socketio.emit('diagnostic_update', msg)


# --- ZMQ Worker ---
class ZMQWorker:
    def __init__(self):
        self.context = zmq.Context()
        self.running = True
        self.sub_sock = None
        self._cmd_queue = queue.Queue()
        self._cmd_thread = threading.Thread(target=self._command_loop, daemon=True)
        self._cmd_thread.start()

    def _new_req_sock(self):
        s = self.context.socket(zmq.REQ)
        s.connect(ZMQ_REQ_ADDR)
        s.setsockopt(zmq.RCVTIMEO, 2000)
        s.setsockopt(zmq.LINGER, 0)
        return s

    def _command_loop(self):
        logger.info("ZMQ command thread started")
        if MOCK_MODE:
            # In mock mode send_command() short-circuits before touching the queue,
            # so this thread has nothing to do. Skip socket creation entirely —
            # ZMQ IPC is not supported on Windows and would crash here.
            return
        req_sock = self._new_req_sock()
        while True:
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
            return True
        except Exception as e:
            logger.error(f"ZMQ Connection Failed: {e}")
            return False

    def send_command(self, cmd, module=None, group=None, **kwargs):
        if MOCK_MODE:
            logger.info(f"MOCK CMD: {cmd} Mod:{module} Grp:{group}")
            return {"status": "mock_ok"}
        msg = {"cmd": cmd}
        if module is not None: msg['module'] = module
        if group is not None: msg['group'] = group
        msg.update(kwargs)
        result_q = queue.Queue(maxsize=1)
        self._cmd_queue.put((msg, result_q))
        try:
            return result_q.get(timeout=5.0)
        except queue.Empty:
            return {"status": "error", "message": "Command queue timeout"}

    def run(self):
        global MOCK_MODE
        if not MOCK_MODE:
            if not self.connect():
                logger.warning("Starting in MOCK MODE due to ZMQ failure.")
                MOCK_MODE = True

        if MOCK_MODE:
            self.run_mock()
        else:
            self.run_real()

    def run_mock(self):
        """
        Simulates ~0.5 Hz real sensor data with dramatic state changes so that
        the difference between smoothing ON and OFF is clearly visible.
        Each loop iteration picks a random engine 'state' and jumps to it,
        producing the kind of raw noise the interpolator is designed to hide.
        """
        logger.info("Starting MOCK Data Generator (0.5Hz source rate, dramatic jumps)...")

        # Discrete engine states: (rpm, boost_mbar)
        ENGINE_STATES = [
            (820,   200),   # idle
            (1800,  600),   # light cruise
            (2800,  950),   # steady cruise
            (4200, 1600),   # spirited
            (5800, 2100),   # hard pull
            (6800, 2400),   # WOT
        ]

        state_rpm, state_boost = ENGINE_STATES[0]
        clutch_1_active = True   # alternates to simulate DCT clutch handoff
        clutch_cycle    = 0      # counts iterations; flips clutch every 10

        while self.running:
            # Jump to a new random state each cycle — creates big abrupt deltas
            state_rpm, state_boost = random.choice(ENGINE_STATES)

            # Add meaningful per-sample noise on top of the state value
            rpm       = state_rpm   + random.uniform(-250, 250)
            boost     = state_boost + random.uniform(-200, 200)
            maf       = rpm * 0.025 + random.uniform(-8, 8)
            throttle  = min(100.0, max(0.0, (rpm - 800) / 62.0 + random.uniform(-15, 15)))
            ign_angle = random.uniform(5, 38)

            # --- Engine ---
            self.ingest(0x01, 3, [
                {'value': round(rpm, 1),       'unit': 'RPM'},
                {'value': round(maf, 2),       'unit': 'g/s'},
                {'value': round(throttle, 1),  'unit': '%'},
                {'value': round(ign_angle, 1), 'unit': '°KW'}
            ])

            # Retard values — jump between 0 and spiky values
            ret_vals = [round(random.uniform(0, 12), 2) if random.random() > 0.6 else 0.0 for _ in range(4)]
            self.ingest(0x01, 20, [{'value': v, 'unit': '°KW'} for v in ret_vals])

            # Fuel rail — pressure swings noticeably under load
            fr_base = 60.0 + (state_rpm / 7000.0) * 45.0
            fr_spec = fr_base + random.uniform(-12, 12)
            self.ingest(0x01, 106, [
                {'value': round(fr_spec, 2),                         'unit': 'bar'},
                {'value': round(fr_spec + random.uniform(-5, 5), 2), 'unit': 'bar'},
                {'value': round(random.uniform(30, 100), 1),         'unit': '%'},
                {'value': round(random.uniform(25, 90), 1),          'unit': 'C'}
            ])

            self.ingest(0x01, 115, [
                {'value': round(rpm, 1),                               'unit': 'RPM'},
                {'value': round(random.uniform(5, 160), 1),            'unit': '%'},
                {'value': round(boost, 0),                             'unit': 'mbar'},
                {'value': round(boost + random.uniform(-150, 150), 0), 'unit': 'mbar'}
            ])

            self.ingest(0x01, 134, [
                {'value': random.randint(75, 115), 'unit': 'C'},
                {'value': random.randint(12, 38),  'unit': 'C'},
                {'value': random.randint(25, 70),  'unit': 'C'},
                {'value': random.randint(75, 110), 'unit': 'C'}
            ])

            self.ingest(0x01, 2, [
                {'value': round(rpm, 1),                    'unit': 'RPM'},
                {'value': round(random.uniform(5, 160), 1), 'unit': '%'},
                {'value': round(random.uniform(0, 6), 2),   'unit': 'ms'},
                {'value': round(maf, 2),                    'unit': 'g/s'}
            ])

            # --- Transmission ---
            # Hold each clutch active for 10 cycles (~6 s) before handing off
            clutch_cycle += 1
            if clutch_cycle >= 10:
                clutch_1_active = not clutch_1_active
                clutch_cycle    = 0
            ratio    = random.choice([3.5, 2.0, 1.4, 1.0, 0.75])
            out_rpm  = int(rpm / ratio)
            out_torq = int(random.uniform(80, 420))
            idle_rpm = int(rpm / random.choice([3.5, 2.0, 1.4, 1.0, 0.75]))  # next gear pre-selected

            # Active clutch: carrying full load, high current & pressure
            # Idle clutch:   pre-engaged next gear — low torque, near-zero current
            self.ingest(0x02, 11, [
                {'value': out_rpm  if clutch_1_active else idle_rpm,                     'unit': 'RPM'},
                {'value': out_torq if clutch_1_active else random.randint(0, 20),        'unit': 'Nm'},
                {'value': round(random.uniform(1.2, 2.0), 2) if clutch_1_active else round(random.uniform(0, 0.15), 2), 'unit': 'A'},
                {'value': round(random.uniform(12, 25), 1)   if clutch_1_active else round(random.uniform(0, 2), 1),    'unit': 'bar'}
            ])
            self.ingest(0x02, 12, [
                {'value': idle_rpm  if clutch_1_active else out_rpm,                     'unit': 'RPM'},
                {'value': random.randint(0, 20) if clutch_1_active else out_torq,        'unit': 'Nm'},
                {'value': round(random.uniform(0, 0.15), 2) if clutch_1_active else round(random.uniform(1.2, 2.0), 2), 'unit': 'A'},
                {'value': round(random.uniform(0, 2), 1)    if clutch_1_active else round(random.uniform(12, 25), 1),   'unit': 'bar'}
            ])
            self.ingest(0x02, 16, [{'value': round(random.uniform(-120, 120), 1), 'unit': 'mm'} for _ in range(4)])
            self.ingest(0x02, 19, [
                {'value': random.randint(55, 115),              'unit': 'C'},
                {'value': random.randint(35, 95),               'unit': 'C'},
                {'value': random.randint(75, 160),              'unit': 'C'},
                {'value': "IDLE" if rpm < 1500 else "ACTIVE",   'unit': ''}
            ])

            # --- AWD ---
            awd_torq = round(random.uniform(0, 2200), 0)
            self.ingest(0x22, 1, [
                {'value': random.randint(18, 95),               'unit': 'C'},
                {'value': random.randint(18, 160),              'unit': 'C'},
                {'value': round(random.uniform(11.8, 14.6), 2), 'unit': 'V'},
                {'value': 0,                                    'unit': ''}
            ])
            self.ingest(0x22, 3, [
                {'value': round(random.uniform(0, 70), 1),  'unit': 'bar'},
                {'value': awd_torq,                         'unit': 'Nm'},
                {'value': random.randint(0, 100),           'unit': '%'},
                {'value': round(random.uniform(0, 5.0), 2), 'unit': 'A'}
            ])
            self.ingest(0x22, 5, [
                {'value': random.randint(0, 255),                    'unit': ''},
                {'value': "SPORT" if state_rpm > 3000 else "NORMAL", 'unit': ''},
                {'value': "ACTIVE" if awd_torq > 500 else "IDLE",    'unit': ''},
                {'value': "OK",                                       'unit': ''}
            ])

            # Single sleep at the bottom — all groups update at ~1.6 Hz
            socketio.sleep(0.625)

    def run_real(self):
        logger.info("Starting ZMQ Subscriber Loop...")
        while self.running:
            try:
                if self.sub_sock.poll(500):
                    topic, msg = self.sub_sock.recv_multipart()
                    if topic == b'HUDIY_DIAG':
                        payload = json.loads(msg)
                        mod = payload.get('module')
                        grp = payload.get('group')
                        data = payload.get('data')
                        self.ingest(mod, grp, data)
                socketio.sleep(0.01)
            except Exception as e:
                logger.error(f"ZMQ Sub Error: {e}")
                socketio.sleep(1)

    def ingest(self, module, group, data):
        """Feed new raw data into the interpolator; emit directly if smoothing is off."""
        interpolator.update(module, group, data)
        if not SMOOTHING_ENABLED:
            # Pass-through: emit raw immediately.
            # Explicit namespace='/' is required when calling from a plain thread
            # (i.e. not a socketio.start_background_task) to avoid silent failures.
            socketio.emit('diagnostic_update', {
                'module': module,
                'group': group,
                'data': data
            }, namespace='/')


# Initialize Worker
worker = ZMQWorker()

current_subscriptions = {}

def sync_subscriptions():
    """Background task to continuously enforce the app's desired subscriptions."""
    while True:
        socketio.sleep(3.0)
        for mod, groups in list(current_subscriptions.items()):
            worker.send_command("SYNC", module=mod, groups=list(groups), client_id="dataview")

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    logger.info("Client Connected")
    emit('status', {'mock_mode': MOCK_MODE, 'smoothing': SMOOTHING_ENABLED})

@socketio.on('toggle_group')
def handle_toggle(data):
    mod = data.get('module')
    grp = data.get('group')
    action = data.get('action')

    if mod is not None and grp is not None:
        mod = int(mod)
        grp = int(grp)
        if mod not in current_subscriptions:
            current_subscriptions[mod] = set()

        if action == 'add':
            current_subscriptions[mod].add(grp)
        elif action == 'remove':
            current_subscriptions[mod].discard(grp)

        worker.send_command("SYNC", module=mod, groups=list(current_subscriptions[mod]), client_id="dataview")

    emit('command_response', {"status": "ok", "action": action, "module": mod, "group": grp})

@socketio.on('set_smoothing')
def handle_set_smoothing(data):
    global SMOOTHING_ENABLED
    SMOOTHING_ENABLED = bool(data.get('enabled', True))
    logger.info(f"Smoothing {'enabled' if SMOOTHING_ENABLED else 'disabled'}")
    emit('status', {'smoothing': SMOOTHING_ENABLED})

    if not SMOOTHING_ENABLED:
        # Immediately push the latest known values so the client doesn't go
        # dark waiting up to 1.5 s for the next mock/real tick.
        with interpolator._lock:
            keys = list(interpolator._latest_msg.keys())
        for (module, group) in keys:
            msg = interpolator.get_raw(module, group)
            if msg:
                emit('diagnostic_update', msg)

if __name__ == '__main__':
    if '--mock' in sys.argv:
        MOCK_MODE = True
        logger.warning("FORCED MOCK MODE")

    worker_thread = threading.Thread(target=worker.run, daemon=True)
    worker_thread.start()

    logger.info("Starting Flask-SocketIO Server on port 5003")
    socketio.start_background_task(sync_subscriptions)
    socketio.start_background_task(interpolation_broadcast_loop)
    socketio.run(app, host='0.0.0.0', port=5003, allow_unsafe_werkzeug=True)
