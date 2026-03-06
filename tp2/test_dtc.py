#!/usr/bin/env python3
import zmq
import json
import time
import sys
import threading

import os
# Default IPC addresses based on config.json
TP2_STREAM_ADDR = "ipc:///run/rnse_control/tp2_stream.ipc"
TP2_CMD_ADDR = "ipc:///run/rnse_control/tp2_cmd.ipc"

try:
    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(_base_dir, 'config.json')) as _f:
        _cfg = json.load(_f)
    if 'zmq' in _cfg:
        TP2_STREAM_ADDR = _cfg['zmq'].get('tp2_stream', TP2_STREAM_ADDR)
        TP2_CMD_ADDR = _cfg['zmq'].get('tp2_command', TP2_CMD_ADDR)
except Exception:
    pass

def listen_for_dtc():
    context = zmq.Context.instance()
    sub_sock = context.socket(zmq.SUB)
    sub_sock.connect(TP2_STREAM_ADDR)
    sub_sock.setsockopt_string(zmq.SUBSCRIBE, "HUDIY_DIAG")

    print(f"[*] Started listener on {TP2_STREAM_ADDR} for HUDIY_DIAG")
    
    # Timeout after 30 seconds since DTC reading might take time
    start_time = time.time()
    while time.time() - start_time < 30:
        try:
            # wait 100ms
            if sub_sock.poll(100):
                parts = sub_sock.recv_multipart()
                if len(parts) >= 2:
                    topic = parts[0].decode('utf-8')
                    payload = json.loads(parts[1].decode('utf-8'))
                    
                    if payload.get("type") == "dtc_report":
                        print("\n[+] Received DTC Report:")
                        print(json.dumps(payload, indent=2))
                        return
                    else:
                        print(f"[-] Received other diag data: {payload.get('type', 'group')} (Mod: {payload.get('module')})")
        except Exception as e:
            print(f"[!] Listener error: {e}")
            break
            
    print("\n[!] Timeout waiting for DTC report")

def main():
    module = 0x01
    action = "READ_DTC"
    
    if len(sys.argv) > 1:
        module = int(sys.argv[1], 0)
    if len(sys.argv) > 2 and sys.argv[2] == "clear":
        action = "CLEAR_DTC"
        
    print(f"[*] Requesting {action} for Module 0x{module:02X}")
    
    # Start listener thread
    listener = threading.Thread(target=listen_for_dtc, daemon=True)
    listener.start()
    
    # Give the subscriber time to connect
    time.sleep(0.5)
    
    context = zmq.Context.instance()
    req_sock = context.socket(zmq.REQ)
    req_sock.connect(TP2_CMD_ADDR)
    
    cmd = {
        "cmd": action,
        "module": module
    }
    
    print(f"[*] Sending command to {TP2_CMD_ADDR}: {json.dumps(cmd)}")
    req_sock.send_json(cmd)
    
    try:
        if req_sock.poll(5000):
            resp = req_sock.recv_json()
            print(f"[*] Command Response: {resp}")
        else:
            print("[!] Timeout waiting for command response")
    except Exception as e:
        print(f"[!] Error sending command: {e}")
        
    print("[*] Waiting for result...")
    listener.join()
    print("[*] Done.")

if __name__ == "__main__":
    main()
