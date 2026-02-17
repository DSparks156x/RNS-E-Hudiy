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

def read_engine_group(group_id):
    protocol = TP2Protocol(channel='can0')
    logger.info(f"Connecting to Engine (0x01) to read Group {group_id}...")
    
    try:
        protocol.open()
        if not protocol.connect(0x01): 
            logger.error("Failed to connect.")
            return

        # 1. Start Session 0x89 (Verified Working)
        logger.info("Step 1: Starting Session 0x89...")
        resp = protocol.send_kvp_request([0x10, 0x89])
        if not resp or resp[0] == 0x7F:
            logger.error(f"Session Failed: {resp}")
            return
        
        # 2. Skip '1A 9B' & '31 B8' (Verified to cause disconnects)
        # We rely on the driver's wait-frame handling and extended timeouts.
        
        # 3. Send Keep Alive (Ensure link is active)
        logger.info("Sending Keep-Alive...")
        protocol.send_keep_alive()
        
        # 4. Read Data
        logger.info(f"Reading Group {group_id}...")
        resp = protocol.send_kvp_request([0x21, group_id])
        
        if resp and resp[0] == 0x61:
            decoded = TP2Coding.decode_block(resp[2:])
            logger.info(f"!!! SUCCESS !!! Group {group_id} Data:")
            for item in decoded:
                logger.info(f"  - {item}")
        elif resp:
            logger.warning(f"Read Failed. Response: {resp}")
        else:
            logger.warning("Read Failed: No Acceptable Response")

        protocol.disconnect()

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    import sys
    group = 1
    if len(sys.argv) > 1:
        group = int(sys.argv[1])
    read_engine_group(group)
