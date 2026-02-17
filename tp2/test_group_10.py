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

def send_tester_present(protocol):
    """Sends Tester Present (0x3E 0x00) to keep Diagnostic Session active."""
    try:
        # We don't really care about the response, just sending it.
        # But we must consume the response to not desync.
        resp = protocol.send_kvp_request([0x3E, 0x00])
        return True
    except TP2Error:
        return False

def send_tester_present(protocol):
    """Sends Tester Present (0x3E 0x00) to keep Diagnostic Session active."""
    try:
        # We don't really care about the response, just sending it.
        # But we must consume the response to not desync.
        resp = protocol.send_kvp_request([0x3E, 0x00])
        return True
    except TP2Error:
        return False

def test_group_10():
    protocol = TP2Protocol(channel='can0')
    logger.info("Starting Group 10 Logger...")
    
    try:
        protocol.open()
        
        # Connect to Engine (0x01)
        if not protocol.connect(0x01):
            logger.error("Failed to connect to Engine ECU.")
            return

        # 1. Start Session
        # Try 0x89 (Adjustment) first, then 0x81 (Standard)
        logger.info("Step 1: Starting Diagnostic Session...")
        session_established = False
        
        for session_type in [0x89, 0x81]:
            try:
                logger.info(f"Trying Session Type 0x{session_type:02X}...")
                resp = protocol.send_kvp_request([0x10, session_type])
                logger.info(f"Session Start Response: {resp}")
                
                # Check for Positive Response (0x50)
                if resp and resp[0] == 0x50:
                    session_established = True
                    break
                elif resp and resp[0] == 0x7F:
                    logger.warning(f"Session 0x{session_type:02X} rejected: {resp}")
            except Exception as e:
                 logger.warning(f"Session 0x{session_type:02X} failed: {e}")
        
        if not session_established:
            logger.error("Failed to establish any Diagnostic Session. Proceeding anyway (risk of failure).")
        
        protocol.send_keep_alive()

        # 2. Read ECU ID (Skipping - causes instant disconnect)
        # logger.info("Step 2: Reading ECU ID (0x1A, 0x9B)...")
        # try:
        #     resp = protocol.send_kvp_request([0x1A, 0x9B])
        #     logger.info(f"ECU ID Response: {resp}")
        # except Exception as e:
        #     logger.warning(f"Failed to read ECU ID: {e}")

        # protocol.send_keep_alive()

        # 3. Start Routine (Skipping - assuming causes disconnect)
        # logger.info("Step 3: Starting Routine (0x31, 0xB8)...")
        # try:
        #     resp = protocol.send_kvp_request([0x31, 0xB8, 0x00, 0x00])
        #     logger.info(f"Routine Start Response: {resp}")
        # except Exception as e:
        #     logger.warning(f"Failed to start routine: {e}")

        # protocol.send_keep_alive()
        
        # TEST: Session Hold Loop
        # We will just send Tester Present for 10 seconds to prove we can hold the session.
        logger.info("TEST: Holding Session for 10 seconds...")
        for i in range(20):
             time.sleep(0.5)
             if not send_tester_present(protocol):
                 logger.error("Tester Present Failed! Session Lost?")
                 break
        logger.info("TEST: Session Held. Now trying to read.")

        # Query Loop
        logger.info("Starting Data Query Loop (Groups 1 and 10)...")
        groups_to_check = [1, 10]
        
        for i in range(5):
            for group in groups_to_check:
                try:
                    # Send Tester Present BEFORE reading to ensure session acts alive
                    send_tester_present(protocol)
                    
                    resp = protocol.send_kvp_request([0x21, group])
                    if resp and resp[0] == 0x61:
                        decoded = TP2Coding.decode_block(resp[2:])
                        logger.info(f"Group {group}: {decoded}")
                    elif resp and resp[0] == 0x7F:
                        logger.warning(f"Group {group} rejected: {resp}")
                    else:
                        logger.warning(f"Group {group} unexpected: {resp}")
                except Exception as e:
                    logger.warning(f"Group {group} error: {e}")
                    if "Disconnected" in str(e): return
                
                time.sleep(0.2)
        
        # Close
        protocol.disconnect()
        
    except Exception as e:
        logger.error(f"Script Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    test_group_10()
