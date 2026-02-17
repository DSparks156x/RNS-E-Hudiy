#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import logging
import argparse
import sys
from tp2_protocol import TP2Protocol, TP2Error
from tp2_coding import TP2Coding

# Configure Logging to file only to keep console clean for data
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("tp2_continuous.log"),
        # logging.StreamHandler() # Disable stream handler for cleaner output
    ]
)
logger = logging.getLogger(__name__)

def read_continuous(groups):
    protocol = TP2Protocol(channel='can0')
    print(f"Connecting to Engine (0x01) to read Groups {groups} continuously...")
    
    try:
        protocol.open()
        if not protocol.connect(0x01): 
            print("Failed to connect.")
            return

        # 1. Start Session 0x89
        resp = protocol.send_kvp_request([0x10, 0x89])
        if not resp or resp[0] == 0x7F:
            print(f"Session Failed: {resp}")
            return
        
        # 3. Initial Keep Alive
        protocol.send_keep_alive()
        
        print("Starting Loop. Press Ctrl+C to stop.")
        
        start_time = time.time()
        last_report_time = start_time
        frame_count = 0
        
        while True:
            for group_id in groups:
                # Send Request
                try:
                    resp = protocol.send_kvp_request([0x21, group_id])
                    
                    if resp and resp[0] == 0x61:
                        decoded = TP2Coding.decode_block(resp[2:])
                        # Print Data concisely
                        output = f"Grp {group_id}: " + ", ".join([f"{item['value']}{item['unit']}" for item in decoded])
                        print(output)
                        frame_count += 1
                    else:
                        logger.warning(f"Group {group_id} Failed. Resp: {resp}")
                except Exception as e:
                    logger.error(f"Read Error: {e}")
                    # Try to recover session?
                    protocol.send_keep_alive()

                # Keep-Alive Logic
                # We can send it less frequently if we are reading fast?
                # But safer to just toggle it for now or rely on the read acting as activity?
                # ECU_Read.cpp sends A3 periodically. 
                # Let's send A3 if > 200ms elapsed since last activity?
                # For simplicity, sending every loop for now to be safe.
                # protocol.send_keep_alive() 
                
            # Report Rate every 1 second
            now = time.time()
            if now - last_report_time >= 1.0:
                rate = frame_count / (now - last_report_time)
                print(f"--- Rate: {rate:.2f} reads/sec ---")
                frame_count = 0
                last_report_time = now

    except KeyboardInterrupt:
        print("\nStopping...")
    except Exception as e:
        print(f"Error: {e}")
        logger.error(f"Fatal Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    # Default groups if none provided
    groups = [1]
    
    if len(sys.argv) > 1:
        # Parse args as comma-separated or space-separated integers
        input_args = sys.argv[1:]
        try:
            # Check if arg is a number or string
            first_arg = input_args[0]
            if ',' in first_arg:
                 groups = [int(x) for x in first_arg.split(',')]
            else:
                 groups = [int(x) for x in input_args]
        except:
            print("Usage: python3 read_engine_data.py <group_numbers>")
            print("Example: python3 read_engine_data.py 1 2 3")
            sys.exit(1)
            
    read_continuous(groups)
