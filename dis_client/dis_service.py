#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# - FIX: Added logic to clear line background only when transition requires it
#   (Red -> Black) to prevent ghosting without causing flicker.
# - FIX: Added 'clear_area' command for precise cleanup.
#
import zmq
import json
import time
import logging
from typing import List, Optional

try:
    from ddp_protocol import DDPProtocol, DDPState, DisMode, DDPError, DDPHandshakeError
except ImportError:
    print("Error: Could not import DDPProtocol. Make sure ddp_protocol.py is in the same directory.")
    exit(1)

try:
    from icons import audscii_trans, ICONS, BITMAPS 
except ImportError:
    print("Error: Could not import icons.py. Make sure it is in the same directory.")
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (DIS Svc) %(message)s')
logger = logging.getLogger(__name__)

class DisService:
    def __init__(self, config_path='/home/pi/config.json'):
        try:
            with open(config_path) as f:
                self.config = json.load(f)
        except FileNotFoundError:
            logger.critical(f"FATAL: config.json not found at {config_path}")
            exit(1)
        except Exception as e:
            logger.critical(f"FATAL: Could not load config.json: {e}")
            exit(1)
            
        try:
            self.ddp = DDPProtocol(self.config)
        except Exception as e:
            logger.critical(f"FATAL: Could not initialize DDPProtocol driver: {e}")
            exit(1)

        self.context = zmq.Context()
        self.draw_socket = self.context.socket(zmq.PULL)
        self.draw_socket.setsockopt(zmq.RCVHWM, 100) # Increased to match sender
        _zmq = self.config.get('interfaces', {}).get('zmq', {})
        try:
            self.draw_socket.bind(_zmq.get('dis_draw', 'ipc:///run/rnse_control/dis_draw.ipc'))
            logger.info(f"ZMQ command socket bound to {_zmq.get('dis_draw')}")
        except Exception as e:
            logger.critical(f"FATAL: Could not bind ZMQ socket: {e}")
            logger.critical("This often means the service is already running (Address already in use).")
            exit(1)
            
        self.poller = zmq.Poller()
        self.poller.register(self.draw_socket, zmq.POLLIN)

        _zmq = self.config.get('interfaces', {}).get('zmq', {})
        self.status_pub = self.context.socket(zmq.PUB)
        try:
            self.status_pub.bind(_zmq.get('dis_status', 'ipc:///run/rnse_control/dis_status.ipc'))
            logger.info("ZMQ status pub socket bound.")
        except Exception as e:
            logger.warning(f"Could not bind status pub socket: {e}")

        self.last_draw_time = 0.0
        self._screen_is_active = False
        self.inactivity_timeout_sec = 30.0 
        self.command_cache = {} 
        self.ENABLE_INACTIVITY_RELEASE = False

        # Default region: 'central'
        self.region_name = 'central'
        self.region_y_offset = 0x1B
        self.region_height = 0x30

    @property
    def screen_is_active(self):
        return self._screen_is_active

    @screen_is_active.setter
    def screen_is_active(self, value):
        if self._screen_is_active != value:
            self._screen_is_active = value

        if not self.ENABLE_INACTIVITY_RELEASE and value:
            logger.info("Inactivity auto-release is DISABLED (screen will stay claimed forever)")

    def parse_time(self, t: str) -> int:
        if not t: return 0
        parts = t.split(':')
        return sum(int(p) * (60 ** i) for i, p in enumerate(reversed(parts)))

    def translate_to_audscii(self, text: str) -> List[int]:
        return [audscii_trans[ord(c) % 256] for c in text]

    def claim_nav_screen(self):
        if self.ddp.state != DDPState.READY:
            logger.warning("Cannot claim screen, session not READY.")
            return False
        
        if self.region_name in ['full', 'top_centre']:
            claim_y = 0x00
            claim_h = 0x58
        else:
            claim_y = 0x1B
            claim_h = self.region_height # usually 0x30 or 0x3D
            
        if self.region_name in ['full', 'top_centre', 'centre_lower']:
            payload_busy  = [0x53, 0x88]
            payload_free  = [0x53, 0x0A]
            payload_ok    = [0x53, 0x8A]
        else:
            payload_busy  = [0x53, 0x84]
            payload_free  = [0x53, 0x05]
            payload_ok    = [0x53, 0x85]
            
        payload_claim = [0x52, 0x05, 0x82, 0x00, claim_y, 0x40, claim_h]
        payload_ready = [0x2E]
        payload_clear = [0x2F]
            
        if self.ddp.dis_mode == DisMode.RED:
            try:
                self.ddp.send_data_packet(payload_claim)
                data = self.ddp._recv_and_ack_data(1000)
                if not self.ddp.payload_is(data, payload_ok):
                    raise DDPHandshakeError(f"Claim Handshake 2/2 failed (wait 1x 53 85), got {data}")
            except DDPError as e:
                logger.error(f"Failed to claim screen (RED path): {e}")
                return False
        else:
            try:
                self.ddp.send_data_packet(payload_claim)
                data = self.ddp._recv_and_ack_data(1000)
                if self.ddp.payload_is(data, payload_ok):
                    self.screen_is_active = True
                    self.last_draw_time = time.time()
                    return True
                if not self.ddp.payload_is(data, payload_busy):
                    raise DDPHandshakeError(f"Claim Handshake 2/7 failed (wait 1x 53 84), got {data}")
                data = self.ddp._recv_and_ack_data(1000)
                if not self.ddp.payload_is(data, payload_free):
                    raise DDPHandshakeError(f"Claim Handshake 3/7 failed (wait 1x 53 05), got {data}")
                data = self.ddp._recv_and_ack_data(1000)
                if not self.ddp.payload_is(data, payload_ready):
                    raise DDPHandshakeError(f"Claim HandShak 4/7 failed (wait 1x 2E), got {data}")
                self.ddp.send_data_packet(payload_clear)
                self.ddp.send_data_packet(payload_claim)
                data = self.ddp._recv_and_ack_data(1000)
                if not self.ddp.payload_is(data, payload_ok):
                    logger.warning(f"Got non-standard status {data} after 2nd claim, but proceeding.")
            except DDPError as e:
                logger.error(f"Failed to claim screen (WHITE path): {e}")
                return False
            
        logger.info(f"Region Claim '{self.region_name}' handshake successful. Screen is active.")
        self.screen_is_active = True
        self.last_draw_time = time.time()
        return True

    def clear_screen_payload(self):
        logger.info(f"Queueing Region Clear for {self.region_name}")
        payload = [0x52, 0x05, 0x02, 0x00, self.region_y_offset, 0x40, self.region_height]
        if not self.ddp.send_ddp_frame(payload):
            logger.error("Failed to send clear payload.")

    def clear_area(self, x, y, w, h):
        """
        Explicitly clears a specific rectangle to BLACK.
        Used to erase artifacts or Red Highlights.
        """
        abs_y = y + self.region_y_offset
        # Flag 0x02: Clear(Bit 7=0), Clear(Bit 1=1), Black(Bit 0=0)
        payload = [0x52, 0x05, 0x02, x, abs_y, w, h]
        self.ddp.send_ddp_frame(payload)
        
        # Reset Window
        payload_reset = [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        self.ddp.send_ddp_frame(payload_reset)

    def get_text_payload(self, text: str, x: int, y: int, flags: int = 0x06) -> List[int]:
        chars = self.translate_to_audscii(text) 
        is_inverted = (flags & 0x80) != 0
        protocol_flags = flags & 0x7C 
        
        if is_inverted:
            abs_y = y + self.region_y_offset
            width, height = 64, 9
            payload = [0x52, 0x05, 0x03, x, abs_y, width, height]
            text_mode_bits = 0x00 
            final_text_flags = protocol_flags | text_mode_bits
            payload += [0x57, len(chars) + 3, final_text_flags, 0, 0] + chars
            payload += [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
            return payload
        else:
            text_mode_bits = 0x02 # Opaque + Normal
            final_text_flags = protocol_flags | text_mode_bits
            return [0x57, len(chars) + 3, final_text_flags, x, y] + chars

    def write_text(self, text: str, x: int, y: int, flags: int = 0x06):
        payload = self.get_text_payload(text, x, y, flags)
        self.ddp.send_ddp_frame(payload)

    def get_bitmap_payload(self, x: int, y: int, icon_name: str, mode_flag: int = 0x02) -> List[int]:
        if not icon_name or icon_name not in BITMAPS:
            return []
        icon = BITMAPS[icon_name]
        w, h, data = icon['w'], icon['h'], icon['data']
        abs_y = y + self.region_y_offset
        payload = [0x52, 0x05, 0x00, x, abs_y, w, h]
        bytes_per_row = (w + 7) // 8
        rows_per_chunk = 37 // bytes_per_row
        if rows_per_chunk < 1: rows_per_chunk = 1
        for i in range(0, h, rows_per_chunk):
            start_byte = i * bytes_per_row
            rows_to_send = min(rows_per_chunk, h - i)
            chunk_data = data[start_byte:start_byte + (rows_to_send * bytes_per_row)]
            payload += [0x55, len(chunk_data) + 3, mode_flag, 0x00, i] + chunk_data
        payload += [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        return payload

    def draw_bitmap(self, x: int, y: int, icon_name: str, mode_flag: int = 0x02):
        payload = self.get_bitmap_payload(x, y, icon_name, mode_flag)
        if payload:
            self.ddp.send_ddp_frame(payload)

    def get_line_payload(self, x: int, y: int, length: int, vertical: bool = True) -> List[int]:
        orientation = 0x10 if vertical else 0x20
        abs_y = y + self.region_y_offset
        return [0x63, 0x04, orientation, x, abs_y, length]

    def draw_line(self, x: int, y: int, length: int, vertical: bool = True):
        payload = self.get_line_payload(x, y, length, vertical)
        self.ddp.send_ddp_frame(payload)

    def get_clear_area_payload(self, x: int, y: int, w: int, h: int) -> List[int]:
        abs_y = y + self.region_y_offset
        payload = [0x52, 0x05, 0x02, x, abs_y, w, h]
        payload += [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        return payload

    def clear_area(self, x, y, w, h):
        payload = self.get_clear_area_payload(x, y, w, h)
        self.ddp.send_ddp_frame(payload)

    def commit_frame(self):
        payload = [0x39]
        if not self.ddp.send_ddp_frame(payload):
             logger.error("Failed to send commit packet.")

    def clear_screen(self):
        logger.info("Executing full clear_screen command...")
        payload_clear = [0x52, 0x05, 0x02, 0x00, self.region_y_offset, 0x40, self.region_height]
        payload_commit = [0x39]
        if not self.ddp.send_ddp_frame(payload_clear + payload_commit):
            logger.error("clear_screen: Failed to send frame.")
            
    def set_source_radio(self):
        self.ddp.send_can(0x661, [0x00] * 8)
        logger.info("Source: Radio")

    def handle_redraw(self):
        if not self.command_cache: return
        logger.info("Restoring screen content after interruption...")
        self.clear_screen_payload() 
        sorted_cmds = sorted(self.command_cache.values(), key=lambda item: (item.get('y',0), item.get('x',0)))
        
        for cmd in sorted_cmds:
            c = cmd.get('command')
            if c == 'draw_text':
                self.write_text(cmd.get('text',''), cmd.get('x',0), cmd.get('y',0), cmd.get('flags', 0x06))
            elif c == 'draw_bitmap':
                self.draw_bitmap(cmd.get('x',0), cmd.get('y',0), cmd.get('icon_name'))
            elif c == 'draw_line':
                self.draw_line(cmd.get('x',0), cmd.get('y',0), cmd.get('length',0), cmd.get('vertical', True))
        
        self.commit_frame()

    def run(self):
        # --- LISTEN FOR IGNITION STATUS ---
        self.ignition_sub = self.context.socket(zmq.SUB)
        # Connect to Base Function publisher for Ignition status
        _zmq = self.config.get('interfaces', {}).get('zmq', {})
        ignition_addr = _zmq.get('system_events', _zmq.get('can_raw_stream'))
        self.ignition_sub.connect(ignition_addr)
        self.ignition_sub.subscribe(b"POWER_STATUS")
        self.poller.register(self.ignition_sub, zmq.POLLIN)
        self.ignition_on = False # Start assuming OFF
        
        logger.info("DIS Service Started. Entering ignition-aware loop.")
        
        while True:
            try:
                # --- CHECK IGNITION STATUS ---
                socks = dict(self.poller.poll(10)) # Short poll (10ms)
                if self.ignition_sub in socks:
                    try:
                        while True: # Drain queue
                            parts = self.ignition_sub.recv_multipart(flags=zmq.NOBLOCK)
                            if len(parts) == 2 and parts[0] == b'POWER_STATUS':
                                pwr = json.loads(parts[1])
                                new_ign = pwr.get('kl15', False)
                                
                                if new_ign != self.ignition_on:
                                    self.ignition_on = new_ign
                                    logger.info(f"Ignition Changed: {'ON' if new_ign else 'OFF'}")
                                    if not self.ignition_on:
                                        logger.info("Ignition OFF -> Stopping DIS Session")
                                        if hasattr(self, 'ddp'):
                                            self.ddp._set_state(DDPState.DISCONNECTED)
                                        self.screen_is_active = False
                                        try:
                                            self.status_pub.send_string("DIS_STATE DISCONNECTED", flags=zmq.NOBLOCK)
                                        except: pass
                    except zmq.Again: pass
                    except Exception as e: logger.error(f"Ignition check error: {e}")

                if not self.ignition_on:
                    # IGNITION OFF - STANDBY MODE
                    time.sleep(0.5)
                    continue

                # --- NORMAL OPERATION (IGNITION ON) ---
                if self.ddp.state == DDPState.DISCONNECTED:
                    self.screen_is_active = False
                    if self.ddp.detect_and_open_session():
                        logger.info(f"Session established (Mode: {self.ddp.dis_mode.name}).")
                    else:
                        time.sleep(1.0) # Faster retry when ON
                elif self.ddp.state == DDPState.SESSION_ACTIVE:
                    if not self.ddp.perform_initialization():
                        logger.error("DDP Initialization failed. Retrying.")
                        time.sleep(3)
                    else:
                        self.set_source_radio()
                        logger.info("DDP READY.")
                        self.last_draw_time = time.time()
                        self.screen_is_active = False
                elif self.ddp.state == DDPState.PAUSED:
                    if self.screen_is_active:
                        logger.info("Service PAUSED by Cluster. Waiting for release...")
                        self.screen_is_active = False
                    self.ddp.send_keepalive_if_needed()
                    self.ddp.poll_bus_events()
                    try:
                        while True:
                            self.draw_socket.recv_json(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        pass
                    time.sleep(0.05)
                    continue
                elif self.ddp.state == DDPState.READY:
                    self.ddp.send_keepalive_if_needed()
                    self.ddp.poll_bus_events()
                    if self.ddp.state != DDPState.READY:
                        continue 
                    if not self.screen_is_active and self.command_cache:
                         logger.info("Auto-Restore triggered.")
                         if self.claim_nav_screen():
                             self.handle_redraw()
                    socks = dict(self.poller.poll(5))
                    if self.draw_socket in socks:
                        cmds = []
                        try:
                            while True:
                                cmds.append(self.draw_socket.recv_json(flags=zmq.NOBLOCK))
                        except zmq.Again: pass

                        if cmds:
                            last_was_commit = (cmds[-1].get('command') == 'commit')
                            had_clear = False
                            
                            for cmd in cmds:
                                c = cmd.get('command')
                                if c in ['clear', 'clear_payload']:
                                    self.command_cache = {}
                                    had_clear = True
                                elif c == 'set_region':
                                    r = cmd.get('region', 'central')
                                    if r == 'full':
                                        self.region_name = 'full'
                                        self.region_y_offset = 0x00
                                        self.region_height = 0x58
                                    elif r == 'centre_lower':
                                        self.region_name = 'centre_lower'
                                        self.region_y_offset = 0x1B
                                        self.region_height = 0x3D
                                    elif r == 'top_centre':
                                        self.region_name = 'top_centre'
                                        self.region_y_offset = 0x00
                                        self.region_height = 75 # 0x4B (27 + 48)
                                    else:
                                        self.region_name = 'central'
                                        self.region_y_offset = 0x1B
                                        self.region_height = 0x30
                                    
                                    # Force a re-claim with new boundaries
                                    if self.screen_is_active:
                                        self.screen_is_active = False
                                    self.command_cache = {}
                                    had_clear = True
                                elif c in ['draw_text', 'draw_bitmap', 'draw_line']:
                                    k = (c, cmd.get('y', 0), cmd.get('x', 0))
                                    self.command_cache[k] = cmd
                            
                            if not self.screen_is_active:
                                if not self.claim_nav_screen():
                                    logger.error("Failed to claim screen.")
                                    continue
                            
                            self.last_draw_time = time.time()

                            # PROCESS COMMANDS WITH SIZE-LIMITED BATCHING
                            # We combine related commands (like wipe + text) into a single 
                            # DDP frame IF they fit in one block (42 bytes). This eliminates 
                            # the 20ms inter-block pacing delay causing flicker.
                            if had_clear:
                                self.handle_redraw()
                            else:
                                current_payload = []
                                for cmd in cmds:
                                    c = cmd.get('command')
                                    p = []
                                    if c == 'draw_text':
                                        p = self.get_text_payload(cmd.get('text', ''), cmd.get('x', 0), cmd.get('y', 0), cmd.get('flags', 0x06))
                                    elif c == 'draw_bitmap':
                                        p = self.get_bitmap_payload(cmd.get('x', 0), cmd.get('y', 0), cmd.get('icon_name'))
                                    elif c == 'draw_line':
                                        p = self.get_line_payload(cmd.get('x', 0), cmd.get('y', 0), cmd.get('length', 0), cmd.get('vertical', True))
                                    elif c == 'clear_area':
                                        p = self.get_clear_area_payload(cmd.get('x', 0), cmd.get('y', 0), cmd.get('w', 64), cmd.get('h', 9))
                                    elif c == 'commit':
                                        if current_payload:
                                            self.ddp.send_ddp_frame(current_payload)
                                            current_payload = []
                                            # Poll after drawing to keep session alive during burst
                                            self.ddp.poll_bus_events()
                                            self.ddp.send_keepalive_if_needed()
                                        self.commit_frame()
                                        continue
                                    elif c == 'draw_raw_bitmap':
                                        if current_payload:
                                            self.ddp.send_ddp_frame(current_payload)
                                            current_payload = []
                                        try:
                                            raw_bytes = bytes.fromhex(cmd.get('data_hex', ''))
                                            w, h, x, y = cmd.get('w', 64), cmd.get('h', 88), cmd.get('x', 0), cmd.get('y', 0)
                                            mode_flag = cmd.get('mode_flag', 0x02)
                                            abs_y = y + self.region_y_offset
                                            payload_clip = [0x52, 0x05, 0x00, x, abs_y, w, h]
                                            if self.ddp.send_ddp_frame(payload_clip):
                                                bytes_per_row = (w + 7) // 8
                                                rows_per_chunk = 37 // bytes_per_row
                                                if rows_per_chunk < 1: rows_per_chunk = 1
                                                for i in range(0, h, rows_per_chunk):
                                                    start_byte = i * bytes_per_row
                                                    rows_to_send = min(rows_per_chunk, h - i)
                                                    chunk_data = list(raw_bytes[start_byte : start_byte + (rows_to_send * bytes_per_row)])
                                                    payload_bmp = [0x55, len(chunk_data) + 3, mode_flag, 0x00, i] + chunk_data
                                                    if not self.ddp.send_ddp_frame(payload_bmp): break
                                                self.ddp.send_ddp_frame([0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height])
                                        except Exception as e:
                                            logger.error(f"Failed drawing raw bitmap: {e}")
                                        continue
                                    
                                    if p:
                                        if current_payload and (len(current_payload) + len(p) > 42):
                                            self.ddp.send_ddp_frame(current_payload)
                                            current_payload = p
                                            # Poll after drawing to keep session alive during burst
                                            self.ddp.poll_bus_events()
                                            self.ddp.send_keepalive_if_needed()
                                        else:
                                            current_payload += p

                                if current_payload:
                                    self.ddp.send_ddp_frame(current_payload)
                                    self.ddp.poll_bus_events()
                                    self.ddp.send_keepalive_if_needed()
                    if (self.ENABLE_INACTIVITY_RELEASE
                        and self.screen_is_active
                        and (time.time() - self.last_draw_time > self.inactivity_timeout_sec)):
                        logger.info("Inactivity timeout. Releasing screen.")
                        if self.ddp.release_screen():
                            self.screen_is_active = False
                        else:
                            self.screen_is_active = False
                
                # Broadcast true service state instead of just screen_is_active
                # dis_display uses READY to know when it can send commands. DDPState.READY is the true indicator.
                now_time = time.time()
                current_state = getattr(self.ddp, 'state', None)
                if current_state != getattr(self, 'last_pub_state', None) or (now_time - getattr(self, 'last_status_cast', 0) > 1.0):
                    if current_state != getattr(self, 'last_pub_state', None):
                        logger.info(f"DDPState Broadcasting new state: {current_state}")
                    self.last_pub_state = current_state
                    self.last_status_cast = now_time
                    
                    state_str = "DISCONNECTED"
                    if current_state == DDPState.READY:
                        state_str = "READY"
                    elif current_state == DDPState.PAUSED:
                        state_str = "PAUSED"
                    elif current_state == DDPState.SESSION_ACTIVE:
                        state_str = "INITIALIZING"
                    
                    try:
                        self.status_pub.send_string(f"DIS_STATE {state_str}", flags=zmq.NOBLOCK)
                    except: pass

                time.sleep(0.01)
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                if hasattr(self, 'ddp'):
                    self.ddp._set_state(DDPState.DISCONNECTED)
                self.screen_is_active = False
                try: 
                    self.status_pub.send_string("DIS_STATE DISCONNECTED", flags=zmq.NOBLOCK)
                except: pass
                time.sleep(3)

if __name__ == "__main__":
    try:
        DisService(config_path='/home/pi/config.json').run()
    except KeyboardInterrupt:
        logger.info("Shutting down service.")
