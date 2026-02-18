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
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Configuration
ZMQ_PUB_ADDR = 'tcp://*:5557' # Data Publish
ZMQ_REP_ADDR = 'tcp://*:5558' # Command Request/Reply

import os

# ... imports ...

class TP2Service:
    def __init__(self, config_file='config.json'):
        self.context = zmq.Context()
        
        # Calculate Path: ../config.json relative to this script
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, config_file)
        
        # Load Config
        try:
            with open(config_path) as f:
                self.config = json.load(f)
            
            # ZMQ Addresses
            self.addr_ignition = self.config['zmq'].get('system_events', 'tcp://localhost:5556')
            self.addr_pub = self.config['zmq'].get('tp2_stream', 'tcp://*:5557') 
            self.addr_rep = self.config['zmq'].get('tp2_command', 'tcp://*:5558')

            self.ignition_sub = self.context.socket(zmq.SUB)
            self.ignition_sub.connect(self.addr_ignition)
            self.ignition_sub.subscribe(b"POWER_STATUS")
            logger.info(f"Monitoring Ignition at {self.addr_ignition}")
        except Exception as e:
            logger.warning(f"Could not load config or connect to ignition bus: {e}. Defaulting to Always Enabled.")
            self.ignition_sub = None
            self.addr_pub = 'tcp://*:5557'
            self.addr_rep = 'tcp://*:5558'

        # Publisher (Data)
        self.pub = self.context.socket(zmq.PUB)
        self.pub.bind(self.addr_pub)
        
        # Replier (Commands)
        self.rep = self.context.socket(zmq.REP)
        self.rep.bind(self.addr_rep)
        
        # Connection Management
        self.sessions = {} 
        self.next_tester_id = 0x300
        self.running = True # Default to ON, will update if Ignition says OFF

    # ... existing methods (get_or_create, ensure_connected) ...
    def _get_or_create_session(self, module_id):
        if module_id in self.sessions:
            return self.sessions[module_id]
        
        # Create new session
        tester_id = self.next_tester_id
        self.next_tester_id += 1 # Increment for next module (0x300, 0x301...)
        
        logger.info(f"Creating new session for Module 0x{module_id:02X} (TesterID: 0x{tester_id:X})")
        
        proto = TP2Protocol(channel='can0', tester_id=tester_id)
        try:
            proto.open()
        except Exception as e:
            logger.error(f"Failed to open CAN for Module 0x{module_id:02X}: {e}")
            return None
            
        session = {
            'protocol': proto,
            'subs': {}, # {group_id: count}
            'groups_list': [], # Ordered list for cycling
            'idx': 0,
            'tester_id': tester_id,
            'connected': False,
            'last_activity': time.time()
        }
        self.sessions[module_id] = session
        return session

    def _ensure_connected(self, module_id):
        session = self.sessions.get(module_id)
        if not session: return False
        
        proto = session['protocol']
        
        if session['connected']:
            return True
            
        # Connect Logic
        try:
            # Ensure Bus is Open (Robustness)
            if not proto.bus:
                 logger.info(f"Opening CAN bus for Module 0x{module_id:02X}...")
                 proto.open()

            if proto.connect(module_id):
                # Start Session 0x89
                resp = proto.send_kvp_request([0x10, 0x89])
                if resp and resp[0] != 0x7F:
                    session['connected'] = True
                    proto.send_keep_alive()
                    logger.info(f"Module 0x{module_id:02X} Connected.")
                    return True
                else:
                    logger.error(f"Module 0x{module_id:02X} Session Refused: {resp}")
        except TP2Error as e:
             logger.error(f"Module 0x{module_id:02X} Connect Error: {e}")
             proto.disconnect()
        
        return False

    def process_ignition(self):
        if not self.ignition_sub: return
        
        try:
            while True:
                parts = self.ignition_sub.recv_multipart(flags=zmq.NOBLOCK)
                if len(parts) == 2 and parts[0] == b'POWER_STATUS':
                    pwr = json.loads(parts[1])
                    kl15 = pwr.get('kl15', False)
                    
                    if kl15 != self.running:
                        self.running = kl15
                        status = "Enabled" if self.running else "Disabled"
                        logger.info(f"Ignition Change: TP2 Service {status}")
                        
                        if not self.running:
                             # Disconnect all
                             for mod, sess in self.sessions.items():
                                 if sess['connected']:
                                     try: sess['protocol'].disconnect()
                                     except: pass
                                     sess['connected'] = False
        except zmq.Again:
            pass
        except Exception as e:
            logger.error(f"Ignition Monitor Error: {e}")

    def process_commands(self):
        # Non-blocking check for commands
        try:
            msg = self.rep.recv_json(flags=zmq.NOBLOCK)
        except zmq.Again:
            return 

        response = {"status": "error", "message": "Unknown command"}
        
        try:
            cmd = msg.get("cmd")
            
            if cmd == "STATUS":
                 # Prepare Status
                 sess_info = []
                 for mod, s in self.sessions.items():
                     sess_info.append({
                         "module": mod,
                         "connected": s['connected'],
                         "groups": list(s['subs'].keys())
                     })
                     
                 response = {
                     "status": "ok",
                     "enabled": self.running,
                     "session_count": len(sess_info),
                     "sessions": sess_info
                 }

            elif cmd == "ADD":
                mod = msg.get("module")
                grp = msg.get("group")
                if mod is not None and grp is not None:
                    param_mod = int(mod)
                    param_grp = int(grp)
                    
                    session = self._get_or_create_session(param_mod)
                    if session:
                        # Ref Counting Logic
                        if param_grp in session['subs']:
                            session['subs'][param_grp] += 1
                            logger.info(f"Incremented Group {param_grp} count to {session['subs'][param_grp]}")
                        else:
                            session['subs'][param_grp] = 1
                            session['groups_list'].append(param_grp)
                            logger.info(f"Added Group {param_grp} to Module 0x{param_mod:02X}")
                            
                        response = {"status": "ok", "message": "Group added", "count": session['subs'][param_grp]}
                    else:
                        response = {"status": "error", "message": "Failed to create session"}
                
            elif cmd == "REMOVE":
                mod = msg.get("module")
                grp = msg.get("group")
                if mod is not None and grp is not None:
                     param_mod = int(mod)
                     param_grp = int(grp)
                     if param_mod in self.sessions:
                         session = self.sessions[param_mod]
                         if param_grp in session['subs']:
                             session['subs'][param_grp] -= 1
                             count = session['subs'][param_grp]
                             logger.info(f"Decremented Group {param_grp} count to {count}")
                             
                             if count <= 0:
                                 del session['subs'][param_grp]
                                 if param_grp in session['groups_list']:
                                     session['groups_list'].remove(param_grp)
                                     # Reset idx if needed to avoid out of bounds
                                     if session['idx'] >= len(session['groups_list']):
                                         session['idx'] = 0
                                 logger.info(f"Removed Group {param_grp} from cycle")
                                 
                             response = {"status": "ok", "message": "Group removed", "count": count}
                         else:
                             response = {"status": "warning", "message": "Group not found"}
                     else:
                         response = {"status": "error", "message": "Module not active"}

            elif cmd == "CLEAR":
                # Close all sessions
                for mod, sess in self.sessions.items():
                    sess['protocol'].close()
                self.sessions = {}
                self.next_tester_id = 0x300
                logger.info("Cleared all sessions.")
                response = {"status": "ok", "message": "Cleared all"}
            
            elif cmd == "TOGGLE":
                self.running = not self.running
                msg = "Enabled" if self.running else "Disabled"
                logger.info(f"Service {msg} by API.")
                
                if not self.running:
                    # Disconnect all active sessions immediately
                    for mod, sess in self.sessions.items():
                        if sess['connected']:
                            sess['protocol'].disconnect()
                            sess['connected'] = False
                            
                response = {"status": "ok", "message": f"Service {msg}", "enabled": self.running}
                
        except Exception as e:
            logger.error(f"Command Error: {e}")
            response = {"status": "error", "message": str(e)}

        self.rep.send_json(response)

    def run(self):
        logger.info("TP2 Multi-Module Service Starting (Ignition Aware)...")
        
        while True:
            try:
                # 0. Check Ignition
                self.process_ignition()

                # 1. Process API Commands
                self.process_commands()
                
                # 2. Check Global Enable
                if not self.running:
                    time.sleep(0.1)
                    continue
                
                # 3. Cycle through active sessions
                active_modules = list(self.sessions.keys())
                
                if not active_modules:
                    time.sleep(0.1)
                    continue
                    
                for mod_id in active_modules:
                    session = self.sessions[mod_id]
                    
                    # Check if we have groups to read
                    if not session['groups_list']:
                        # Just send Keep-Alive if idle to maintain connection
                        if session['connected']:
                             try:
                                 session['protocol'].send_keep_alive()
                             except:
                                 session['connected'] = False
                        continue

                    # Ensure Connection
                    if not self._ensure_connected(mod_id):
                        continue
                    
                    # Read Next Group
                    # Safety check on index
                    if session['idx'] >= len(session['groups_list']):
                        session['idx'] = 0
                        
                    grp = session['groups_list'][session['idx']]
                    proto = session['protocol']
                    
                    try:
                        resp = proto.send_kvp_request([0x21, grp])
                        
                        if resp and resp[0] == 0x61 and resp[1] == grp:
                            # Decode
                            decoded = TP2Coding.decode_block(resp[2:])
                            # Publish
                            payload = {
                                'module': mod_id,
                                'group': grp,
                                'data': decoded
                            }
                            self.pub.send_multipart([b'HUDIY_DIAG', json.dumps(payload).encode()])
                            
                            # Cycle
                            if session['groups_list']:
                                 session['idx'] = (session['idx'] + 1) % len(session['groups_list'])
                            
                        elif resp and resp[0] == 0x7F:
                            logger.warning(f"Mod 0x{mod_id:02X} Grp {grp} Rejected: {resp}")
                        
                        # MANDATORY KEEP-ALIVE
                        proto.send_keep_alive()

                    except TP2Error as e:
                        logger.error(f"Mod 0x{mod_id:02X} Error: {e}")
                        # Try soft recovery
                        try:
                            proto.send_keep_alive()
                        except:
                            session['connected'] = False
                            proto.disconnect()
                
                # Rate Limiting
                time.sleep(0.1)

            except KeyboardInterrupt:
                logger.info("Stopping TP2 Service...")
                break
            except Exception as e:
                logger.error(f"CRITICAL MAIN LOOP ERROR: {e}")
                # Robust Recovery: Close all sessions so they rebuild next cycle
                for mod, sess in self.sessions.items():
                    try: 
                        sess['protocol'].close() # Sets bus = None
                        sess['connected'] = False
                    except: pass
                time.sleep(5)  # Wait for system to stabilize

