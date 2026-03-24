#!/usr/bin/env python3
#v1.3.6
# can_base_function.py
#
# This service provides base CAN bus functionality, including TV Tuner simulation,
# Time Synchronization, and Auto-Shutdown, using a robust asyncio architecture.
#
# Version: 1.3.6 (Fixed global RUNNING declaration in shutdown_monitor_task)
#

import zmq
import json
import time
import logging
import signal
import sys
from datetime import datetime
import pytz
from typing import Optional, List, Dict, Any
import asyncio
import aiozmq
import subprocess
try:
    from gpiozero import Button
    GPIO_AVAILABLE = True
except ImportError:
    Button = None
    GPIO_AVAILABLE = False

# --- Global State ---
RUNNING = True
RELOAD_CONFIG = False
CONFIG: Dict[str, Any] = {}
FEATURES: Dict[str, Any] = {}
ZMQ_CONTEXT: Optional[zmq.Context] = None
ZMQ_PUSH_SOCKET: Optional[zmq.Socket] = None

# --- Logging Setup ---
def setup_logging():
    log_file = '/var/log/rnse_control/can_base_function.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# --- Helper function for BCD conversion ---
def hex_to_bcd(hex_str: str) -> int:
    if not (isinstance(hex_str, str) and len(hex_str) == 2 and hex_str.isalnum()):
        raise ValueError(f"Input must be a 2-char hex string, got '{hex_str}'")
    return int(hex_str[0]) * 10 + int(hex_str[1])

# --- State Management Class ---
class AppState:
    def __init__(self):
        self.last_time_sync_attempt_time: float = 0.0
        self.time_sync_in_progress: bool = False
        self.time_sync_task: Optional[asyncio.Task] = None
        # Auto-shutdown state
        self.last_kl15_status: Optional[int] = None  # Ignition status (1=ON, 0=OFF, None=Unknown)
        self.last_kls_status: Optional[int] = None   # Key in lock sensor status (1=IN, 0=PULLED, None=Unknown)
        self.shutdown_trigger_timestamp: Optional[float] = None
        self.shutdown_pending: bool = False
        
        # Listen-only state
        self.can_listen_only: bool = False
        self.desired_listen_only: bool = False
        self.listen_only_pending: bool = False
        self.listen_only_trigger_timestamp: Optional[float] = None
        self.listen_only_transition_in_progress: bool = False
        
        # GPIO shutdown state
        self.gpio_shutdown_pending: bool = False
        self.gpio_shutdown_trigger_timestamp: Optional[float] = None
        
        self.zmq_pub = None # ZMQ Publisher socket

    async def check_shutdown_condition(self) -> bool:
        """Check if shutdown delay has been reached and execute shutdown."""
        if self.shutdown_pending and self.shutdown_trigger_timestamp:
            delay = getattr(self, '_current_shutdown_delay', CONFIG.get('shutdown_delay', 300))
            if time.time() - self.shutdown_trigger_timestamp >= delay:
                logger.info(f"Shutdown delay ({delay}s) reached. Shutting down system NOW.")
                shutdown_command = ["sudo", "shutdown", "-h", "now"]
                if await execute_system_command_async(shutdown_command):
                    logger.info("Shutdown command executed successfully.")
                    return True  # Signal to stop the service
                else:
                    logger.error("Shutdown command failed! Resetting shutdown state.")
                    self.shutdown_pending = False
                    self.shutdown_trigger_timestamp = None
        return False

