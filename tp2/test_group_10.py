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
    logger.info("Starting Group 10 Logger...")
    
    try:
        protocol.open()
        
        # Connect to Engine (0x01)
        if not protocol.connect(0x01):
            logger.error("Failed to connect to Engine ECU.")
            return

        # Start Session
        logger.info("Starting Diagnostic Session...")
        protocol.send_kvp_request([0x10, 0x89])
        
        # Query Group 10 Loop
        logger.info("Reading Group 10...")
        for i in range(20): # Read 20 samples then exit
            try:
                # KWP ReadGroup 10 (0x0A)
                resp = protocol.send_kvp_request([0x21, 0x0A])
                
                if resp and resp[0] == 0x61 and resp[1] == 0x0A:
                    decoded = TP2Coding.decode_block(resp[2:])
                    logger.info(f"Sample {i+1}: {decoded}")
                else:
                    logger.warning(f"Sample {i+1}: Unexpected response {resp}")
                    
                time.sleep(0.5)
                
            except TP2Error as e:
                logger.error(f"Error reading sample {i+1}: {e}")
                break
                
        # Close
        protocol.disconnect()
        
    except Exception as e:
        logger.error(f"Script Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    test_group_10()
