#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_line_subpixel.py
Test script to send drawing commands to the running dis_service.py over ZMQ.
Tests subpixel positioning for 0x63 line drawing commands.
"""

import zmq
import time
import json
import os
import sys

def main():
    print("=========================================================")
    print("    Audi DIS 128x176 ZMQ Line Command Subpixel Tester    ")
    print("=========================================================")
    print("This script pushes experimental line commands to the running")
    print("dis_service.py over ZMQ to evaluate subpixel offsets.")
    print("---------------------------------------------------------")

    # Load config to get the ZMQ IPC address
    config_path = '/home/pi/config.json'
    if not os.path.exists(config_path) and os.path.exists('./config.json'):
        config_path = './config.json'

    try:
        with open(config_path) as f:
            config = json.load(f)
        zmq_cfg = config.get('interfaces', {}).get('zmq', {})
        if not zmq_cfg:
            zmq_cfg = config.get('zmq', {})
        config_addr = zmq_cfg.get('dis_draw', "tcp://127.0.0.1:5557")
    except Exception as e:
        config_addr = "ipc:///run/rnse_control/dis_draw.ipc"

    print(f"Connecting ZMQ socket to: {config_addr}")
    context = zmq.Context()
    draw = context.socket(zmq.PUSH)
    try:
        draw.connect(config_addr)
    except Exception as e:
        print(f"Failed to connect to ZMQ socket: {e}")
        return

    print("Connected. Sleeping 0.5s to settle...")
    time.sleep(0.5)

    # 1. Clear the area
    print("Clearing central region area...")
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    print("\n--- Sending Vertical Line Subpixel Tests ---")
    # Reference Lines (logical x=10 and x=11, which map to physical X=20 and X=22)
    # We draw reference lines from y=2 to y=42 (vertical height = 40)
    draw.send_json({'command': 'draw_line', 'x': 10, 'y': 2, 'length': 40, 'vertical': True})
    draw.send_json({'command': 'draw_line', 'x': 11, 'y': 2, 'length': 40, 'vertical': True})

    # Test 1: Orientation Byte subpixel shift (0x11 instead of 0x10)
    # Expected if successful: Vertical line at physical X=21 (centered between references) at y=5..10
    draw.send_json({'command': 'draw_line', 'x': 10, 'y': 5, 'length': 5, 'vertical': True, 'orientation': 0x11})

    # Test 2: Orientation Byte other bits (0x12)
    # Expected if successful: Vertical line at physical X=21 at y=15..20
    draw.send_json({'command': 'draw_line', 'x': 10, 'y': 15, 'length': 5, 'vertical': True, 'orientation': 0x12})

    # Test 3: Coordinate Byte high-bit 7 subpixel shift (x = 10 | 0x80 = 138)
    # Expected if successful: Vertical line at physical X=21 at y=25..30
    draw.send_json({'command': 'draw_line', 'x': (10 | 0x80), 'y': 25, 'length': 5, 'vertical': True})

    # Test 4: Coordinate Byte high-bit 6 subpixel shift (x = 10 | 0x40 = 74)
    # Expected if successful: Vertical line at physical X=21 at y=35..40
    draw.send_json({'command': 'draw_line', 'x': (10 | 0x40), 'y': 35, 'length': 5, 'vertical': True})

    draw.send_json({'command': 'commit'})

    print("Sent vertical line tests to dis_service.py.")
    print("Observe the cluster screen:")
    print("  - Two full-height vertical reference lines should appear at physical X=20 and X=22.")
    print("  - Look for short vertical segments exactly in the middle gap (physical X=21) at:")
    print("    * Band 1 (y=5..10): Orientation 0x11")
    print("    * Band 2 (y=15..20): Orientation 0x12")
    print("    * Band 3 (y=25..30): Coord X with bit 7 set (138)")
    print("    * Band 4 (y=35..40): Coord X with bit 6 set (74)")

    print("\nPress Enter to clear and proceed to horizontal line tests...")
    input()

    # Clear screen
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    print("\n--- Sending Horizontal Line Subpixel Tests ---")
    # Reference Lines (logical y=10 and y=11, which map to physical Y=20 and Y=22)
    # We draw reference lines from x=2 to x=60 (horizontal length = 58)
    draw.send_json({'command': 'draw_line', 'x': 2, 'y': 10, 'length': 58, 'vertical': False})
    draw.send_json({'command': 'draw_line', 'x': 2, 'y': 11, 'length': 58, 'vertical': False})

    # Test 1: Orientation Byte subpixel shift (0x21 instead of 0x20)
    # Expected if successful: Horizontal line at physical Y=21 at x=5..10
    draw.send_json({'command': 'draw_line', 'x': 5, 'y': 10, 'length': 5, 'vertical': False, 'orientation': 0x21})

    # Test 2: Orientation Byte other bits (0x22)
    # Expected if successful: Horizontal line at physical Y=21 at x=15..20
    draw.send_json({'command': 'draw_line', 'x': 15, 'y': 10, 'length': 5, 'vertical': False, 'orientation': 0x22})

    # Test 3: Coordinate Byte high-bit 7 subpixel shift (y = 10 | 0x80 = 138)
    # Expected if successful: Horizontal line at physical Y=21 at x=25..30
    draw.send_json({'command': 'draw_line', 'x': 25, 'y': (10 | 0x80), 'length': 5, 'vertical': False})

    # Test 4: Coordinate Byte high-bit 6 subpixel shift (y = 10 | 0x40 = 74)
    # Expected if successful: Horizontal line at physical Y=21 at x=35..40
    draw.send_json({'command': 'draw_line', 'x': 35, 'y': (10 | 0x40), 'length': 5, 'vertical': False})

    draw.send_json({'command': 'commit'})

    print("Sent horizontal line tests to dis_service.py.")
    print("Observe the cluster screen:")
    print("  - Two full-width horizontal reference lines should appear at physical Y=20 and Y=22.")
    print("  - Look for short horizontal segments exactly in the middle gap (physical Y=21) at:")
    print("    * Band 1 (x=5..10): Orientation 0x21")
    print("    * Band 2 (x=15..20): Orientation 0x22")
    print("    * Band 3 (x=25..30): Coord Y with bit 7 set (138)")
    print("    * Band 4 (x=35..40): Coord Y with bit 6 set (74)")

    print("\nPress Enter to finish and clear screen...")
    input()

    # Clear screen
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    print("Test complete.")

if __name__ == "__main__":
    main()
