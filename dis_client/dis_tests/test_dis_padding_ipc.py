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
        except Exception:
            config_addr = "tcp://127.0.0.1:5557"
            print(f"Assuming mock/emulator mode: {config_addr}")

    print(f"Connecting to {config_addr}...")
    context = zmq.Context()
    draw = context.socket(zmq.PUSH)
    draw.connect(config_addr)
    
    print("Connected. Sleeping for 1s to ensure connection is ready...")
    time.sleep(1)

    print("==========================================")
    print("Starting padding cycle tests...")
    print("==========================================")
    
    # 1. Full wipe to start clean
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    # 2. Base Header
    draw.send_json({'command': 'draw_text', 'text': 'PADDING TEST', 'x': 0, 'y': 1, 'flags': 0x26})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    char_before_map = chr(0x65)
    char_after_map_65 = None
    char_after_map_D7 = None

    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from icons import audscii_trans
        
        # Look for any index that maps to 0x65
        mapped_indices_65 = [i for i, x in enumerate(audscii_trans) if x == 0x65]
        if mapped_indices_65:
            char_after_map_65 = chr(mapped_indices_65[0])
            print(f"Found char mapped TO 0x65: chr({mapped_indices_65[0]}) (0x{mapped_indices_65[0]:02X})")
        else:
            print("WARNING: No character maps to 0x65 in audscii_trans!")
            
    except ImportError as e:
        print(f"Could not load icons.py: {e}")

    # TEST 1
    print("\n--- Test 1: Full line clear with chr(0x65) (Before Translation Map) ---")
    print("Step A: Drawing a FULL WIDTH string.")
    draw.send_json({'command': 'draw_text', 'text': "1234567890", 'x': 0, 'y': 11, 'flags': 0x06})
    draw.send_json({'command': 'commit'})
    time.sleep(2)
    
    print("Step B: Drawing a FULL LINE (11 chars) of the char mapped to 0x65 to see if it clears.")
    print("If it works, the entire string should disappear without flickering.")
    
    # Send a string of 11 characters that map to 0x65 on the display
    clear_string = char_after_map_65 * 11 if char_after_map_65 else chr(0x65) * 11
    
    draw.send_json({'command': 'draw_text', 'text': clear_string, 'x': 0, 'y': 11, 'flags': 0x06})
    draw.send_json({'command': 'commit'})
    time.sleep(3)
    
    # TEST 2
    if char_after_map_65:
        print("\n--- Test 2: Padding with char mapped to 0x65 (After Translation Map) ---")
        print(f"This ensures the physical payload to the DIS receives the literal byte 0x65.")
        for i in range(10):
            text = f"T2CK {i}" if i % 2 == 0 else f"T2CK {i} PADDING"
            target_len = 11
            pad_len = max(0, target_len - len(text))
            padded_text = text + (char_after_map_65 * pad_len)
            
            draw.send_json({'command': 'draw_text', 'text': padded_text, 'x': 0, 'y': 21, 'flags': 0x06})
            draw.send_json({'command': 'commit'})
            
            sys.stdout.write(f"\rCycle {i+1}/10 sent   ")
            sys.stdout.flush()
            time.sleep(0.5)


    print("\nTest complete. Clearing in 2 seconds...")
    time.sleep(2)
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})

if __name__ == "__main__":
    run_test()
