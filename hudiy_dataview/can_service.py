#!/usr/bin/env python3
import os
import sys
import json
import time
import zmq
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (CAN Service) %(message)s')
logger = logging.getLogger(__name__)

def load_config():
    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
         with open(os.path.join(_base_dir, 'config.json')) as _f:
             cfg = json.load(_f)
         can_raw = cfg['zmq'].get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc')
         # Create a separate ipc file that app.py will subscribe to alongside tp2
         pub_stream = cfg['zmq'].get('status_stream', 'ipc:///run/rnse_control/status_stream.ipc')
         return can_raw, pub_stream
    except Exception as e:
         logger.warning(f"Could not read config.json: {e}")
         return 'ipc:///run/rnse_control/can_stream.ipc', 'ipc:///run/rnse_control/status_stream.ipc'

class CANService:
    def __init__(self):
        self.context = zmq.Context()
        self.can_addr, self.pub_addr = load_config()
        self.running = True

        self._last_ambient = 0
        self._last_oil = 0
        
        # State tracking for rate limiting (e.g 4 Hz)
        self._last_publish = 0
        self._publish_interval = 0.25 
        
        self.latest_data = {
            'rpm': None,
            'coolant': None,
            'boost': None
        }

    def connect(self):
        try:
            # Subscribe to RAW CAN bus mapped by tp2_worker/dis_service
            self.can_sock = self.context.socket(zmq.SUB)
            self.can_sock.connect(self.can_addr)
            for t in [b"CAN_35B", b"CAN_0x35B", b"CAN_555", b"CAN_0x555", b"CAN_527", b"CAN_0x527"]:
                self.can_sock.subscribe(t)
            logger.info(f"Connected to RAW CAN at {self.can_addr}")

            # Publisher to app.py
            self.pub_sock = self.context.socket(zmq.PUB)
            self.pub_sock.bind(self.pub_addr)
            logger.info(f"Publishing HUDIY_DIAG CAN status to {self.pub_addr}")
            return True
        except Exception as e:
            logger.error(f"ZMQ Connection Failed: {e}")
            return False

    def publish_status(self):
        now = time.monotonic()
        if now - self._last_publish < self._publish_interval:
            return

        self._last_publish = now
        
        # We model this exactly after the legacy code so it mimics tp2 format
        if self._last_oil != 0 or self._last_ambient != 0:
            payload = {
                'module': 0,
                'group': 0,
                'data': [
                     {'value': self._last_oil, 'unit': 'C'},
                     {'value': self._last_ambient, 'unit': 'C'}
                ]
            }
            self.pub_sock.send_multipart([b'HUDIY_DIAG', json.dumps(payload).encode()])

    def run(self):
        if not self.connect():
            sys.exit(1)

        poller = zmq.Poller()
        poller.register(self.can_sock, zmq.POLLIN)

        logger.info("CAN Service running...")
        
        while self.running:
            try:
                socks = dict(poller.poll(50))
                
                if self.can_sock in socks:
                    while self.can_sock.poll(0):
                        topic, msg = self.can_sock.recv_multipart()
                        t_str = topic.decode()
                        
                        try:
                            payload = bytes.fromhex(json.loads(msg)['data_hex'])
                            if '35B' in t_str and len(payload) >= 4:
                                self.latest_data['rpm'] = (payload[2] * 256 + payload[1]) / 4.0
                                self.latest_data['coolant'] = (payload[3] * 0.75) - 64
                                
                            if '555' in t_str and len(payload) >= 8:
                                self.latest_data['boost'] = (payload[3] + payload[4] * 256) * 0.08
                                self._last_oil = payload[7] - 60
                                
                            if '527' in t_str and len(payload) >= 6:
                                self._last_ambient = (payload[5] * 0.5) - 50
                        except Exception as e:
                            logger.debug(f"Error parsing CAN message {t_str}: {e}")
                
                self.publish_status()
                
            except KeyboardInterrupt:
                self.running = False
                break
            except Exception as e:
                logger.error(f"CAN Service error: {e}")
                time.sleep(1)

if __name__ == '__main__':
    service = CANService()
    service.run()