# --- Configuration Handling ---
def load_and_initialize_config(config_path='/home/pi/config.json') -> bool:
    global CONFIG, FEATURES
    logger.info(f"Loading configuration from {config_path}...")
    try:
        with open(config_path, 'r') as f: cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.critical(f"FATAL: Could not load or parse {config_path}: {e}"); return False

    try:
        # Features & Power Management
        FEATURES = cfg.setdefault('features', {})
        CONFIG['car_time_zone'] = FEATURES.get('car_time_zone', 'UTC')
        debug_mode = FEATURES.get('debug_mode', False)
        pw_mgmt = FEATURES.get('power_management', {})
        
        # Initialize default sections if missing
        FEATURES.setdefault('tv_simulation', {'enabled': False})
        FEATURES.setdefault('time_sync', {'enabled': False, 'data_format': 'old_logic'})
        
        pw_mgmt.setdefault('auto_shutdown', {'enabled': False, 'trigger': 'ignition_off'})
        pw_mgmt.setdefault('listen_only_mode', {'enabled': False, 'delay_seconds': 0})
        pw_mgmt.setdefault('gpio_shutdown', {'enabled': False, 'pin': 26, 'active_low': True, 'delay_seconds': 0})

        interfaces_cfg = cfg.get('interfaces', {})
        can_config = interfaces_cfg.get('can', {})
        zmq_config = interfaces_cfg.get('zmq', {})
        can_ids = cfg.get('can_ids', {})
        car_tz = pytz.timezone(CONFIG['car_time_zone'])
        
        CONFIG.update({
            'can_interface': can_config.get('infotainment', 'can0'),
            'car_timezone': car_tz,
            'zmq_publish_address': zmq_config.get('can_raw_stream'),
            'zmq_send_address': zmq_config.get('send_address'),
            'zmq_base_publish_address': zmq_config.get('system_events'),
            'can_ids': {
                'tv_presence': int(can_ids.get('tv_presence', '0x602'), 16),
                'time_data': int(can_ids.get('time_data', '0x623'), 16),
                'ignition_status': int(can_ids.get('ignition_status', '0x2C3'), 16),
            },
            'time_data_format': FEATURES['time_sync'].get('data_format', 'old_logic'),
            'time_sync_threshold_seconds': FEATURES['time_sync'].get('threshold_minutes', 1.0) * 60,
            'shutdown_delay': pw_mgmt.get('auto_shutdown', {}).get('delay_seconds', 300),
        })
        
        # Add power management to FEATURES for consistency in handlers
        FEATURES['power_management'] = pw_mgmt

        if not CONFIG['zmq_send_address'] or not CONFIG['zmq_publish_address'] or not CONFIG['zmq_base_publish_address']:
            raise KeyError("'send_address' or 'can_raw_stream' or 'system_events' not found in 'interfaces.zmq' section")

        log_level = logging.DEBUG if debug_mode else logging.INFO
        logger.setLevel(log_level)
            
        logger.info("Configuration for base functions loaded successfully.")
        return True
    except (KeyError, ValueError) as e:
        logger.critical(f"FATAL: Config is missing a key or has an invalid value: {e}", exc_info=True); return False

# --- Core Logic ---
def initialize_zmq_sender() -> bool:
    global ZMQ_CONTEXT, ZMQ_PUSH_SOCKET
    try:
        logger.info(f"Connecting ZeroMQ PUSH socket to {CONFIG['zmq_send_address']}...")
        ZMQ_CONTEXT = zmq.Context.instance()
        ZMQ_PUSH_SOCKET = ZMQ_CONTEXT.socket(zmq.PUSH)
        ZMQ_PUSH_SOCKET.connect(CONFIG['zmq_send_address'])
        return True
    except zmq.ZMQError as e:
        logger.error(f"Failed to connect ZMQ PUSH socket: {e}"); return False

def send_can_message(can_id: int, payload_hex: str) -> bool:
    if not ZMQ_PUSH_SOCKET: return False
    try:
        ZMQ_PUSH_SOCKET.send_multipart([str(can_id).encode('utf-8'), payload_hex.encode('utf-8')])
        return True
    except zmq.ZMQError as e:
        logger.error(f"Failed to queue CAN message via ZMQ: {e}"); return False

# --- CAN Interface Management ---
class CanInterfaceManager:
    @staticmethod
    def set_listen_only(enable: bool):
        mode = "listen-only on" if enable else "listen-only off"
        logger.info(f"Setting CAN interface to {mode}...")
        can_interface = CONFIG.get('can_interface', 'can0')
        
        # We need to bring the interface down, change mode, and bring it up
        commands = [
            ["sudo", "ip", "link", "set", can_interface, "down"],
            ["sudo", "ip", "link", "set", can_interface, "type", "can"] + (["listen-only", "on"] if enable else ["listen-only", "off"]),
            ["sudo", "ip", "link", "set", can_interface, "up"]
        ]
        
        success = True
        for cmd in commands:
            if not execute_system_command(cmd):
                success = False
                break
        
        if success:
            logger.info(f"CAN interface switched to {mode} successfully.")
        else:
            logger.error(f"Failed to switch CAN interface to {mode}.")
        return success

