#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tel_ddp.py (Refined - v2)
Triggers cluster with 0x665 heartbeat, then responds to A0 on 0x6C4 using 0x6C5.
"""

import can
import time
import sys

# --- Configuration ---
CAN_CHANNEL = 'can0'
CAN_BITRATE = 100000
ID_HEARTBEAT = 0x665  # Phone heartbeat / Trigger
ID_TX = 0x6C5         # Corrected TX ID based on user feedback
ID_RX = 0x6C4         # Cluster's TX ID (Our RX)

def main():
    try:
        bus = can.Bus(interface='socketcan', channel=CAN_CHANNEL, bitrate=CAN_BITRATE)
        print(f"CAN Bus {CAN_CHANNEL} initialized.")
    except Exception as e:
        print(f"Error: Could not open CAN bus: {e}")
        sys.exit(1)

    print(f"Step 1: Sending periodic heartbeats to 0x{ID_HEARTBEAT:X}...")
    # Send a few heartbeats to get the cluster's attention
    for _ in range(3):
        bus.send(can.Message(arbitration_id=ID_HEARTBEAT, data=[0x00]*8, is_extended_id=False))
        time.sleep(0.1)

    print(f"Step 2: Listening for A0 (Open Session) on 0x{ID_RX:X}...")
    start = time.time()
    
    # We will loop for a bit to catch the A0
    while time.time() - start < 10.0:
        msg = bus.recv(0.1)
        if msg and msg.arbitration_id == ID_RX:
            data = list(msg.data)
            print(f"RX [0x{ID_RX:X}]: {' '.join(f'{b:02X}' for b in data)}")
            
            if data[0] == 0xA0:
                print(">>> Handshake Detected: Cluster wants to open a session!")
                
                # Step 3: Respond with A1 (Accept)
                # We replicate the params (BlockSize, timers)
                a1_resp = [0xA1] + data[1:]
                print(f"Step 3: Sending A1 (Accept) to 0x{ID_TX:X}: {' '.join(f'{b:02X}' for b in a1_resp)}")
                bus.send(can.Message(arbitration_id=ID_TX, data=a1_resp, is_extended_id=False))
                
                # Step 4: DDP sequence
                print("Step 4: Sending DDP initialization frames...")
                
                # Packet: [Type+Seq, Op, Data...]
                # Type 0x1x = End of Frame
                
                # 0x15: Discovery/Init
                bus.send(can.Message(arbitration_id=ID_TX, data=[0x10, 0x15, 0x01, 0x01, 0x02, 0x00, 0x00, 0x00], is_extended_id=False))
                time.sleep(0.05)
                
                # 0x57: Write "HELLO"
                # Characters: H=0x48, E=0x45, L=0x4C, L=0x4C, O=0x4F
                # Flags=0x02, X=0, Y=0
                bus.send(can.Message(arbitration_id=ID_TX, data=[0x11, 0x57, 0x08, 0x02, 0x00, 0x00, 0x48, 0x45], is_extended_id=False))
                bus.send(can.Message(arbitration_id=ID_TX, data=[0x22, 0x4C, 0x4C, 0x4F, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
                
                # 0x39: Commit
                bus.send(can.Message(arbitration_id=ID_TX, data=[0x13, 0x39, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], is_extended_id=False))
                
                print("DDP Frames sent via 0x6C5. Observe FIS.")
                
            elif data[0] == 0xA8:
                print("Cluster sent A8 (Disconnect).")
            
        # Keep sending heartbeats so it doesn't close the "door"
        if int(time.time() * 10) % 5 == 0:
             bus.send(can.Message(arbitration_id=ID_HEARTBEAT, data=[0x00]*8, is_extended_id=False))

    print("\nTest complete.")
    bus.shutdown()

if __name__ == "__main__":
    main()
