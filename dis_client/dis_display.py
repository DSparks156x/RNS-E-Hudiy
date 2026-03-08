#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import zmq, json, time, logging, sys, os
from typing import Set, List, Dict, Union

# Import Apps
from apps.menu import MenuApp
from apps.radio import RadioApp
from apps.media import MediaApp
from apps.nav import NavApp
from apps.phone import PhoneApp
from apps.settings import SettingsApp
from apps.car_info import CarInfoApp

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SETTINGS_FILE = '/home/pi/dis_settings.json'

class DisplayEngine:
    Y = {'line1': 1, 'line2': 11, 'line3': 21, 'line4': 31, 'line5': 41}

    def __init__(self, config_path='/home/pi/config.json', mock=False):
        with open(config_path) as f: self.cfg = json.load(f)
        self.settings = self.load_settings()
        
        # --- Apps Definition (No Menu) ---
        self.apps = {}
        self.apps['app_nav']          = NavApp(self.cfg)
        self.apps['app_media_player'] = MediaApp(self.cfg)
        self.apps['app_phone']        = PhoneApp(self.cfg)
        self.apps['app_car']          = CarInfoApp(self.cfg)
        # Settings still exists if needed, but not in cycle
        self.apps['app_settings']     = SettingsApp(self) 

        # --- Page Cycle Definition ---
        self.pages = ['app_nav', 'app_media_player', 'app_phone', 'app_car']
        self.current_page_idx = 0

        self.zmq_ctx = zmq.Context()
        self.sub = self.zmq_ctx.socket(zmq.SUB)
        self.can_connected = False
        try:
            if mock:
                self.sub.connect("tcp://127.0.0.1:5558")
                self.can_connected = True
                logger.info("MOCK MODE: Connected to Emulator CAN Publisher on TCP 5558")
            else:
                _zmq = self.cfg.get('interfaces', {}).get('zmq', {})
                if not _zmq:
                    _zmq = self.cfg.get('zmq', {})
                self.sub.connect(_zmq.get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc'))
                self.can_connected = True
        except Exception as e:
            logger.warning(f"Mock Mode/Windows: Could not connect to CAN stream: {e}")
            
        self.t_btn = self._topics('steering_module', '0x2C1')
        
        # We need to subscribe to radio topics for the header/footer even without RadioApp active
        if self.can_connected:
            self.sub.subscribe(b"CAN_0x363") # fis_line1
            self.sub.subscribe(b"CAN_0x365") # fis_line2
        
        self.t_car = set()
        for key in ['oil_temp', 'battery', 'fuel_level']:
             self.t_car.update(self._topics(key, '0x000'))
        
        # Subscriptions
        if self.can_connected:
            for t in self.t_btn | self.t_car:
                self.sub.subscribe(t.encode())
        
        self.sub_hudiy = self.zmq_ctx.socket(zmq.SUB)
        self.hudiy_connected = False
        try:
            if mock:
                self.sub_hudiy.connect("tcp://127.0.0.1:5559")
                self.hudiy_connected = True
                logger.info("MOCK MODE: Connected to Emulator Hudiy Publisher on TCP 5559")
                
                # Mock Log push channel 
                self.log_push = self.zmq_ctx.socket(zmq.PUSH)
                self.log_push.connect("tcp://127.0.0.1:5560")
                self.log_push.send_string("dis_display connected to Emulator Log Pipe")
            else:
                _zmq = self.cfg.get('interfaces', {}).get('zmq', {})
                if not _zmq:
                    _zmq = self.cfg.get('zmq', {})
                self.sub_hudiy.connect(_zmq.get('metric_stream', 'ipc:///run/rnse_control/hudiy_stream.ipc'))
                self.sub_hudiy.connect(_zmq.get('status_stream', 'ipc:///run/rnse_control/status_stream.ipc'))
                self.hudiy_connected = True
        except Exception as e:
            logger.warning(f"Mock Mode/Windows: Could not connect to metric_stream: {e}")
            
        if self.hudiy_connected:
            for t in [b'HUDIY_MEDIA', b'HUDIY_NAV', b'HUDIY_PHONE', b'HUDIY_NAV_STATUS', b'HUDIY_DIAG']: 
                self.sub_hudiy.subscribe(t)

        self.draw = self.zmq_ctx.socket(zmq.PUSH)
        self.draw.setsockopt(zmq.SNDHWM, 20) # Prevent long backlogs if service freezes
        if mock:
            logger.info("MOCK MODE: Connecting to Emulator on TCP 5557")
            self.draw.connect("tcp://127.0.0.1:5557")
        else:
            _zmq = self.cfg.get('interfaces', {}).get('zmq', {})
            if not _zmq:
                _zmq = self.cfg.get('zmq', {})
            self.draw.connect(_zmq.get('dis_draw', 'ipc:///run/rnse_control/dis_draw.ipc'))
            
        self.poller = zmq.Poller()
        if self.can_connected:
            self.poller.register(self.sub, zmq.POLLIN)
        if self.hudiy_connected:
            self.poller.register(self.sub_hudiy, zmq.POLLIN)

        self.service_ready = False
        self.sub_status = self.zmq_ctx.socket(zmq.SUB)
        try:
            if mock:
                 self.service_ready = True
            else:
                 _zmq = self.cfg.get('interfaces', {}).get('zmq', {})
                 if not _zmq:
                     _zmq = self.cfg.get('zmq', {})
                 self.sub_status.connect(_zmq.get('dis_status', 'ipc:///run/rnse_control/dis_status.ipc'))
                 self.sub_status.subscribe(b"DIS_STATE")
                 self.poller.register(self.sub_status, zmq.POLLIN)
        except Exception as e:
            logger.warning(f"Could not connect to dis_status: {e}")

        self.nav_active = False # Default inactive

        # --- Startup Logic ---
        start_app = 'app_media_player'
        if self.settings.get('remember_last', False):
            start_app = self.settings.get('last_app', 'app_media_player')
        else:
            start_app = self.settings.get('startup_app', 'app_media_player')
            
        if start_app in self.pages:
            self.current_page_idx = self.pages.index(start_app)
        else:
            self.current_page_idx = 0
            
        self.current_app = self.apps[self.pages[self.current_page_idx]]
            
        logger.info(f"Starting in App: {self.pages[self.current_page_idx]}")
        self.current_app.on_enter()
        
        self.last_sent = {k: None for k in self.Y}
        self.last_sent['custom_sig'] = None 
        self.last_sent_flags = {k: 0 for k in self.Y} 
        self.btn = {'up': {'p':False, 's':0, 'l':0}, 'down': {'p':False, 's':0, 'l':0}}

        # --- Advanced Nav Auto-Switching ---
        self.pre_nav_app_name = None
        self.auto_switch_back_at = 0
        self.last_maneuver_id = None

        # --- Phone Auto-Switching ---
        self.phone_active = False
        self.pre_phone_app_name = None

    def load_settings(self):
        default = {'startup_app': 'app_media_player', 'remember_last': False, 'last_app': 'app_media_player'}
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
                    default.update(data)
        except Exception as e: logger.error(f"Failed to load settings: {e}")
        return default

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, 'w') as f: json.dump(self.settings, f, indent=4)
        except Exception as e: logger.error(f"Failed to save settings: {e}")

    def _topics(self, key, default) -> Set[str]:
        v = set()
        val = str(self.cfg['can_ids'].get(key, default))
        if val == '0x000': return v 
        v.add(f"CAN_{val}"); v.add(f"CAN_{val.strip()}")
        try: n = int(val, 16); v.add(f"CAN_{n:X}"); v.add(f"CAN_0x{n:X}"); v.add(f"CAN_{n}")
        except: pass
        return v

    def switch_page(self, delta):
        """Cycles to the next/prev page in the list, skipping inactive apps."""
        # Throttle page switching to avoid accidental double-taps causing rapid jumps
        now = time.time()
        if hasattr(self, 'last_switch') and (now - self.last_switch < 0.2):
            return
        self.last_switch = now

        count = len(self.pages)
        start_idx = self.current_page_idx
        
        for _ in range(count):
            self.current_page_idx = (self.current_page_idx + delta) % count
            target_name = self.pages[self.current_page_idx]
            
            # Sub-Check: Skip Nav if inactive
            if target_name == 'app_nav' and not self.nav_active:
                continue
            
            # Sub-Check: Skip Phone if inactive
            if target_name == 'app_phone' and not self.phone_active:
                continue
                
            # If we found a valid app, break loop
            break
            
        target_name = self.pages[self.current_page_idx]
        
        self.current_app.on_leave()
        self.current_app = self.apps[target_name]
        self.current_app.on_enter()
        
        logger.info(f"Switched to App: {target_name}")
        
        if self.settings.get('remember_last', False):
            self.settings['last_app'] = target_name
            self.save_settings()
            
        self.force_redraw(send_clear=True)

    def switch_to_app(self, app_name):
        """Direct jump to an app by name."""
        if app_name not in self.pages: return
        
        idx = self.pages.index(app_name)
        if idx == self.current_page_idx: return
        
        self.current_page_idx = idx
        self.current_app.on_leave()
        self.current_app = self.apps[app_name]
        self.current_app.on_enter()
        logger.info(f"Auto-Switched to App: {app_name}")
        self.force_redraw(send_clear=True)

    def process_input(self, action):
        # Override standard logic: Up/Down Tap cycles pages
        # Holds are passed to app (but currently User requested ignores)
        
        if action == 'tap_up':
            self.auto_switch_back_at = 0 
            self.pre_nav_app_name = None
            self.pre_phone_app_name = None
            self.switch_page(-1) # Previous
        elif action == 'tap_down':
            self.auto_switch_back_at = 0 
            self.pre_nav_app_name = None
            self.pre_phone_app_name = None
            self.switch_page(1)  # Next
        else:
            # Pass holds or other events to app if needed
            self.current_app.handle_input(action)

    def _send_draw(self, payload):
        """Send a JSON command to the DIS service without blocking. Returns True if sent."""
        try:
            self.draw.send_json(payload, flags=zmq.NOBLOCK)
            return True
        except zmq.Again:
            # If the service is stuck, we drop frames rather than backlogging them
            # logger.debug("Draw socket full, dropping frame")
            return False
        except Exception as e:
            logger.error(f"Draw socket error: {e}")
            return False

    def force_redraw(self, send_clear=False):
        self.last_sent = {}
        self.last_sent_flags = {}
        if send_clear:
            self._send_draw({'command': 'clear'})
            self._send_draw({'command': 'commit'})

    def run(self):
        logger.info("DIS Engine V5.8 Running")
        time.sleep(1.0) 
        self.force_redraw(send_clear=True)
        self.last_loop = time.time()
        
        while True:
            try:
                now = time.time()
                self.last_loop = now

                socks = dict(self.poller.poll(30))
                if self.sub_hudiy in socks:
                    try:
                        # Limit Hudiy processing per loop to avoid blocking too long
                        h_count = 0
                        while h_count < 20:
                            parts = self.sub_hudiy.recv_multipart(flags=zmq.NOBLOCK)
                            h_count += 1
                            if len(parts) == 2:
                                topic, msg = parts
                                try:
                                    data = json.loads(msg)
                                    
                                    if hasattr(self, 'log_push'):
                                        self.log_push.send_string(f"RX: {topic.decode('utf-8')} -> {data}")
                                        
                                    if topic == b'HUDIY_NAV_STATUS':
                                        active = data.get('active', False)
                                        if active != self.nav_active:
                                            self.nav_active = active
                                            logger.info(f"Nav Active State Changed: {active}")
                                            
                                            if active:
                                                # Auto-switch TO nav
                                                self.switch_to_app('app_nav')
                                            else:
                                                # Auto-switch AWAY from nav if currently on it
                                                current_name = self.pages[self.current_page_idx]
                                                if current_name == 'app_nav':
                                                    self.switch_to_app('app_media_player')
                                            
                                            # Reset auto-switch state when nav status changes
                                            self.auto_switch_back_at = 0
                                            self.last_maneuver_id = None
                                            self.pre_nav_app_name = None

                                    # Update NavApp even if not current, for distance monitoring
                                    # We skip if it's HUDIY_NAV_STATUS as NavApp doesn't use it
                                    if topic.startswith(b'HUDIY_NAV') and topic != b'HUDIY_NAV_STATUS':
                                        nav_app = self.apps['app_nav']
                                        
                                        # Only update if it's NOT the current app (to avoid double update)
                                        if self.current_app != nav_app:
                                            nav_app.update_hudiy(topic, data)
                                        
                                        self._handle_nav_auto_switch(nav_app)

                                    if topic == b'HUDIY_PHONE':
                                        self._handle_phone_status(data)

                                    self.current_app.update_hudiy(topic, data)
                                except json.JSONDecodeError: pass
                    except zmq.Again: pass

                if getattr(self, 'sub_status', None) and self.sub_status in socks:
                    try:
                        while True:
                            msg = self.sub_status.recv_string(flags=zmq.NOBLOCK)
                            if msg.startswith("DIS_STATE"):
                                state = msg.split(" ")[1]
                                is_ready = (state == "READY")
                                if self.service_ready != is_ready:
                                    self.service_ready = is_ready
                                    logger.info(f"DIS Service State Changed to: {state}. Ready={self.service_ready}")
                                    if self.service_ready:
                                        self.force_redraw(send_clear=True)
                    except zmq.Again: pass

                if self.sub in socks: self._handle_can()
                
                # Handle Auto-Switch Back Timer
                if self.auto_switch_back_at > 0 and now > self.auto_switch_back_at:
                    self.auto_switch_back_at = 0
                    if self.pages[self.current_page_idx] == 'app_nav' and self.pre_nav_app_name:
                        logger.info(f"Auto-switching back to {self.pre_nav_app_name}")
                        self.switch_to_app(self.pre_nav_app_name)
                        self.pre_nav_app_name = None

                self._check_buttons()
                self._draw()
                time.sleep(0.01)
            except KeyboardInterrupt: break
            except Exception as e: logger.error(f"Err: {e}", exc_info=True); time.sleep(1)

    def _handle_nav_auto_switch(self, nav_app):
        # Distance-based Auto-Switch Logic
        if not self.nav_active: return
        
        man_id = f"{nav_app.description}_{nav_app.maneuver_type}"
        meters = nav_app.parse_distance(nav_app.distance_label)
        current_name = self.pages[self.current_page_idx]

        if current_name != 'app_nav':
            # Threshold to switch TO Nav: 200m
            if 0 <= meters <= 500 and man_id != self.last_maneuver_id:
                logger.info(f"Maneuver Alert: {meters}m. Switching to Nav.")
                self.pre_nav_app_name = current_name
                self.last_maneuver_id = man_id
                self.auto_switch_back_at = 0
                self.switch_to_app('app_nav')
        elif self.pre_nav_app_name:
            # Currently on Nav via auto-switch, check for switch back
            if man_id != self.last_maneuver_id:
                # Direction changed!
                if meters > 1000:
                    # New maneuver is far away, trigger auto-return timer
                    if self.auto_switch_back_at == 0:
                        logger.info(f"Maneuver finished, next ({meters}m) > 1000m. Returning to {self.pre_nav_app_name} in 10s.")
                        self.auto_switch_back_at = time.time() + 6.0
                else:
                    # New maneuver is close, stay on nav and reset timer
                    self.auto_switch_back_at = 0
                
                # Update tracker so we don't spam timer/logs
                self.last_maneuver_id = man_id
            else:
                # Same maneuver, keep timer reset if we stay/get close
                if 0 <= meters <= 1000:
                    self.auto_switch_back_at = 0

    def _handle_phone_status(self, data):
        state = data.get('state', 'IDLE')
        # Interesting if INCOMING, ALERTING, or ACTIVE
        interesting = state in ['INCOMING', 'ALERTING', 'ACTIVE']
        
        if interesting != self.phone_active:
            self.phone_active = interesting
            logger.info(f"Phone Interesting State Changed: {interesting} (state: {state})")
            
            current_name = self.pages[self.current_page_idx]
            if interesting:
                # Auto-switch TO phone
                if current_name != 'app_phone':
                    self.pre_phone_app_name = current_name
                    self.switch_to_app('app_phone')
            else:
                # Auto-switch AWAY from phone if we auto-switched to it
                if current_name == 'app_phone' and self.pre_phone_app_name:
                    logger.info(f"Call ended, switching back to {self.pre_phone_app_name}")
                    self.switch_to_app(self.pre_phone_app_name)
                self.pre_phone_app_name = None

    def _handle_can(self):
        try:
            m_count = 0
            limit = 50
            
            while m_count < limit:
                parts = self.sub.recv_multipart(flags=zmq.NOBLOCK)
                m_count += 1
                if len(parts) == 2:
                    topic, msg = parts
                    t_str = topic.decode()
                    payload = bytes.fromhex(json.loads(msg)['data_hex'])
                    self.current_app.update_can(t_str, payload)
                    if t_str in self.t_btn and len(payload) > 2:
                        b = payload[2]
                        now = time.time()
                        if b & 0x20: self._btn_event('up', True, now)
                        elif self.btn['up']['p']: self._btn_event('up', False, now)
                        if b & 0x10: self._btn_event('down', True, now)
                        elif self.btn['down']['p']: self._btn_event('down', False, now)
        except zmq.Again: pass

    def _btn_event(self, name, pressed, now):
        b = self.btn[name]
        if pressed:
            if not b['p']: 
                b.update(p=True, s=now, l=False)
                self.force_redraw(send_clear=False)
        else:
            if b['p'] and not b['l']: self.process_input(f"tap_{name}")
            b['p'] = b['l'] = False

    def _check_buttons(self):
        now = time.time()
        for name, b in self.btn.items():
            if b['p']:
                if not b['l'] and (now - b['s'] > 2.0):
                    b['l'] = True
                    self.process_input(f"hold_{name}")
                elif (now - b['s'] > 5.0): b['p'] = False

    def _draw(self):
        if not getattr(self, 'service_ready', True):
            return

        view = self.current_app.get_view()
        
        if isinstance(view, list):
            current_type = view[0].get('type') if view else None
            prev_type = self.last_sent.get('last_type')
            
            full_redraw = (current_type != prev_type)
            if full_redraw:
                if view and view[0].get('clear_on_update', True) and prev_type:
                    self._send_draw({'command': 'clear_payload'})
                else:    
                    self._send_draw({'command': 'clear'})
                
                self.last_sent['groups'] = {}
                self.last_sent['last_type'] = current_type

            # Grouping Logic for smart delta updates
            groups_current = {}
            for item in view:
                if not isinstance(item, dict): # Safety check: ensure item is a dictionary
                    logger.warning(f"Skipping non-dictionary item in view: {item}")
                    continue
                if 'type' in item: continue
                # Unique random ID if not provided so it's guaranteed to render
                # Hash the item contents instead of memory id() so identical dictionaries deduplicate
                g = item.get('group') or str(sorted((k, v) for k, v in item.items() if k != 'group'))
                if g not in groups_current:
                    groups_current[g] = []
                groups_current[g].append(item)
                
            last_groups = self.last_sent.get('groups', {})
            
            changed = False
            changed = False
            for g, items in groups_current.items():
                items_str = str(items)
                if full_redraw or last_groups.get(g) != items_str:
                    all_sent = True
                    for item in items:
                        success = False
                        cmd = item.get('cmd')
                        if cmd == 'draw_bitmap':
                            icon_key = item.get('icon', '')
                            from icons import BITMAPS
                            bmp = BITMAPS.get(icon_key.upper())
                            payload = {'command': 'draw_bitmap', 'icon_name': icon_key, 'x': item.get('x', 0), 'y': item.get('y', 0)}
                            if 'mode_flag' in item:
                                payload['mode_flag'] = item['mode_flag']
                            if bmp:
                                payload.update({'w': bmp['w'], 'h': bmp['h'], 'data': bmp['data']})
                            success = self._send_draw(payload)
                        elif cmd == 'draw_text':
                            success = self._send_draw({'command': 'draw_text', 'text': item.get('text', ''), 'x': item.get('x', 0), 'y': item.get('y', 0), 'flags': item.get('flags', 0x06)})
                        elif cmd == 'draw_line':
                            success = self._send_draw({'command': 'draw_line', 'x': item.get('x', 0), 'y': item.get('y', 0), 'length': item.get('len', 0), 'vertical': item.get('vert', True)})
                        elif cmd == 'clear_area':
                            success = self._send_draw({'command': 'clear_area', 'x': item.get('x', 0), 'y': item.get('y', 0), 'w': item.get('w', 0), 'h': item.get('h', 0)})
                        
                        if not success:
                            all_sent = False
                    
                    if all_sent:
                        changed = True
                        last_groups[g] = items_str
            
            if changed:
                self._send_draw({'command': 'commit'})
                
            self.last_sent['groups'] = last_groups
            for k in self.Y: self.last_sent[k] = None
            return

        if self.last_sent.get('groups') is not None:
             self._send_draw({'command': 'clear'})
             self._send_draw({'command': 'commit'})
             self.last_sent['groups'] = None
             self.last_sent['custom_sig'] = None
             for k in self.Y: self.last_sent[k] = None

        changed = False
        for k, (txt, flag) in view.items():
            if k == 'type' or k not in self.Y: continue
            
            # Ensure text is stringy
            txt = str(txt)
            
            prev_txt = self.last_sent.get(k)
            prev_flag = self.last_sent_flags.get(k, 0)
            
            if prev_txt != txt or prev_flag != flag:
                padded_txt = txt
                
                # Check for inversion transition
                if (prev_flag & 0x80) and not (flag & 0x80):
                    # We must fully clear the line. Use a standard safe width like 15 chars.
                    target_len = max(len(prev_txt) if prev_txt else 0, 15)
                else:
                    # Normal case, check if shrinking
                    target_len = len(prev_txt) if prev_txt else len(txt)
                
                # If the string shrank or we need a full clear
                if len(txt) < target_len:
                    blanks_needed = target_len - len(txt)
                    blank_char = chr(0x1F)
                    
                    # Pad Right: Always use simple padding to clear trailing characters
                    # Center-aligned text is wiped separately via PRE-CLEAR.
                    padded_txt = txt + (blank_char * blanks_needed)
                
                # --- PRE-CLEAR FOR CENTERED TEXT ---
                # If centering is enabled in config and this text is centered (0x20),
                # send a full blank line (0x1F chars) first to wipe ghosting.
                # Crucial: Wipe is LEFT-ALIGNED (0x06) to cover the full width reliably.
                center_enabled = self.cfg.get('display', {}).get('text_centering', False)
                if center_enabled and (flag & 0x20):
                    blank_char = chr(0x1F)
                    wipe_len = 16 # Full width
                    self._send_draw({'command':'draw_text', 'text': blank_char * wipe_len, 'y':self.Y[k], 'flags': 0x06})

                if self._send_draw({'command':'draw_text', 'text':padded_txt, 'y':self.Y[k], 'flags':flag}):
                    self.last_sent[k] = txt # Store original raw text for comparison
                    self.last_sent_flags[k] = flag
                    changed = True
        
        if changed: 
            self._send_draw({'command':'commit'})

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true', help='Connect to DIS Emulator (TCP 5557)')
    args = parser.parse_args()
    
    config_path = '../config.json' if os.path.exists('../config.json') else '/home/pi/config.json'
    DisplayEngine(config_path=config_path, mock=args.mock).run()

