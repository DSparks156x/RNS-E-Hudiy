"""Root-only exclusiveJ2534 bench: actual DisService constructor/run and local ZMQ IPC.

Default is offline identity/config validation. --run-bench opens hardware.
The production source is not modified. Main owns service/ZMQ sockets and the
adapter lifetime; IPC client owns a separate thread/context; wake is serialized.
"""
import argparse
from collections import deque
from dataclasses import asdict,is_dataclass
import hashlib,importlib.util,json,logging
from pathlib import Path
import signal,struct,sys,threading,time,types

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[1];CAR=REPO.parent;DEPS=CAR/'clusterRE/.bench_deps'
RUNTIME=('ddp_protocol.py','dis_service.py','ddp_application.py','ddp_transport.py',
         'native_nav_glyphs.py','stock_nav_composition.py','native_nav_catalog.json','native_nav_catalog.sha256')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def identities():return {name:sha(REPO/'dis_client'/name) for name in RUNTIME}
def endpoint(port):return 'tcp://127.0.0.1:'+str(port)
def configuration(args):
    return dict(can_channel='exclusive-j2534-fullservice',can_bitrate=500000,
        interfaces={'zmq':{'dis_draw':endpoint(args.draw_port),'dis_status':endpoint(args.status_port),
                           'system_events':endpoint(args.power_port)}},
        features={'debug_mode':False},display={'center_display':{'enabled':True,'start_inactive':args.start_inactive,
            'navigation':{'claim_on_nav':False}},'phone':{'claim_on_phone':False}})
def frame(seq):
    return dict(command='frame',seq=seq,commands=[
        dict(command='draw_stock_mono_frame',source_object=[0,2,1,13,64,0],
             object_stage='render',screen_selector=4,raw_progress=128,
             road_bytes=list(b'STOCK IPC'))])
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

