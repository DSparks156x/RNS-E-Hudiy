#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import json
import zmq
import logging
import sys
import threading
from tp2_protocol import TP2Protocol, TP2Error
from tp2_coding import TP2Coding

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Configuration
ZMQ_PUB_ADDR = 'tcp://*:5557' # Data Publish
ZMQ_REP_ADDR = 'tcp://*:5558' # Command Request/Reply

import os

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
        
        # Replier (Commands) - Moved to Command Thread
        self.rep = self.context.socket(zmq.REP)
        self.rep.bind(self.addr_rep)
        
        # Connection Management
        self.sessions = {} 
        self.next_tester_id = 0x300
        self.running = True # Default to ON, will update if Ignition says OFF
        
        # Threading
        self.lock = threading.Lock()
        self.shutdown_event = threading.Event()
        
        # State Tracking
        self.last_ignition_state = None 

    def _get_or_create_session(self, module_id):
        # NOTE: Must be called within Lock
        if module_id in self.sessions:
            return self.sessions[module_id]
        
        # Create new session
        tester_id = self.next_tester_id
        self.next_tester_id += 1 # Increment for next module (0x300, 0x301...)
        
        logger.info(f"Creating new session for Module 0x{module_id:02X} (TesterID: 0x{tester_id:X})")
        
        # Protocol creation (Lightweight, actual open happens in Main Thread)
        proto = TP2Protocol(channel='can0', tester_id=tester_id)
            
        session = {
            'protocol': proto,
            'subs': {}, # {group_id: count}
            'groups_list': [], # Ordered list for cycling
            'idx': 0,
            'tester_id': tester_id,
            'connected': False,
            'active': True,         # Controls lifecycle
            'last_activity': time.time(),
            'last_connect_attempt': 0,
            'error_count': 0
        }
        self.sessions[module_id] = session
        return session

    def _ensure_connected(self, module_id, session):
        # Main Thread Only
        # Cooldown Check
        if not session['connected']:
            if time.time() - session.get('last_connect_attempt', 0) < 5.0:
                return False

        proto = session['protocol']
        
        if session['connected']:
            return True
            
        # Connect Logic
        session['last_connect_attempt'] = time.time()
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
             try: proto.disconnect()
             except: pass
        
        return False

    def process_ignition(self):
        # Main Thread
        if not self.ignition_sub: return
        
        try:
            while True:
                parts = self.ignition_sub.recv_multipart(flags=zmq.NOBLOCK)
                if len(parts) == 2 and parts[0] == b'POWER_STATUS':
                    pwr = json.loads(parts[1])
                    kl15 = pwr.get('kl15', False)
                    
                    with self.lock:
                        # Logic:
                        # 1. First Run: Always Sync
                        # 2. Change Detected: Sync
                        # 3. Steady State: Do Nothing (Preserve Manual Toggles)
                        
                        if self.last_ignition_state is None:
                            # First startup sync
                            self.running = kl15
                            self.last_ignition_state = kl15
                            status = "Enabled" if self.running else "Disabled"
                            logger.info(f"Ignition Startup Sync: TP2 Service {status}")
                            
                        elif kl15 != self.last_ignition_state:
                            # Edge detected
                            self.running = kl15
                            self.last_ignition_state = kl15
                            status = "Enabled" if self.running else "Disabled"
                            logger.info(f"Ignition Change: TP2 Service {status}")
                            
                        # If steady, we respect the current self.running state (which might be manually toggled)
                        
                        if not self.running:
                            # We will handle disconnection in main loop logic
                            pass
        except zmq.Again:
            pass
        except Exception as e:
            logger.error(f"Ignition Monitor Error: {e}")

    def command_thread_func(self):
        logger.info("Command Thread Started (ZMQ REP)")
        while not self.shutdown_event.is_set():
            try:
                # Blocking receive is fine here!
                msg = self.rep.recv_json()
                
                cmd = msg.get("cmd")
                response = {"status": "error", "message": "Unknown command"}
                
                if cmd == "STATUS":
                    with self.lock:
                        sess_info = []
                        for mod, s in self.sessions.items():
                            sess_info.append({
                                "module": mod,
                                "connected": s['connected'],
                                "active": s['active'],
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
                        with self.lock:
                            session = self._get_or_create_session(param_mod)
                            session['active'] = True # Revive if pending delete
                            
                            # Ref Counting
                            if param_grp in session['subs']:
                                session['subs'][param_grp] += 1
                                logger.info(f"(Cmd) Incremented Group {param_grp} count to {session['subs'][param_grp]}")
                            else:
                                session['subs'][param_grp] = 1
                                session['groups_list'].append(param_grp)
                                logger.info(f"(Cmd) Added Group {param_grp} to Module 0x{param_mod:02X}")
                                
                            response = {"status": "ok", "message": "Group added", "count": session['subs'][param_grp]}
                
                elif cmd == "REMOVE":
                    mod = msg.get("module")
                    grp = msg.get("group")
                    if mod is not None and grp is not None:
                         param_mod = int(mod)
                         param_grp = int(grp)
                         with self.lock:
                             if param_mod in self.sessions:
                                 session = self.sessions[param_mod]
                                 if param_grp in session['subs']:
                                     session['subs'][param_grp] -= 1
                                     count = session['subs'][param_grp]
                                     logger.info(f"(Cmd) Decremented Group {param_grp} count to {count}")
                                     
                                     if count <= 0:
                                         del session['subs'][param_grp]
                                         if param_grp in session['groups_list']:
                                             session['groups_list'].remove(param_grp)
                                             if session['idx'] >= len(session['groups_list']):
                                                 session['idx'] = 0
                                         logger.info(f"(Cmd) Removed Group {param_grp}")
                                         
                                         # Check if session is empty
                                         if not session['subs']:
                                             logger.info(f"(Cmd) Module 0x{param_mod:02X} has no subs. Marking inactive.")
                                             session['active'] = False
                                     
                                     response = {"status": "ok", "message": "Group removed", "count": count}
                                 else:
                                     response = {"status": "warning", "message": "Group not found"}
                             else:
                                 response = {"status": "error", "message": "Module not active"}

                elif cmd == "CLEAR":
                    with self.lock:
                        for mod, sess in self.sessions.items():
                            sess['active'] = False
                        logger.info("(Cmd) Cleared all sessions (marked inactive).")
                    response = {"status": "ok", "message": "Cleared all"}
                
                elif cmd == "TOGGLE":
                    with self.lock:
                        self.running = not self.running
                        status = "Enabled" if self.running else "Disabled"
                    logger.info(f"(Cmd) Service {status}")
                    response = {"status": "ok", "message": f"Service {status}", "enabled": self.running}

                self.rep.send_json(response)
                
            except zmq.ContextTerminated:
                break
            except Exception as e:
                logger.error(f"Command Error: {e}")
                # Try to send error if possible
                try: self.rep.send_json({"status": "error", "message": str(e)})
                except: pass

    def run(self):
        logger.info("TP2 Multi-Module Service Starting (Threaded + Error Counting)...")
        
        # Start Command Thread
        t_cmd = threading.Thread(target=self.command_thread_func, daemon=True)
        t_cmd.start()
        
        while not self.shutdown_event.is_set():
            try:
                # 0. Check Ignition (Updates running state)
                self.process_ignition()

                # Get Snapshot of State to work on
                # We do NOT stay locked during CAN I/O
                with self.lock:
                    is_running = self.running
                    # Copy dict keys/values to avoid modification issues
                    current_sessions = list(self.sessions.items())
                
                # 1. Global Enable Check
                if not is_running:
                    # Maintenance: Disconnect any connected sessions
                    for mod_id, session in current_sessions:
                        if session['connected']:
                            try: 
                                session['protocol'].disconnect()
                                session['connected'] = False
                                logger.info(f"Module 0x{mod_id:02X} Disconnected (Disabled).")
                            except: pass
                    
                    time.sleep(0.5)
                    continue

                # 2. Process Sessions
                if not current_sessions:
                    time.sleep(0.1)
                    continue
                    
                for mod_id, session in current_sessions:
                    # Lifecycle Management
                    if not session['active']:
                        # Cleanup
                        if session['connected']:
                             try: 
                                 session['protocol'].disconnect()
                                 logger.info(f"Module 0x{mod_id:02X} Disconnected (Cleanup).")
                             except: pass
                        
                        # Remove from main dict safely
                        with self.lock:
                            if mod_id in self.sessions and not self.sessions[mod_id]['active']:
                                del self.sessions[mod_id]
                                logger.info(f"Module 0x{mod_id:02X} Session Deleted.")
                        continue
                    
                    # Connection Management
                    if not session['groups_list']:
                        # Keep Alive Only
                        if session['connected']:
                             try:
                                 session['protocol'].send_keep_alive()
                             except:
                                 session['connected'] = False
                        continue
                        
                    if not self._ensure_connected(mod_id, session):
                        continue
                    
                    # Find Next Available Group
                    # Logic
                    # Safety check on index
                    if session['idx'] >= len(session['groups_list']):
                        session['idx'] = 0
                        
                    # Initialize tracking if missing
                    if 'group_errors' not in session: session['group_errors'] = {}
                    if 'group_cooldowns' not in session: session['group_cooldowns'] = {}
                        
                    start_idx = session['idx']
                    grp = None
                    valid_group_found = False
                    
                    for _ in range(len(session['groups_list'])):
                        candidate_grp = session['groups_list'][session['idx']]
                        if time.time() > session['group_cooldowns'].get(candidate_grp, 0):
                            grp = candidate_grp
                            valid_group_found = True
                            break
                        # Move to next
                        session['idx'] = (session['idx'] + 1) % len(session['groups_list'])
                        
                    if not valid_group_found:
                        # All groups in cooldown. Keep session alive but do nothing else.
                        if session['connected']:
                             try:
                                 session['protocol'].send_keep_alive()
                             except:
                                 session['connected'] = False
                        continue
                        
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
                            
                            session['group_errors'][grp] = 0 
                            session['error_count'] = 0 
                            
                        elif resp and resp[0] == 0x7F:
                            # NRC (Negative Response Code)
                            logger.warning(f"Mod 0x{mod_id:02X} Grp {grp} Rejected: {resp}")
                            session['group_errors'][grp] = session['group_errors'].get(grp, 0) + 1
                            
                        # MANDATORY KEEP-ALIVE
                        proto.send_keep_alive()

                    except TP2Error as e:
                        session['group_errors'][grp] = session['group_errors'].get(grp, 0) + 1
                        logger.error(f"Mod 0x{mod_id:02X} Grp {grp} Error: {e} (Count: {session['group_errors'][grp]})")
                        
                        # Session level fallback
                        session['error_count'] += 1
                        if session['error_count'] >= 5:
                            logger.error("Too many session errors. Forcing Reconnect.")
                            session['connected'] = False
                            proto.disconnect()
                            session['error_count'] = 0
                        else:
                            try: proto.send_keep_alive()
                            except: 
                                session['connected'] = False
                                proto.disconnect()
                                
                    # Cooldown logic for this group
                    if session['group_errors'].get(grp, 0) >= 3:
                         logger.warning(f"Mod 0x{mod_id:02X} Grp {grp} failed 3 times. Suspending for 30 seconds.")
                         session['group_cooldowns'][grp] = time.time() + 30.0
                         session['group_errors'][grp] = 0
                         
                    # Cycle to next group unconditionally for next loop
                    if session['groups_list']:
                         session['idx'] = (session['idx'] + 1) % len(session['groups_list'])
                
                # Rate Limiting
                time.sleep(0.05) # Faster for responsiveness, thread handles command blocking

            except KeyboardInterrupt:
                logger.info("Stopping TP2 Service...")
                self.shutdown_event.set()
                break
            except Exception as e:
                logger.error(f"CRITICAL MAIN LOOP ERROR: {e}")
                time.sleep(1)

        # Shutdown Cleanup
        for mod, sess in self.sessions.items():
            try: sess['protocol'].close()
            except: pass

if __name__ == "__main__":
    TP2Service().run()

