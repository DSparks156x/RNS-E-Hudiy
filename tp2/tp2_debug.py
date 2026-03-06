import zmq
import json
import argparse
import sys

def main():
    default_addr = "ipc:///run/rnse_control/tp2_cmd.ipc"
    try:
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base_dir, 'config.json')) as f:
            cfg = json.load(f)
        default_addr = cfg['zmq'].get('tp2_command', default_addr)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="TP2 Worker Debugger")
    parser.add_argument("--addr", type=str, default=default_addr, help=f"TP2 Command Address (default: {default_addr})")
    args = parser.parse_args()

    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, 2000) # 2s timeout
    socket.connect(args.addr)

    cmd = {"cmd": "STATUS"}
    print(f"Sending STATUS command to TP2 Worker on {args.addr}...")
    
    socket.send_json(cmd)

    try:
        reply = socket.recv_json()
        print("\n=== TP2 Worker Status ===")
        print(json.dumps(reply, indent=4))
    except zmq.Again:
        print("\n[!] Error: Timeout waiting for response. Is TP2 Worker running?")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!] Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
