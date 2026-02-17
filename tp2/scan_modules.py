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
        logging.FileHandler("scan_log.txt"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def test_module(module_id, module_name):
    logger.info(f"--- Testing Module 0x{module_id:02X} ({module_name}) ---")
    protocol = TP2Protocol(channel='can0')
    
    try:
        protocol.open()
        
        # Connect
        if not protocol.connect(module_id):
            logger.error(f"Failed to connect to {module_name}.")
            return

        protocol.send_keep_alive()

        # Try Reading Group 1 immediately (No Session)
        logger.info("Attempting to read Group 1 (No Session)...")
        try:
            resp = protocol.send_kvp_request([0x21, 0x01])
            if resp and resp[0] == 0x61:
                decoded = TP2Coding.decode_block(resp[2:])
                logger.info(f"SUCCESS: Group 1 Data: {decoded}")
                return # We are done, it works!
            else:
                logger.warning(f"Group 1 Read Failed: {resp}")
        except Exception as e:
            logger.warning(f"Group 1 Read Error: {e}")

        # Try Starting Session 0x89
        logger.info("Attempting Session 0x89...")
        protocol.send_keep_alive()
        try:
            resp = protocol.send_kvp_request([0x10, 0x89])
            if resp and resp[0] == 0x50:
                logger.info("Session 0x89 Started.")
            else:
                 logger.warning(f"Session 0x89 Failed: {resp}")
        except Exception as e:
            logger.warning(f"Session 0x89 Error: {e}")

        protocol.disconnect()

    except Exception as e:
        logger.error(f"Module {module_name} Test Error: {e}")
    finally:
        protocol.close()

def run_scan():
    test_module(0x01, "Engine")
    test_module(0x17, "Instruments")

if __name__ == "__main__":
    run_scan()