def run(args):
    before=identities()
    sources={'ddp_protocol.py':REPO/'dis_client/ddp_protocol.py',
             'dis_service.py':REPO/'dis_client/dis_service.py'}
    for name,path in sources.items():
        assert path.is_file() and path.name==name,'Missing production source: '+str(path)
    assert len({args.draw_port,args.status_port,args.power_port})==3 and all(1024<=port<=65535 for port in (args.draw_port,args.status_port,args.power_port))
    stage=REPO/'dis_client'
    cfg=configuration(args)
    if not args.run_bench:
        print(json.dumps(dict(status='OFFLINE_PREFLIGHT_NO_CONSTRUCTORS',runtime=before,
            loaded_sources={name:dict(path=str(path),sha256=sha(path)) for name,path in sources.items()},
            config=cfg,frame=frame(701),can_io=False,ipc_sockets_opened=0),indent=2));return
    assert struct.calcsize('P')==4,'32-bit Python required by ScanmatikDLL'
    args.out.mkdir(parents=True,exist_ok=False)
    logging.basicConfig(level=logging.DEBUG,format='%(asctime)s %(levelname)s %(name)s %(message)s',
        handlers=[logging.FileHandler(args.out/'driver.log',encoding='utf-8')])
    wire=(args.out/'wire.jsonl').open('w',encoding='utf-8',buffering=1)
    evidence=(args.out/'events.jsonl').open('w',encoding='utf-8',buffering=1)
    evidence_lock=threading.RLock();io_lock=threading.RLock();pending=deque()
    wake_stop=threading.Event();client_stop=threading.Event();wake_thread=client_thread=None
    device=service=None;opened=False;old_signals={key:signal.getsignal(key) for key in (signal.SIGINT,signal.SIGTERM)}
    def event(kind,**values):
        row=dict(event=kind,time_ns=time.time_ns(),monotonic_ns=time.monotonic_ns(),**values)
        with evidence_lock:evidence.write(json.dumps(row,default=lambda value:asdict(value) if is_dataclass(value) else str(value))+'\n')
        print(json.dumps(row,default=str),flush=True)
    dependencies=[str(DEPS)] if sys.version_info[:2]==(3,11) else []
    sys.path[:0]=dependencies+[str(stage),str(REPO),str(args.j2534_shim.parent)]
    from j2534 import J2534Device
    from flasher.traffic import flashing_mode_enabled,transmission_guard
    import zmq
    assert not flashing_mode_enabled(),'FlashingMode blocks bench traffic'
    device=J2534Device();last_wake=last_ignition=0
    def send(cid,data):
        payload=bytes(data)
        with io_lock:
            result=device.can_send(cid,payload)
            wire.write(json.dumps(dict(direction='tx',time_ns=time.time_ns(),id=cid,data=payload.hex(),result=result))+'\n')
        if result:raise OSError('J2534 send failed:%s'%result)
    def wake():
        nonlocal last_wake,last_ignition
        with transmission_guard() as allowed:
            if not allowed:raise RuntimeError('FlashingMode became active')
            with io_lock:
                now=time.monotonic()
                if now-last_wake>=.5:send(0x575,[255]*8);last_wake=now
                if now-last_ignition>=.1:send(0x2C3,[7]);last_ignition=now
    def native_receive(timeout_ms):
        with io_lock:
            result=device.can_recv_ts(timeout_ms)
            for cid,payload,bus,stamp in result:
                wire.write(json.dumps(dict(direction='rx',time_ns=time.time_ns(),id=cid,data=payload.hex(),hardware_us=stamp))+'\n')
            return result
    def wake_worker():
        try:
            while not wake_stop.is_set():wake();wake_stop.wait(.025)
        except Exception as error:
            event('wake_error',error=repr(error));wake_stop.set()
            if service is not None:service.running=False
    class BenchBus:
        def set_filters(self,filters):self.rx=filters[0]['can_id']
        def shutdown(self):pending.clear()
        def send(self,message,timeout=None):send(message.arbitration_id,message.data)
        def recv(self,timeout=None):
            deadline=time.monotonic()+(timeout or 0)
            while True:
                wake()
                if pending:return pending.popleft()
                for cid,payload,bus,stamp in native_receive(0 if not timeout else 5):
                    if cid==self.rx:pending.append(types.SimpleNamespace(arbitration_id=cid,data=payload,timestamp=stamp/1000000))
                if pending:return pending.popleft()
                if time.monotonic()>=deadline:return None
    can=types.ModuleType('can');can.Bus=lambda **kwargs:BenchBus()
    can.Message=lambda **kwargs:types.SimpleNamespace(**kwargs);can.CanError=OSError;sys.modules['can']=can

    def client_worker():
        # Everyclient socket/context is created, used and destroyed here.
        context=None;sockets=[]
        seq=701;sent_at=0;acked=False;ready=False;resumed=False;last_power=0
        try:
            context=zmq.Context()
            power=context.socket(zmq.PUB);sockets.append(power)
            push=context.socket(zmq.PUSH);sockets.append(push)
            status=context.socket(zmq.SUB);sockets.append(status)
            for socket in sockets:socket.setsockopt(zmq.LINGER,0)
            push.setsockopt(zmq.SNDHWM,10);push.setsockopt(zmq.SNDTIMEO,200)
            status.subscribe(b'')
            power.bind(endpoint(args.power_port));push.connect(endpoint(args.draw_port));status.connect(endpoint(args.status_port))
            start=time.monotonic();deadline=start+args.hold if args.hold else float('inf')
            event('ipc_client_open',thread=threading.get_ident(),ports=[args.draw_port,args.status_port,args.power_port])
            while not client_stop.is_set() and time.monotonic()<deadline and not (args.out/'stop.flag').exists():
                now=time.monotonic()
                if now-last_power>=.1:
                    power.send_multipart([b'POWER_STATUS',json.dumps(dict(kl15=True,bus_active=True)).encode()]);last_power=now
                while status.poll(0):
                    message=status.recv_string();event('ipc_status',message=message)
                    if message.startswith('DIS_STATE '):ready=message=='DIS_STATE READY'
                    if message=='DRAW_ACK '+str(seq):acked=True;event('ipc_frame_acked',seq=seq)
                    if message=='DRAW_NACK '+str(seq):event('ipc_frame_nacked',seq=seq)
                # Power/wake only; the full web DisplayEngine is the sole painter.
                client_stop.wait(.02)
            event('ipc_client_stop_requested',frame_acked=acked,seq=seq)
            # Cooperative publicpause beforemain closes the session. No CAN
            #or production methods are called from thisclient thread.
            try:push.send_json(dict(command='pause'));time.sleep(.25)
            except zmq.ZMQError as error:event('ipc_pause_send_error',error=repr(error))
        except Exception as error:event('ipc_client_error',error=repr(error))
        finally:
            if service is not None:service.running=False
            for socket in reversed(sockets):socket.close(linger=0)
            if context is not None:context.term()
            event('ipc_client_closed',thread=threading.get_ident())

    try:
        event('source_snapshot',identities=before,harness_sha256=sha(Path(__file__)),
            loaded_sources={name:dict(path=str(path),sha256=sha(path)) for name,path in sources.items()},
            scope='ActualDisService constructor/run, real localZMQ IPC, exclusiveJ2534 adapter facade. Root-onlyhardwareexecution.')
        device.open();opened=True;device.connect_can(500000);event('adapter_open',dll=device.dll_path)
        wake_thread=threading.Thread(target=wake_worker,name='serialized-fullservice-wake',daemon=False);wake_thread.start()
        until=time.monotonic()+args.settle
        while time.monotonic()<until and not (args.out/'stop.flag').exists():native_receive(5);time.sleep(.02)
        assert not wake_stop.is_set() and not (args.out/'stop.flag').exists(),'Stopped before serviceconstructor'
        config_path=args.out/'bench_config.json';config_path.write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf-8')
        load('ddp_protocol',sources['ddp_protocol.py']);module=load('dis_service',sources['dis_service.py'])
        service=module.DisService(config_path=str(config_path))
        assert not wake_stop.is_set(),'Wake worker failed during service construction'
        event('service_constructor_complete',thread=threading.get_ident(),main_thread=threading.main_thread().ident)
        client_thread=threading.Thread(target=client_worker,name='fullservice-local-ipc',daemon=False);client_thread.start()
        event('service_run_begin');service.run();event('service_run_returned')
    finally:
        client_stop.set()
        if service is not None:service.running=False
        if client_thread is not None:
            client_thread.join(timeout=5);assert not client_thread.is_alive(),'IPCclient did not close; retainadapter'
        # Mainthread is the solecaller of productionCAN methods. Session close
        #finishes while wake still runs; adapter remains owned until joined.
        if service is not None:
            try:service.ddp.close_session()
            except Exception as error:event('session_close_error',error=repr(error))
            for name in ('ignition_sub','draw_socket','status_pub'):
                socket=getattr(service,name,None)
                if socket is not None:socket.close(linger=0)
            service.context.term();event('service_sockets_closed',thread=threading.get_ident())
        wake_stop.set()
        if wake_thread is not None:
            wake_thread.join(timeout=5);assert not wake_thread.is_alive(),'Wakeworker did not stop; retainadapter'
        if opened:
            try:device.disconnect();event('adapter_disconnected')
            finally:device.close();event('adapter_closed')
        for key,handler in old_signals.items():signal.signal(key,handler)
        after=identities();event('closed',identities=after,sources_unchanged=before==after,
            ipc_worker_alive=bool(client_thread and client_thread.is_alive()),wake_worker_alive=bool(wake_thread and wake_thread.is_alive()))
        wire.close();evidence.close()

