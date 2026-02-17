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
        
        if not resp or resp[0] == 0x7F:
            logger.error(f"Session Failed: {resp}")
            return
        logger.info(f"Session Started: {resp}")
        
        # Give ECU time to settle
        time.sleep(0.1)

        # 2. Read ECU ID (1A 9B) - Re-enabling to check if timing fixed it
        logger.info("Step 2: Reading ECU ID (1A 9B)...")
        try:
             resp = protocol.send_kvp_request([0x1A, 0x9B])
             logger.info(f"ECU ID: {resp}")
        except Exception as e:
             logger.warning(f"Step 2 Failed: {e}")
             # If this disconnects, we know framing/timing didn't help.
             if "Disconnected" in str(e): return

        time.sleep(0.1)

        # 3. Start Routine (31 B8 00 00) - Still skipped for now to isolate Step 2
        # logger.info("Step 3: Starting Routine (31 B8 00 00)...")
        # try:
        #      resp = protocol.send_kvp_request([0x31, 0xB8, 0x00, 0x00])
        #      logger.info(f"Routine Response: {resp}")
        # except Exception as e:
        #      logger.warning(f"Step 3 Failed: {e}")

        # time.sleep(0.1)

        # 4. NOW Send Keep Alive (A3)
        # Note: ECU_Read.cpp sends A3 after the full init. 
        # But if we stop here, we should send it.
        logger.info("Step 4: Sending KeepAlive (A3)...")
        protocol.send_keep_alive()
        
        # 5. Read Group 1
        logger.info("Step 5: Reading Group 1...")
        for i in range(5):
             try:
                 resp = protocol.send_kvp_request([0x21, 0x01])
                 if resp and resp[0] == 0x61:
                      logger.info(f"!!! SUCCESS !!! Group 1: {TP2Coding.decode_block(resp[2:])}")
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
