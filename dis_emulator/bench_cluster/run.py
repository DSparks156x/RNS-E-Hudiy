"""Launch one exclusive J2534 service and the web console; Ctrl+C closes both."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=HERE.parents[1])
    p.add_argument('--adapter-python',type=Path)
    p.add_argument('--j2534-shim',type=Path)
    p.add_argument('--port',type=int,default=8766)
    p.add_argument('--base-port',type=int,default=18650)
    p.add_argument('--connect-existing',action='store_true',help='Do not open CAN; use an already running service')
    p.add_argument('--draw-port',type=int)
    p.add_argument('--status-port',type=int)
    args=p.parse_args()
    if sys.platform!='win32' and not args.connect_existing:p.error('J2534 bench launcher requires Windows')
    adapter_python=args.adapter_python or Path(sys.executable)
    if not args.adapter_python and struct.calcsize('P')!=4:
        adapter_python=Path.home()/'AppData/Local/Programs/Python/Python311-32/python.exe'
    shim=args.j2534_shim or args.repo.parent/'HaldexRE/flasher/j2534.py'
    if not args.connect_existing and (not adapter_python.is_file() or not shim.is_file()):
        p.error('Specify a 32-bit --adapter-python and --j2534-shim path (with flasher/traffic.py alongside)')
    session=HERE/'runtime'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    session.mkdir(parents=True)
    ui=session/'console';ui.mkdir()
    service_out=session/'service'
    draw=args.draw_port or args.base_port+2
    status=args.status_port or args.base_port+3
    processes=[];logs=[]
    stop=False
    def shutdown(*_):
        nonlocal stop
        stop=True
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,shutdown)
    env=dict(os.environ)
    adapter_env=dict(env)
    deps=args.repo.parent/'clusterRE/.bench_deps'
    if deps.is_dir():
        # This local folder contains CPython3.11/win32 extension modules.
        if adapter_python.parent.name=='Python311-32':
            adapter_env['PYTHONPATH']=str(deps)+os.pathsep+adapter_env.get('PYTHONPATH','')
        if sys.version_info[:2]==(3,11) and struct.calcsize('P')==4:
            env['PYTHONPATH']=str(deps)+os.pathsep+env.get('PYTHONPATH','')
    try:
        if not args.connect_existing:
            out=(session/'service_stdout.log').open('w',encoding='utf-8');logs.append(out)
            command=[str(adapter_python),str(HERE/'j2534_service.py'),'--run-bench','--repo',str(args.repo),
                     '--out',str(service_out),'--hold','0','--j2534-shim',str(shim),
                     '--draw-port',str(draw),'--status-port',str(status),'--power-port',str(args.base_port+7)]
            owner=subprocess.Popen(command,stdout=out,stderr=subprocess.STDOUT,env=adapter_env);processes.append(owner)
            # Constructor event confirms port reservation and adapter setup;
            # READY is still established by the actual cluster handshake.
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if owner.poll() is not None:raise RuntimeError('Bench service failed; inspect '+str(session/'service_stdout.log'))
                events=service_out/'events.jsonl'
                if events.exists() and 'service_constructor_complete' in events.read_text(encoding='utf-8'):break
                time.sleep(.1)
            else:raise RuntimeError('Bench service constructor timed out')
        console=subprocess.Popen([sys.executable,str(HERE/'server.py'),'--repo',str(args.repo),'--runtime',str(ui),
                                  '--port',str(args.port),'--base-port',str(args.base_port),
                                  '--draw-port',str(draw),'--status-port',str(status)],env=env)
        processes.append(console)
        print(f'Open http://127.0.0.1:{args.port} | Session: {session}',flush=True)
        while not stop and all(proc.poll() is None for proc in processes):time.sleep(.2)
    finally:
        # Stop painters first, then finish service session while wake runs.
        (ui/'stop.flag').write_text('launcher stop\n')
        if len(processes)>int(not args.connect_existing):
            try:processes[-1].wait(timeout=10)
            except subprocess.TimeoutExpired:processes[-1].terminate();processes[-1].wait(timeout=5)
        if not args.connect_existing and processes:
            if service_out.exists():(service_out/'stop.flag').write_text('launcher stop\n')
            # Hardware owner uses cooperative closure. Never force-kill it
            # while a worker might still be inside the adapter DLL.
            try:processes[0].wait(timeout=15)
            except subprocess.TimeoutExpired:
                print('Adapter service still closing; retained its process. See session logs.',flush=True)
        for log in logs:log.close()


if __name__=='__main__':main()
