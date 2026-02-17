#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import logging
from tp2_protocol import TP2Protocol, TP2Error
from tp2_coding import TP2Coding

# Configure Logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("group_10_log.txt"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def test_group_10():
    protocol = TP2Protocol(channel='can0')
    logger.info("Starting Group 10 Logger using 0x89...")
    
    try:
        protocol.open()
        if not protocol.connect(0x01): return

        # 1. Start Session 0x89
        logger.info("Step 1: Starting Session 0x89...")
        resp = protocol.send_kvp_request([0x10, 0x89])
        
        if not resp or resp[0] == 0x7F:
            logger.error(f"Session Failed: {resp}")
            return
        logger.info(f"Session Started: {resp}")
        
        # Give ECU time to settle & Keep Alive
        # We skip the fatal 1A 9B and 31 B8 commands.
        time.sleep(0.2)
        protocol.send_keep_alive()

        # 2. Reading Group 1 directly
        # The previous scan timed out on this, but we now have the "Wait Frame" fix.
        logger.info("Step 2: Reading Group 1 directly...")
        
        groups = [1, 2, 3] # Try a few groups
        
        for group in groups:
             logger.info(f"Reading Group {group}...")
             try:
                 resp = protocol.send_kvp_request([0x21, group])
                 if resp and resp[0] == 0x61:
                      logger.info(f"!!! SUCCESS !!! Group {group}: {TP2Coding.decode_block(resp[2:])}")
                 elif resp and resp[0] == 0x7F:
                      logger.warning(f"Group {group} Rejected: {resp}")
                 else:
                      logger.warning(f"Group {group} Unexpected: {resp}")
             except Exception as e:
                 logger.error(f"Group {group} Error: {e}")
                 # If disconnect, stop
                 if "Disconnected" in str(e): break
             
             time.sleep(0.5)
             protocol.send_keep_alive()

        protocol.disconnect()

    except Exception as e:
        logger.error(f"Script Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    test_group_10()
