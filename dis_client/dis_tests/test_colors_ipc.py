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

    config_path = '/home/pi/config.json'
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
    time.sleep(1)

    print("==========================================")
    print("Starting Experimental Colors & Flags tests...")
    print("==========================================")
    
    # Wipe
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    draw.send_json({'command': 'draw_text', 'text': 'EXP. TEST', 'x': 0, 'y': 1, 'flags': 0x26})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    print("\n--- Test 1: Bitmask Spam (Lower Nibble) for Text ---")
    print("Documented colors: 00=blk/trans, 01=xor/trans, 10=red/blk, 11=red/trans")
    print("Documented modes: 0x06 is default, 0x86 is inverted.")
    
    # We will test flags from 0x00 to 0x1F to see if there's yellow or anything else
    for flags in range(0x00, 0x20):
        # Clear lines 2 and 3
        draw.send_json({'command': 'clear_area', 'x': 0, 'y': 11, 'w': 64, 'h': 20})
        
        # We will also test if adding the "Invert" flag (0x80) on top changes things
        draw.send_json({'command': 'draw_text', 'text': f"FLG: {flags:02X}", 'x': 0, 'y': 11, 'flags': flags})
        draw.send_json({'command': 'draw_text', 'text': f"INV: {(flags|0x80):02X}", 'x': 0, 'y': 21, 'flags': flags | 0x80})
        
        draw.send_json({'command': 'commit'})
        
        sys.stdout.write(f"\rTesting Flag {flags:02X} and {(flags|0x80):02X}    ")
        sys.stdout.flush()
        
        time.sleep(1.0)
    print()

    # What if X coordinate for bitmap goes higher? Or flags byte for graphics?
    print("\n--- Test 2: Unknown Bitmap Flags ---")
    # documented: U command: Length, Flags, X(must be 0), Y, bitmap_data...
    # Let's test the 'flags' byte for draw_bitmap by slightly tweaking the dis_service if we could.
    # Currently dis_service hardcodes `payload_bmp = [0x55, len(chunk_data) + 3, 0x02, 0x00, chunk_y] + chunk_data`
    # We'd have to edit dis_service.py to expose it. For now, testing text is the safest.

    print("\nClearing all in 2 seconds...")
    time.sleep(2)
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    print("Test complete.")

if __name__ == "__main__":
    run_test()
