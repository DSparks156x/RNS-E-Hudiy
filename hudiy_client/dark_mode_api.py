#!/usr/bin/env python3
"""
Hudiy Dark Mode Service

This service listens for CAN bus messages (via ZMQ from can_handler.py)
to automatically toggle the Hudiy day/night mode and optionally Android Auto.

The target mode follows the latest light-status frame (features.initial_mode
until one arrives). It is sent as soon as Hudiy's API accepts a connection,
re-asserted shortly after, and re-sent whenever Hudiy comes back after being
gone, so Hudiy never keeps its own saved theme.

sync_android_auto
true: bind AA settings to script
false: bin AA settings to hudiy option

It reads /home/pi/config.json to check if the feature is enabled.
"""

import socket
import struct
import zmq
import json
import logging
import signal
import sys
import os
import time

# --- Setup Logging ---
LOG_FILE = '/var/log/rnse_control/dark_mode_service.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- Add API Files Path ---
api_path = os.path.dirname(os.path.abspath(__file__)) + '/api_files/common'
sys.path.insert(0, api_path)
try:
    # Api_pb2 regenerated/updated to include the new 1.1 definitions
    from Api_pb2 import *
except ImportError:
    logger.critical(f"FATAL: Could not import Api_pb2.")
    logger.critical(f"Looked in: {api_path}")
    sys.exit(1)


# --- Hudiy API Link ---
HUDIY_ADDRESS = ('localhost', 44405)
CONNECT_TIMEOUT = 0.3      # localhost: refused is instant, this only caps a stall
SEND_TIMEOUT = 0.3
RETRY_FAST = 0.5           # while Hudiy is starting (boot, restart, update)
RETRY_SLOW = 2.0           # once it has been gone for FAST_RETRY_WINDOW
FAST_RETRY_WINDOW = 30.0
REASSERT_DELAYS = (2.0, 5.0)  # Hudiy may apply its saved theme after our first send
FIRST_FRAME_WAIT = 1.0     # give 0x635 a moment before falling back to initial_mode
HEADER = struct.Struct('<III')  # payload size, message id, flags


def mode_name(enabled):
    return 'night' if enabled else 'day'


