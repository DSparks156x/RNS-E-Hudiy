#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import json
import zmq
import logging
from tp2_protocol import TP2Protocol, TP2Error
from tp2_coding import TP2Coding

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Configuration
CONFIG_PATH = '/home/pi/config.json' # Or relative
ZMQ_PUB_ADDR = 'tcp://*:5557' # New topic for diagnostics? Or share existing?
# Let's use a new port or same publisher if possible. 
# dis_service uses 5556. Let's use 5557 for HUDIY_DIAG.

class TP2Worker:
    def __init__(self):
        self.protocol = TP2Protocol(channel='can0')
        self.context = zmq.Context()
        self.pub = self.context.socket(zmq.PUB)
        self.pub.bind(ZMQ_PUB_ADDR)
        
        # Modules to Query
        # 0x01: Engine
        # 0x17: Instruments
        self.target_module = 0x01 
        
        # Groups to Query
        # Group 003: RPM, MAF, etc.
        # Group 011: Turbo Boost
        # Group 115: Turbo (Petrol)
        self.groups = [3, 11] 
        self.current_group_idx = 0

    def run(self):
        logger.info("TP2 Worker Starting...")
        self.protocol.open()
        
        while True:
            try:
                # 1. Ensure Connection
                if not self.protocol.connected:
                    if self.protocol.connect(self.target_module):
                        # 2. Start Diagnostic Session (KWP 0x10 0x89)
                        # Payload: [SID=0x10, Mode=0x89]
                        try:
                            resp = self.protocol.send_kvp_request([0x10, 0x89])
                            logger.info(f"Session Started: {resp}")
                        except TP2Error as e:
                            logger.error(f"Failed session start: {e}")
                    else:
                        time.sleep(2)
                        continue

                # 3. Query Groups
                grp = self.groups[self.current_group_idx]
                
                # KWP ReadGroup: [SID=0x21, Group]
                try:
                    resp = self.protocol.send_kvp_request([0x21, grp])
                    
                    # Resp: [0x61, Group, (Type,A,B), (Type,A,B)...]
                    if resp and resp[0] == 0x61 and resp[1] == grp:
                        data_triplets = resp[2:]
                        decoded = TP2Coding.decode_block(data_triplets)
                        
                        # Publish
                        payload = {
                            'module': self.target_module,
                            'group': grp,
                            'data': decoded
                        }
                        self.pub.send_multipart([b'HUDIY_DIAG', json.dumps(payload).encode()])
                        
                        logger.info(f"Group {grp}: {decoded}")
                        
                        # Cycle group
                        self.current_group_idx = (self.current_group_idx + 1) % len(self.groups)
                        
                    else:
                        logger.warning(f"Unexpected response for Group {grp}: {resp}")
                        
                except TP2Error as e:
                    logger.error(f"Query Error: {e}")
                    self.protocol.connected = False # Force reconnect
                
                # Rate Limiting
                time.sleep(0.2) 

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Worker Loop Error: {e}")
                time.sleep(1)

        self.protocol.close()

if __name__ == "__main__":
    TP2Worker().run()
