"""Local web inputs/routines for the real DIS engine and exclusive bench service."""
import argparse
from collections import deque
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import queue
import random
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
PAGES = ['app_media', 'app_nav', 'app_phone', 'app_car_info', 'app_acceleration_test',
         'app_coverart', 'app_openpilot','app_easteregg']
INPUTS = ['stalk_up','stalk_down','wheel_up','wheel_down','wheel_click','wheel_mode',
          'wheel_mode_double','wheel_click_double','wheel_mode_hold','wheel_click_hold']
TOPICS = ['HUDIY_MEDIA', 'HUDIY_NAV', 'HUDIY_NAV_DISTANCE', 'HUDIY_NAV_STATUS', 'HUDIY_PHONE',
          'HUDIY_VALUES', 'HUDIY_DIAG', 'HUDIY_OPENPILOT', 'HUDIY_COVERART']
MANEUVERS = [{'value': k, 'label': v} for k, v in [(1,'Depart'), (2,'Name change'),
    (3,'Slight turn'), (4,'Turn'), (5,'Sharp turn'), (6,'U-turn'), (7,'On-ramp'),
    (8,'Off-ramp'), (9,'Fork'), (10,'Merge'), (11,'Enter roundabout'),
    (12,'Exit roundabout'), (13,'Roundabout'), (14,'Straight'),
    (16,'Ferry'), (17,'Train'), (19,'Destination')]]


def validate(action):
    def finite_json(value,depth=0):
        if depth>12:raise ValueError('JSON nesting exceeds 12 levels')
        if isinstance(value,float) and not math.isfinite(value):raise ValueError('JSON numbers must be finite')
        if isinstance(value,dict):
            for key,item in value.items():finite_json(item,depth+1)
        elif isinstance(value,list):
            for item in value:finite_json(item,depth+1)
    finite_json(action)
    if not isinstance(action, dict):
        raise ValueError('Expected a JSON object')
    kind = action.get('action')
    if kind == 'data':
        if action.get('topic') not in TOPICS or not isinstance(action.get('payload'), dict):
            raise ValueError('Use a supported HUDIY topic and object payload')
        payload=action['payload'];topic=action['topic']
        for key in ('title','artist','album','position','duration','source_label','description','caller_name','caller_id','state','connection_state'):
            if key in payload and (not isinstance(payload[key],str) or len(payload[key])>512):
                raise ValueError(key+' must be text, at most 512 characters')
        for key in ('playing','has_route','active','call_active','maneuver_angle_present','is_new_track'):
            if key in payload and type(payload[key]) is not bool:raise ValueError(key+' must be boolean')
        for key in ('distance','label'):
            if key in payload and payload[key] is not None and (isinstance(payload[key],bool) or not isinstance(payload[key],(str,int,float))):
                raise ValueError(key+' must be a distance label or number')
        for key,lo,hi in [('maneuver_type',0,19),('maneuver_side',1,3),('maneuver_angle',0,360),('battery',0,100),('signal',0,100),('source_id',0,255)]:
            if key in payload and (isinstance(payload[key],bool) or not isinstance(payload[key],(int,float)) or not math.isfinite(payload[key]) or not lo<=payload[key]<=hi):
                raise ValueError(key+f' must be {lo}..{hi}')
        for key in ('maneuver_type','maneuver_side'):
            if key in payload and type(payload[key]) is not int:raise ValueError(key+' must be an integer')
        if topic in ('HUDIY_VALUES','HUDIY_DIAG'):
            key='values' if topic=='HUDIY_VALUES' else 'data'
            samples=payload.get(key,[])
            if not isinstance(samples,list) or len(samples)>128 or any(not isinstance(s,dict) for s in samples):
                raise ValueError(key+' must be a list of at most 128 sample objects')
            if topic=='HUDIY_VALUES' and any(not isinstance(s.get('id'),str) or len(s['id'])>128 for s in samples):
                raise ValueError('Every value sample requires a string id')
        if topic=='HUDIY_PHONE' and payload.get('state','IDLE') not in ('IDLE','INCOMING','ALERTING','DIALING','ACTIVE'):
            raise ValueError('Unknown phone state')
    elif kind == 'workspace':
        from vehicle_data.workspace import validate_workspace
        validate_workspace(action.get('document'))
    elif kind == 'logging':
        cmd=action.get('cmd')
        if cmd not in ('START','MARK','STOP','STATUS'):raise ValueError('Unknown logging command')
        if cmd=='START' and (not isinstance(action.get('profile_id'),str) or len(action['profile_id'])>64):raise ValueError('Choose a recording profile')
        if cmd=='MARK' and (not isinstance(action.get('note','Mark'),str) or not 1<=len(action.get('note','Mark').strip())<=256):raise ValueError('Marker must contain 1..256 characters')
    elif kind == 'page':
        if action.get('page') not in PAGES:
            raise ValueError('Unknown page')
    elif kind == 'input':
        if action.get('event') not in INPUTS:
            raise ValueError('Unknown virtual input')
    elif kind == 'can':
        cid=action.get('can_id');data=action.get('data_hex')
        if type(cid) is not int or not 0<=cid<=0x7ff or not isinstance(data,str):raise ValueError('Use an 11-bit receive ID and data_hex')
        try:raw=bytes.fromhex(data)
        except ValueError:raise ValueError('Invalid hexadecimal receive data')
        if not 1<=len(raw)<=8:raise ValueError('Receive fixture must contain 1..8 bytes')
    elif kind == 'config':
        if action.get('icon_style') not in ('stock', 'bitmap') or type(action.get('high_resolution')) is not bool:
            raise ValueError('Choose stock/bitmap and a boolean resolution setting')
        distance = action.get('approach_bar_max_distance')
        if isinstance(distance, bool) or not isinstance(distance, (float, int)) or not math.isfinite(distance) or not 1 <= distance <= 10000:
            raise ValueError('Approach threshold must be 1..10000 meters')
    elif kind == 'routine':
        if action.get('name') not in ('mixed', 'approach', 'random', 'stop'):
            raise ValueError('Unknown routine')
        interval = action.get('interval', 2)
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or not .5 <= interval <= 30:
            raise ValueError('Routine interval must be 0.5..30 seconds')
        seed = action.get('seed', 123)
        if type(seed) is not int or not 0 <= seed <= 2**32-1:
            raise ValueError('Seed must be a 32-bit nonnegative integer')
    else:
        raise ValueError('Unknown action')
    return action


