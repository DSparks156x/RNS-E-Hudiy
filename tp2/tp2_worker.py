#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import json
import zmq
import logging
import sys
from tp2_protocol import TP2Protocol, TP2Error
from tp2_coding import TP2Coding

# Configure Logging
# Use StreamHandler for systemd/console logging, and optionally a file.
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Configuration
ZMQ_PUB_ADDR = 'tcp://*:5557' # Validated Port

class TP2Worker:
    def __init__(self):
        self.protocol = TP2Protocol(channel='can0')
        self.context = zmq.Context()
        self.pub = self.context.socket(zmq.PUB)
        self.pub.bind(ZMQ_PUB_ADDR)
        
        # Modules to Query
        # 0x01: Engine
        self.target_module = 0x01 
        
        # Groups to Query
        # Group 003: RPM, MAF, etc.
        # Group 011: Turbo Boost
        # Group 115: Turbo (Petrol)
        self.groups = [3, 11] 
        self.current_group_idx = 0
        self.connected = False

    def run(self):
        logger.info("TP2 Worker Service Starting (Validated Logic)...")
        
        try:
            self.protocol.open()
        except:
            logger.error("Failed to open CAN bus. Retrying in 5s...")
            time.sleep(5)
            return

        while True:
            try:
                # 1. Ensure Connection
                if not self.connected:
                    if self.protocol.connect(self.target_module):
                        logger.info(f"Connected to Module 0x{self.target_module:02X}")
                        
                        # VALIDATED LOGIC: Start Session 0x89
                        try:
                            resp = self.protocol.send_kvp_request([0x10, 0x89])
                            if resp and resp[0] != 0x7F:
                                logger.info(f"Session 0x89 Started: {resp}")
                                self.connected = True
                            else:
                                logger.error(f"Session Start Failed: {resp}")
                                self.protocol.disconnect()
                                time.sleep(2)
                                continue
                                
                            # VALIDATED LOGIC: SKIP 1A 9B (Read ID) and 31 B8 (Routine)
                            # These caused disconnects in testing.
                            
                            # Initial Keep-Alive
                            self.protocol.send_keep_alive()

                        except TP2Error as e:
                            logger.error(f"Setup Error: {e}")
                            self.protocol.disconnect()
                            self.connected = False
                            time.sleep(2)
                            continue
                    else:
                        time.sleep(2)
                        continue

                # 2. Query Loop
                grp = self.groups[self.current_group_idx]
                
                try:
                    # KWP ReadGroup
                    resp = self.protocol.send_kvp_request([0x21, grp])
                    
                    if resp and resp[0] == 0x61 and resp[1] == grp:
                        decoded = TP2Coding.decode_block(resp[2:])
                        
                        # Publish
                        payload = {
                            'module': self.target_module,
                            'group': grp,
                            'data': decoded
                        }
                        self.pub.send_multipart([b'HUDIY_DIAG', json.dumps(payload).encode()])
                        
                        # Log periodically (every 10th sample to avoid spam)
                        # logger.debug(f"Group {grp}: {decoded}") 
                        
                        # Move to next group
                        self.current_group_idx = (self.current_group_idx + 1) % len(self.groups)
                        
                    elif resp and resp[0] == 0x7F:
                        logger.warning(f"Group {grp} Rejected: {resp}")
                    else:
                        logger.warning(f"Group {grp} Unexpected: {resp}")
                        
                    # VALIDATED LOGIC: Aggressive Keep-Alive
                    # Sending Keep-Alive after EVERY request stabilizes the link on some ECUs.
                    self.protocol.send_keep_alive()
                        
                except TP2Error as e:
                    logger.error(f"Query Error (Group {grp}): {e}")
                    # Try to recover without full reconnect first
                    try:
                        if not self.protocol.send_keep_alive():
                            raise TP2Error("Keep-Alive Failed")
                    except:
                        logger.warning("Link Lost. Reconnecting...")
                        self.protocol.disconnect()
                        self.connected = False
                
                # Rate Limiting (Validated ~5Hz refresh overall)
                time.sleep(0.1) 

            except KeyboardInterrupt:
                logger.info("Stopping...")
                break
            except Exception as e:
                logger.error(f"Worker Loop Fatal Error: {e}")
                time.sleep(1)

        self.protocol.close()

if __name__ == "__main__":
    TP2Worker().run()
