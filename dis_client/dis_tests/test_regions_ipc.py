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
    if not os.path.exists(config_path) and os.path.exists('../../config.json'):
        config_path = '../../config.json'

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
    print("Testing Different Screen Regions...")
    print("==========================================")
    
    # --- TEST 1: FULL SCREEN (0,0, 64,88) ---
    print("\n--- Test 1: Full Screen (y=0 to y=88) ---")
    draw.send_json({'command': 'set_region', 'region': 'full'})
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 88})
    
    # We should be able to write completely at the top (radio area)
    draw.send_json({'command': 'draw_text', 'text': 'FULL SCREEN TOP', 'x': 0, 'y': 1, 'flags': 0x06})
    
    # We should be able to write completely at the bottom (outside navigation area)
    draw.send_json({'command': 'draw_text', 'text': 'FULL SCREEN BTM', 'x': 0, 'y': 70, 'flags': 0x06})
    
    draw.send_json({'command': 'commit'})
    time.sleep(4)

    # --- TEST 2: CENTRE LOWER (0,27, 64,61) ---
    print("\n--- Test 2: Centre + Lower Area (Relative Y=0 to Y=61) ---")
    draw.send_json({'command': 'set_region', 'region': 'centre_lower'})
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 61})
    
    # y=0 is now relative to the 27 pixel offset
    draw.send_json({'command': 'draw_text', 'text': 'CNTR.LWR. TOP', 'x': 0, 'y': 0, 'flags': 0x06})
    
    # y=52 is near the bottom of this extended region
    draw.send_json({'command': 'draw_text', 'text': 'CNTR.LWR. BTM', 'x': 0, 'y': 52, 'flags': 0x06})
    draw.send_json({'command': 'commit'})
    time.sleep(4)

    # --- TEST 3: TOP + CENTRE (0,0, 64,75) ---
    print("\n--- Test 3: Experimental Top + Centre Area (Relative Y=0 to Y=75) ---")
    draw.send_json({'command': 'set_region', 'region': 'top_centre'})
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 75})
    
    # y=0 is relative to 0
    draw.send_json({'command': 'draw_text', 'text': 'TOP_CNTR TOP', 'x': 0, 'y': 0, 'flags': 0x06})
    
    # y=65 is near the bottom of this extended region (just above gear row)
    draw.send_json({'command': 'draw_text', 'text': 'TOP_CNTR BTM', 'x': 0, 'y': 65, 'flags': 0x06})
    draw.send_json({'command': 'commit'})
    time.sleep(4)

    # --- TEST 4: CENTRAL (0,27, 64,48) - DEFAULT ---
    print("\n--- Test 4: Standard Central Area (Relative Y=0 to Y=48) ---")
    draw.send_json({'command': 'set_region', 'region': 'central'})
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    
    # y=0 is relative to 27
    draw.send_json({'command': 'draw_text', 'text': 'CENTRAL TOP', 'x': 0, 'y': 0, 'flags': 0x06})
    
    # y=39 is the standard bottom line
    draw.send_json({'command': 'draw_text', 'text': 'CENTRAL BTM', 'x': 0, 'y': 39, 'flags': 0x06})
    draw.send_json({'command': 'commit'})
    time.sleep(4)

    print("\nClearing all in 2 seconds and returning to Central...")
    time.sleep(2)
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})
    print("Test complete.")

if __name__ == "__main__":
    run_test()