def configuration(repo, base):
    cfg = json.loads((repo / 'config.json').read_text(encoding='utf-8'))
    endpoint = lambda n: f'tcp://127.0.0.1:{n}'
    addresses = cfg.setdefault('interfaces', {}).setdefault('zmq', {})
    for key in ('metric_stream', 'status_stream', 'tp2_stream', 'vehicle_data_stream', 'input_control_stream'):
        addresses[key] = endpoint(base)
    addresses.update(can_raw_stream=endpoint(base+1), dis_draw=endpoint(base+2),
                     dis_status=endpoint(base+3), dis_display_status=endpoint(base+4),
                     vehicle_data_command=endpoint(base+6), system_events=endpoint(base+7),data_logs_command=endpoint(base+8))
    cfg['bench_control'] = endpoint(base+5)
    cfg.setdefault('can_ids', {})
    center = cfg['display']['center_display']
    center.update(applist=[p[4:] for p in PAGES], start_inactive=False)
    center.setdefault('navigation', {}).update(icon_style='stock', auto_switch=False, claim_on_nav=False)
    cfg['display'].setdefault('phone', {})['claim_on_phone'] = False
    center.setdefault('coverart', {})['brief'] = False
    cfg['features'] = dict(cfg.get('features', {}), debug_mode=False)
    return cfg


def prepare_workspace(cfg,runtime):
    """Import the production DataView document once; all bench writes stay local."""
    from vehicle_data.workspace import WorkspaceStore
    source=WorkspaceStore(cfg)
    source_exists=source.path.exists()
    imported=not (runtime/'workspace.json').exists()
    cfg.setdefault('data_logs',{}).update(workspace_path=str(runtime/'workspace.json'),directory=str(runtime/'logs'))
    target=WorkspaceStore(cfg)
    if not target.path.exists():target.save(source.load())
    else:target.load()  # Surface malformed local documents rather than replacing them.
    cfg['bench_workspace_source']=str(source.path)
    cfg['bench_workspace_origin']=('saved production document' if source_exists else 'production default document') if imported else 'existing local bench document'
    return cfg


