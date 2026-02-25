import zmq
import json
import time
import logging
from typing import Dict, Any

from smart_driver import SmartDriver
from screens.nav import NavScreen
from screens.now_playing import NowPlayingScreen
from screens.car_info import CarInfoScreen
from screens.tetris import TetrisScreen

logger = logging.getLogger(__name__)

class AppManager:
    def __init__(self, config_path='/home/pi/config.json'):
        try:
            with open(config_path) as f:
                self.config = json.load(f)
        except Exception as e:
            logger.critical(f"Failed to load config: {e}")
            exit(1)

        # Initialize ZMQ context and poller
        self.context = zmq.Context()
        self.poller = zmq.Poller()

        # Connect to CAN Stream (for steering wheel buttons and car info)
        self.can_sub = self.context.socket(zmq.SUB)
        self.can_sub.connect(self.config['zmq']['can_raw_stream'])
        # Subscribe to steering wheel buttons
        self.can_sub.subscribe(b"CAN_0x2C1")
        # Subscribe to Car Info topics (if known, or we just listen via the car_info screen later)
        self.can_sub.subscribe(b"CAN_") # Catch-all for now
        self.poller.register(self.can_sub, zmq.POLLIN)

        # Connect to Hudiy API Stream
        self.hudiy_sub = self.context.socket(zmq.SUB)
        self.hudiy_sub.connect(self.config['zmq']['metric_stream'])
        for topic in [b'HUDIY_MEDIA', b'HUDIY_NAV', b'HUDIY_PHONE', b'HUDIY_NAV_STATUS']:
            self.hudiy_sub.subscribe(topic)
        self.poller.register(self.hudiy_sub, zmq.POLLIN)

        # Connect to Ignition Power Status
        self.ignition_sub = self.context.socket(zmq.SUB)
        ignition_addr = self.config['zmq'].get('system_events', self.config['zmq']['can_raw_stream'])
        self.ignition_sub.connect(ignition_addr)
        self.ignition_sub.subscribe(b"POWER_STATUS")
        self.poller.register(self.ignition_sub, zmq.POLLIN)

        # Drivers
        self.driver_split = SmartDriver(self.config, claim_full_screen=False)
        self.driver_full = SmartDriver(self.config, claim_full_screen=True)
        # We start with the split driver (with divider)
        self.active_driver = self.driver_split

        # Screens (Placeholder init)
        self.screens = {}
        self.active_screen_name = "now_playing"
        
        self.ignition_on = False

    def setup_screens(self):
        self.screens["nav"] = NavScreen()
        self.screens["now_playing"] = NowPlayingScreen()
        self.screens["car_info"] = CarInfoScreen()
        self.screens["tetris"] = TetrisScreen()
        self.screen_order = ["now_playing", "nav", "car_info", "tetris"]

    def _switch_screen(self, direction: int):
        idx = self.screen_order.index(self.active_screen_name)
        new_idx = (idx + direction) % len(self.screen_order)
        self.active_screen_name = self.screen_order[new_idx]
        
        # Determine if we need to switch the underlying DDP driver
        needs_full = self.screens[self.active_screen_name].needs_full_screen
        
        # Stop current session and swap active driver
        self.active_driver.stop_session()
        self.active_driver = self.driver_full if needs_full else self.driver_split
        logger.info(f"Switched to screen: {self.active_screen_name} (Full: {needs_full})")

    def run(self):
        logger.info("New DIS AppManager Started. Waiting for Ignition...")
        self.setup_screens()

        while True:
            try:
                # Polling
                socks = dict(self.poller.poll(10))

                # Handle Ignition
                if self.ignition_sub in socks:
                    while True:
                        try:
                            parts = self.ignition_sub.recv_multipart(flags=zmq.NOBLOCK)
                            if len(parts) == 2 and parts[0] == b'POWER_STATUS':
                                pwr = json.loads(parts[1])
                                new_ign = pwr.get('kl15', False)
                                if new_ign != self.ignition_on:
                                    self.ignition_on = new_ign
                                    logger.info(f"Ignition Changed: {'ON' if new_ign else 'OFF'}")
                                    if not self.ignition_on:
                                        self.driver_split.stop_session()
                                        self.driver_full.stop_session()
                        except zmq.Again:
                            break

                if not self.ignition_on:
                    time.sleep(0.5)
                    continue

                # Session Management
                session_ready = self.active_driver.start_session()

                if not session_ready:
                    time.sleep(0.5)
                    continue

                # Handle Hudiy External Data
                if self.hudiy_sub in socks:
                    while True:
                        try:
                            parts = self.hudiy_sub.recv_multipart(flags=zmq.NOBLOCK)
                            if len(parts) == 2:
                                topic = parts[0]
                                data = json.loads(parts[1])
                                # Let active screen handle it
                                self.screens[self.active_screen_name].handle_hudiy_data(topic, data)
                                # Let inactive screens also stay updated (especially nav/now_playing)
                                for name, screen in self.screens.items():
                                    if name != self.active_screen_name:
                                        screen.handle_hudiy_data(topic, data)
                        except zmq.Again:
                            break
                            
                # Handle CAN data (buttons + engine/car info)
                if self.can_sub in socks:
                    while True:
                        try:
                            parts = self.can_sub.recv_multipart(flags=zmq.NOBLOCK)
                            if len(parts) == 2:
                                t_str = parts[0].decode()
                                payload = bytes.fromhex(json.loads(parts[1])['data_hex'])
                                self.screens[self.active_screen_name].handle_can_message(t_str, payload)
                                
                                # Process buttons from 0x2C1
                                if t_str in ["CAN_0x2C1", "CAN_705"] and len(payload) > 2:
                                    b = payload[2]
                                    if b & 0x20: # Up tap
                                        if self.active_screen_name == 'tetris':
                                            self.screens['tetris'].handle_button_press('up', 'tap')
                                        else:
                                            self._switch_screen(-1)
                                    elif b & 0x10: # Down tap
                                        if self.active_screen_name == 'tetris':
                                            self.screens['tetris'].handle_button_press('down', 'tap')
                                        else:
                                            self._switch_screen(1)
                                            
                                # Optional: map left/right to Tetris from RNSE CAN if active
                                # e.g. RNS-E wheel spinning or track arrows
                        except zmq.Again:
                            break

                # Render active screen
                elements = self.screens[self.active_screen_name].render()
                self.active_driver.render(elements)
                
                time.sleep(0.05)

            except Exception as e:
                logger.error(f"AppManager Loop Error: {e}")
                time.sleep(1)

if __name__ == "__main__":
    AppManager().run()
