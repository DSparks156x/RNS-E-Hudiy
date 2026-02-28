#!/usr/bin/env python3
import zmq
import time
import json

def run_mock():
    # Use TCP by default for emulator convenience as requested
    tcp_addr = "tcp://127.0.0.1:5557"
    
    # Load config for reference
    try:
        with open('../config.json') as f:
            config = json.load(f)
        config_addr = config['zmq']['dis_draw']
    except:
        config_addr = None

    context = zmq.Context()
    draw = context.socket(zmq.PUSH)

    # Prioritize TCP for Windows/Emulator setup
    try:
        draw.connect(tcp_addr)
        print(f"Connecting to {tcp_addr} (TCP)...")
    except Exception as e:
        if config_addr:
            print(f"TCP connect failed, trying config addr {config_addr}: {e}")
            draw.connect(config_addr)
        else:
            print(f"TCP connect failed and no config addr found: {e}")
            return

    print("Sending mock DIS commands...")

    # Clear
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    # Header
    draw.send_json({'command': 'draw_text', 'text': 'EMULATOR', 'x': 0, 'y': 1, 'flags': 0x26})
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    # Navigation Icon
    draw.send_json({'command': 'draw_bitmap', 'icon_name': 'STRAIGHT', 'x': 16, 'y': 27})
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    # Main text
    draw.send_json({'command': 'draw_text', 'text': '500 m', 'x': 10, 'y': 50, 'flags': 0x26})
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    # Inverted Footer
    draw.send_json({'command': 'draw_text', 'text': 'READY', 'x': 0, 'y': 70, 'flags': 0xA6})
    draw.send_json({'command': 'commit'})
    
    print("Done. Check the browser.")

if __name__ == "__main__":
    run_mock()
