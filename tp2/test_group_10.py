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
        
        # Hold briefly
        protocol.send_keep_alive()
        
        # 2. Start Routine 31 B8 (Might be needed?)
        # Let's try it since we fixed the timeout handling
        logger.info("Step 2: Starting Routine 0x31 0xB8...")
        try:
             resp = protocol.send_kvp_request([0x31, 0xB8, 0x00, 0x00])
             logger.info(f"Routine Response: {resp}")
        except Exception as e:
             logger.warning(f"Routine Error: {e}")
        
        protocol.send_keep_alive()

        # 3. Read Group 1
        logger.info("Step 3: Reading Group 1...")
        for i in range(5):
             try:
                 resp = protocol.send_kvp_request([0x21, 0x01])
                 if resp and resp[0] == 0x61:
                      logger.info(f"Group 1: {TP2Coding.decode_block(resp[2:])}")
                 else:
                      logger.warning(f"Read Fail: {resp}")
             except Exception as e:
                 logger.error(f"Read Error: {e}")
                 break
             time.sleep(0.5)
             protocol.send_keep_alive()

        protocol.disconnect()

    except Exception as e:
        logger.error(f"Script Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    test_group_10()