if __name__ == "__main__":
    TP2Service().run()

                # 1. Process API Commands
                self.process_commands()
                
                # 2. Check Global Enable
                if not self.running:
                    time.sleep(0.1)
                    continue
                
                # 3. Cycle through active sessions
                active_modules = list(self.sessions.keys())
                
                if not active_modules:
                    time.sleep(0.1)
                    continue
                    
                for mod_id in active_modules:
                    session = self.sessions[mod_id]
                    
                    # Check if we have groups to read
                    if not session['groups_list']:
                        # Just send Keep-Alive if idle to maintain connection
                        if session['connected']:
                             try:
                                 session['protocol'].send_keep_alive()
                             except:
                                 session['connected'] = False
                        continue

                    # Ensure Connection
                    if not self._ensure_connected(mod_id):
                        continue
                    
                    # Read Next Group
                    # Safety check on index
                    if session['idx'] >= len(session['groups_list']):
                        session['idx'] = 0
                        
                    grp = session['groups_list'][session['idx']]
                    proto = session['protocol']
                    
                    try:
                        resp = proto.send_kvp_request([0x21, grp])
                        
                        if resp and resp[0] == 0x61 and resp[1] == grp:
                            # Decode
                            decoded = TP2Coding.decode_block(resp[2:])
                            # Publish
                            payload = {
                                'module': mod_id,
                                'group': grp,
                                'data': decoded
                            }
                            self.pub.send_multipart([b'HUDIY_DIAG', json.dumps(payload).encode()])
                            
                            # Cycle
                            if session['groups_list']:
                                 session['idx'] = (session['idx'] + 1) % len(session['groups_list'])
                            
                        elif resp and resp[0] == 0x7F:
                            logger.warning(f"Mod 0x{mod_id:02X} Grp {grp} Rejected: {resp}")
                        
                        # MANDATORY KEEP-ALIVE
                        proto.send_keep_alive()

                    except TP2Error as e:
                        logger.error(f"Mod 0x{mod_id:02X} Error: {e}")
                        # Try soft recovery
                        try:
                            proto.send_keep_alive()
                        except:
                            session['connected'] = False
                            proto.disconnect()
                
                # Rate Limiting
                # If we have many modules, we might want to sleep less
                time.sleep(0.1)

            except KeyboardInterrupt:
                logger.info("Stopping TP2 Service...")
                break
            except Exception as e:
                logger.error(f"CRITICAL MAIN LOOP ERROR: {e}")
                # Robust Recovery: Close all sessions so they rebuild next cycle
                for mod, sess in self.sessions.items():
                    try: 
                        sess['protocol'].close() # Sets bus = None
                        sess['connected'] = False
                    except: pass
                time.sleep(5)  # Wait for system to stabilize

            # 1. Process API Commands
            self.process_commands()
            
            # 2. Check Global Enable
            if not self.running:
                time.sleep(0.1)
                continue
            
            # 3. Cycle through active sessions
            active_modules = list(self.sessions.keys())
            
            if not active_modules:
                time.sleep(0.1)
                continue
                
            for mod_id in active_modules:
                session = self.sessions[mod_id]
                
                # Check if we have groups to read
                if not session['groups_list']:
                    # Just send Keep-Alive if idle to maintain connection?
                    # Or disconnect? Let's Keep-Alive for now.
                    if session['connected']:
                         try:
                             session['protocol'].send_keep_alive()
                         except:
                             session['connected'] = False
                    continue

                # Ensure Connection
                if not self._ensure_connected(mod_id):
                    continue
                
                # Read Next Group
                # Safety check on index
                if session['idx'] >= len(session['groups_list']):
                    session['idx'] = 0
                    
                grp = session['groups_list'][session['idx']]
                proto = session['protocol']
                
                try:
                    resp = proto.send_kvp_request([0x21, grp])
                    
                    if resp and resp[0] == 0x61 and resp[1] == grp:
                        # Decode
                        decoded = TP2Coding.decode_block(resp[2:])
                        # Publish
                        payload = {
                            'module': mod_id,
                            'group': grp,
                            'data': decoded
                        }
                        self.pub.send_multipart([b'HUDIY_DIAG', json.dumps(payload).encode()])
                        
                        # Cycle
                        if session['groups_list']:
                             session['idx'] = (session['idx'] + 1) % len(session['groups_list'])
                        
                    elif resp and resp[0] == 0x7F:
                        logger.warning(f"Mod 0x{mod_id:02X} Grp {grp} Rejected: {resp}")
                    
                    # MANDATORY KEEP-ALIVE
                    proto.send_keep_alive()

                except TP2Error as e:
                    logger.error(f"Mod 0x{mod_id:02X} Error: {e}")
                    # Try soft recovery
                    try:
                        proto.send_keep_alive()
                    except:
                        session['connected'] = False
                        proto.disconnect()
            
            # Rate Limiting
            # If we have many modules, we might want to sleep less
            time.sleep(0.1)

        except KeyboardInterrupt:
            logger.info("Stopping TP2 Service...")
            break
        except Exception as e:
            logger.error(f"CRITICAL MAIN LOOP ERROR: {e}")
            # Robust Recovery: Close all sessions so they rebuild next cycle
            for mod, sess in self.sessions.items():
                try: 
                    sess['protocol'].close() # Sets bus = None
                    sess['connected'] = False
                except: pass
            time.sleep(5)  # Wait for system to stabilize

if __name__ == "__main__":
    TP2Service().run()
