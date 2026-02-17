#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import logging
from tp2_protocol import TP2Protocol, TP2Error

# Configure Logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("probe_log.txt"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def probe_engine():
    protocol = TP2Protocol(channel='can0')
    logger.info("--- Probing Engine ECU (0x01) ---")
    
    try:
        protocol.open()
        if not protocol.connect(0x01):
            logger.error("Failed to connect.")
            return

        protocol.send_keep_alive()
        
        # 1. Probe Diagnostic Sessions
        sessions = [
            0x81, # KWP Standard
            0x89, # KWP Adjustment
            0xC0, # KWP VW Specific?
            0x01, # UDS Default
            0x03, # UDS Extended
            0x02  # UDS Programming
        ]
        
        logger.info("--- Probing Diagnostic Sessions ---")
        for session in sessions:
            try:
                resp = protocol.send_kvp_request([0x10, session])
                if resp and resp[0] == 0x50:
                    logger.info(f"SUCCESS: Session 0x{session:02X} Accepted!")
                elif resp and resp[0] == 0x7F:
                    logger.info(f"Session 0x{session:02X} Rejected (NRC 0x{resp[2]:02X})")
                else:
                    logger.info(f"Session 0x{session:02X} Unknown Resp: {resp}")
            except Exception as e:
                logger.warning(f"Session 0x{session:02X} Error: {e}")
            protocol.send_keep_alive()
            time.sleep(0.2)

        # 2. Probe Read Commands
        logger.info("--- Probing Read Commands ---")
        
        # KWP Read Group 1 (0x21 0x01)
        try:
            logger.info("Trying KWP Read Group 0x01 (21 01)...")
            resp = protocol.send_kvp_request([0x21, 0x01])
            if resp and resp[0] == 0x61:
                 logger.info(f"SUCCESS: KWP Read Group 1: {resp}")
            elif resp and resp[0] == 0x7F:
                 logger.info(f"KWP Read Group 1 Rejected (NRC 0x{resp[2]:02X})")
        except Exception as e:
            logger.warning(f"KWP Read Error: {e}")

        protocol.send_keep_alive()

        # UDS Read DID F190 (VIN) (0x22 F1 90)
        try:
            logger.info("Trying UDS Read DID F190 (22 F1 90)...")
            resp = protocol.send_kvp_request([0x22, 0xF1, 0x90])
            if resp and resp[0] == 0x62:
                 logger.info(f"SUCCESS: UDS Read DID F190: {resp}")
            elif resp and resp[0] == 0x7F:
                 logger.info(f"UDS Read DID F190 Rejected (NRC 0x{resp[2]:02X})")
        except Exception as e:
            logger.warning(f"UDS Read Error: {e}")

        # 3. Tester Present (0x3E 0x00)
        try:
            logger.info("Trying Tester Present (3E 00)...")
            resp = protocol.send_kvp_request([0x3E, 0x00])
             if resp and resp[0] == 0x7E:
                 logger.info(f"SUCCESS: Tester Present Ack: {resp}")
            elif resp and resp[0] == 0x7F:
                 logger.info(f"Tester Present Rejected (NRC 0x{resp[2]:02X})")
        except Exception as e:
            pass

        protocol.disconnect()

    except Exception as e:
        logger.error(f"Probe Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    probe_engine()
