#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tel_ddp_final.py
Uses the refactored DDPProtocol to communicate with the Phone FIS area.
"""

import sys
import os
import time
import logging
import threading

# Add parent directory to path so we can import ddp_protocol
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ddp_protocol import DDPProtocol, DDPState, DDPCANError

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
TEL_CONFIG = {
    'can_channel': 'can0',
    'can_bitrate': 100000,
    'ddp_tx_id': 0x6C4,  # Our TX (Device)
    'ddp_rx_id': 0x6C5,  # Cluster TX (Our RX)
}
ID_HEARTBEAT = 0x665

def heartbeat_worker(bus_ref, stop_event):
    """Sends heartbeats to keep the cluster interested."""
    while not stop_event.is_set():
        try:
            msg = bus_ref.send(can.Message(arbitration_id=ID_HEARTBEAT, data=[0x00]*8, is_extended_id=False))
        except:
            pass
        time.sleep(1.0)

def main():
    import can # Import here to avoid issues if not installed
    
    # 1. Initialize Protocol
    try:
        ddp = DDPProtocol(TEL_CONFIG)
    except DDPCANError as e:
        print(f"Failed to init CAN: {e}")
        return

    stop_heartbeat = threading.Event()
    h_thread = threading.Thread(target=heartbeat_worker, args=(ddp.bus, stop_heartbeat), daemon=True)
    h_thread.start()

    print("--- Phone DDP Final Test ---")
    print(f"Triggering with 0x{ID_HEARTBEAT:X} heartbeats...")

    try:
        # 2. Handshake (Step 1: Open Session)
        # We use detect_and_open_session which handles both Active and Passive (A0) opens.
        if ddp.detect_and_open_session():
            print(f"Session Open! (Mode: {ddp.dis_mode.name})")
            
            # Step 2: Protocol Initialization
            if ddp.perform_initialization():
                print("DDP Initialization Successful! State: READY")
                
                # 3. Send Text
                # Opcode 0x57 (Write), Len, Flags, X, Y, Characters
                # "PHONE TEST"
                text = "PHONE TEST"
                chars = [ord(c) for c in text]
                # Wrapping in DDP payload
                payload = [0x57, len(chars)+3, 0x02, 0x00, 0x00] + chars
                # Commit
                payload += [0x39]
                
                print(f"Sending test payload: '{text}'")
                if ddp.send_ddp_frame(payload):
                    print("DDP Frame sent successfully!")
                else:
                    print("Failed to send DDP frame.")
                
                # 4. Keep session alive for observation
                print("Keeping session alive for 10 seconds. Observe FIS.")
                start_obs = time.time()
                while time.time() - start_obs < 10:
                    ddp.poll_bus_events()
                    ddp.send_keepalive_if_needed()
                    time.sleep(0.05)
            else:
                print("DDP Initialization failed.")
        else:
            print("Failed to open DDP session.")

    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        stop_heartbeat.set()
        ddp.close_session()
        print("Test finished.")

if __name__ == "__main__":
    main()
