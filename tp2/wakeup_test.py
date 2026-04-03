#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import can
import time
import sys

def test_wakeup():
    print("Initializing CAN bus...")
    try:
        bus = can.Bus(interface='socketcan', channel='can0', bitrate=100000)
    except Exception as e:
        print(f"Failed to open CAN: {e}")
        sys.exit(1)
        
    print("\n--- TEST 1: TP2.0 Wakeup Broadcast ---")
    print("Sending Wakeup (0x23) to Engine (0x01) 5 times...")
    for i in range(5):
        msg = can.Message(
            arbitration_id=0x200, 
            data=[0x01, 0x23, 0x00, 0x00, 0x00, 0x00, 0x00], 
            is_extended_id=False
        )
        try:
            bus.send(msg)
            time.sleep(0.05)
        except Exception as e:
            print(f"Failed to send: {e}")
        
    print("Waiting for response on 0x201...")
    start = time.time()
    wakeup_success = False
    while time.time() - start < 2.0:
        msg = bus.recv(0.1)
        if msg and msg.arbitration_id == 0x201:
            print(f">>> Gateway/Engine Replied to Wakeup: {[hex(x) for x in msg.data]}")
            wakeup_success = True
            break

    if not wakeup_success:
        print("No response to Wakeup broadcast.")
            
    print("\n--- TEST 2: TP2.0 Channel Setup ---")
    print("Sending Setup Request (0xC0) to Engine (0x01)...")
    req = [0x01, 0xC0, 0x00, 0x10, 0x00, 0x03, 0x01]
    
    try:
        bus.send(can.Message(arbitration_id=0x200, data=req, is_extended_id=False))
    except Exception as e:
        print(f"Failed to send: {e}")
        
    start = time.time()
    setup_success = False
    while time.time() - start < 2.0:
        msg = bus.recv(0.1)
        if msg and msg.arbitration_id == 0x201:
            print(f">>> Gateway/Engine Replied to Setup: {[hex(x) for x in msg.data]}")
            setup_success = True
            break
            
    if not setup_success:
        print("No response to Channel Setup.")
        
    print("\nDone.")
    bus.shutdown()

if __name__ == '__main__':
    test_wakeup()
