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
        
        # Give ECU time to settle
        time.sleep(0.2)
        protocol.send_keep_alive()

        # 2. Test KWP Framing with TesterPresent (3E 00)
        # This is the simplest command. If framing is wrong, this will fail.
        logger.info("Step 2: Testing KWP Framing with TesterPresent(3E 00)...")
        try:
             # We expect 7E 00 as response
             resp = protocol.send_kvp_request([0x3E, 0x00])
             if resp and resp[0] == 0x7E:
                  logger.info(f"!!! SUCCESS !!! Framing Verified. Response: {resp}")
             else:
                  logger.warning(f"TesterPresent Failed: {resp}")
        except Exception as e:
             logger.error(f"TesterPresent Transmission Error: {e}")

        protocol.send_keep_alive()
        
        # If that worked, TRY Group 1 again
        if resp and resp[0] == 0x7E:
            logger.info("Step 3: Reading Group 1 (Since Framing is confirmed)...")
            try:
                resp = protocol.send_kvp_request([0x21, 0x01])
                logger.info(f"Group 1: {resp}")
            except: pass

        protocol.disconnect()

    except Exception as e:
        logger.error(f"Script Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    test_group_10()
