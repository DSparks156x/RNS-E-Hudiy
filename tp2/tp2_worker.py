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
        self._tester_id_pool = list(range(0x300, 0x30A))  # 0x300-0x309
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
        if not self._tester_id_pool:
            raise RuntimeError("No tester IDs available (max 10 simultaneous modules)")
        tester_id = self._tester_id_pool.pop(0)
        
        logger.info(f"Creating new session for Module 0x{module_id:02X} (TesterID: 0x{tester_id:X})")
        
        # Protocol creation (Lightweight, actual open happens in Main Thread)
        proto = TP2Protocol(channel='can0', tester_id=tester_id)
            
        session = {
            'protocol': proto,
            'subs': {}, # {group_id: count}
            'normal_groups_list': [],
            'low_groups_list': [],
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

    def _rebuild_groups_list(self, session):
        # NOTE: Must be called within Lock
        now = time.time()
        normal_set = set()
        low_set = set()
        expired_clients = []
        
        for cid, data in session.get('client_subs', {}).items():
            if now - data.get('last_sync', 0) >= 15.0:
                expired_clients.append(cid)
            else:
                normal_set.update(data.get('groups', []))
                low_set.update(data.get('low_groups', []))
                
        for cid in expired_clients:
            del session['client_subs'][cid]
            logger.info(f"Client {cid} timed out and was removed.")
            
        # If a group is in normal, don't keep it in low
        low_set = low_set - normal_set
        
        new_normal = list(normal_set)
        new_low = list(low_set)
        
        session['normal_groups_list'] = new_normal
        session['low_groups_list'] = new_low
        session['active'] = len(new_normal) > 0 or len(new_low) > 0

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
                                "connected": s.get('connected', False),
                                "active": s.get('active', False),
                                "client_subs": s.get('client_subs', {}),
                                "normal_groups_list": s.get('normal_groups_list', []),
                                "low_groups_list": s.get('low_groups_list', []),
                                "error_count": s.get('error_count', 0),
                                "last_activity": s.get('last_activity', 0),
                                "group_errors": s.get('group_errors', {}),
                                "group_cooldowns": s.get('group_cooldowns', {})
                            })
                        response = {
                            "status": "ok", 
                            "enabled": self.running, 
                            "session_count": len(sess_info),
                            "sessions": sess_info
                        }

                elif cmd == "SYNC":
                    client_id = msg.get("client_id")
                    mod = msg.get("module")
                    groups = msg.get("groups", [])
                    lp_groups = msg.get("low_priority_groups", [])
                    
                    if client_id and mod is not None:
                        param_mod = int(mod)
                        param_groups = [int(g) for g in groups]
                        param_lp_groups = [int(g) for g in lp_groups]
                        
                        with self.lock:
                            session = self._get_or_create_session(param_mod)
                            
                            if 'client_subs' not in session:
                                session['client_subs'] = {}
                                
                            session['client_subs'][client_id] = {
                                'groups': param_groups,
                                'low_groups': param_lp_groups,
                                'last_sync': time.time()
                            }
                            
                            self._rebuild_groups_list(session)
                            
                            logger.info(f"(Cmd) SYNC for client '{client_id}', Mod 0x{param_mod:02X}, Normal: {session['normal_groups_list']}, Low: {session['low_groups_list']}")
                            response = {"status": "ok", "message": "Synced", "active_groups": session['normal_groups_list']}
                    else:
                        response = {"status": "error", "message": "Missing client_id or module"}

                elif cmd == "READ_DTC":
                    mod = msg.get("module")
                    if mod is not None:
                        param_mod = int(mod)
                        with self.lock:
                            session = self._get_or_create_session(param_mod)
                            session['pending_dtc_req'] = True
                            if 'dtc_cooldown' not in session:
                                session['dtc_cooldown'] = 0
                            if not session['active']:
                                session['active'] = True
                        response = {"status": "queued", "module": mod}
                    else:
                        response = {"status": "error", "message": "Missing module"}

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
                    # Check for expired clients periodically
                    now = time.time()
                    if now - session.get('last_expiry_check', 0) > 5.0:
                        with self.lock:
                            self._rebuild_groups_list(session)
                        session['last_expiry_check'] = now

                    # Lifecycle Management
                    if not session['active']:
                        # Cleanup
                        if session['connected']:
                             try: 
                                 session['protocol'].disconnect()
                                 logger.info(f"Module 0x{mod_id:02X} Disconnected (Cleanup).")
                             except: pass
                        
                        # Remove from main dict safely, return tester ID to pool
                        with self.lock:
                            if mod_id in self.sessions and not self.sessions[mod_id]['active']:
                                freed_id = self.sessions[mod_id]['tester_id']
                                del self.sessions[mod_id]
                                if freed_id not in self._tester_id_pool:
                                    self._tester_id_pool.append(freed_id)
                                    self._tester_id_pool.sort()
                                logger.info(f"Module 0x{mod_id:02X} Session Deleted (TesterID 0x{freed_id:X} returned to pool).")
                        continue
                    
                    # Connection Management
                    normal_list = session.get('normal_groups_list', [])
                    low_list = session.get('low_groups_list', [])
                    cycle = session.get('cycle_count', 1)
                    pending_dtc = session.get('pending_dtc_req', False)
                    
                    if not normal_list and not low_list and not pending_dtc:
                        # Keep Alive Only
                        if session['connected']:
                             try:
                                 session['protocol'].send_keep_alive()
                             except:
                                 session['connected'] = False
                        continue
                        
                    if not self._ensure_connected(mod_id, session):
                        continue
                    
                    def get_active_list(n_list, l_list, c):
                        if not n_list: return l_list
                        if c >= 10 and l_list: return n_list + l_list
                        return n_list
                        
                    active_list = get_active_list(normal_list, low_list, cycle)
                    
                    if 'idx' not in session: session['idx'] = 0
                    if session['idx'] >= len(active_list):
                        session['idx'] = 0
                        if normal_list:
                            cycle += 1
                            if cycle > 10 and low_list: cycle = 1
                            session['cycle_count'] = cycle
                            active_list = get_active_list(normal_list, low_list, cycle)

                    if not active_list and not session.get('pending_dtc_req'):
                        continue

                    # Process DTC Request if pending
                    if session.get('pending_dtc_req') and time.time() > session.get('dtc_cooldown', 0):
                        proto = session['protocol']
                        logger.info(f"Polling Mod 0x{mod_id:02X} for DTCs...")
                        try:
                            # 0x18 Read By Status
                            resp = proto.send_kvp_request([0x18, 0x00, 0xFF, 0x00])
                            
                            if not resp:
                                logger.error(f"Mod 0x{mod_id:02X} No response for DTC request.")
                            elif resp[0] == 0x7F:
                                logger.warning(f"Mod 0x{mod_id:02X} DTC Request Rejected (NRC): {resp}")
                            elif resp[0] == 0x58:
                                count = resp[1]
                                dtc_data = resp[2:]
                                dtc_list = []
                                
                                if len(dtc_data) >= count * 3:
                                    for i in range(count):
                                        idx = i * 3
                                        hi = dtc_data[idx]
                                        lo = dtc_data[idx+1]
                                        status = dtc_data[idx+2]
                                        code = (hi << 8) | lo
                                        # Format as unshortened 5-digit hex string per user request
                                        dtc_list.append({
                                            'code': f"{code:04X}", # Need pure hex format or 5 digit code
                                            'code_dec': code,
                                            'status': status
                                        })
                                else:
                                    logger.warning(f"Mod 0x{mod_id:02X} DTC Response length mismatch. Expected {count*3}, got {len(dtc_data)}")
                                
                                # Fetch freeze frame data for each DTC if possible
                                for dtc_item in dtc_list:
                                    dtc_code = dtc_item['code_dec']
                                    hi = (dtc_code >> 8) & 0xFF
                                    lo = dtc_code & 0xFF
                                    try:
                                        # Try requesting specific freeze frame for this DTC
                                        ff_resp = proto.send_kvp_request([0x12, 0x00, hi, lo])
                                        if ff_resp and ff_resp[0] == 0x52:
                                            # successful freeze frame read, attach raw hex string
                                            dtc_item['freeze_frame_raw'] = [f"{b:02X}" for b in ff_resp[1:]]
                                        elif ff_resp and ff_resp[0] == 0x7F:
                                            logger.debug(f"Mod 0x{mod_id:02X} Rejected Freeze Frame for {dtc_item['code']}: {ff_resp}")
                                    except Exception as ff_e:
                                        logger.debug(f"Mod 0x{mod_id:02X} Freeze Frame read error for {dtc_item['code']}: {ff_e}")

                                # Broadcast DTCs
                                payload = {
                                    'module': mod_id,
                                    'type': 'dtc_report',
                                    'count': count,
                                    'dtcs': dtc_list
                                }
                                self.pub.send_multipart([b'HUDIY_DIAG', json.dumps(payload).encode()])
                                logger.info(f"Published Mod 0x{mod_id:02X} DTCs: {dtc_list}")
                            
                                # (Freeze frame requests are now handled per-DTC above)
                            
                        except Exception as e:
                            logger.error(f"Mod 0x{mod_id:02X} DTC Error: {e}")
                            
                        # Clear flag and set a cooldown so we don't spam requests if the UI bugs out
                        session['pending_dtc_req'] = False
                        session['dtc_cooldown'] = time.time() + 2.0
                        
                        # Continue to normal polling
                        if not active_list:
                            try:
                                session['protocol'].send_keep_alive()
                            except:
                                session['connected'] = False
                            continue

                    # Initialize tracking if missing
                    if 'group_errors' not in session: session['group_errors'] = {}
                    if 'group_cooldowns' not in session: session['group_cooldowns'] = {}
                        
                    grp = None
                    valid_group_found = False
                    
                    for step in range(len(active_list)):
                        check_idx = (session['idx'] + step) % len(active_list)
                        candidate_grp = active_list[check_idx]
                        if time.time() > session['group_cooldowns'].get(candidate_grp, 0):
                            grp = candidate_grp
                            valid_group_found = True
                            session['idx'] = check_idx
                            break
                        
                    if not valid_group_found:
                        # All groups in cooldown. Keep session alive but do nothing else.
                        if session['connected']:
                             try:
                                 session['protocol'].send_keep_alive()
                             except:
                                 session['connected'] = False
                        continue
                        
                    proto = session['protocol']
                    
                    logger.info(f"Polling Mod 0x{mod_id:02X} Grp {grp}")
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
                            logger.info(f"Published Mod 0x{mod_id:02X} Grp {grp}: {[d.get('value') for d in decoded]}")
                            
                            session['group_errors'][grp] = 0 
                            session['error_count'] = 0
                            
                            # Keep ECU session alive after each successful read.
                            # ECUs have a channel-level inactivity timeout; without this
                            # the session drops when cycling through many groups.
                            try:
                                proto.send_keep_alive()
                            except Exception as ka_e:
                                logger.warning(f"Mod 0x{mod_id:02X} Keep-Alive failed after read: {ka_e}")
                                session['connected'] = False
                            
                        elif resp and resp[0] == 0x7F:
                            # NRC (Negative Response Code)
                            logger.warning(f"Mod 0x{mod_id:02X} Grp {grp} Rejected (NRC): {resp}")
                            session['group_errors'][grp] = session['group_errors'].get(grp, 0) + 1


                    except Exception as e:
                        session['group_errors'][grp] = session['group_errors'].get(grp, 0) + 1
                        logger.error(f"Mod 0x{mod_id:02X} Grp {grp} Error: {e} (Count: {session['group_errors'][grp]})")
                        
                        # Session level fallback
                        session['error_count'] += 1
                        if session['error_count'] >= 10:
                            logger.error(f"Mod 0x{mod_id:02X}: Too many session errors. Forcing Reconnect.")
                            session['connected'] = False
                            try: proto.disconnect()
                            except: pass
                            session['error_count'] = 0
                        else:
                            try:
                                if not proto.send_keep_alive():
                                    session['connected'] = False
                                    proto.disconnect()
                            except:
                                session['connected'] = False
                                try: proto.disconnect()
                                except: pass
                                
                    # Cooldown logic for this group
                    if session['group_errors'].get(grp, 0) >= 3:
                         logger.warning(f"Mod 0x{mod_id:02X} Grp {grp} failed 3 times. Suspending for 30 seconds.")
                         session['group_cooldowns'][grp] = time.time() + 30.0
                         session['group_errors'][grp] = 0
                         
                    # Move to next group index unconditionally for next loop
                    if active_list:
                         session['idx'] += 1
                
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