async def set_listen_only_async(enable: bool) -> bool:
    return await asyncio.to_thread(CanInterfaceManager.set_listen_only, enable)

def execute_system_command(command_list: List[str]) -> bool:
    if not command_list: return False
    cmd_str = ' '.join(command_list)
    try:
        logger.info(f"Executing system command: {cmd_str}")
        subprocess.run(command_list, check=True, capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Failed to execute command '{cmd_str}': {e}"); return False

async def execute_system_command_async(command_list: List[str]) -> bool:
    return await asyncio.to_thread(execute_system_command, command_list)

# --- Message Handling ---
async def complete_time_sync(state: AppState, date_str: str, time_diff_seconds: float):
    try:
        logger.info(f"Car time differs by {time_diff_seconds:.1f}s. Syncing system time.")
        await execute_system_command_async(["sudo", "date", "-u", date_str])
    except asyncio.CancelledError:
        logger.info("Time sync task cancelled before completion.")
        raise
    finally:
        state.time_sync_in_progress = False
        state.time_sync_task = None

async def handle_time_data_message(msg: Dict[str, Any], state: AppState):
    if not FEATURES.get('time_sync', {}).get('enabled', False) or msg.get('dlc', 0) < 8: return
    
    data_hex = msg['data_hex']
    time_format = CONFIG['time_data_format']
    
    try:
        if time_format == 'old_logic':
            second, minute, hour = hex_to_bcd(data_hex[6:8]), hex_to_bcd(data_hex[4:6]), hex_to_bcd(data_hex[2:4])
            day, month, year = hex_to_bcd(data_hex[8:10]), hex_to_bcd(data_hex[10:12]), int(data_hex[12:14] + data_hex[14:16])
        else:
            second, minute, hour = int(data_hex[6:8], 16), int(data_hex[4:6], 16), int(data_hex[2:4], 16)
            day, month, year = int(data_hex[8:10], 16), int(data_hex[10:12], 16), (int(data_hex[12:14], 16) * 100) + int(data_hex[14:16], 16)
        
        state.last_time_sync_attempt_time = time.time()
        car_dt = datetime(year=year, month=month, day=day, hour=hour, minute=minute, second=second)
        pi_utc_dt = datetime.now(pytz.utc)
        car_utc_dt = CONFIG['car_timezone'].localize(car_dt).astimezone(pytz.utc)
        time_diff_seconds = abs((car_utc_dt - pi_utc_dt).total_seconds())

        if time_diff_seconds > CONFIG['time_sync_threshold_seconds'] and not state.time_sync_in_progress:
            date_str = car_utc_dt.strftime('%m%d%H%M%Y.%S')
            state.time_sync_in_progress = True
            state.time_sync_task = asyncio.create_task(complete_time_sync(state, date_str, time_diff_seconds))
        else:
            logger.debug(f"Time sync check: difference {time_diff_seconds:.1f}s (threshold: {CONFIG['time_sync_threshold_seconds']}s)")
            
    except Exception as e:
        logger.warning(f"Could not parse time message (data_hex: {data_hex}): {e}")

def handle_power_status_message(msg: Dict[str, Any], state: AppState):
    """Handle ignition/key status messages for auto-shutdown and listen-only."""
    if msg.get('dlc', 0) < 1:
        logger.debug(f"Power status message too short (DLC: {msg.get('dlc', 'N/A')}). Skipping.")
        return
        
    try:
        data_hex = msg['data_hex']
        data_byte0 = int(data_hex[:2], 16)
        kls_status = data_byte0 & 0x01       # Bit 0: Key in Lock Sensor (1=IN, 0=PULLED)
        kl15_status = (data_byte0 >> 1) & 0x01 # Bit 1: Ignition KL15 (1=ON, 0=OFF)

        # Detect changes (Treat None as a change for initialization)
        kls_changed = (state.last_kls_status != kls_status)
        kl15_changed = (state.last_kl15_status != kl15_status)
        
        # Update State
        state.last_kls_status = kls_status
        state.last_kl15_status = kl15_status

        # Power Management Logic
        pw_mgmt = FEATURES.get('power_management', {})

        # Auto-Shutdown Logic
        if pw_mgmt.get('auto_shutdown', {}).get('enabled', False):
            auto_shutdown = pw_mgmt['auto_shutdown']
            trigger_config = auto_shutdown.get('trigger', 'ignition_off')
            trigger_event = False
            
            # Check for trigger conditions
            if trigger_config == 'ignition_off' and kl15_changed and kl15_status == 0:
                trigger_event = True
                logger.info("Ignition OFF detected (or initial state). Starting shutdown timer.")
            elif trigger_config == 'key_pulled' and kls_changed and kls_status == 0:
                trigger_event = True
                logger.info("Key PULLED detected (or initial state). Starting shutdown timer.")

            if trigger_event and not state.shutdown_pending:
                delay = auto_shutdown.get('delay_seconds', CONFIG['shutdown_delay'])
                logger.info(f"Starting {delay}s shutdown timer due to '{trigger_config}' trigger.")
                state.shutdown_pending = True
                state.shutdown_trigger_timestamp = time.time()
                # Store the current delay in the state to allow individual feature delays
                state._current_shutdown_delay = delay
                
            # Cancel shutdown if ignition/key comes back ON/IN
            elif state.shutdown_pending:
                if (trigger_config == 'ignition_off' and kl15_changed and kl15_status == 1) or \
                   (trigger_config == 'key_pulled' and kls_changed and kls_status == 1):
                    logger.info("Ignition ON or Key INSERTED detected. Cancelling pending shutdown.")
                    state.shutdown_pending = False
                    state.shutdown_trigger_timestamp = None

        # --- Publish Power Status (Ignition / Key) ---
        if state.zmq_pub:
            try:
                payload = {
                    'kl15': bool(kl15_status), 
                    'kls': bool(kls_status), 
                    'timestamp': time.time()
                }
                state.zmq_pub.send_multipart([b'POWER_STATUS', json.dumps(payload).encode()])
            except Exception as e:
                logger.error(f"Failed to publish POWER_STATUS: {e}")

        # Listen-Only Mode Logic
        if pw_mgmt.get('listen_only_mode', {}).get('enabled', False):
            listen_only_cfg = pw_mgmt['listen_only_mode']
            delay = listen_only_cfg.get('delay_seconds', 0)
            
            if kl15_changed:
                if kl15_status == 0: # Ignition OFF
                    if delay > 0:
                        if not state.listen_only_pending and not state.can_listen_only:
                            logger.info(f"Ignition OFF detected (or initial state). Starting {delay}s listen-only delay.")
                            state.listen_only_pending = True
                            state.listen_only_trigger_timestamp = time.time()
                            state.desired_listen_only = False
                    else:
                        logger.info("Ignition OFF detected. Queuing immediate listen-only transition.")
                        state.desired_listen_only = True
                        state.listen_only_pending = False
                        state.listen_only_trigger_timestamp = None
                            
                elif kl15_status == 1: # Ignition ON
                    if state.listen_only_pending:
                        logger.info("Ignition ON detected. Cancelling pending listen-only transition.")
                        state.listen_only_pending = False
                        state.listen_only_trigger_timestamp = None
                    state.desired_listen_only = False
                    if state.can_listen_only:
                        logger.info("Ignition ON detected. Queuing return to normal CAN mode.")
                
    except (IndexError, ValueError) as e:
        logger.warning(f"Could not parse power status message (data_hex: {msg.get('data_hex', 'N/A')}): {e}")

# --- GPIO Shutdown Monitor ---
class GpioShutdownMonitor:
    def __init__(self, pin, active_low=True):
        self.pin = pin
        self.active_low = active_low
        self.shutdown_triggered = False
        self.button = None
        
        if GPIO_AVAILABLE:
            # gpiozero.Button handles pull-up/down logic based on active_state/pull_up.
            # If active_low is True: pull_up=True, active_state=False (default behavior of Button).
            # If active_low is False: pull_up=False, active_state=True.
            
            try:
                # Button(pin, pull_up=None, active_state=..., bounce_time=None)
                # pull_up=None disables internal resistors (floating).
                # active_state=False means active Low. active_state=True means active High.
                target_active_state = False if active_low else True
                
                self.button = Button(pin, pull_up=None, active_state=target_active_state, bounce_time=0.1)
                logger.info(f"GPIO Shutdown Monitor initialized on pin {pin} (Active Low: {active_low}) with NO internal resistors.")
                
                # Verify initial state
                initial_state = "PRESSED" if self.button.is_pressed else "RELEASED"
                logger.info(f"DEBUG: Initial GPIO {self.pin} State: {initial_state}")
                
            except Exception as e:
                logger.error(f"Failed to initialize gpiozero Button on pin {pin}: {e}")
        else:
            logger.error("CRITICAL: gpiozero library not found but gpio_shutdown is ENABLED. Feature will NOT work.")

    def is_pressed(self):
        if not self.button: return False
        return self.button.is_pressed

    def check(self):
        """Original check logic for immediate triggers (legacy/compatibility)."""
        if not self.button or self.shutdown_triggered: return False
        
        if self.button.is_pressed:
            logger.info("GPIO Shutdown Monitor triggered!")
            self.shutdown_triggered = True
            return True
        return False

# --- Async Tasks ---
async def send_periodic_messages_task(state: AppState):
    logger.info("Periodic sender task started.")
    while RUNNING:
        try:
            if (
                FEATURES.get('tv_simulation', {}).get('enabled')
                and not state.can_listen_only
                and not state.desired_listen_only
                and not state.listen_only_transition_in_progress
            ):
                send_can_message(CONFIG['can_ids']['tv_presence'], "0912300000000000")
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in periodic sender task: {e}", exc_info=True)
            await asyncio.sleep(5)
    logger.info("Periodic sender task finished.")

async def listen_for_can_messages_task(state: AppState):
    logger.info("ZMQ listener task started.")
    sub_stream = None
    try:
        sub_stream = await aiozmq.create_zmq_stream(
            zmq.SUB,
            connect=CONFIG['zmq_publish_address']
        )
        
        # Subscribe to relevant topics
        time_topic = f"CAN_{CONFIG['can_ids']['time_data']:03X}"
        power_topic = f"CAN_{CONFIG['can_ids']['ignition_status']:03X}"
        
        if FEATURES.get('time_sync', {}).get('enabled', False):
            sub_stream.transport.subscribe(time_topic.encode('utf-8'))
            logger.info(f"Subscribing to time sync topic: {time_topic}")
            
        # Always subscribe to power status (Ignition/Key) because other services (e.g., dis_service, tp2_worker) rely on POWER_STATUS
        sub_stream.transport.subscribe(power_topic.encode('utf-8'))
        logger.info(f"Subscribing to power status topic: {power_topic}")

        while RUNNING:
            msg = await sub_stream.read()
            if len(msg) < 2:
                logger.warning(f"Received incomplete message: {msg}")
                continue
            topic_bytes, msg_bytes = msg
            try:
                topic = topic_bytes.decode('utf-8')
                msg_dict = json.loads(msg_bytes.decode('utf-8'))
                can_id = msg_dict.get('arbitration_id')
                if can_id is None and topic.startswith("CAN_"):
                    can_id = int(topic[4:], 16)
                if can_id is None:
                    logger.warning(f"Received CAN message without arbitration ID on topic '{topic}'.")
                    continue
                data_hex = msg_dict.get('data_hex', '')
                dlc = msg_dict.get('dlc', 0)
                if len(data_hex) < dlc * 2:
                    logger.warning(f"Received malformed CAN payload for ID={can_id:03X}: dlc={dlc}, data_hex='{data_hex}'")
                    continue
                
                logger.debug(f"Received CAN message ID={can_id:03X}: {msg_dict}")
                
                # Dispatch to handlers
                if can_id == CONFIG['can_ids']['time_data']:
                    await handle_time_data_message(msg_dict, state)
                elif can_id == CONFIG['can_ids']['ignition_status']:
                    handle_power_status_message(msg_dict, state)
                    
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode JSON from message: {msg_bytes[:100]}... ({e})")
            
    except asyncio.CancelledError:
        logger.info("ZMQ listener task was cancelled.")
    except Exception as e:
        logger.error(f"Critical error in ZMQ listener task setup or loop: {e}", exc_info=True)
    finally:
        if sub_stream:
            sub_stream.close()
        logger.info("ZMQ listener task finished.")

async def shutdown_monitor_task(state: AppState):
    """Monitor shutdown conditions periodically."""
    global RUNNING
    
    gpio_monitor = None
    try:
        pw_mgmt = FEATURES.get('power_management', {})
        if pw_mgmt.get('gpio_shutdown', {}).get('enabled', False):
             gpio_shutdown = pw_mgmt['gpio_shutdown']
             gpio_monitor = GpioShutdownMonitor(
                 gpio_shutdown.get('pin', 26),
                 gpio_shutdown.get('active_low', True)
             )
    except Exception as e:
        logger.error(f"Failed to initialize GPIO Shutdown Monitor: {e}", exc_info=True)

    while RUNNING:
        try:
            pw_mgmt = FEATURES.get('power_management', {})
            now = time.time()
            
            # 1. Check existing auto_shutdown logic
            if await state.check_shutdown_condition():
                RUNNING = False
                break
            
            # 2. Check Listen-Only delay countdown
            if state.listen_only_pending and state.listen_only_trigger_timestamp:
                delay = pw_mgmt.get('listen_only_mode', {}).get('delay_seconds', 0)
                if now - state.listen_only_trigger_timestamp >= delay:
                    logger.info(f"Listen-only delay ({delay}s) reached. Queuing listen-only mode.")
                    state.desired_listen_only = True
                    state.listen_only_pending = False
                    state.listen_only_trigger_timestamp = None

            # 2b. Reconcile actual CAN mode with desired mode.
            if state.can_listen_only != state.desired_listen_only and not state.listen_only_transition_in_progress:
                state.listen_only_transition_in_progress = True
                target_mode = state.desired_listen_only
                try:
                    if await set_listen_only_async(target_mode):
                        state.can_listen_only = target_mode
                    else:
                        logger.warning(
                            "CAN mode transition to %s failed. Will retry.",
                            "listen-only" if target_mode else "normal"
                        )
                finally:
                    state.listen_only_transition_in_progress = False
            
            # 3. Check GPIO shutdown (with delay and cancellation)
            if gpio_monitor:
                gpio_cfg = pw_mgmt.get('gpio_shutdown', {})
                delay = gpio_cfg.get('delay_seconds', 0)
                is_pressed = gpio_monitor.is_pressed()
                
                if is_pressed:
                    if not state.gpio_shutdown_pending:
                        if delay > 0:
                            logger.info(f"GPIO Shutdown trigger detected. Starting {delay}s delay.")
                            state.gpio_shutdown_pending = True
                            state.gpio_shutdown_trigger_timestamp = now
                        else:
                            logger.info("GPIO Shutdown trigger detected. Shutting down system NOW (delay=0).")
                            if await execute_system_command_async(["sudo", "shutdown", "-h", "now"]):
                                RUNNING = False
                                break
                    else:
                        # Pending - check if time reached
                        if state.gpio_shutdown_trigger_timestamp and (now - state.gpio_shutdown_trigger_timestamp >= delay):
                            logger.info(f"GPIO Shutdown delay ({delay}s) reached. Shutting down system NOW.")
                            if await execute_system_command_async(["sudo", "shutdown", "-h", "now"]):
                                RUNNING = False
                                break
                else:
                    # Not pressed - cancel pending if any
                    if state.gpio_shutdown_pending:
                        logger.info("GPIO button released. Cancelling pending GPIO shutdown.")
                        state.gpio_shutdown_pending = False
                        state.gpio_shutdown_trigger_timestamp = None

            await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"Error in shutdown monitor task: {e}")
            await asyncio.sleep(5)

