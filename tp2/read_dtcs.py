#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import logging
from tp2_protocol import TP2Protocol, TP2Error
from dtc_lookup import lookup_dtc

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def read_dtcs():
    protocol = TP2Protocol(channel='can0')
    logger.info("Connecting to Engine (0x01) to read DTCs...")
    
    try:
        protocol.open()
        if not protocol.connect(0x01):
            logger.error("Failed to connect.")
            return

        # 1. Start Session 0x89
        # Skipped 1A/31 commands as per validated logic
        try:
             resp = protocol.send_kvp_request([0x10, 0x89])
             if resp and resp[0] != 0x7F:
                 logger.info(f"Session Started: {resp}")
             else:
                 logger.error(f"Session Start Failed: {resp}")
                 return
        except TP2Error as e:
             logger.error(f"Session Error: {e}")
             return
             
        # Keep Alive
        protocol.send_keep_alive()
        
        # 2. Read DTCs (0x18)
        # Request: [0x18, 0x00, 0xFF, 0x00] -> ReadByStatus, Group 0, All, Filter 0
        logger.info("Requesting DTCs (0x18)...")
        try:
            resp = protocol.send_kvp_request([0x18, 0x00, 0xFF, 0x00])
            
            if not resp:
                logger.error("No response for DTC request.")
            elif resp[0] == 0x7F:
                 logger.error(f"DTC Request Rejected: {resp}")
            elif resp[0] == 0x58:
                 # Response Format: [0x58, Count, DTC1_Hi, DTC1_Lo, Status1, DTC2_Hi, ...]
                 count = resp[1]
                 logger.info(f"DTC Count: {count}")
                 
                 # Each DTC is 3 bytes (High, Low, Status)
                 dtc_data = resp[2:]
                 if len(dtc_data) >= count * 3:
                     for i in range(count):
                         idx = i * 3
                         hi = dtc_data[idx]
                         lo = dtc_data[idx+1]
                         status = dtc_data[idx+2]
                         
                         code = (hi << 8) | lo
                         desc = lookup_dtc(code)
                         
                         logger.info(f"DTC #{i+1}: {code} (0x{code:04X}) - {desc} [Status: 0x{status:02X}]")
                 else:
                     logger.warning(f"Response length mismatch. Expected {count*3}, got {len(dtc_data)}")
                     logger.info(f"Raw Data: {dtc_data}")
            else:
                 logger.warning(f"Unexpected DTC Response: {resp}")
                 
        except TP2Error as e:
            logger.error(f"DTC Read Error: {e}")
            
        # Clean Disconnect
        protocol.disconnect()

    except Exception as e:
        logger.error(f"Script Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    read_dtcs()
