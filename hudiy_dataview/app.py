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
data_cache = {
    'engine': {},
    'transmission': {}, 
    'awd': {}
}
MOCK_MODE = False

# --- ZMQ Worker ---
class ZMQWorker:
    def __init__(self):
        self.context = zmq.Context()
        self.running = True
        self.sub_sock = None
        # Command queue: items are (msg_dict, result_queue)
        self._cmd_queue = queue.Queue()
        self._cmd_thread = threading.Thread(target=self._command_loop, daemon=True)
        self._cmd_thread.start()

    def _new_req_sock(self):
        """Create a fresh REQ socket connected to tp2_worker."""
        s = self.context.socket(zmq.REQ)
        s.connect(ZMQ_REQ_ADDR)
        s.setsockopt(zmq.RCVTIMEO, 2000)
        s.setsockopt(zmq.LINGER, 0)
        return s

    def _command_loop(self):
        """Single thread that owns the REQ socket. Processes commands serially."""
        logger.info("ZMQ command thread started")
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
            # Subscriber (Data Stream)
            self.sub_sock = self.context.socket(zmq.SUB)
            self.sub_sock.connect(ZMQ_PUB_ADDR)
            self.sub_sock.subscribe(b"HUDIY_DIAG")
            logger.info(f"Connected to ZMQ PUB at {ZMQ_PUB_ADDR}")
            return True
        except Exception as e:
            logger.error(f"ZMQ Connection Failed: {e}")
            return False

    def send_command(self, cmd, module=None, group=None):
        if MOCK_MODE:
            logger.info(f"MOCK CMD: {cmd} Mod:{module} Grp:{group}")
            return {"status": "mock_ok"}

        msg = {"cmd": cmd}
        if module is not None: msg['module'] = module
        if group is not None: msg['group'] = group

        # Put the command on the queue and wait for the serial thread to process it
        result_q = queue.Queue(maxsize=1)
        self._cmd_queue.put((msg, result_q))
        try:
            return result_q.get(timeout=5.0)
        except queue.Empty:
            return {"status": "error", "message": "Command queue timeout"}

    def run(self):
        global MOCK_MODE
        if not self.connect() and not MOCK_MODE:
             logger.warning("Starting in MOCK MODE due to ZMQ failure.")
             MOCK_MODE = True

        if MOCK_MODE:
            self.run_mock()
        else:
            self.run_real()

    def run_mock(self):
        logger.info("Starting MOCK Data Generator...")
        while self.running:
            socketio.sleep(0.5)
            # Generate random data mimicking TP2 structure
            
            # --- Engine Mock ---
            # Group 3: RPM, MAF, Throttle, Ign Angle
            rpm = random.randint(800, 7000)
            maf = random.uniform(2.0, 180.0)
            throttle = random.uniform(0, 100)
            ign_angle = random.uniform(0, 45)
            self.emit_data(0x01, 3, [
                {'value': rpm, 'unit': 'RPM'},
                {'value': maf, 'unit': 'g/s'},
                {'value': throttle, 'unit': '%'},
                {'value': ign_angle, 'unit': '°KW'}
            ])

            # Group 20: Timing Retardation Cyl 1-4
            ret_1 = random.uniform(0, 12) if random.random() > 0.7 else 0
            ret_2 = random.uniform(0, 12) if random.random() > 0.7 else 0
            ret_3 = random.uniform(0, 12) if random.random() > 0.7 else 0
            ret_4 = random.uniform(0, 12) if random.random() > 0.7 else 0
            self.emit_data(0x01, 20, [
                {'value': ret_1, 'unit': '°KW'},
                {'value': ret_2, 'unit': '°KW'},
                {'value': ret_3, 'unit': '°KW'},
                {'value': ret_4, 'unit': '°KW'}
            ])

            # Group 106: Fuel Rail
            fr_spec = random.uniform(40, 110)
            fr_act = fr_spec + random.uniform(-2, 2)
            fp_duty = random.uniform(40, 90)
            f_temp = random.uniform(30, 80)
            self.emit_data(0x01, 106, [
                {'value': fr_spec, 'unit': 'bar'},
                {'value': fr_act, 'unit': 'bar'},
                {'value': fp_duty, 'unit': '%'},
                {'value': f_temp, 'unit': 'C'}
            ])

            # Group 115: Boost
            # RPM already generated
            load = random.uniform(10, 150)
            boost_spec = random.randint(300, 2500)
            boost_act = boost_spec + random.randint(-100, 100)
            self.emit_data(0x01, 115, [
                {'value': rpm, 'unit': 'RPM'},
                {'value': load, 'unit': '%'},
                {'value': boost_spec, 'unit': 'mbar'},
                {'value': boost_act, 'unit': 'mbar'}
            ])

            # Group 134: Temperatures
            oil_t = random.randint(70, 110)
            amb_t = random.randint(15, 35)
            iat = amb_t + random.randint(5, 30)
            out_t = random.randint(80, 105)
            self.emit_data(0x01, 134, [
                {'value': oil_t, 'unit': 'C'},
                {'value': amb_t, 'unit': 'C'},
                {'value': iat, 'unit': 'C'},
                {'value': out_t, 'unit': 'C'}
            ])
            
            # Group 2: General (redundant but requested)
            self.emit_data(0x01, 2, [
                {'value': rpm, 'unit': 'RPM'},
                {'value': load, 'unit': '%'},
                {'value': random.uniform(0, 5), 'unit': 'ms'},
                {'value': maf, 'unit': 'g/s'}
            ])
            
            # Transmission Mock
            # Group 11: Speed(G501), Torque(K1), Current(V1), Pressure(G193)
            ts1 = random.randint(0, 3000)
            tq1 = random.randint(0, 400)
            cur1 = random.uniform(0, 1.5)
            pre1 = random.uniform(0, 20)
            self.emit_data(0x02, 11, [
                 {'value': ts1, 'unit': 'RPM'},
                 {'value': tq1, 'unit': 'Nm'},
                 {'value': cur1, 'unit': 'A'},
                 {'value': pre1, 'unit': 'bar'}
            ])
            
            # Group 12: Speed(G502), Torque(K2), Current(V2), Pressure(G194)
            ts2 = random.randint(0, 3000)
            tq2 = random.randint(0, 400)
            cur2 = random.uniform(0, 1.5)
            pre2 = random.uniform(0, 20)
            self.emit_data(0x02, 12, [
                 {'value': ts2, 'unit': 'RPM'},
                 {'value': tq2, 'unit': 'Nm'},
                 {'value': cur2, 'unit': 'A'},
                 {'value': pre2, 'unit': 'bar'}
            ])
            
            # Group 16: Selector Travel (1-3, 2-4, 5-N, 6-R)
            s1 = random.uniform(-100, 100)
            s2 = random.uniform(-100, 100)
            s3 = random.uniform(-100, 100)
            s4 = random.uniform(-100, 100)
            self.emit_data(0x02, 16, [
                  {'value': s1, 'unit': 'mm'},
                  {'value': s2, 'unit': 'mm'},
                  {'value': s3, 'unit': 'mm'},
                  {'value': s4, 'unit': 'mm'}
            ])
            
            # Group 19: Temps (Fluid, Module, Clutch, Status)
            temp_f = random.randint(60, 110)
            temp_m = random.randint(40, 90)
            temp_c = random.randint(80, 150)
            status = "IDLE" if random.random() > 0.5 else "ACTIVE"
            self.emit_data(0x02, 19, [
                 {'value': temp_f, 'unit': 'C'},
                 {'value': temp_m, 'unit': 'C'},
                 {'value': temp_c, 'unit': 'C'},
                 {'value': status, 'unit': ''}
            ])

            # AWD Mock
            # Group 1: Status (Oil Temp, Plate Temp, Voltage)
            awd_temp1 = random.randint(20, 90)
            awd_temp2 = random.randint(20, 150)
            awd_volt = random.uniform(12.0, 14.5)
            self.emit_data(0x22, 1, [
                 {'value': awd_temp1, 'unit': 'C'},
                 {'value': awd_temp2, 'unit': 'C'},
                 {'value': awd_volt, 'unit': 'V'},
                 {'value': 0, 'unit': ''}
            ])

            # Group 3: Hydraulics (Pressure, Torque, Valve, Current)
            awd_pres = random.uniform(0, 60)
            awd_tq = random.uniform(0, 2000)
            awd_valve = random.randint(0, 100)
            awd_cur = random.uniform(0, 4.0)
            self.emit_data(0x22, 3, [
                 {'value': awd_pres, 'unit': 'bar'},
                 {'value': awd_tq, 'unit': 'Nm'},
                 {'value': awd_valve, 'unit': '%'},
                 {'value': awd_cur, 'unit': 'A'}
            ])

            # Group 5: Modes
            val_out = random.randint(0, 255)
            veh_mode = "NORMAL" if random.random() > 0.5 else "SPORT"
            slip_ctrl = "ACTIVE" if random.random() > 0.8 else "IDLE"
            op_mode = "OK"
            self.emit_data(0x22, 5, [
                 {'value': val_out, 'unit': ''},
                 {'value': veh_mode, 'unit': ''},
                 {'value': slip_ctrl, 'unit': ''},
                 {'value': op_mode, 'unit': ''}
            ])

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
                        self.emit_data(mod, grp, data)
                socketio.sleep(0.01)
            except Exception as e:
                logger.error(f"ZMQ Sub Error: {e}")
                socketio.sleep(1)

    def emit_data(self, module, group, data):
        # Broadcast to all connected clients
        socketio.emit('diagnostic_update', {
            'module': module,
            'group': group,
            'data': data
        })