# --- Signal Handling and Main Loop ---
def setup_signal_handlers(loop):
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: shutdown_handler(s))
    loop.add_signal_handler(signal.SIGHUP, lambda s=signal.SIGHUP: reload_config_handler(s))

def shutdown_handler(sig):
    global RUNNING
    if RUNNING: logger.info(f"Shutdown signal {sig.name} received. Stopping..."); RUNNING = False

def reload_config_handler(sig):
    global RELOAD_CONFIG
    logger.info("SIGHUP signal received. Flagging for configuration reload."); RELOAD_CONFIG = True

async def start_runtime(state: AppState):
    context = zmq.Context()
    state.zmq_pub = context.socket(zmq.PUB)
    try:
        state.zmq_pub.bind(CONFIG['zmq_base_publish_address'])
        logger.info(f"ZMQ Publisher bound to {CONFIG['zmq_base_publish_address']}")
    except Exception as e:
        if not state.zmq_pub.closed:
            state.zmq_pub.close()
        context.term()
        raise RuntimeError(f"Failed to bind ZMQ publisher: {e}") from e

    tasks = [
        asyncio.create_task(listen_for_can_messages_task(state)),
        asyncio.create_task(send_periodic_messages_task(state)),
        asyncio.create_task(shutdown_monitor_task(state))
    ]
    return context, tasks

