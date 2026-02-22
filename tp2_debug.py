import zmq
import json
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="TP2 Worker Debugger")
    parser.add_argument("--port", type=int, default=5556, help="TP2 Command Port (default: 5556)")
    args = parser.parse_args()

    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, 2000) # 2s timeout
    socket.connect(f"tcp://localhost:{args.port}")

    cmd = {"cmd": "STATUS"}
    print(f"Sending STATUS command to TP2 Worker on port {args.port}...")
    
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
