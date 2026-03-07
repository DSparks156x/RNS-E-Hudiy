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
    elif not os.path.exists(config_path) and os.path.exists('config.json'):
         config_path = 'config.json'

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
        except Exception:
            config_addr = "tcp://127.0.0.1:5557"
            print(f"Assuming mock/emulator mode: {config_addr}")

    print(f"Connecting to {config_addr}...")
    context = zmq.Context()
    draw = context.socket(zmq.PUSH)
    draw.connect(config_addr)
    
    print("Connected. Sleeping for 1s to ensure connection is ready...")
    time.sleep(1)

    # Find the 0x1F mapping
    char_0x1F = None
    try:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        from icons import audscii_trans
        # Look for the index that maps TO 0x1F (which usually maps to 0x65 in icons.py)
        # Actually, in icons.py line 13: ..., 0x1C, 0x20, 0xD7, 0x65
        # Index 31 is 0x65. User says 0x1F blank char. AUDSCII[0x1F] is often 6px space.
        # In current icons.py: audscii_trans[31] = 0x65. 
        # So chr(31) is the character that sends 0x65 to the hardware.
        char_0x1F = chr(31)
        print(f"Using AUDSCII character index 31 (0x1F) for padding.")
    except Exception as e:
        print(f"Warning: Could not determine mapping from icons.py, falling back to chr(0x1F): {e}")
        char_0x1F = chr(31)

    def draw_line(text, y, flags=0x26, x=0):
        print(f"Drawing: '{text}' at y={y}, flags={flags:#x}, x={x}")
        draw.send_json({'command': 'draw_text', 'text': text, 'x': x, 'y': y, 'flags': flags})
        draw.send_json({'command': 'commit'})

    # 0. Initial Clear
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    print("\n" + "="*40)
    print("TEST 1: Growing and Shrinking Text with 0x1F Padding")
    print("Short text has 0x1F blank char padding equally to fill space.")
    print("="*40)
    
    long_text = "CENTERED TEXT" # Centered flag is 0x20. 0x06 | 0x20 = 0x26
    short_text = "SHORT"
    
    # 0x1F is 6px wide. Standard space is 2px.
    # We want equal padding on both sides to fill space occupied by long text.
    # This is qualitative since font is proportional, but let's add 2 pads on each side.
    padded_short = char_0x1F * 3+ short_text + char_0x1F * 3
    
    for _ in range(3):
        draw_line(long_text, 1, flags=0x26)
        time.sleep(1.5)
        draw_line(padded_short, 1, flags=0x26)
        time.sleep(1.5)

    print("\n" + "="*40)
    print("TEST 2: Centering with X != 0 (Middle of screen x=32)")
    print("Determines how centering flag interacts with X start position.")
    print("="*40)
    
    # Draw a divider or marker if possible? No, just draw text.
    draw_line("CENTER_X12", 11, flags=0x26, x=12)
    draw_line("CENTER_X32", 21, flags=0x26, x=32)
    time.sleep(3)

    print("\n" + "="*40)
    print("TEST 3: Alternating Overshoot vs Padded Overshoot")
    print("Screen is 64px. Font is proportional.")
    print("="*40)
    
    overshoot_text = "Very long text"
    padded_overshoot = char_0x1F * 3 + overshoot_text + char_0x1F * 3
    
    for _ in range(3):
        draw_line(overshoot_text, 31, flags=0x26)
        time.sleep(2)
        draw_line(padded_overshoot, 31, flags=0x26)
        time.sleep(2)

    print("\nTests complete.")
    time.sleep(1)
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})

if __name__ == "__main__":
    run_test()
