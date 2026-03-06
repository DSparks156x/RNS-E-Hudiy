#!/usr/bin/env python3
import os
import sys
import json
import time
import zmq
import logging
import argparse
import select

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (Data Logger) %(message)s')
logger = logging.getLogger(__name__)

def load_config():
    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(_base_dir, 'config.json')
    try:
         with open(config_path) as _f:
             cfg = json.load(_f)
         can_raw = cfg['zmq'].get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc')
         tp2_stream = cfg['zmq'].get('tp2_stream', 'ipc:///run/rnse_control/tp2_stream.ipc')
         tp2_cmd = cfg['zmq'].get('tp2_command', 'ipc:///run/rnse_control/tp2_cmd.ipc')
         return can_raw, tp2_stream, tp2_cmd
    except Exception as e:
         logger.warning(f"Could not read config.json: {e}")
         return 'ipc:///run/rnse_control/can_stream.ipc', 'ipc:///run/rnse_control/tp2_stream.ipc', 'ipc:///run/rnse_control/tp2_cmd.ipc'

class DataLogger:
    def __init__(self, module, groups, can_ids):
        self.context = zmq.Context()
        self.can_addr, self.tp2_stream_addr, self.tp2_cmd_addr = load_config()
        self.running = True

        self.module = module
        self.groups = groups
        self.can_ids = can_ids
        
        self.latest_data = {
            'tp2': {},
            'can': {}
        }
        for g in self.groups:
            self.latest_data['tp2'][g] = None
        for i in self.can_ids:
            self.latest_data['can'][i.lower()] = None
            
        self.client_id = "data_logger_" + str(os.getpid())

    def connect(self):
        try:
            # Subscribe to RAW CAN bus mapped by tp2_worker/dis_service
            self.can_sock = self.context.socket(zmq.SUB)
            self.can_sock.connect(self.can_addr)
            for i in self.can_ids:
                # Add various formats to be safe
                self.can_sock.subscribe(f"CAN_{i}".encode())
                self.can_sock.subscribe(f"CAN_0x{i}".encode())
                self.can_sock.subscribe(f"CAN_{i.upper()}".encode())
                self.can_sock.subscribe(f"CAN_0x{i.upper()}".encode())
            logger.info(f"Connected to RAW CAN at {self.can_addr}")

            # Subscribe to TP2 stream
            self.tp2_sock = self.context.socket(zmq.SUB)
            self.tp2_sock.connect(self.tp2_stream_addr)
            self.tp2_sock.subscribe(b"HUDIY_DIAG")
            logger.info(f"Connected to TP2 Stream at {self.tp2_stream_addr}")

            # Command socket for TP2
            self.cmd_sock = self.context.socket(zmq.REQ)
            self.cmd_sock.connect(self.tp2_cmd_addr)
            logger.info(f"Connected to TP2 Command at {self.tp2_cmd_addr}")
            
            return True
        except Exception as e:
            logger.error(f"ZMQ Connection Failed: {e}")
            return False

    def sync_tp2(self):
        try:
            cmd = {
                "cmd": "SYNC",
                "client_id": self.client_id,
                "module": self.module,
                "groups": self.groups,
                "low_priority_groups": []
            }
            self.cmd_sock.send_json(cmd)
            resp = self.cmd_sock.recv_json()
            if resp.get("status") == "ok":
                logger.info(f"Synced TP2 for module 0x{self.module:02X}, groups: {self.groups}")
            else:
                logger.error(f"Failed to sync TP2: {resp}")
        except Exception as e:
            logger.error(f"Error syncing TP2: {e}")

    def log_current_data(self):
        print("\n" + "="*50)
        print(f"Data Log at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*50)
        
        print(f"--- CAN Messages ---")
        for can_id in self.can_ids:
            key = can_id.lower()
            val = self.latest_data['can'].get(key)
            if val:
                print(f"[{can_id.upper()}] Payload: {val}")
            else:
                print(f"[{can_id.upper()}] No data received yet.")
                
        print(f"\n--- TP2 Module 0x{self.module:02X} Groups ---")
        for grp in self.groups:
            data = self.latest_data['tp2'].get(grp)
            if data:
                print(f"[Group {grp}]")
                for i, item in enumerate(data):
                    val = item.get('value', 'N/A')
                    unit = item.get('unit', '')
                    desc = item.get('description', f'Field {i}')
                    print(f"  - {desc}: {val} {unit}")
            else:
                print(f"[Group {grp}] No data received yet.")
                
        print("="*50 + "\n")

    def run(self):
        if not self.connect():
            sys.exit(1)

        poller = zmq.Poller()
        poller.register(self.can_sock, zmq.POLLIN)
        poller.register(self.tp2_sock, zmq.POLLIN)

        logger.info("Data Logger running...")
        logger.info("Press ENTER to log current data. Press Ctrl+C to exit.")
        
        last_sync = 0
        
        while self.running:
            try:
                # Sync TP2 every 5 seconds to keep our client_id alive
                now = time.time()
                if now - last_sync > 5.0:
                    self.sync_tp2()
                    last_sync = now

                # Check for zero-timeout stdin (Enter keypress)
                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    sys.stdin.readline() # consume the enter
                    self.log_current_data()
                
                socks = dict(poller.poll(50))
                
                # Process CAN Raw
                if self.can_sock in socks:
                    while self.can_sock.poll(0):
                        topic, msg = self.can_sock.recv_multipart()
                        t_str = topic.decode()
                        
                        try:
                            payload_hex = json.loads(msg)['data_hex']
                            for can_id in self.can_ids:
                                if str(can_id).lower() in t_str.lower():
                                    self.latest_data['can'][can_id.lower()] = payload_hex
                        except Exception as e:
                            logger.debug(f"Error parsing CAN message {t_str}: {e}")
                
                # Process TP2 Stream
                if self.tp2_sock in socks:
                    while self.tp2_sock.poll(0):
                        topic, msg = self.tp2_sock.recv_multipart()
                        try:
                            payload = json.loads(msg)
                            if payload.get('module') == self.module:
                                grp = payload.get('group')
                                if grp in self.groups:
                                    self.latest_data['tp2'][grp] = payload.get('data', [])
                        except Exception as e:
                            logger.debug(f"Error parsing TP2 message: {e}")
                            
            except KeyboardInterrupt:
                self.running = False
                break
            except Exception as e:
                logger.error(f"Data Logger error: {e}")
                time.sleep(1)

        logger.info("Shutting down Data Logger.")
        # Cleanup TP2 client
        try:
            cmd = {
                "cmd": "SYNC",
                "client_id": self.client_id,
                "module": self.module,
                "groups": [],
                "low_priority_groups": []
            }
            self.cmd_sock.send_json(cmd)
            self.cmd_sock.recv_json() # consume response
        except:
            pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="CAN and TP2 Data Logger")
    parser.add_argument("-m", "--module", type=lambda x: int(x, 0), default=1, help="TP2 Module ID (default: 1)")
    parser.add_argument("-g", "--groups", type=lambda s: [int(item) for item in s.split(',')], default=[6, 114], help="Comma separated list of TP2 groups (default: 6,114)")
    parser.add_argument("-i", "--ids", type=lambda s: [item.strip() for item in s.split(',')], default=["555"], help="Comma separated list of CAN IDs in hex (default: 555)")
    
    args = parser.parse_args()
    
    logger = DataLogger(module=args.module, groups=args.groups, can_ids=args.ids)
    logger.run()