async def stop_runtime(state: AppState, context: zmq.Context, tasks):
    if state.time_sync_task and not state.time_sync_task.done():
        state.time_sync_task.cancel()
    for task in tasks:
        task.cancel()
    pending_tasks = list(tasks)
    if state.time_sync_task:
        pending_tasks.append(state.time_sync_task)
    await asyncio.gather(*pending_tasks, return_exceptions=True)
    if state.zmq_pub and not state.zmq_pub.closed:
        state.zmq_pub.close()
    context.term()

async def main_async():
    global RELOAD_CONFIG, RUNNING
    state = AppState()
    pub_context, tasks = await start_runtime(state)
    
    while RUNNING:
        if RELOAD_CONFIG:
            logger.info("Reloading configuration...")
            if load_and_initialize_config(): 
                RELOAD_CONFIG = False
                if ZMQ_PUSH_SOCKET and not ZMQ_PUSH_SOCKET.closed:
                    ZMQ_PUSH_SOCKET.close()
                if not initialize_zmq_sender():
                    logger.error("Failed to reconnect ZMQ sender after reload. Stopping service.")
                    RUNNING = False
                    break
                preserved_can_listen_only = state.can_listen_only
                preserved_desired_listen_only = state.desired_listen_only
                await stop_runtime(state, pub_context, tasks)
                state = AppState()
                state.can_listen_only = preserved_can_listen_only
                state.desired_listen_only = preserved_desired_listen_only
                pub_context, tasks = await start_runtime(state)
                logger.info("Configuration reload complete.")
            else:
                logger.error("Config reload failed!")
        
        await asyncio.sleep(1)

    await stop_runtime(state, pub_context, tasks)

def main():
    logger.info("Starting CAN Base Function service...")
    if not load_and_initialize_config(): sys.exit(1)
    if not initialize_zmq_sender(): sys.exit(1)

    loop = asyncio.get_event_loop()
    setup_signal_handlers(loop)
    
    try:
        logger.info("--- Service is running ---")
        loop.run_until_complete(main_async())
    finally:
        logger.info("Main loop terminated. Closing ZeroMQ resources.")
        if ZMQ_PUSH_SOCKET and not ZMQ_PUSH_SOCKET.closed: ZMQ_PUSH_SOCKET.close()
        if ZMQ_CONTEXT and not ZMQ_CONTEXT.closed: ZMQ_CONTEXT.term()
        loop.close()
        logger.info("CAN Base Function service has finished.")

if __name__ == '__main__':
    main()
