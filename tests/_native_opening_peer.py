"""Offline physical-edge peer; all production application/TP code remains real."""
import importlib.util
import os
import sys
import types
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get('DDP_TEST_REPO', str(HERE.parent)))
DEFAULT = Path(os.environ.get('DDP_TEST_SOURCE', str(HERE.parent / 'dis_client/ddp_protocol.py')))

def deny(*args, **kwargs):
    raise AssertionError('Hardware/socket construction prohibited')

can = types.ModuleType('can')
can.Bus = deny
can.Message = lambda **kwargs: types.SimpleNamespace(**kwargs)
can.CanError = type('CanError', (Exception,), {})
sys.modules.setdefault('can', can)
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO/'dis_client'))
from flasher.vag_protocols import tp2 as tp

def load(path=DEFAULT, name='native_controller_under_test'):
    spec=importlib.util.spec_from_file_location(name, path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    module.logger.disabled=True
    return module

class Clock:
    def __init__(self): self.now=100.0
    def monotonic(self): return self.now
    perf_counter=monotonic
    time=monotonic
    def sleep(self, seconds): self.now+=seconds

CAR=[9,32,11,80,9,36,74]
GEOMETRY=[48,57,0,50,0]
VECTOR_COUNT=0

def exercise(module, capabilities=CAR, *, mode='WHITE', before_ack=False,
             start_seq=0, geometry=None, geometry_order='before', setup_replies=None,
             late=None, stale_setup=False, mode_record=None, retain_previous=None,
             setup_control=None, late_control=None, capabilities_during_mode=False,
             query_prefix=(), release_records=(), release_control=None,
             announcement_capabilities=False, reply_to_query=True, command_script=None):
    global VECTOR_COUNT
    VECTOR_COUNT+=1
    d=module.DDPProtocol.__new__(module.DDPProtocol)
    d.config=d.cfg={}
    d.transport_profile=module.DDPTransportProfile(frame_gap_s=0,white_post_message_delay_s=0)
    d.state=module.DDPState.SESSION_ACTIVE
    d.dis_mode=getattr(module.DisMode,mode)
    d.state_generation=d.presentation_request_generation=d.send_seq_num=0
    d.i_am_opener=d.screen_released_by_cluster=False
    d.last_ka_sent=0
    d._last_received_ack=d._last_received_data=d._last_screen_status=None
    d._data_inbox=deque()
    d.bus=None
    d.tx_id,d.rx_id=0x6C0,0x6C1
    d._reset_receive_transport()
    d._reset_application_session()
    d._receive_seq_num=start_seq
    d._flashing_inhibited=lambda:False
    if retain_previous is not None:
        d.cluster_capabilities=module.ClusterCapabilities.parse(retain_previous)
    clock=Clock()
    module.time=clock
    incoming=deque()
    tx,rx,commands=[],[],[]
    partial=bytearray()
    peer_seq=start_seq
    setup_count=0
    query_count=0
    occurrences={}
    cap_snapshot=[]
    status_snapshot=[]
    setup_snapshot=[]
    def respond(payload):
        nonlocal peer_seq
        frames,_=tp.segment_message(bytes(payload),peer_seq,block_size=6,length_prefixed=False)
        peer_seq=(peer_seq+len(frames))&15
        rx.extend(list(frame) for frame in frames)
        incoming.extend(list(frame) for frame in frames)
    def recv(timeout=.01):
        if incoming: return incoming.popleft()
        clock.sleep(max(timeout,.001))
        return None
    def send(cid,data):
        nonlocal setup_count,query_count
        data=list(data)
        tx.append(data)
        if data==d.KA_KEEP_PING:
            if late is not None:
                for record in late: respond(record)
            if late_control is not None: incoming.append(list(late_control))
            incoming.append(list(d.KA_RED_ACCEPT if mode=='RED' else d.KA_WHITE_ACCEPT))
            return
        op,seq=tp.classify_frame(data)
        if op not in (0,1,2,3): return
        if not before_ack and op in (0,1): incoming.append([0xB0|((seq+1)&15)])
        partial.extend(data[1:])
        if op in (1,3):
            payload=list(partial)
            partial.clear()
            commands.append(payload)
            occurrences[payload[0]]=occurrences.get(payload[0],0)+1
            override=command_script(payload,occurrences[payload[0]]) if command_script is not None else None
            if override is not None:
                if payload[0]==8:query_count+=1
                if payload[0]==0x20:setup_count+=1
                for record in override:respond(record)
            elif payload[0]==0x15:
                respond([0,1] if mode_record is None else mode_record)
                if announcement_capabilities:respond(capabilities)
            elif payload==[1,1,0] and capabilities_during_mode:
                respond(capabilities)
            elif payload==[8]:
                query_count+=1
                if not reply_to_query:
                    if before_ack and op in (0,1):incoming.append([0xB0|((seq+1)&15)])
                    return
                for record in query_prefix:respond(record)
                if geometry is not None and geometry_order=='before': respond(geometry)
                respond(capabilities)
                if geometry is not None and geometry_order=='after': respond(geometry)
                if stale_setup: respond([0x21,0x3B,0xA0,0])
            elif payload==[0x33]:
                for record in release_records: respond(record)
                if release_control is not None:incoming.append(list(release_control))
            elif payload[0]==0x20:
                setup_count+=1
                if setup_control is not None: incoming.append(list(setup_control))
                if setup_replies is None:
                    records=[[0x21,0x3B,payload[2],0]]
                elif callable(setup_replies):
                    records=setup_replies(setup_count,payload)
                else:
                    records=setup_replies[setup_count-1] if setup_count<=len(setup_replies) else []
                for record in records: respond(record)
        if before_ack and op in (0,1): incoming.append([0xB0|((seq+1)&15)])
    d._recv,d.send_can=recv,send
    result=d.perform_initialization()
    return {'result':result,'state':d.state.name,'commands':commands,'tx':tx,'rx':rx,
            'setup_count':setup_count,'query_count':query_count,
            'family':d.renderer_command_family(),'render_ready':d.renderer_ready(),
            'setup_record':d.application_setup_record,
            'capability_generation':d._capability_generation,
            'confirmed_generation':d._confirmed_capability_generation,
            'last_capabilities':d.last_capability_record,
            'mode':d._application_mode,'geometry':d.geometry_record,
            'exchanges':list(getattr(d,'application_exchange_history',())),
            'observations':list(getattr(d,'capability_observation_history',())),
            'elapsed':clock.now-100,'instance':d}
