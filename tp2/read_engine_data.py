#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import logging
import argparse
from tp2_protocol import TP2Protocol, TP2Error
from tp2_coding import TP2Coding

# Configure Logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def read_engine_groups(groups):
    protocol = TP2Protocol(channel='can0')
    logger.info(f"Connecting to Engine (0x01) to read Groups {groups}...")
    
    try:
        protocol.open()
        if not protocol.connect(0x01): 
            logger.error("Failed to connect.")
            return

        # 1. Start Session 0x89
        logger.info("Step 1: Starting Session 0x89...")
        resp = protocol.send_kvp_request([0x10, 0x89])
        if not resp or resp[0] == 0x7F:
            logger.error(f"Session Failed: {resp}")
            return
        
        # 2. Skip '1A 9B' & '31 B8' (Verified to cause disconnects)
        
        # 3. Initial Keep Alive
        logger.info("Sending Keep-Alive...")
        protocol.send_keep_alive()
        
        # 4. Read Groups Loop
        for group_id in groups:
            logger.info(f"--- Reading Group {group_id} ---")
            
            # Send Request
            resp = protocol.send_kvp_request([0x21, group_id])
            
            # Handle Response
            if resp and resp[0] == 0x61:
                decoded = TP2Coding.decode_block(resp[2:])
                logger.info(f"SUCCESS Group {group_id}:")
                for item in decoded:
                    logger.info(f"  {item['type']}: {item['value']} {item['unit']}")
            elif resp:
                logger.warning(f"Group {group_id} Failed. Response: {resp}")
            else:
                logger.warning(f"Group {group_id} Failed: No Acceptable Response")

            # Keep Alive between groups (and slight delay)
            # ECU_Read.cpp interleaves Keep-Alives
            time.sleep(0.2)
            protocol.send_keep_alive()

        protocol.disconnect()

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    import sys
    
    # Default groups if none provided
    groups = [1, 2, 3]
    
    if len(sys.argv) > 1:
        # Parse args as comma-separated or space-separated integers
        input_args = sys.argv[1:]
        groups = []
        for arg in input_args:
            if ',' in arg:
                groups.extend([int(x) for x in arg.split(',')])
            else:
                groups.append(int(arg))
    
    read_engine_groups(groups)
