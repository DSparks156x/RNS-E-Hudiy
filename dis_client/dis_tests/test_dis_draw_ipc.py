#!/usr/bin/env python3
import zmq
import time
import json
import os
import sys

def run_test():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true', help='Connect to DIS Emulator (TCP 5557)')
    args = parser.parse_args()

    # Load config to get the IPC address, or default to standard location
    config_path = '/home/pi/config.json'
    # Fallback to local config if present (e.g., ran from project root)
    if not os.path.exists(config_path) and os.path.exists('./config.json'):
        config_path = './config.json'

    if args.mock:
        config_addr = "tcp://127.0.0.1:5557"
    else:
        try:
            with open(config_path) as f:
                config = json.load(f)
            config_addr = config['zmq']['dis_draw']
        except Exception as e:
            config_addr = "tcp://127.0.0.1:5557"
            print(f"Assuming mock/emulator mode: {config_addr}")

    print(f"Connecting to {config_addr}...")
    context = zmq.Context()
    draw = context.socket(zmq.PUSH)
    draw.connect(config_addr)
    
    print("Connected. Sleeping for 1s to ensure connection is ready...")
    time.sleep(1)

    print("==========================================")
    print("Starting clear/draw/commit cycle tests...")
    print("==========================================")
    
    # 1. Full wipe to start clean
    print("Full clear...")
    # 'clear' operates on the back buffer, clear_area bypasses directly to LCD
    # Central area: x=0, y=0, w=64, h=48
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    # 2. Base Header to ensure drawing works
    print("Drawing initial header...")
    draw.send_json({'command': 'draw_text', 'text': 'TEST INIT', 'x': 0, 'y': 1, 'flags': 0x26})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    # 3. Test loop: clear_area -> draw_text -> commit
    # This specifically tests if clear_area is being rendered before commit, causing flicker.
    print("\n--- Test 1: Rapid clear_area -> draw_text -> commit ---")
    print("Watch the display. It should alternate TICK and TOCK without flickering to black.")
    for i in range(10):
        # 1. Clear area (line 2)
        draw.send_json({'command': 'clear_area', 'x': 0, 'y': 11, 'w': 64, 'h': 9})
        
        # 2. Draw text
        text = f"TICK {i}" if i % 2 == 0 else f"TOCK {i}"
        draw.send_json({'command': 'draw_text', 'text': text, 'x': 0, 'y': 11, 'flags': 0x06})
        
        # 3. Commit
        draw.send_json({'command': 'commit'})
        
        sys.stdout.write(f"\rCycle {i+1}/10 sent: {text}    ")
        sys.stdout.flush()
        
        # Delay to allow eye to catch flicker
        time.sleep(0.5)
    print()

    # 4. Test changing flags (invert vs normal) which also triggers clear in dis_display
    print("\n--- Test 2: Changing flags (normal to inverted) ---")
    print("This will flash line 3. Watch for black flicker before the inverted draw.")
    for i in range(10):
        flags = 0x86 if i % 2 == 0 else 0x06
        mode = "INVERT" if i % 2 == 0 else "NORMAL"
        
        draw.send_json({'command': 'clear_area', 'x': 0, 'y': 21, 'w': 64, 'h': 9})
        draw.send_json({'command': 'draw_text', 'text': f"MODE {mode}", 'x': 0, 'y': 21, 'flags': flags})
        draw.send_json({'command': 'commit'})
        
        sys.stdout.write(f"\rCycle {i+1}/10 sent: {mode} (flags {flags:#04x})    ")
        sys.stdout.flush()
        time.sleep(0.5)
    print()

    print("\n--- Test 3: Fast update loop ---")
    print("Sending updates very quickly (0.1s) to test if service drops logic orders.")
    for i in range(20):
        draw.send_json({'command': 'clear_area', 'x': 0, 'y': 31, 'w': 64, 'h': 9})
        draw.send_json({'command': 'draw_text', 'text': f"FAST {i}", 'x': 0, 'y': 31, 'flags': 0x06})
        draw.send_json({'command': 'commit'})
        time.sleep(0.1)
    print("Done with fast update loop.")

    print("\nClearing all in 2 seconds...")
    time.sleep(2)
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})
    print("Test complete.")

if __name__ == "__main__":
    run_test()