class Bridge:
    """The worker owns every ZMQ socket; HTTP handlers only enqueue."""
    def __init__(self, cfg, runtime):
        self.cfg, self.runtime = cfg, runtime
        self.actions = queue.Queue(maxsize=128)
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.ready = threading.Event()
        self.last_service = self.last_display = 0
        self.error = None
        self.state = dict(connected=False, service_state='WAITING', display={}, last_ack=None,
                          last_nack=None, routine=dict(name='stopped', running=False, step=0),
                          data=dict(media={}, nav={}, phone={}, values={}), config=dict(
                              icon_style='stock', high_resolution=cfg['display']['center_display']['high_resolution'],
                              approach_bar_max_distance=cfg['display']['center_display']['navigation'].get('approach_bar_max_distance',300)),
                          pages=PAGES, maneuvers=MANEUVERS, inputs=INPUTS, logs=[])
        self.logs = deque(maxlen=80)
        self.rng = random.Random(123)
        self.routine_step = 0
        self.recorder = None
        self.action_id = 0
        self.next_step = 0
        self.interval = 2
        self.state['engine'] = dict(applied=0,pending_seq=None)
        self.state['last_queued'] = 0
        self.thread = threading.Thread(target=self.run, name='bench-input-bridge', daemon=False)

    def log(self, message):
        with self.lock:
            self.logs.append(dict(time=time.time(), message=message))

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.state)
            now = time.monotonic()
            result.update(connected=now-self.last_service < 3 and now-self.last_display < 3,
                          service_age_s=None if not self.last_service else round(now-self.last_service,1),
                          display_age_s=None if not self.last_display else round(now-self.last_display,1),
                          logs=list(self.logs), error=self.error)
            return result

    def init_data_logs(self):
        from hudiy_dataview.data_logs import DataLogs
        self.recorder=DataLogs(self.cfg)  # No acquisition workers or vehicle broker.
        self.refresh_data_logs()

    def refresh_data_logs(self):
        if self.recorder is None:return
        from vehicle_data.catalog import CATALOG
        self.state['dataview']=dict(workspace=self.recorder.workspace.load(),
            catalog=[dict(id=v['id'],name=v.get('name',v['id']),unit=v.get('unit')) for v in CATALOG.values()],
            workspace_path=str(self.recorder.workspace.path),source_workspace_path=self.cfg.get('bench_workspace_source'),
            workspace_origin=self.cfg.get('bench_workspace_origin'),
            log_directory=str(self.recorder.directory),
            acquisition='submitted HUDIY_VALUES only',recording=self.recorder.status(),sessions=self.recorder.sessions(),
            last_result=getattr(self,'last_logger_result',None),error=self.recorder.last_error or None)

    def enqueue(self, action):
        validate(action)
        try:
            self.actions.put_nowait(action)
        except queue.Full:
            raise ValueError('Input queue is full; wait for the bridge')

    def apply(self, action, pub, control, manual=True):
        kind = action['action']
        if manual and kind != 'routine':
            self.state['routine']['running'] = False
        if kind == 'data':
            topic, payload = action['topic'], action['payload']
            key = {'HUDIY_MEDIA':'media','HUDIY_NAV':'nav','HUDIY_PHONE':'phone','HUDIY_VALUES':'values'}.get(topic)
            if key:
                # These are complete callbacks, not shallow patch messages.
                self.state['data'][key] = copy.deepcopy(payload)
            if topic == 'HUDIY_VALUES' and self.recorder is not None:
                self.recorder.ingest(dict(payload,client_id=self.recorder.CLIENT_ID))
            if topic == 'HUDIY_NAV_DISTANCE':
                self.state['data']['nav']['distance'] = payload.get('label','')
            self.log(f'{topic}: {json.dumps(payload)[:160]}')
        elif kind == 'workspace':
            self.recorder.save_config(action['document'])
            self.refresh_data_logs()
        elif kind == 'logging':
            self.last_logger_result=self.recorder.command(action)
            self.refresh_data_logs()
            self.log('Logger: '+json.dumps(self.last_logger_result))
        elif kind == 'routine':
            self.interval = action.get('interval',2)
            self.rng = random.Random(action.get('seed',123))
            self.routine_step = 0
            self.next_step = time.monotonic()
            self.state['routine'] = dict(name=action['name'], running=action['name']!='stop',step=0)
            self.log('Routine: '+action['name'])
        else:
            if kind == 'config':
                self.state['config'] = {k:action[k] for k in ('icon_style','high_resolution','approach_bar_max_distance')}
            self.log(json.dumps(action))
        if kind != 'routine':
            self.action_id += 1
            control.send_json(dict(action,id=self.action_id))
            self.state['last_queued'] = self.action_id
            journal=getattr(self,'journal',None)
            if journal is not None:
                journal.write(json.dumps(dict(time=time.time(),event='queued',id=self.action_id,action=action),allow_nan=False)+'\n')

    def routine_actions(self):
        name = self.state['routine']['name']
        step = self.routine_step
        self.routine_step += 1
        self.state['routine']['step'] = step + 1
        threshold = self.state['config']['approach_bar_max_distance']
        if name == 'approach':
            distances = [threshold*1.5, threshold+1, threshold, *[threshold*i/10 for i in range(9,-1,-1)], threshold+1]
            distance = distances[step % len(distances)]
            if step % len(distances) == 0:
                return [dict(action='data', topic='HUDIY_NAV', payload=dict(maneuver_type=4,maneuver_side=1,
                    description='APPROACH TEST ROAD',distance=f'{distance:g} m')),dict(action='page',page='app_nav')]
            return [dict(action='data',topic='HUDIY_NAV_DISTANCE',payload=dict(label=f'{distance:g} m'))]
        if name == 'mixed':
            phase = step % 18
            turn = MANEUVERS[(step//18) % len(MANEUVERS)]['value']
            if phase == 0:
                return [dict(action='data',topic='HUDIY_PHONE',payload=dict(state='IDLE')),
                        dict(action='data',topic='HUDIY_MEDIA',payload=dict(title=f'Bench track {step//18+1}',
                             artist='RNS-E HUDIY',album='Media / navigation transitions',position='1:08',duration='4:32',playing=True)),
                        dict(action='page',page='app_media')]
            if phase == 3:
                return [dict(action='data',topic='HUDIY_NAV',payload=dict(maneuver_type=turn,maneuver_side=1+(step//18)%2,
                    maneuver_angle=(step//18*45)%360,maneuver_angle_present=True,
                    description='LONG ROAD NAME FOR SCROLLING' if step//18%2 else 'MAIN STREET',distance=f'{threshold*1.5:g} m')),
                    dict(action='page',page='app_nav')]
            if 4 <= phase <= 14:
                return [dict(action='data',topic='HUDIY_NAV_DISTANCE',payload=dict(label=f'{threshold*(14-phase)/10:g} m'))]
            if phase == 15:
                return [dict(action='data',topic='HUDIY_NAV_DISTANCE',payload=dict(label=f'{threshold+1:g} m'))]
            if phase == 16:
                return [dict(action='data',topic='HUDIY_PHONE',payload=dict(state='INCOMING',caller_name='Bench caller',caller_id='01234')),
                        dict(action='page',page='app_phone')]
            return []
        turn = self.rng.choice(MANEUVERS)['value']
        if self.rng.random() < .3:
            return [dict(action='data',topic='HUDIY_MEDIA',payload=dict(title=f'Seeded track {self.rng.randrange(1000)}',
                    artist=self.rng.choice(['Bench artist','Long artist name to test scrolling']),album='Random sequence',playing=True)),
                    dict(action='page',page='app_media')]
        return [dict(action='data',topic='HUDIY_PHONE',payload=dict(state='IDLE')),
                dict(action='data',topic='HUDIY_NAV',payload=dict(maneuver_type=turn,maneuver_side=self.rng.choice([1,2,3]),
                maneuver_angle=self.rng.randrange(360),maneuver_angle_present=True,
                description=self.rng.choice(['OAK AVENUE','STATION ROAD','LONG STREET NAME TEST']),
                distance=f'{self.rng.choice([0,30,100,threshold,threshold+1,1200]):g} m')),
                dict(action='page',page='app_nav')]

    def run(self):
        import zmq
        context = zmq.Context()
        sockets = []
        try:
            self.journal=(self.runtime/'input_events.jsonl').open('a',encoding='utf-8',buffering=1)
            self.init_data_logs()
            z = self.cfg['interfaces']['zmq']
            pub = context.socket(zmq.PUB); sockets.append(pub); pub.bind(z['metric_stream'])
            control = context.socket(zmq.PUSH); sockets.append(control)
            control.setsockopt(zmq.SNDHWM,128);control.setsockopt(zmq.SNDTIMEO,100)
            control.bind(self.cfg['bench_control'])
            status = context.socket(zmq.SUB); sockets.append(status); status.subscribe(b'');status.connect(z['dis_status'])
            display = context.socket(zmq.SUB);sockets.append(display);display.subscribe(b'');display.connect(z['dis_display_status'])
            # This answers only value lease requests, not diagnostics or CAN.
            leases = context.socket(zmq.REP);sockets.append(leases);leases.bind(z['vehicle_data_command'])
            logger_commands=context.socket(zmq.REP);sockets.append(logger_commands);logger_commands.bind(z['data_logs_command'])
            for sock in sockets:
                sock.setsockopt(zmq.LINGER,0)
            self.ready.set()
            while not self.stop.is_set():
                with self.lock:
                    for _ in range(32):
                        try: action = self.actions.get_nowait()
                        except queue.Empty: break
                        self.apply(action,pub,control)
                    while status.poll(0):
                        message = status.recv_string()
                        self.last_service=time.monotonic()
                        if message.startswith('DIS_STATE '): self.state['service_state']=message.split()[1]
                        elif message.startswith('DRAW_ACK '): self.state['last_ack']=dict(seq=int(message.split()[1]),time=time.time())
                        elif message.startswith('DRAW_NACK '):
                            self.state['last_nack']=dict(seq=int(message.split()[1]),time=time.time());self.log(message)
                            self.state['routine']['running']=False
                        else: self.log(message)
                    while display.poll(0):
                        parts=display.recv_multipart()
                        if len(parts)==2:
                            if parts[0]==b'DIS_DISPLAY_STATUS':self.state['display']=json.loads(parts[1]);self.last_display=time.monotonic()
                            elif parts[0]==b'BENCH_ENGINE_STATUS':self.state['engine']=json.loads(parts[1])
                    if logger_commands.poll(0):
                        request=logger_commands.recv_json()
                        self.last_logger_result=self.recorder.command(request)
                        logger_commands.send_json(self.last_logger_result)
                    self.recorder.expire()
                    if time.monotonic()>=getattr(self,'_next_logger_status',0):
                        self.refresh_data_logs();self._next_logger_status=time.monotonic()+.5
                    if leases.poll(0):
                        request=leases.recv_json(); leases.send_json(dict(ok=True,bench=True,values=request.get('values',[])))
                    if (self.state['routine']['running'] and self.snapshot()['connected']
                            and self.state['service_state']=='READY' and not self.state['engine'].get('pending_seq')
                            and self.state['engine'].get('applied')==self.state['last_queued']
                            and time.monotonic()>=self.next_step):
                        for action in self.routine_actions(): self.apply(action,pub,control,manual=False)
                        self.next_step=time.monotonic()+self.interval
                self.stop.wait(.02)
            control.send_json(dict(action='shutdown'))
            time.sleep(.15)
        except Exception as exc:
            self.error=repr(exc);self.log('Bridge failed: '+repr(exc));self.ready.set();self.stop.set()
        finally:
            if self.recorder is not None:
                try:self.recorder.close()
                except Exception as exc:self.error='Logger close: '+repr(exc)
            for sock in reversed(sockets):sock.close(linger=0)
            context.term()
            if getattr(self,'journal',None) is not None:self.journal.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=HERE.parents[1])
    parser.add_argument('--runtime',type=Path,default=HERE/'runtime')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--base-port',type=int,default=18650)
    parser.add_argument('--draw-port',type=int)
    parser.add_argument('--status-port',type=int)
    parser.add_argument('--no-engine',action='store_true',help='Bridge-only troubleshooting; never fakes readiness')
    args=parser.parse_args()
    if not 1024<=args.port<=65535 or not 1024<=args.base_port<=65527:
        parser.error('Ports must be nonprivileged and within range')
    args.runtime.mkdir(parents=True,exist_ok=True)
    sentinel=args.runtime/'stop.flag'
    if sentinel.is_file():sentinel.unlink()
    deps=args.repo.parent/'clusterRE/.bench_deps'
    if deps.is_dir() and sys.version_info[:2]==(3,11) and __import__('struct').calcsize('P')==4:
        sys.path.insert(0,str(deps))
        os.environ['PYTHONPATH']=str(deps)+os.pathsep+os.environ.get('PYTHONPATH','')
    sys.path.insert(0,str(args.repo))
    cfg=prepare_workspace(configuration(args.repo,args.base_port),args.runtime)
    if args.draw_port: cfg['interfaces']['zmq']['dis_draw']=f'tcp://127.0.0.1:{args.draw_port}'
    if args.status_port: cfg['interfaces']['zmq']['dis_status']=f'tcp://127.0.0.1:{args.status_port}'
    config_path=args.runtime/'bench_display_config.json'
    config_path.write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf-8')
    source_files=sorted((args.repo/'dis_client').rglob('*.py'))
    source_files += sorted((args.repo/'dis_client').glob('*.json'))
    (args.runtime/'client_sources_at_start.json').write_text(json.dumps(
        {str(path.relative_to(args.repo)):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},indent=2)+'\n')
    bridge=Bridge(cfg,args.runtime)
    engine=None

    class Handler(BaseHTTPRequestHandler):
        def send(self,status,payload,content_type='application/json'):
            data=payload if isinstance(payload,bytes) else json.dumps(payload,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if urlsplit(self.path).path=='/api/state':
                state=bridge.snapshot();state['engine_alive']=engine is not None and engine.poll() is None
                self.send(200,state)
            elif self.path in ('/','/index.html'):
                self.send(200,(HERE/'static/index.html').read_bytes(),'text/html; charset=utf-8')
            else:self.send(404,dict(error='Not found'))
        def do_POST(self):
            # Browser tooling is local. Reject cross-site writes (including
            # DNS rebinding) rather than expose a CAN controller to websites.
            host=self.headers.get('Host','')
            allowed={f'127.0.0.1:{args.port}',f'localhost:{args.port}'}
            origin=self.headers.get('Origin')
            if host not in allowed or (origin and origin not in {'http://'+h for h in allowed}):
                self.send(403,dict(error='Local same-origin requests only'));return
            if self.path!='/api/action':self.send(404,dict(error='Not found'));return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=65536:raise ValueError('Payload must be 1..65536 bytes')
                action=json.loads(self.rfile.read(length),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
                bridge.enqueue(action);self.send(202,dict(queued=True))
            except (ValueError,TypeError,KeyError) as exc:self.send(400,dict(error=str(exc)))
        def log_message(self,*args):pass

    class ExclusiveHTTPServer(ThreadingHTTPServer):
        allow_reuse_address=False
        def server_bind(self):
            import socket
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            super().server_bind()
    server=ExclusiveHTTPServer(('127.0.0.1',args.port),Handler)
    server.daemon_threads=True
    server.timeout=.2
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    try:
        bridge.thread.start();bridge.ready.wait(5)
        if bridge.error or not bridge.ready.is_set():raise RuntimeError(bridge.error or 'Bridge startup timed out')
        if not args.no_engine:
            logfile=(args.runtime/'engine.log').open('a',encoding='utf-8')
            engine=subprocess.Popen([sys.executable,str(HERE/'engine.py'),'--repo',str(args.repo),
                                     '--config',str(config_path),'--runtime',str(args.runtime)],stdout=logfile,stderr=subprocess.STDOUT)
        print(f'Bench console: http://127.0.0.1:{args.port} (real DIS service required)',flush=True)
        while not stop.is_set() and not bridge.stop.is_set() and not (args.runtime/'stop.flag').exists():
            if engine is not None and engine.poll() is not None:
                with bridge.lock:
                    bridge.state['routine']['running']=False
                    bridge.error=f'Display engine exited with code {engine.returncode}; inspect runtime/engine.log'
            server.handle_request()
    finally:
        bridge.stop.set()
        if bridge.thread.is_alive():bridge.thread.join(5)
        if engine is not None:
            try:engine.wait(timeout=5)
            except subprocess.TimeoutExpired:engine.terminate();engine.wait(timeout=5)
            logfile.close()
        server.server_close()


if __name__=='__main__':main()
