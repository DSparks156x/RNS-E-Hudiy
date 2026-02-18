#!/usr/bin/env python3
import zmq
import time
import json
import threading

def subscribe_task():
    context = zmq.Context()
    sub = context.socket(zmq.SUB)
    sub.connect("tcp://localhost:5557")
    sub.setsockopt_string(zmq.SUBSCRIBE, "HUDIY_DIAG")
    
    print("Subscriber started...")
    while True:
        try:
            topic, msg = sub.recv_multipart()
            data = json.loads(msg)
            print(f"RX-DATA: Mod 0x{data['module']:02X} Grp {data['group']}")
        except Exception as e:
            print(f"Sub Error: {e}")
            break

def send_cmd(socket, cmd):
    print(f"CMD: {cmd}")
    socket.send_json(cmd)
    resp = socket.recv_json()
    print(f"RESP: {resp}")

def main():
    # Start Subscriber in BG
    threading.Thread(target=subscribe_task, daemon=True).start()
    
    context = zmq.Context()
    req = context.socket(zmq.REQ)
    req.connect("tcp://localhost:5558")
    
    # 1. Get Status
    print("\n--- Status Check ---")
    send_cmd(req, {"cmd": "STATUS"})
    
    # 2. Add Group
    print("\n--- Adding Group ---")
    send_cmd(req, {"cmd": "ADD", "module": 0x01, "group": 10})
    time.sleep(1)
    
    # 3. Get Status
    print("\n--- Status Check (Active) ---")
    send_cmd(req, {"cmd": "STATUS"})
    
    # 4. Toggle Off
    print("\n--- Toggle OFF ---")
    send_cmd(req, {"cmd": "TOGGLE"})
    
    # 5. Get Status
    print("\n--- Status Check (Disabled) ---")
    send_cmd(req, {"cmd": "STATUS"})
    
    # 6. Toggle On
    print("\n--- Toggle ON ---")
    send_cmd(req, {"cmd": "TOGGLE"})
    time.sleep(1)
    
    # 7. Clear
    print("\n--- Clear ---")
    send_cmd(req, {"cmd": "CLEAR"})
    print("Done.")

if __name__ == "__main__":
    main()