class HudiyLink:
    """Holds one connection to the Hudiy API and keeps its theme on `desired`.

    Hudiy has no dark-mode status event, so the connection itself is the
    signal: while it is open Hudiy is up; when it closes Hudiy has gone
    (crash, update, quit) and the mode is re-sent on the next connect. Never
    blocks for longer than CONNECT_TIMEOUT / SEND_TIMEOUT.
    """

    def __init__(self, desired, sync_android_auto=False, address=None, clock=time.monotonic):
        self.desired = desired
        self.sync_android_auto = sync_android_auto
        self.address = address or HUDIY_ADDRESS
        self.clock = clock
        self.sock = None
        self.ever_connected = False
        self.reassert_at = []
        self._buffer = b''
        now = clock()
        self.next_attempt = now
        self.down_since = now

    @property
    def connected(self):
        return self.sock is not None

    def set_desired(self, enabled):
        if enabled == self.desired:
            return
        self.desired = enabled
        logger.info(f"Light status changed: target {mode_name(enabled)}.")
        if self.connected:
            self._send_mode('mode change')

    def hold_until(self, when):
        """Delay the first connect attempt (used to wait for the first CAN frame)."""
        self.next_attempt = max(self.next_attempt, when)

    def release_hold(self):
        """First CAN frame is in: no need to keep waiting for it."""
        if not self.ever_connected:
            self.next_attempt = min(self.next_attempt, self.clock())

    def seconds_until_due(self):
        if not self.connected:
            due = self.next_attempt
        elif self.reassert_at:
            due = self.reassert_at[0]
        else:
            return None
        return max(0.0, due - self.clock())

    def tick(self):
        now = self.clock()
        if not self.connected:
            if now >= self.next_attempt:
                self._connect(now)
            return
        if self.reassert_at and now >= self.reassert_at[0]:
            self.reassert_at.pop(0)
            self._send_mode('re-assert')

    def _connect(self, now):
        sock = None
        try:
            sock = socket.create_connection(self.address, timeout=CONNECT_TIMEOUT)
            sock.settimeout(SEND_TIMEOUT)
            hello = HelloRequest()
            hello.name = "DarkModeService"
            hello.api_version.major = 1
            hello.api_version.minor = 1
            self._frame(sock, MESSAGE_HELLO_REQUEST, hello)
        except OSError as e:
            if sock is not None:
                sock.close()
            delay = RETRY_FAST if now - self.down_since < FAST_RETRY_WINDOW else RETRY_SLOW
            self.next_attempt = now + delay
            logger.debug(f"Hudiy API not reachable ({e}); retry in {delay:.1f} s.")
            return
        self.sock = sock
        self._buffer = b''
        what = 'reconnected' if self.ever_connected else 'connected'
        self.ever_connected = True
        logger.info(f"Hudiy API {what}; setting {mode_name(self.desired)}.")
        if self._send_mode('connect'):
            self.reassert_at = [now + d for d in REASSERT_DELAYS]

    def _send_mode(self, reason):
        enabled = self.desired
        try:
            dark = SetDarkMode()
            dark.enabled = enabled
            self._frame(self.sock, MESSAGE_SET_DARK_MODE, dark)
            # Only when asked: it overrides Hudiy's "Common" AA setting.
            if self.sync_android_auto:
                aa = SetAndroidAutoDayNightMode()
                aa.mode = SetAndroidAutoDayNightMode.NIGHT if enabled else SetAndroidAutoDayNightMode.DAY
                self._frame(self.sock, MESSAGE_SET_ANDROID_AUTO_DAY_NIGHT_MODE, aa)
        except OSError as e:
            self.drop(f"send failed: {e}")
            return False
        log = logger.debug if reason == 're-assert' else logger.info
        log(f"Sent {mode_name(enabled)} ({reason}, AA sync={self.sync_android_auto}).")
        return True

    @staticmethod
    def _frame(sock, message_id, message):
        data = message.SerializeToString()
        sock.sendall(HEADER.pack(len(data), message_id, 0) + data)

    def on_readable(self):
        """Drain what Hudiy sent: answer PING, notice BYEBYE or a closed socket."""
        try:
            chunk = self.sock.recv(4096)
        except (BlockingIOError, socket.timeout):
            return
        except OSError as e:
            self.drop(f"receive failed: {e}")
            return
        if not chunk:
            self.drop("closed by Hudiy")
            return
        self._buffer += chunk
        while len(self._buffer) >= HEADER.size:
            size, message_id, _flags = HEADER.unpack_from(self._buffer)
            if len(self._buffer) < HEADER.size + size:
                break
            self._buffer = self._buffer[HEADER.size + size:]
            if message_id == MESSAGE_PING:
                try:
                    self.sock.sendall(HEADER.pack(0, MESSAGE_PONG, 0))
                except OSError as e:
                    self.drop(f"pong failed: {e}")
                    return
            elif message_id == MESSAGE_BYEBYE:
                self.drop("Hudiy said bye")
                return

    def drop(self, reason):
        if self.sock is None:
            return
        try:
            self.sock.close()
        except OSError:
            pass
        self.sock = None
        self.reassert_at = []
        now = self.clock()
        self.down_since = now
        self.next_attempt = now + RETRY_FAST
        logger.info(f"Hudiy API connection lost ({reason}); will re-send mode when it is back.")

    def close(self):
        if self.sock is not None:
            try:
                self.sock.sendall(HEADER.pack(0, MESSAGE_BYEBYE, 0))
            except OSError:
                pass
            self.sock.close()
            self.sock = None


def light_is_night(data_hex):
    """0x635 byte 1: any non-zero dimmer value means headlights on (night)."""
    return int(data_hex[2:4], 16) > 0

# --- Config Loading Function ---
def load_config(config_path='/home/pi/config.json'):
    """Loads the main config file to get all required settings."""
    logger.info(f"Loading configuration from {config_path}...")
    try:
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        
        _interfaces = config_data.get('interfaces', {})
        _zmq = _interfaces.get('zmq', {})
        _can_ids = config_data.get('can_ids', {})
        _features = config_data.get('features', {})
        
        config = {
            'zmq_publish_address': _zmq.get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc'),
            'light_status_can_id': _can_ids.get('light_status', '0x271'),
            'day_night_mode': _features.get('day_night_mode', False),
            'initial_mode': _features.get('initial_mode', 'night'),
            'sync_android_auto': _features.get('sync_android_auto', False) 
        }

        if not config['zmq_publish_address']:
            logger.critical("FATAL: 'zmq_publish_address' not found in config.json.")
            return None
        if not config['light_status_can_id']:
            logger.critical("FATAL: 'light_status_can_id' not found in config.json.")
            return None

        logger.info("Configuration loaded successfully.")
        return config
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.critical(f"FATAL: Could not load or parse config.json: {e}")
        return None