# Initialize Worker
worker = ZMQWorker()

current_subscriptions = {}  # {module_id: set([group1, group2])}

def sync_subscriptions():
    """Background task to continuously enforce the app's desired subscriptions."""
    while True:
        socketio.sleep(3.0)
        # Avoid syncing if no clients connected, or just sync anyway to keep it alive
        for mod, groups in list(current_subscriptions.items()):
            worker.send_command("SYNC", module=mod, groups=list(groups), client_id="dataview")

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    logger.info("Client Connected")
    emit('status', {'mock_mode': MOCK_MODE})

@socketio.on('toggle_group')
def handle_toggle(data):
    # data: {module: int, group: int, action: 'add'|'remove'}
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
            
        # Immediately trigger a sync for responsiveness
        worker.send_command("SYNC", module=mod, groups=list(current_subscriptions[mod]), client_id="dataview")
        
    emit('command_response', {"status": "ok", "action": action, "module": mod, "group": grp})

if __name__ == '__main__':
    # Determine mode based on args or environment
    if '--mock' in sys.argv:
        MOCK_MODE = True
        logger.warning("FORCED MOCK MODE")

    # Start Worker in Background
    worker_thread = threading.Thread(target=worker.run, daemon=True)
    worker_thread.start()

    logger.info("Starting Flask-SocketIO Server on port 5003")
    socketio.start_background_task(sync_subscriptions)
    socketio.run(app, host='0.0.0.0', port=5003, allow_unsafe_werkzeug=True)
