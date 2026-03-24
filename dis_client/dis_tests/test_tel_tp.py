#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tel_tp.py
Experimental script to test TP1.6 (Infotainment TP) wrapping on Telephone IDs.
Tries to send a string > 8 bytes to the FIS top lines.
"""

import can
import time
import sys

# --- Configuration ---
CAN_CHANNEL = 'can0'
CAN_BITRATE = 100000
ID_TX = 0x667  # Telephone -> Cluster
ID_RX = 0x66B  # Cluster -> Telephone

def send_tp_message(bus, text):
    print(f"--- Starting TP Test for: '{text}' ---")
    
    # 1. Attempt TP Connect (A0)
    print(f"Step 1: Sending Connect (A0) to 0x{ID_TX:X}...")
    connect_pkt = [0xA0, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    msg_connect = can.Message(arbitration_id=ID_TX, data=connect_pkt, is_extended_id=False)
    bus.send(msg_connect)
    
    # Wait for Accept (A1)
    start = time.time()
    accepted = False
    while time.time() - start < 1.0:
        msg = bus.recv(0.1)
        if msg and msg.arbitration_id == ID_RX:
            if msg.data[0] == 0xA1:
                print(f"Step 2: Received Accept (A1) from 0x{ID_RX:X}!")
                accepted = True
                break
    
    if not accepted:
        print("Warning: No A1 response received. The cluster might not require a handshake or uses a different ID.")
        print("Attempting 'Blind Send' anyway...")

    # 2. Prepare Data Frames
    # AUDSCII translation (Simple ASCII for now, clusters usually accept it)
    data = [ord(c) for c in text]
    
    # Chunk into 7-byte blocks
    chunks = [data[i:i + 7] for i in range(0, len(data), 7)]
    
    seq = 0
    for i, chunk in enumerate(chunks):
        is_last = (i == len(chunks) - 1)
        # Type 0x20 = Continuous, 0x10 = Final/End
        prefix = 0x10 if is_last else 0x20
        header = prefix | (seq & 0x0F)
        
        pkt = [header] + chunk
        # Pad with 0x00 if needed (some clusters require 8-byte DLC)
        if len(pkt) < 8:
            pkt += [0x00] * (8 - len(pkt))
            
        print(f"Sending Block {i} (Type 0x{prefix:02X}, Seq {seq}): {pkt}")
        msg_data = can.Message(arbitration_id=ID_TX, data=pkt, is_extended_id=False)
        bus.send(msg_data)
        
        seq = (seq + 1) % 16
        
        # In TP, we expect an ACK (0xBx) after the 0x1x frame
        if is_last:
            print("Waiting for ACK (B0)...")
            start = time.time()
            while time.time() - start < 1.0:
                ack = bus.recv(0.1)
                if ack and ack.arbitration_id == ID_RX:
                    if (ack.data[0] & 0xF0) == 0xB0:
                        print(f"Success: Received ACK 0x{ack.data[0]:02X}")
                        return True
            print("Notice: No ACK received for the data block.")
            
    return False

def main():
    try:
        bus = can.Bus(interface='socketcan', channel=CAN_CHANNEL, bitrate=CAN_BITRATE)
        print(f"CAN Bus {CAN_CHANNEL} initialized.")
    except Exception as e:
        print(f"Error: Could not open CAN bus: {e}")
        sys.exit(1)

    test_text = "LONG TELEPHONE TEST TEXT"
    if len(sys.argv) > 1:
        test_text = " ".join(sys.argv[1:])

    send_tp_message(bus, test_text)
    
    print("\nTest complete. Check your FIS display.")
    bus.shutdown()

if __name__ == "__main__":
    main()
