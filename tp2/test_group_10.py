#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import logging
from tp2_protocol import TP2Protocol, TP2Error
from tp2_coding import TP2Coding

# Configure Logging
if not logging.getLogger().hasHandlers():
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
    logger.info("Starting Critical Test: Session 0x89 -> Skip Fatal -> ReadGroup...")
    
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
        
        # 2. SKIP Fatal Commands (1A 9B, 31 B8)
        # We suspect these cause disconnects. 
        # We rely on new Driver Fixes (T1=2.5s, T3=12ms, BufferClear, WaitFrame) to handle the direct read.
        logger.info("Step 2: Skipped 1A 9B (Read ID) to avoid disconnects.")
        logger.info("Step 3: Skipped 31 B8 (Routine) to avoid disconnects.")

        # 4. Send Keep Alive (A3)
        # Just to ensure link is alive before reading.
        logger.info("Step 4: Sending KeepAlive (A3)...")
        protocol.send_keep_alive()
        
        # 5. Read Group 1
        logger.info("Step 5: Reading Group 1...")
        
        # TEST 1: Try Standard 0x21 0x01
        logger.info("Trying Command 0x21 0x01 (ECU_Read.cpp)...")
        try:
             resp = protocol.send_kvp_request([0x21, 0x01])
             if resp and resp[0] == 0x61:
                  logger.info(f"!!! SUCCESS !!! (0x21) Group 1: {TP2Coding.decode_block(resp[2:])}")
             else:
                  logger.warning(f"0x21 Failed: {resp}")
        except Exception as e:
             logger.error(f"0x21 Error: {e}")

        protocol.send_keep_alive()
        time.sleep(0.5)

        # TEST 2: Try FISBlocks 0x29 0x01
        logger.info("Trying Command 0x29 0x01 (FISBlocks)...")
        try:
             resp = protocol.send_kvp_request([0x29, 0x01])
             if resp and resp[0] == 0x69: # Positive response to 29?
                  logger.info(f"!!! SUCCESS !!! (0x29) Group 1: {TP2Coding.decode_block(resp[2:])}")
             elif resp and resp[0] != 0x7F:
                  logger.info(f"!!! POSSIBLE SUCCESS !!! (0x29) Response: {resp}")
             else:
                  logger.warning(f"0x29 Failed: {resp}")
        except Exception as e:
             logger.error(f"0x29 Error: {e}")

        # protocol.disconnect()

    except Exception as e:
        logger.error(f"Script Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    test_group_10()
