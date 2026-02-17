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
                    try:
                        protocol.send_keep_alive()
                    except: pass

                # Keep-Alive Logic
                # RESTORED: Sending A3 every loop proved to be the most stable.
                # The ECU seems to need this 'heartbeat' or 'breather' between requests.
                try:
                    protocol.send_keep_alive()
                except Exception as e:
                    logger.error(f"Keep-Alive Error: {e}")
                
            # Report Rate every 1 second
            now = time.time()
            elapsed = now - last_report_time
            if elapsed >= 1.0:
                rate = frame_count / elapsed
                per_group_rate = rate / len(groups) if groups else 0
                print(f"--- Total: {rate:.1f} reads/sec | Refresh: {per_group_rate:.1f} Hz/group ---")
                
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
