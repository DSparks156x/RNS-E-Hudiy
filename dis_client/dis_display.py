#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import zmq, json, time, logging, sys, os, signal, argparse
from typing import Set, List, Dict, Union

# Import Apps
from apps.menu import MenuApp
from apps.radio import RadioApp
from apps.media import MediaApp
from apps.nav import NavApp
from apps.phone import PhoneApp
from apps.settings import SettingsApp
from apps.car_info import create_car_info_app
from apps.coverart import CoverArtApp
from apps.easteregg import EasterEggApp
from apps.acceleration_test import AccelerationTestApp
from apps.openpilot import OpenpilotApp
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from navigation_policy import NavigationPolicy

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SETTINGS_FILE = '/home/pi/dis_settings.json'

class DisplayEngine:
    Y = {'line1': 1, 'line2': 11, 'line3': 21, 'line4': 31, 'line5': 41}

    def __init__(self, config_path='/home/pi/config.json', mock=False):
        self._wheel_epoch = time.time_ns()
        with open(config_path) as f: self.cfg = json.load(f)
        self.car_units = {
            'speed': 'metric',
            'temp': 'metric',
            'pressure': 'bar'
        }
        self.cfg['car_units'] = self.car_units
        self.settings = self.load_settings()
        
        center_display_cfg = self.cfg.get('display', {}).get('center_display', {})
        self.start_inactive = center_display_cfg.get('start_inactive', False)

        # --- Apps Definition (No Menu) ---
        self.apps = {}
        self.apps['app_nav']          = NavApp(self.cfg)
        self.apps['app_media'] = MediaApp(self.cfg)
        self.apps['app_phone']        = PhoneApp(self.cfg)
        self.apps['app_car_info'] = create_car_info_app(self.cfg)
        self.apps['app_acceleration_test'] = AccelerationTestApp(self.cfg)
        # Settings still exists if needed, but not in cycle
        self.apps['app_settings']     = SettingsApp(self) 
        self.apps['app_coverart']     = CoverArtApp(self.cfg) 
        self.apps['app_easteregg']    = EasterEggApp(self.cfg)
        self.apps['app_openpilot']    = OpenpilotApp(self.cfg)
        self.egg_app = self.apps['app_easteregg']

        # --- Page Cycle Definition ---
        configured_apps = center_display_cfg.get('applist', ['nav', 'media', 'phone', 'car_info', 'acceleration_test'])
        
        self.pages = [f"app_{app}" for app in configured_apps if f"app_{app}" in self.apps]
        if not self.pages:
            self.pages = ['app_media']
        
        # Load Cover Art Configuration
        coverart_cfg = center_display_cfg.get('coverart', {})
        self.coverart_brief = coverart_cfg.get('brief', True)
        
        self.current_page_idx = 0
        self.running = True
        self._setup_signals()

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
        self.t_mfsw = self._topics('mfsw', '0x5C3')
        
        # We need to subscribe to radio topics for the header/footer even without RadioApp active
        #if self.can_connected:
        #    self.sub.subscribe(b"CAN_0x363") # fis_line1
        #    self.sub.subscribe(b"CAN_0x365") # fis_line2
        
        self.t_car = set()
        for key in ['oil_temp', 'battery', 'fuel_level']:
             self.t_car.update(self._topics(key, '0x000'))
        
        # Subscriptions
        if self.can_connected:
            self.sub.subscribe(b"CAN_351")
            self.sub.subscribe(b"CAN_0x351")
            self.sub.subscribe(b"CAN_60E")
            self.sub.subscribe(b"CAN_0x60E")
            for t in self.t_btn | self.t_car | self.t_mfsw:
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
                self.sub_hudiy.connect(_zmq.get('tp2_stream', 'ipc:///run/rnse_control/tp2_stream.ipc'))
                self.sub_hudiy.connect(_zmq.get('vehicle_data_stream', 'ipc:///run/rnse_control/vehicle_data_stream.ipc'))
                self.sub_hudiy.connect(_zmq.get('input_control_stream', 'ipc:///run/rnse_control/input_control_stream.ipc'))
                self.hudiy_connected = True
        except Exception as e:
            logger.warning(f"Mock Mode/Windows: Could not connect to metric_stream: {e}")
            
        if self.hudiy_connected:
            for t in [b'HUDIY_MEDIA', b'HUDIY_NAV', b'HUDIY_PHONE', b'HUDIY_NAV_STATUS', b'HUDIY_DIAG', b'HUDIY_VALUES', b'HUDIY_COVERART', b'HUDIY_OPENPILOT', b'DIS_INPUT', b'WHEEL_CONTROL']:
                self.sub_hudiy.subscribe(t)

        self.draw = self.zmq_ctx.socket(zmq.PUSH)
        self.draw.setsockopt(zmq.SNDHWM, 100) # Increased from 20 to prevent drops during rapid updates
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

        self.service_ready = False # Default to False: proven ready by dis_service
        self.sub_status = self.zmq_ctx.socket(zmq.SUB)
        try:
            if mock:
                 self.sub_status.connect("tcp://127.0.0.1:5562")
                 logger.info("MOCK MODE: dis_status (Ready/Paused) sub on TCP 5562")
            else:
                 _zmq = self.cfg.get('interfaces', {}).get('zmq', {})
                 if not _zmq:
                     _zmq = self.cfg.get('zmq', {})
                 self.sub_status.connect(_zmq.get('dis_status', 'ipc:///run/rnse_control/dis_status.ipc'))
            
            self.sub_status.subscribe("") # Subscribe to everything to be sure
            self.poller.register(self.sub_status, zmq.POLLIN)
        except Exception as e:
            logger.warning(f"Could not connect to dis_status: {e}")

        # --- Display Status Publication (for App Awareness) ---
        self.pub_status = self.zmq_ctx.socket(zmq.PUB)
        try:
            if mock:
                self.pub_status.bind("tcp://127.0.0.1:5561")
                logger.info("MOCK MODE: dis_display_status bound to TCP 5561")
            else:
                _zmq = self.cfg.get('interfaces', {}).get('zmq', {})
                if not _zmq:
                    _zmq = self.cfg.get('zmq', {})
                addr = _zmq.get('dis_display_status', 'ipc:///run/rnse_control/dis_display_status.ipc')
                self.pub_status.bind(addr)
                logger.info(f"dis_display_status (for top service) bound to {addr}")
        except Exception as e:
            logger.warning(f"Could not bind dis_display_status socket: {e}")

        if not mock:
            # Value subscription command socket (diagnostic sessions belong to TP2).
            self.tp2_cmd = self.zmq_ctx.socket(zmq.REQ)
            self.tp2_cmd.setsockopt(zmq.RCVTIMEO, 1000)
            self.tp2_cmd.setsockopt(zmq.LINGER, 0)
            _tp2_addr = self.cfg.get('interfaces', {}).get('zmq', {}).get('vehicle_data_command', 'ipc:///run/rnse_control/vehicle_data_cmd.ipc')
            self.tp2_cmd.connect(_tp2_addr)
            self.last_tp2_sync = 0

        self.nav_active = False # Default inactive

        # --- Startup Logic ---
        start_app = 'app_media'
        if self.settings.get('remember_last', False):
            start_app = self.settings.get('last_app', 'app_media')
        else:
            start_app = self.settings.get('startup_app', 'app_media')
            
        if start_app in self.pages:
            self.current_page_idx = self.pages.index(start_app)
        else:
            self.current_page_idx = 0
            start_app = self.pages[0]
            
        self.current_app = self.apps[start_app]
            
        logger.info(f"Starting in App: {start_app}")
        self.current_app.on_enter()
        
        self.last_sent = {k: None for k in self.Y}
        self.last_sent['custom_sig'] = None 
        self.last_sent_flags = {k: 0 for k in self.Y} 
        self.btn = {'up': {'p':False, 's':0, 'l':0}, 'down': {'p':False, 's':0, 'l':0}}

        # --- Advanced Nav Auto-Switching ---
        self.pre_nav_app_name = None
        self.pre_cover_app_name = None
        
        # Load Navigation Auto-Switch Config
        nav_cfg = center_display_cfg.get('navigation', {})
        self.nav_auto_switch = nav_cfg.get('auto_switch', True)
        self.nav_approach_threshold = nav_cfg.get('auto_switch_approach_threshold', 500)
        self.nav_return_threshold = nav_cfg.get('auto_switch_return_threshold', 1000)
        self.nav_peek_seconds = nav_cfg.get('auto_switch_peek_seconds', 5)
        self.nav_policy = NavigationPolicy(self.nav_approach_threshold, self.nav_return_threshold, self.nav_peek_seconds)
        self.cluster_selected_session = False
        self._last_cluster_request = 0
        self._context_nav_peek_until = 0
        self.nav_claim_on_nav = nav_cfg.get('claim_on_nav', False)
        self.user_paused = False
        self.boot_inactive_hold = self.start_inactive
        self.has_entered_paused_state = False
        self.content_auto_claimed = False

        # Load Phone Config
        phone_cfg = self.cfg.get('display', {}).get('phone', {})
        self.phone_claim_on_phone = phone_cfg.get('claim_on_phone', False)
        self.context_claim_only = bool(self.nav_claim_on_nav or self.phone_claim_on_phone)
        self.start_inactive = bool(self.start_inactive or self.context_claim_only)
        self.boot_inactive_hold = self.start_inactive
        self.user_paused = self.start_inactive

        # --- Advanced Nav Auto-Switching ---
        self.nav_auto_triggered = False

        # --- Phone Auto-Switching ---
        self.phone_active = False
        self.phone_auto_overlay = False
        self.pre_phone_app_name = None
        self.frame_seq_counter = 0
        self._pending_ui_frame = None

        # --- Easter Egg & Sequencing State ---
        self.egg_active = False
        self.egg_pending = False
        self.last_egg_match = None # Track 'Artist - Title' string that last triggered
        self.brief_cover_active = False
        self.brief_auto_switch_end = 0
        self.last_cover_trigger_time = 0

        # --- Input Rate Limiting ---
        self.press_history = [] # Timestamps of recent app switches

    def _setup_signals(self):
        """Register signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info(f"Shutdown signal {signum} received. Stopping DisplayApplication...")
        self.running = False

    def load_settings(self):
        default = {'startup_app': 'app_media', 'remember_last': False, 'last_app': 'app_media'}
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
                    default.update(data)
        except Exception as e: logger.error(f"Failed to load settings: {e}")
        return default

    def publish_status(self, force=False):
        """Broadcast current app and ready state for top-display awareness."""
        if not hasattr(self, 'pub_status'):
            return
        
        try:
            state_str = "READY" if getattr(self, 'service_ready', False) else "PAUSED"
            app_name = "unknown"
            for k, v in self.apps.items():
                if v == self.current_app:
                    app_name = k
                    break
            
            payload = {
                "state": state_str,
                "app": app_name,
                "wheel_supported": hasattr(self.current_app, 'set_control_mode'),
                "control_epoch": getattr(self, '_wheel_epoch', 0),
                "timestamp": time.time()
            }

            # Avoid redundant publishes unless forced (e.g. heartbeat or app switch)
            if not force:
                current_id = (state_str, app_name, getattr(self, '_wheel_epoch', 0))
                if getattr(self, '_last_published_id', None) == current_id:
                    return
                self._last_published_id = current_id

            #logger.info(f"Broadcasting Display Status: {app_name} ({state_str})")
            self.pub_status.send_multipart([b"DIS_DISPLAY_STATUS", json.dumps(payload).encode()])
        except Exception as e:
            logger.error(f"Failed to publish display status: {e}")

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
        if not getattr(self, 'service_ready', False):
            return

        now = time.time()
        
        # --- Burst-Aware Rate Limiting ---
        # Keep only presses from the last 1.5 seconds
        self.press_history = [t for t in self.press_history if now - t < 1.5]
        
        # Calculate dynamic throttle: 
        # - Default 0.2s for responsiveness
        # - If 3+ presses in 1.5s, slow down to 0.7s
        recent_count = len(self.press_history)
        min_interval = 0.7 if recent_count >= 3 else 0.2
        
        last_s = self.press_history[-1] if self.press_history else 0
        if (now - last_s < min_interval):
            return
            
        self.press_history.append(now)

        count = len(self.pages)
        # Cycle from the visible navigation override, then keep the resulting
        # page as the user's choice beneath future temporary interruptions.
        if self.pre_nav_app_name is not None and 'app_nav' in self.pages:
            self.current_page_idx = self.pages.index('app_nav')
        start_idx = self.current_page_idx
        
        for _ in range(count):
            self.current_page_idx = (self.current_page_idx + delta) % count
            target_name = self.pages[self.current_page_idx]
            
            # Sub-Check: Skip Nav if inactive or has no route (with debounce)
            if target_name == 'app_nav' and not self.is_nav_available():
                continue
            
            # Sub-Check: Phone exists in rotation only during a live call
            if target_name == 'app_phone' and not self.is_phone_available():
                continue
                
            # If we found a valid app, break loop
            break
            
        target_name = self.pages[self.current_page_idx]
        if not ((target_name != 'app_nav' or self.is_nav_available()) and
                (target_name != 'app_phone' or self.is_phone_available())):
            self.current_page_idx = start_idx
            return
        self._cancel_auto_switches()

        self.current_app.on_leave()
        self.current_app = self.apps[target_name]
        
        if hasattr(self.current_app, 'reset_timers'):
            self.current_app.reset_timers()
            logger.info("Timers manually reset via stalk cycle.")
            
        self.current_app.on_enter()
        self._wheel_epoch = getattr(self, '_wheel_epoch', 0) + 1
        self.last_tp2_sync = 0 # Force immediate TP2 sync on context switch
        
        logger.info(f"Switched to App: {target_name}")
        
        if self.settings.get('remember_last', False):
            self.settings['last_app'] = target_name
            self.save_settings()
            
        self._deferred_app_clear = self._wheel_epoch
        self.force_redraw(send_clear=False)
        self.publish_status()

    def switch_to_app(self, app_name):
        """Direct jump to an app by name."""
        if app_name not in self.apps: return
        
        if self.current_app == self.apps[app_name]: return
        
        if app_name in self.pages:
            self.current_page_idx = self.pages.index(app_name)
        
        self.current_app.on_leave()
        self.current_app = self.apps[app_name]
        self.current_app.on_enter()
        self._wheel_epoch = getattr(self, '_wheel_epoch', 0) + 1
        self.last_tp2_sync = 0 # Force immediate TP2 sync on context switch
        logger.info(f"Auto-Switched to App: {app_name}")
        self._deferred_app_clear = self._wheel_epoch
        self.force_redraw(send_clear=False)
        self.publish_status()

    def _leave_empty_context_page(self, fallback):
        """Replace an unavailable underlying page without disturbing overlays."""
        if fallback not in self.pages:
            return
        if self.phone_auto_overlay and self.current_app == self.apps.get('app_phone'):
            # Keep the live call overlay visible while changing the page that
            # will be restored beneath it.
            self.current_page_idx = self.pages.index(fallback)
            self.publish_status()
            return
        self.switch_to_app(fallback)

    def process_input(self, action):
        if getattr(self, 'boot_inactive_hold', False):
            return

        # Ignore stalk inputs if the display is paused (unless we paused it ourselves)
        if not getattr(self, 'service_ready', False) and not self.user_paused:
            # logger.info(f"Ignoring input {action} while paused")
            return
        
        # Override standard logic: Up/Down Tap cycles pages
        
        if action == 'tap_up':
            self.switch_page(-1) # Previous
        elif action == 'tap_down':
            self.switch_page(1)  # Next
        else:
            # Pass holds or other events to app if needed
            self.current_app.handle_input(action)

    def _handle_wheel_input(self, topic, data):
        """Consume the keyboard service's already debounced, single-owner events."""
        app_name = next((name for name, app in self.apps.items() if app is self.current_app), None)
        matching = (data.get('app') == app_name and
                    data.get('control_epoch') == getattr(self, '_wheel_epoch', 0))
        if topic == b'WHEEL_CONTROL':
            self._wheel_status_at = time.monotonic()
            active = matching and data.get('owner') == 'dis' and self.service_ready
            if hasattr(self.current_app, 'set_control_mode'):
                self.current_app.set_control_mode(active)
        elif (matching and data.get('owner') == 'dis' and self.service_ready
                and getattr(self.current_app, 'control_mode', False)):
            action = data.get('event')
            if action in ('previous', 'next', 'select', 'back'):
                self.process_input(action)

    def _cancel_auto_switches(self):
        """Reset all auto-switch states when the user manually interacts."""
        if hasattr(self, 'nav_policy'):
            self.nav_policy.manual_select()
        self._context_nav_peek_until = 0
        self.pre_nav_app_name = None
        self.pre_phone_app_name = None
        self.pre_cover_app_name = None
        self.brief_cover_active = False
        self.egg_active = False
        self.egg_pending = False
        self.phone_auto_overlay = False

    def _check_nav_availability_pause(self):
        """Hide empty contextual pages and manage content-triggered claims."""
        current_app_name = self.pages[self.current_page_idx]
        is_nav_page = (current_app_name == 'app_nav')
        nav_available = self.is_nav_available()
        phone_available = self.is_phone_available()

        # Contextual pages must never remain selected without content.
        if is_nav_page and not nav_available:
            fallback = self.pre_nav_app_name
            if not fallback or fallback == 'app_nav' or fallback not in self.pages:
                fallback = 'app_media' if 'app_media' in self.pages else next(
                    (page for page in self.pages if page not in ('app_nav', 'app_phone')), None
                )
            if fallback:
                logger.info("Navigation has no active maneuver: switching to %s.", fallback)
                self.pre_nav_app_name = None
                self.nav_auto_triggered = False
                self._leave_empty_context_page(fallback)
                current_app_name = fallback
                is_nav_page = False

        is_phone_page = (current_app_name == 'app_phone')
        if is_phone_page and not phone_available:
            fallback = 'app_media' if 'app_media' in self.pages else next(
                (page for page in self.pages if page not in ('app_nav', 'app_phone')), None
            )
            if fallback:
                logger.info("Phone has no available content: switching to %s.", fallback)
                self._leave_empty_context_page(fallback)
                current_app_name = fallback
                is_phone_page = False

        nav_should_claim = bool(
            self.nav_claim_on_nav and nav_available
        )
        phone_should_claim = bool(
            self.phone_claim_on_phone
            and phone_available
        )
        should_claim = nav_should_claim or phone_should_claim
        # A contextual claim must present its context, not the startup media page.
        if nav_should_claim and not phone_should_claim and not is_nav_page and (self.user_paused or self.boot_inactive_hold):
            self.pre_nav_app_name = current_app_name
            # Claim-on-nav is an explicit request to present this context even
            # when routine maneuver auto-switching is disabled.
            self._context_nav_peek_until = time.monotonic() + max(0,
                getattr(getattr(self, 'nav_policy', None), 'peek_s', 5))
        if (getattr(self, 'context_claim_only', False) and not should_claim
                and not getattr(self, 'cluster_selected_session', False)):
            if not self.user_paused:
                if self._send_draw({'command': 'pause'}):
                    self.user_paused = True
                    self.content_auto_claimed = False
            return

        if getattr(self, 'boot_inactive_hold', False):
            if should_claim:
                logger.info("Available navigation/phone content is claiming the center display.")
                if self._send_draw({'command': 'resume'}):
                    self.boot_inactive_hold = False
                    self.user_paused = False
                    self.content_auto_claimed = True
                else:
                    return
            else:
                return

        if not getattr(self, 'service_ready', False) and not self.user_paused:
            return

        if should_claim and self.user_paused:
            logger.info("Available navigation/phone content is claiming the center display.")
            if self._send_draw({'command': 'resume'}):
                self.user_paused = False
                self.content_auto_claimed = True
        elif (self.content_auto_claimed and not should_claim
                and not getattr(self, 'cluster_selected_session', False)):
            logger.info("Claiming content ended: releasing the center display.")
            if self._send_draw({'command': 'pause'}):
                self.user_paused = True
                self.content_auto_claimed = False

    def is_nav_available(self):
        """Navigation exists only when the provider has a real route."""
        return bool(self.nav_active and self.apps['app_nav'].has_route)

    def is_phone_available(self):
        """Phone exists only while call activity is present."""
        phone_app = self.apps.get('app_phone')
        return bool(phone_app and phone_app.has_phone)

    def _resolve_app_priority(self):
        """Unified resolver for the current active app based on priority.
        
        Priority: Phone > Brief Cover Art > Easter Egg > User Selection
        """
        # 1. Phone Priority
        if getattr(self, 'phone_auto_overlay', False):
            return 'app_phone'

        # 2. Nav Auto Switch
        if getattr(self, 'pre_nav_app_name', None) is not None:
            return 'app_nav'

        # 3. Brief Cover Art (sequencing first)
        if self.brief_cover_active and self.pages[self.current_page_idx] == 'app_media':
            if time.time() < self.brief_auto_switch_end:
                return 'app_coverart'
            else:
                self.brief_cover_active = False
                # Transition to Egg if pending
                if self.egg_pending:
                    self.egg_active = True
                    self.egg_pending = False

        # 4. Easter Egg Priority
        if self.egg_active and self.pages[self.current_page_idx] == 'app_media':
            if self.apps['app_easteregg'].finished:
                self.egg_active = False
            else:
                return 'app_easteregg'

        # 5. Normal Application Cycle
        return self.pages[self.current_page_idx]

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

    def draw_native_bitmap(self, source, *, render_order='planes', band_rows=12, delta=False, update_rect=None):
        """Queue one full128x96 packed/Pillow mode1 snapshot with normal feedback.

        This opt-in path requires the white cluster center. No resizing or
        conversion is implicit. Returns False while unavailable or a previous
        UI frame is awaiting feedback; it never adds another drawing queue.
        """
        from native_bitmap import packed_bitmap, validate_render_options, validate_update_rect
        validate_render_options(render_order, band_rows)
        if not isinstance(delta, bool) or (delta and render_order not in ('tiles', 'planes')):
            raise ValueError('Native delta is a boolean option for tiles or planes')
        update_rect = validate_update_rect(update_rect, render_order, delta)
        data = packed_bitmap(source)  # Validate before sequence or cache changes.
        if (not getattr(self, 'service_ready', True)
                or getattr(self, 'user_paused', False)
                or getattr(self, '_pending_ui_frame', None) is not None):
            return False
        self.frame_seq_counter = (self.frame_seq_counter + 1) % 1000000 or 1
        seq = self.frame_seq_counter
        command = dict(command='draw_native_bitmap', x=0, y=0, w=128, h=96,
                       data_hex=data.hex(), render_order=render_order, band_rows=band_rows)
        if delta:
            command['delta'] = True
        if update_rect is not None:
            command['update_rect'] = update_rect
        if self._send_draw(dict(command='frame', commands=[command], seq=seq)):
            import time
            self._pending_ui_frame_started = time.monotonic()
            self._pending_ui_frame = (seq, self.current_app)
            self.current_app.on_frame_sent(seq)
            return True
        # No atomic frame was queued; reuse the existing commit backpressure
        # contract instead of waiting for feedback that cannot arrive.
        self._pending_ui_frame = None
        reset = getattr(self.current_app, 'on_display_reset', None)
        if reset:
            reset()
        self.last_sent = {}
        self.last_sent_flags = {}
        return False

    def _commit_ui_frame(self):
        self.frame_seq_counter = (self.frame_seq_counter + 1) % 1000000 or 1
        if self._send_draw({'command': 'commit', 'seq': self.frame_seq_counter}):
            import time
            self._pending_ui_frame_started = time.monotonic()
            self._pending_ui_frame = (self.frame_seq_counter, self.current_app)
            self.current_app.on_frame_sent(self.frame_seq_counter)
            return True
        # No commit was queued, so waiting for its ACK would deadlock an app.
        # Discard cached presentation and restore a full image on retry.
        self._pending_ui_frame = None
        reset = getattr(self.current_app, 'on_display_reset', None)
        if reset:
            reset()
        self.last_sent = {}
        self.last_sent_flags = {}
        return False

    def _handle_ui_frame_result(self, seq, success):
        pending = getattr(self, '_pending_ui_frame', None)
        if pending is None or pending[0] != seq or pending[1] is not self.current_app:
            return False
        self._pending_ui_frame = None
        if success:
            if (getattr(self, '_pending_ui_frame_clear_epoch', None) is not None
                    and getattr(self, '_pending_ui_frame_clear_epoch', None)
                    == getattr(self, '_deferred_app_clear', None)):
                self._deferred_app_clear = None
            self.current_app.on_frame_acked(seq)
        else:
            failed = getattr(self.current_app, 'on_frame_failed', None)
            if failed:
                failed(seq)
            self.force_redraw(send_clear=getattr(self, '_deferred_app_clear', None) is None)
        return True

    def force_redraw(self, send_clear=False):
        self._pending_ui_frame = None
        reset = getattr(self.current_app, 'on_display_reset', None)
        if reset:
            reset()
        self.last_sent = {}
        self.last_sent_flags = {}
        if hasattr(self.current_app, 'prev_road_img'):
            self.current_app.prev_road_img = None
        if send_clear and not self.user_paused and not self.boot_inactive_hold:
            self._send_draw({'command': 'clear'})
            self._send_draw({'command': 'commit'})
        self.publish_status()

    def run(self):
        logger.info("DIS Engine V5.8 Running")
        self.publish_status()
        time.sleep(1.0) 
        if getattr(self, 'start_inactive', False):
            logger.info("Configured to start inactive. Sending startup pause command...")
            self._send_draw({'command': 'pause'})
            self.user_paused = True
        else:
            self.force_redraw(send_clear=True)
        self.last_loop = time.time()
        
        logger.info("Main loop started.")
        while self.running:
            try:
                # 1. Wait for messages
                # (Logic previously handled inside while True)
                now = time.time()
                self.last_loop = now

                socks = dict(self.poller.poll(30))
                if self.sub_hudiy in socks:
                    try:
                        # Limit Hudiy processing per loop to avoid blocking too long
                        h_count = 0
                        while h_count < 50:
                            parts = self.sub_hudiy.recv_multipart(flags=zmq.NOBLOCK)
                            h_count += 1
                            if len(parts) == 2:
                                topic, msg = parts
                                try:
                                    data = json.loads(msg)
                                    if topic in (b'DIS_INPUT', b'WHEEL_CONTROL'):
                                        self._handle_wheel_input(topic, data)
                                        continue
                                    
                                    if hasattr(self, 'log_push'):
                                        self.log_push.send_string(f"RX: {topic.decode('utf-8')} -> {data}")
                                        
                                    if topic == b'HUDIY_NAV_STATUS':
                                        self.apps['app_nav'].update_hudiy(topic, data)
                                        active = data.get('active') is True
                                        if active != self.nav_active:
                                            self.nav_active = active
                                            logger.info("Nav Active State Changed: %s", active)
                                        self._handle_nav_auto_switch(self.apps['app_nav'])

                                    # Update NavApp specifically for background monitoring (auto-switch, availability)
                                    if topic.startswith(b'HUDIY_NAV') and topic != b'HUDIY_NAV_STATUS':
                                        nav_app = self.apps['app_nav']
                                        nav_app.update_hudiy(topic, data)
                                        self._handle_nav_auto_switch(nav_app)

                                    if topic == b'HUDIY_PHONE':
                                        if 'app_phone' in self.apps: self.apps['app_phone'].update_hudiy(topic, data)
                                        self._handle_phone_status(data)

                                    if topic == b'HUDIY_MEDIA':
                                        if 'app_media' in self.apps: self.apps['app_media'].update_hudiy(topic, data)
                                        self._handle_media_match(data)

                                    if topic == b'HUDIY_OPENPILOT':
                                        if 'app_openpilot' in self.apps: self.apps['app_openpilot'].update_hudiy(topic, data)

                                    if topic == b'HUDIY_COVERART':
                                        self.apps['app_coverart'].update_hudiy(topic, data)
                                        
                                        # Only trigger brief cover if on Media app
                                        now_time = time.time()
                                        has_bitmap = bool(data.get('bitmap_hex', ''))
                                        is_new = data.get('is_new_track', False)
                                        recently_triggered = (now_time - getattr(self, 'last_cover_trigger_time', 0) < 6.0)
                                        
                                        # Logic: 
                                        # 1. Trigger if it's a completely new track (even if no bitmap yet, to clear UI)
                                        # 2. ALSO trigger if we just received a real bitmap and haven't triggered recently (handles delayed art)
                                        if self.pages[self.current_page_idx] == 'app_media' and (is_new or (has_bitmap and not recently_triggered)) and \
                                           getattr(self, 'service_ready', False) and getattr(self, 'coverart_brief', True):
                                            
                                            if not recently_triggered or is_new:
                                                logger.info(f"Cover Art trigger: Auto-switching to Cover Art app (New: {is_new}, Delayed: {not is_new and has_bitmap})")
                                                self.last_cover_trigger_time = now_time
                                                self.brief_cover_active = True
                                                self.brief_auto_switch_end = now_time + 5.0
                                                self.force_redraw(send_clear=True)

                                    # ALWAYS update the currently active app to ensure it doesn't miss any data
                                    if self.current_app:
                                        self.current_app.update_hudiy(topic, data)
                                except json.JSONDecodeError: pass
                    except zmq.Again: pass

                if getattr(self, 'sub_status', None) and self.sub_status in socks:
                    try:
                        while True:
                            msg = self.sub_status.recv_string(flags=zmq.NOBLOCK)
                            #logger.info(f"DEBUG: sub_status RX: {msg}")
                            if msg.startswith("DIS_STATE"):
                                try:
                                    state = msg.split(" ")[1]
                                    is_ready = (state == "READY")
                                    
                                    # Reset hold flags on disconnection (ignition cycle)
                                    if state == "DISCONNECTED":
                                        if self.start_inactive and not self.boot_inactive_hold:
                                            logger.info("Service disconnected. Resetting boot inactive hold flags.")
                                        self._handle_service_disconnect()
                                        self.has_entered_paused_state = False

                                    # Set paused flag once service acknowledges pause
                                    if state == "PAUSED":
                                        self.has_entered_paused_state = True
                                        
                                    if self.service_ready != is_ready:
                                        self.service_ready = is_ready
                                        logger.info(f"DIS Service State Changed to: {state}. Ready={self.service_ready}")
                                        if self.service_ready:
                                            if not self.boot_inactive_hold:
                                                self.force_redraw(send_clear=True)
                                                # Navigation data may have arrived while the DIS
                                                # service was paused. Re-evaluate it on readiness.
                                                self._handle_nav_auto_switch(self.apps['app_nav'])
                                            else:
                                                logger.info("Service READY but holding inactive. Skipping redraw.")
                                        self.publish_status()
                                except Exception as split_err:
                                    logger.error(f"Failed to parse DIS_STATE message '{msg}': {split_err}")
                            elif msg.startswith("DIS_REQUESTED"):
                                try:
                                    self._handle_cluster_request(int(msg.split()[1]))
                                except (ValueError, IndexError):
                                    logger.warning("Invalid cluster request: %s", msg)
                            elif msg.startswith("DRAW_NACK"):
                                try:
                                    seq = int(msg.split()[1])
                                    self._handle_ui_frame_result(seq, False)
                                except (ValueError, IndexError) as exc:
                                    logger.error("Failed to parse DRAW_NACK: %s", exc)
                            elif msg.startswith("DRAW_ACK"):
                                try:
                                    parts = msg.split(" ")
                                    if len(parts) >= 2:
                                        seq = int(parts[1])
                                        self._handle_ui_frame_result(seq, True)
                                except Exception as e:
                                    logger.error(f"Failed to parse DRAW_ACK: {e}")
                    except zmq.Again: pass

                if self.sub in socks: self._handle_can()
                
                self._handle_nav_auto_switch(self.apps['app_nav'])
                # Periodic App Priority Resolution
                active_app_name = self._resolve_app_priority()
                if self.apps[active_app_name] != self.current_app:
                    logger.info(f"Priority Switch: {active_app_name}")
                    if self.current_app: self.current_app.on_leave()
                    self.current_app = self.apps[active_app_name]
                    self.current_app.on_enter()
                    self._wheel_epoch = getattr(self, '_wheel_epoch', 0) + 1
                    self.last_tp2_sync = 0 # Force immediate TP2 sync on priority switch
                    self.force_redraw(send_clear=True)

                # Config/subpage edits renew immediately; logging keeps its own lease.
                for app in self.apps.values():
                    if hasattr(app, 'tick'):
                        app.tick()
                requested = getattr(self.current_app, 'value_requests', [])
                if hasattr(self, 'tp2_cmd') and (now - self.last_tp2_sync > 5.0
                        or requested != getattr(self, '_last_value_requests', None)):
                    self.last_tp2_sync = now
                    self._last_value_requests = requested.copy()
                    try:
                        sync_msg = {
                            "cmd": "SYNC_VALUES",
                            "client_id": "dis_display",
                            "values": requested
                        }
                        self.tp2_cmd.send_json(sync_msg, flags=zmq.NOBLOCK)
                        # We must receive the reply to satisfy the REQ/REP state machine
                        if self.tp2_cmd.poll(100):
                            try:
                                self.tp2_cmd.recv_json()
                            except zmq.Again:
                                pass
                        else:
                            # If it timed out, the REQ socket is stuck. Re-create it.
                            logger.warning("TP2 sync reply timed out, recreating command socket.")
                            self.tp2_cmd.close()
                            self.tp2_cmd = self.zmq_ctx.socket(zmq.REQ)
                            self.tp2_cmd.setsockopt(zmq.RCVTIMEO, 1000)
                            self.tp2_cmd.setsockopt(zmq.LINGER, 0)
                            _tp2_addr = self.cfg.get('interfaces', {}).get('zmq', {}).get('vehicle_data_command', 'ipc:///run/rnse_control/vehicle_data_cmd.ipc')
                            self.tp2_cmd.connect(_tp2_addr)
                    except Exception as e:
                        logger.debug(f"TP2 Sync failure handled: {e}")

                self._check_nav_availability_pause()
                self._check_buttons()
                if time.monotonic() - getattr(self, '_wheel_status_at', 0) > 3.0:
                    if hasattr(self.current_app, 'set_control_mode'):
                        self.current_app.set_control_mode(False)
                self._draw()

                # Periodic status heartbeat (every 1s)
                if now - getattr(self, 'last_status_pub', 0) > 1.0:
                    self.publish_status(force=True)
                    self.last_status_pub = now

                time.sleep(0.01)
            except KeyboardInterrupt: break
            except Exception as e: logger.error(f"Err: {e}", exc_info=True); time.sleep(1)

    def _handle_nav_auto_switch(self, nav_app):
        """Observe route events without replacing the user's selected page."""
        if not hasattr(self, 'nav_policy'):
            self.nav_policy = NavigationPolicy(
                getattr(self, 'nav_approach_threshold', 500),
                getattr(self, 'nav_return_threshold', 1000),
                getattr(self, 'nav_peek_seconds', 5))
        signature = tuple(getattr(nav_app, key, None) for key in
            ('maneuver_type', 'maneuver_side', 'maneuver_angle', 'description'))
        available = self.is_nav_available()
        selected = self.pages[self.current_page_idx]
        now = time.monotonic()
        interrupt = self.nav_policy.update(available, signature,
            getattr(nav_app, 'meters', -1), now,
            enabled=getattr(self, 'nav_auto_switch', True) and 'app_nav' in self.pages)
        interrupt = interrupt or (available and now < getattr(self, '_context_nav_peek_until', 0))
        self.nav_auto_triggered = self.nav_policy.approaching
        # A manually selected Nav page stays selected, regardless of distance.
        self.pre_nav_app_name = selected if interrupt and selected != 'app_nav' else None

    def _handle_service_disconnect(self):
        """A lost cluster session restores the configured ownership policy."""
        self.boot_inactive_hold = bool(self.start_inactive)
        self.user_paused = bool(self.start_inactive)
        self.content_auto_claimed = False
        self.cluster_selected_session = False
        self._last_cluster_request = 0
        self._context_nav_peek_until = 0
        self.pre_nav_app_name = None
        if hasattr(self, 'nav_policy'):
            self.nav_policy.reset()
        self.force_redraw(send_clear=False)

    def _handle_cluster_request(self, generation):
        """Accept a confirmed 2E/2F content request, never generic READY."""
        if generation <= getattr(self, '_last_cluster_request', 0):
            return
        if not self._send_draw({'command': 'resume'}):
            return
        self._last_cluster_request = generation
        self.cluster_selected_session = True
        self.boot_inactive_hold = False
        self.user_paused = False
        self.content_auto_claimed = False
        self.force_redraw(send_clear=False)
        logger.info("Cluster requested DIS content; allowing presentation.")

    def _handle_media_match(self, data):
        """Check for Easter Egg matches using regex."""
        title = data.get('title', '')
        artist = data.get('artist', '')
        album = data.get('album', '')
        combined = f"{artist} - {title} [{album}]"
        
        # If the track hasn't changed, don't re-process matches to avoid 
        # resetting a one-off GIF's 'finished' state.
        if combined == getattr(self, '_last_processed_media', None):
            return
        self._last_processed_media = combined

        # Only proceed to trigger if on media page
        if self.pages[self.current_page_idx] != 'app_media':
            return

        eggs_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'eggs.json')
        if not os.path.exists(eggs_cfg_path):
            return

        try:
            with open(eggs_cfg_path, 'r') as f:
                eggs_cfg = json.load(f)
            
            matched_any = False
            for match_def in eggs_cfg.get('matches', []):
                pattern = match_def.get('regex', '')
                if pattern and re.search(pattern, combined, re.IGNORECASE):
                    matched_any = True
                    gif_name = match_def.get('gif')
                    logger.info(f"Easter Egg Match! '{combined}' matched regex '{pattern}'.")
                    
                    egg_app = self.apps['app_easteregg']
                    
                    # Extract logic items
                    loop = match_def.get('loop', 999)
                    
                    # Pass all other keys as processing params to dis_image
                    params = {k: v for k, v in match_def.items() if k not in ['regex', 'gif', 'loop']}
                    
                    if egg_app.load_gif(gif_name, loop_count=loop, **params):
                        # If Brief Cover art is active, we go into PENDING
                        if self.brief_cover_active:
                            logger.info("Cover Art is active, queuing Easter Egg.")
                            self.egg_pending = True
                        else:
                            self.egg_active = True
                        break # First match wins
            
            if not matched_any:
                if self.egg_active or self.egg_pending:
                    logger.info("Track changed to non-egg song: Deactivating Easter Egg.")
                    self.egg_active = False
                    self.egg_pending = False
                    
            # If no match, clear existing eggs if a song changed
            # (Note: simpler to just let the priority resolver handle it if we have a robust ID check)
        except Exception as e:
            logger.error(f"Failed to process Easter Eggs: {e}")

    def _handle_phone_status(self, data):
        state = PhoneApp.call_state(data)
        interesting = state in PhoneApp.CALL_STATES
        
        if interesting != self.phone_active:
            self.phone_active = interesting
            logger.info(f"Phone Interesting State Changed: {interesting} (state: {state})")
            
            if interesting:
                self.phone_auto_overlay = True
                self.pre_phone_app_name = self.pages[self.current_page_idx]
            else:
                self.phone_auto_overlay = False
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
                    
                    if '60E' in t_str or '1550' in t_str:
                        if len(payload) >= 1:
                            byte0 = payload[0]
                            self.car_units['speed'] = 'imperial' if (byte0 & 0x01) else 'metric'
                            self.car_units['temp'] = 'imperial' if (byte0 & 0x02) else 'metric'
                            press_val = (byte0 >> 4) & 0x03
                            if press_val == 1:
                                self.car_units['pressure'] = 'psi'
                            elif press_val == 3:
                                self.car_units['pressure'] = 'kPa'
                            else:
                                self.car_units['pressure'] = 'bar'
                                
                    self.current_app.update_can(t_str, payload)
                    
                    if 'app_acceleration_test' in self.apps and self.current_app != self.apps['app_acceleration_test']:
                        if '351' in t_str:
                            self.apps['app_acceleration_test'].update_can(t_str, payload)
                            
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

    def _queue_ui_frame(self, commands):
        """Queue one complete view atomically; never overwrite an in-flight seq."""
        if getattr(self, '_pending_ui_frame', None) is not None:
            return False
        self.frame_seq_counter = (self.frame_seq_counter + 1) % 1000000 or 1
        seq = self.frame_seq_counter
        if not self._send_draw(dict(command='frame', seq=seq, commands=commands)):
            self.force_redraw(send_clear=False)
            return False
        import time
        self._pending_ui_frame_started = time.monotonic()
        self._pending_ui_frame = (seq, self.current_app)
        self._pending_ui_frame_clear_epoch = getattr(self, '_deferred_app_clear', None)
        self.current_app.on_frame_sent(seq)
        return True

    def _ui_frame_waiting(self):
        """Recover from lost PUB feedback with a fresh view after a bounded wait."""
        if getattr(self, '_pending_ui_frame', None) is None:
            return False
        import time
        started = getattr(self, '_pending_ui_frame_started', None)
        if started is None:
            self._pending_ui_frame_started = time.monotonic()
            return True
        timeout = getattr(self, 'cfg', {}).get('display', {}).get('center_display', {}).get('frame_feedback_timeout_s', 30)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 10 <= timeout <= 120:
            timeout = 30
        if time.monotonic()-started < timeout:
            return True
        logger.warning('DIS frame feedback timed out; rebuilding the current view')
        self.force_redraw(send_clear=False)
        return False

    def _prepare_text_group(self, items, previous_items, profile, group):
        """Replace field wipes with measured atomic text updates.

        A clear rectangle is a field boundary, not an instruction to erase
        neighboring overlays every time proportional text changes.
        """
        from text_render import text_update
        texts = [item for item in items if item.get('cmd') == 'draw_text']
        old_texts = [item for item in previous_items if item.get('cmd') == 'draw_text']
        clears = [item for item in items if item.get('cmd') == 'clear_area']
        consumed = set()
        slots = []
        for index, new in enumerate(texts):
            previous = old_texts[index] if index < len(old_texts) else None
            matching = next((clear for clear in clears
                if clear.get('y', 0) <= new.get('y', 0) < clear.get('y', 0) + clear.get('h', 0)
                and clear.get('x', 0) <= new.get('x', 0) < clear.get('x', 0) + clear.get('w', 0)), None)
            viewport = tuple(matching.get(k, 0) for k in ('x', 'y', 'w', 'h')) if matching else (0, 0, 64, 48)
            if matching:
                consumed.add(id(matching))
            new = dict(new, field_id=f'{group}:{index}')
            update = text_update(new, previous, profile, viewport=viewport, config=self.cfg)
            # The renderer's public representation uses cmd; service IPC uses command.
            update['cmd'] = update.pop('command')
            slots.append(update)
        result = []
        text_index = 0
        for item in items:
            if item.get('cmd') == 'clear_area' and id(item) in consumed:
                continue
            if item.get('cmd') == 'draw_text':
                result.append(slots[text_index])
                text_index += 1
            else:
                result.append(item)
        for index, previous in enumerate(old_texts[len(texts):], start=len(texts)):
            update = text_update(dict(previous, text='', field_id=f'{group}:{index}'), previous, profile, config=self.cfg)
            update['cmd'] = update.pop('command')
            result.append(update)
        return result

    def _draw(self):
        if (not getattr(self, 'service_ready', True) or getattr(self, 'user_paused', False)
                or self._ui_frame_waiting()):
            return
        view = self.current_app.get_view()
        from font_metrics import font_profile
        from text_render import text_update
        profile = font_profile(self.cfg)
        deferred_clear = getattr(self, '_deferred_app_clear', None) is not None
        if isinstance(view, list):
            current_type = view[0].get('type') if view else None
            # Explicit white navigation can use normal artwork while keeping
            # native text metrics. Other app/profile defaults remain global.
            if (isinstance(current_type, str) and current_type.startswith('nav_white_')
                    and view[0].get('text_profile') == 'native'):
                profile = 'native'
            prev_type = self.last_sent.get('last_type')
            full_redraw = (current_type != prev_type
                or self.last_sent.get('_text_profile') != profile)
            payloads = []
            if deferred_clear or (full_redraw and current_type != 'nav_stock_mono'):
                clear = 'clear_payload' if view and view[0].get('clear_on_update', True) and prev_type else 'clear'
                if deferred_clear or (isinstance(current_type, str) and current_type.startswith(('nav_enhanced_', 'nav_white_'))):
                    # Enhanced snapshots clear and draw under one final39;
                    # retain the established clear behavior for other views.
                    clear = 'clear_payload'
                payloads.append(dict(command=clear))
            groups_current = {}
            for item in view:
                if not isinstance(item, dict) or 'type' in item:
                    continue
                group = item.get('group') or str(sorted((k, v) for k, v in item.items() if k != 'group'))
                groups_current.setdefault(group, []).append(item)
            last_groups = {} if full_redraw else dict(self.last_sent.get('groups') or {})
            # A full native image erases all overlays. Resend them even if their
            # signatures stayed identical when only the maneuver icon changed.
            from native_bitmap import validate_update_rect
            def preserves_overlays(item):
                if item.get('preserves_overlays') is not True:
                    return False
                try:
                    return validate_update_rect(item.get('update_rect'),
                        item.get('render_order', 'tiles'), item.get('delta', False)) is not None
                except (ValueError, TypeError):
                    return False
            replaces_center = any(any(item.get('cmd') == 'native_bitmap' and not preserves_overlays(item) for item in items)
                and (full_redraw or last_groups.get(group) != str(items))
                for group, items in groups_current.items())
            for group, items in groups_current.items():
                if not (full_redraw or replaces_center or last_groups.get(group) != str(items)):
                    continue
                previous_items = [] if full_redraw or replaces_center else (self.last_sent.get('group_items') or {}).get(group, [])
                prepared_items = self._prepare_text_group(items, previous_items, profile, group)
                for item in prepared_items:
                    cmd = item.get('cmd')
                    if (full_redraw and group == 'icon' and cmd == 'clear_area'
                            and isinstance(current_type, str) and current_type.startswith('nav_white_')):
                        # The snapshot already has a payload-only full clear.
                        continue
                    if cmd == 'native_bitmap':
                        payload = dict(command='draw_native_bitmap', x=0, y=0, w=128, h=96,
                            data_hex=item.get('data_hex', ''), render_order=item.get('render_order', 'tiles'),
                            band_rows=item.get('band_rows', 12))
                        if 'post_message_delay_s' in item:
                            payload['post_message_delay_s'] = item['post_message_delay_s']
                        if item.get('delta', False):
                            payload['delta'] = True
                        if item.get('update_rect') is not None:
                            payload['update_rect'] = item['update_rect']
                    elif cmd == 'draw_bitmap':
                        payload = dict(command=cmd, icon_name=item.get('icon', ''),
                            x=item.get('x', 0), y=item.get('y', 0))
                        if 'mode_flag' in item:
                            payload['mode_flag'] = item['mode_flag']
                    elif cmd in ('draw_text', 'update_text', 'draw_line', 'clear_area', 'draw_raw_bitmap', 'draw_stock_mono_frame', 'draw_native_font', 'draw_stock_nav_glyph'):
                        payload = {key: value for key, value in item.items() if key not in ('cmd', 'group', 'type')}
                        payload['command'] = cmd
                    else:
                        logger.warning('Unsupported app drawing command: %s', cmd)
                        self.force_redraw(send_clear=False)
                        return
                    payloads.append(payload)
                last_groups[group] = str(items)
            if payloads and not self._queue_ui_frame(payloads):
                return
            self.last_sent['groups'] = {group: value for group, value in last_groups.items() if group in groups_current}
            self.last_sent['last_type'] = current_type
            self.last_sent['group_items'] = groups_current
            self.last_sent['_text_profile'] = profile
            for key in self.Y:
                self.last_sent[key] = None
            return

        from font_metrics import fit_text, font_profile, text_character_capacity
        profile = font_profile(self.cfg)
        custom_transition = self.last_sent.get('groups') is not None
        profile_changed = self.last_sent.get('_text_profile') != profile
        payloads = [dict(command='clear_payload')] if custom_transition or deferred_clear else []
        next_text, next_flags = {}, {}
        # Normal text pages use the 48-logical-pixel central region.
        # Background navigation does not enlarge the active page's window.
        max_height = 48
        for key, y_pos in self.Y.items():
            if key not in view:
                # An omitted line must not retain content from the prior view.
                if not custom_transition and self.last_sent.get(key) not in (None, ''):
                    height = min(9, max_height - y_pos)
                    if height > 0:
                        payloads.append(text_update(dict(text='', x=0, y=y_pos, flags=self.last_sent_flags.get(key, 6), field_id=key),
                            dict(text=self.last_sent[key], x=0, y=y_pos, flags=self.last_sent_flags.get(key, 6)),
                            profile=profile, viewport=(0, y_pos, 64, height), config=self.cfg))
                next_text[key], next_flags[key] = None, 0
                continue
            text, flags = view[key]
            text = fit_text(str(text), 128, flags, profile,
                max_chars=text_character_capacity(flags,profile,self.cfg))
            next_text[key], next_flags[key] = text, flags
            if (custom_transition or profile_changed or self.last_sent.get(key) != text
                    or self.last_sent_flags.get(key, 0) != flags):
                height = min(9, max_height - y_pos)
                if height > 0:
                    previous = None if custom_transition else dict(text=self.last_sent.get(key) or '',
                        x=0, y=y_pos, flags=self.last_sent_flags.get(key, 6))
                    payloads.append(text_update(dict(text=text, x=0, y=y_pos, flags=flags, field_id=key),
                        previous, profile=profile, viewport=(0, y_pos, 64, height),
                        force_clear=profile_changed and not custom_transition, config=self.cfg))
        if payloads and not self._queue_ui_frame(payloads):
            return
        self.last_sent.update(next_text)
        self.last_sent_flags.update(next_flags)
        self.last_sent['_text_profile'] = profile
        if custom_transition:
            self.last_sent['groups'] = None
            self.last_sent['last_type'] = None
            self.last_sent['custom_sig'] = None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true', help='Connect to Emulator ports')
    args = parser.parse_args()
    
    config_path = '../config.json' if os.path.exists('../config.json') else '/home/pi/config.json'
    try:
        DisplayEngine(config_path=config_path, mock=args.mock).run()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
