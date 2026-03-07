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
            
            # Check new structure first, then legacy
            zmq_cfg = config.get('interfaces', {}).get('zmq', {})
            if not zmq_cfg:
                zmq_cfg = config.get('zmq', {})
            
            config_addr = zmq_cfg.get('dis_draw', "tcp://127.0.0.1:5557")
        except Exception as e:
            config_addr = "tcp://127.0.0.1:5557"
            print(f"Assuming mock/emulator mode: {config_addr}")

    print(f"Connecting to {config_addr}...")
    context = zmq.Context()
    draw = context.socket(zmq.PUSH)
    draw.connect(config_addr)
    time.sleep(1)

    print("==========================================")
    print("Starting Experimental Bitmap flags tests...")
    print("==========================================")
    
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    # Use a pre-existing icon in icons.py mapping
    test_icon = 'DEPART' 
    
    # Text Header
    draw.send_json({'command': 'draw_text', 'text': 'BMP TEST', 'x': 0, 'y': 1, 'flags': 0x26})

    print("Testing Bitmaps with various mode flags (0x00 to 0x0F)...")
    print("Documented modes:")
    print("0x00: Erase mode")
    print("0x01: Invert mode")
    print("0x02: Draw mode (Standard)")
    print("0x03: Set mode")

    for flag in range(0x00, 0x10):
        # Clear the bitmap drawing area (bottom section)
        draw.send_json({'command': 'clear_area', 'x': 10, 'y': 11, 'w': 40, 'h': 38})
        
        # Test Drawing the Bitmap with the specific experimental flag
        draw.send_json({
            'command': 'draw_bitmap', 
            'icon_name': test_icon, 
            'x': 16,     # X-coordinate 
            'y': 11,     # Y-coordinate below the text header
            'mode_flag': flag
        })
        
        # Draw some indicator text
        draw.send_json({
            'command': 'draw_text', 
            'text': f"FLG {flag:02X}", 
            'x': 16, 
            'y': 48, # Right at the bottom
            'flags': 0x06
        })
        
        draw.send_json({'command': 'commit'})
        
        sys.stdout.write(f"\rTesting Flag {flag:02X}     ")
        sys.stdout.flush()
        
        time.sleep(1.5)
    print()

    print("\nClearing all in 2 seconds...")
    time.sleep(2)
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    print("Test complete.")

if __name__ == "__main__":
    run_test()
