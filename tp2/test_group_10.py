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

def test_protocol_scan():
    protocol = TP2Protocol(channel='can0')
    logger.info("Starting TP2.0 Protocol Scanner...")
    
    try:
        protocol.open()
        
        # Connect to Engine (0x01)
        if not protocol.connect(0x01):
            logger.error("Failed to connect to Engine ECU.")
            return

        # List of Sessions to Probe
        # 0x81: KWP Standard
        # 0x89: KWP Adjustment
        # 0x86: KWP
        # 0xC0: VW Specific
        # 0x01: UDS Default
        # 0x03: UDS Extended
        sessions = [0x81, 0x89, 0x86, 0xC0, 0x03, 0x01]
        
        for session in sessions:
            logger.info(f"--- Testing Session 0x{session:02X} ---")
            
            # 1. Start Session
            try:
                resp = protocol.send_kvp_request([0x10, session])
                if not resp or resp[0] == 0x7F:
                    logger.warning(f"Session 0x{session:02X} rejected: {resp}")
                    # If session rejected, we probably don't need to reconnect, 
                    # but simple keep-alive might be needed?
                    protocol.send_keep_alive()
                    continue
                logger.info(f"Session 0x{session:02X} Accepted: {resp}")
            except Exception as e:
                logger.warning(f"Session 0x{session:02X} start error: {e}")
                # Reconnect if died
                protocol.disconnect()
                time.sleep(1)
                if not protocol.connect(0x01):
                    logger.error("FATAL: Could not reconnect during scan.")
                    break
                continue

            # Hold session briefly to stabilize
            for _ in range(3):
                protocol.send_keep_alive()
                time.sleep(0.1)

            # 2. Try Reading (Hybrid Approach)
            
            # Test A: KWP Read Group 001 (21 01)
            logger.info(f"[Session 0x{session:02X}] Probing KWP ReadGroup (0x21 0x01)...")
            try:
                resp = protocol.send_kvp_request([0x21, 0x01])
                if resp and resp[0] == 0x61:
                    logger.info(f"!!! SUCCESS !!! KWP Data Read: {resp}")
                    decoded = TP2Coding.decode_block(resp[2:])
                    logger.info(f"Decoded: {decoded}")
                else:
                    logger.info(f"KWP Read Rejected: {resp}")
            except Exception as e:
                logger.warning(f"KWP Read Error: {e}")

            protocol.send_keep_alive()

            # Test B: UDS Read VIN (22 F1 90)
            logger.info(f"[Session 0x{session:02X}] Probing UDS ReadDID (0x22 0xF1 0x90)...")
            try:
                resp = protocol.send_kvp_request([0x22, 0xF1, 0x90])
                if resp and resp[0] == 0x62:
                    logger.info(f"!!! SUCCESS !!! UDS Data Read: {resp}")
                    # Try interpreting as ASCII
                    try:
                        ascii_val = "".join([chr(x) for x in resp[3:] if 32 <= x <= 126])
                        logger.info(f"UDS ASCII: {ascii_val}")
                    except: pass
                else:
                    logger.info(f"UDS Read Rejected: {resp}")
            except Exception as e:
                 logger.warning(f"UDS Read Error: {e}")

            protocol.send_keep_alive()
            
            # Test C: KWP Read ID (1A 9B) - Just to check
            logger.info(f"[Session 0x{session:02X}] Probing KWP ReadID (1A 9B)...")
            try:
                resp = protocol.send_kvp_request([0x1A, 0x9B])
                if resp and resp[0] != 0x7F:
                     logger.info(f"KWP ReadID OK: {resp}")
                else:
                     logger.info(f"KWP ReadID Rejected: {resp}")
            except Exception as e:
                 logger.warning(f"KWP ReadID Error: {e}")

            # End Session / Prepare for next
            # We disconnect to reset state so next session start is clean
            logger.info("Disconnecting to reset state...")
            protocol.disconnect()
            time.sleep(1)
            if not protocol.connect(0x01):
                 logger.error("Failed to reconnect for next loop.")
                 break
        
    except Exception as e:
        logger.error(f"Script Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    test_protocol_scan()
