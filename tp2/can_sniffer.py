#!/usr/bin/env python3
import zmq
import json
import time

# Add all the known IDs (in Hex) from your config and general knowledge here
KNOWN_IDS = {
    # Known from config.json
    "635", "623", "2C3", "602", "365", "367", "6C1", "6C0", "461", "5C3", "661",
    # Typical TP2.0 IDs (Diagnostic/Transport protocol stuff you might want to ignore)
    "200", "288", "300", "301", "302", "303", "304", "305", "306", "307", "308", "309",
    "714", "740"
}

def main():
    context = zmq.Context()
    sub_socket = context.socket(zmq.SUB)
    
    # Connect to the raw CAN stream from your base function
    ipc_path = "ipc:///run/rnse_control/can_stream.ipc"
    import os
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base_dir, 'config.json')) as f:
            cfg = json.load(f)
        if 'zmq' in cfg:
            ipc_path = cfg['zmq'].get('can_raw_stream', ipc_path)
    except Exception:
        pass

    print(f"Connecting to {ipc_path}...")
    
    try:
        sub_socket.connect(ipc_path)
        # Your base function prepends "CAN_" or similar to the topic. Subscribe to all.
        sub_socket.subscribe(b"") 
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    print("Listening for unknown CAN IDs. Press Ctrl+C to exit.\n")
    print(f"{'ID':<6} | {'DATA STR (HEX)':<25} | NOTES")
    print("-" * 50)

    last_seen = {} # Keep track of last payloads to only print on change

    try:
        while True:
            parts = sub_socket.recv_multipart(flags=zmq.NOBLOCK)
            if len(parts) >= 2:
                topic = parts[0].decode('utf-8', errors='ignore')
                msg = parts[1].decode('utf-8', errors='ignore')
                
                # We expect topics like "CAN_0x5C0" or "CAN_5C0"
                if "CAN_" in topic:
                    # Clean up the ID string to get just the hex value (e.g., "5C0")
                    msg_id_hex = topic.replace("CAN_", "").replace("0x", "").upper()
                    
                    if msg_id_hex and msg_id_hex not in KNOWN_IDS:
                        try:
                            # Parse your specific JSON format (usually contains 'data_hex')
                            payload = json.loads(msg)
                            data_hex = payload.get('data_hex', '')
                            
                            # Pad the string with spaces for readability if it isn't already
                            if len(data_hex) > 0 and ' ' not in data_hex:
                                data_hex = ' '.join(data_hex[i:i+2] for i in range(0, len(data_hex), 2)).upper()

                            # Only print if this specific ID has broadcasted a NEW value
                            if last_seen.get(msg_id_hex) != data_hex:
                                last_seen[msg_id_hex] = data_hex
                                print(f"{msg_id_hex:<6} | {data_hex:<25} | ")

                        except json.JSONDecodeError:
                            pass
            time.sleep(0.001)
            
    except zmq.Again:
        pass
    except KeyboardInterrupt:
        print("\nExiting.")

if __name__ == "__main__":
    main()