# --- Signal Handling ---
RUNNING = True

def setup_signal_handlers():
    """Sets up handlers for graceful shutdown."""
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

def shutdown_handler(signum, frame):
    """Flags the application to exit the main loop."""
    global RUNNING
    if RUNNING:
        logger.info(f"Shutdown signal {signum} received. Cleaning up...")
        RUNNING = False

def pause(seconds):
    """Sleep in short slices so a shutdown signal is honoured within 0.1 s."""
    deadline = time.monotonic() + seconds
    while RUNNING and time.monotonic() < deadline:
        time.sleep(0.1)

# --- Main Service Loop ---
def open_subscriber(context, zmq_address, can_topic):
    sub = context.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(zmq_address)
    sub.setsockopt_string(zmq.SUBSCRIBE, can_topic)
    return sub


def handle_frame(link, payload, last_data):
    """Apply one 0x635 ZMQ message; returns the data_hex it carried."""
    data_hex = json.loads(payload.decode('utf-8')).get('data_hex')
    if not data_hex or data_hex == last_data:
        return last_data
    try:
        night = light_is_night(data_hex)
    except (IndexError, ValueError) as e:
        logger.error(f"Could not parse light value from data_hex '{data_hex}'. Error: {e}")
        return data_hex
    link.set_desired(night)
    return data_hex


def run(link, sub, reopen=None):
    """Serve until RUNNING is cleared. Every wait is at most 200 ms."""
    last_data = None
    while RUNNING:
        try:
            link.tick()
            poller = zmq.Poller()
            poller.register(sub, zmq.POLLIN)
            hudiy_sock = link.sock
            if hudiy_sock is not None:
                poller.register(hudiy_sock, zmq.POLLIN)
            timeout = 200
            due = link.seconds_until_due()
            if due is not None:
                timeout = min(timeout, max(10, int(due * 1000) + 1))
            events = dict(poller.poll(timeout))
            if hudiy_sock is not None and hudiy_sock in events:
                link.on_readable()
            if sub in events:
                _topic, payload = sub.recv_multipart()
                first = last_data is None
                last_data = handle_frame(link, payload, last_data)
                if first and last_data is not None:
                    logger.info(f"First light-status frame: {last_data} -> {mode_name(link.desired)}.")
                    link.release_hold()
        except zmq.ZMQError as e:
            if e.errno == zmq.ETERM:
                logger.info("ZMQ context terminated. Shutting down.")
                break
            logger.error(f"ZMQ Error: {e}. Reconnecting...")
            sub.close()
            pause(5)
            if reopen is None:
                break
            sub = reopen()
        except KeyboardInterrupt:
            logger.info("Shutdown signal received. Exiting...")
            break
        except Exception as e:
            logger.critical(f"An unexpected error occurred in main loop: {e}", exc_info=True)
            pause(10)
    return sub


def main():
    """Main service loop."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    config = load_config()
    if not config:
        sys.exit(1)

    if not config.get('day_night_mode'):
        logger.info("Day/Night mode feature is disabled in config.json. Exiting.")
        sys.exit(0)

    setup_signal_handlers()

    initial_mode_str = config.get('initial_mode', 'night').lower()
    sync_aa = config.get('sync_android_auto', False)
    logger.info(f"Day/Night feature enabled. Default: {initial_mode_str}. Sync AA: {sync_aa}")

    # initial_mode is only the fallback until the first 0x635 frame.
    link = HudiyLink(initial_mode_str == 'night', sync_android_auto=sync_aa)
    link.hold_until(time.monotonic() + FIRST_FRAME_WAIT)

    zmq_address = config['zmq_publish_address']
    can_id_str = config['light_status_can_id'].replace('0x', '').upper()
    can_topic = f"CAN_{can_id_str}"

    context = zmq.Context()
    logger.info(f"Connecting to ZMQ publisher at {zmq_address}...")
    try:
        sub = open_subscriber(context, zmq_address, can_topic)
    except zmq.ZMQError as e:
        logger.critical(f"Failed to connect ZMQ socket: {e}. Is can_handler.py running?")
        sys.exit(1)
    logger.info(f"Subscribed to ZMQ topic: {can_topic}. Waiting for CAN messages and Hudiy...")

    sub = run(link, sub, reopen=lambda: open_subscriber(context, zmq_address, can_topic))

    link.close()
    sub.close()
    context.term()
    logger.info("Day/Night service stopped.")

if __name__ == '__main__':
    main()