def main():
    global REPO,CAR,DEPS
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=REPO)
    parser.add_argument('--run-bench',action='store_true');parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--hold',type=float,default=0);parser.add_argument('--settle',type=float,default=0)
    parser.add_argument('--draw-port',type=int,default=18652);parser.add_argument('--status-port',type=int,default=18653)
    parser.add_argument('--power-port',type=int,default=18657);parser.add_argument('--start-inactive',action='store_true')
    parser.add_argument('--j2534-shim',type=Path,default=CAR/'HaldexRE/flasher/j2534.py')
    args=parser.parse_args();REPO=args.repo.resolve();CAR=REPO.parent;DEPS=CAR/'clusterRE/.bench_deps'
    assert 0<=args.hold<=86400 and 0<=args.settle<=60
    assert args.j2534_shim.is_file(),'Specify --j2534-shim path to j2534.py'
    # Reserve all service ports BEFORE opening the adapter. This catches an
    # existing bench service and concurrent launch attempts without CAN I/O.
    import socket
    reservations=[]
    lock=socket.socket()
    try:
        if args.run_bench:
            lock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            lock.bind(('127.0.0.1',18649))
            for port in (args.draw_port,args.status_port,args.power_port):
                reservation=socket.socket();reservations.append(reservation)
                reservation.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                reservation.bind(('127.0.0.1',port))
            for reservation in reservations:reservation.close()
        run(args)
    finally:
        for reservation in reservations:reservation.close()
        lock.close()

if __name__=='__main__':main()
