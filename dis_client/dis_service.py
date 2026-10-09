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
import signal
import sys
import os
import threading
from typing import List, Optional

try:
    from ddp_protocol import DDPProtocol, DDPState, DisMode, DDPError, DDPHandshakeError, DDPMessages
except ImportError:
    print("Error: Could not import DDPProtocol. Make sure ddp_protocol.py is in the same directory.")
    exit(1)

try:
    from icons import audscii_trans, encode_audscii, ICONS, BITMAPS
except ImportError:
    print("Error: Could not import icons.py. Make sure it is in the same directory.")
    exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (DIS Svc) %(message)s')
logger = logging.getLogger(__name__)

class DisService:
    def __init__(self, config_path='/home/pi/config.json'):
        # --- EXPERIMENTAL FLAGS ---
        # Set to True to bypass raw-bitmap application-message batching.
        # Whole commands still obey the internal cluster-specific message cap;
        # TP2 ACK blocks and CAN frame sizing are separate transport concerns.
        self.UNSAFE_BATCHING_BYPASS = False

        self.config = {}
        self.load_config(config_path)
        
        self.running = True
        self._setup_signals()

    def _setup_signals(self):
        """Register signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        logger.info(f"Shutdown signal {signum} received. Stopping DisService...")
        self.running = False

    def load_config(self, config_path):
        try:
            with open(config_path) as f:
                self.config = json.load(f)
            self._graphics_message_budget()
            self._bitmap_message_budget()
            self._bitmap_rows_per_command()
            logger.info(f"Configuration loaded from: {config_path}")
                
            if self.config.get('features', {}).get('debug_mode', False):
                logger.setLevel(logging.DEBUG)
                logging.getLogger().setLevel(logging.DEBUG)
                logger.debug("Debug mode enabled via config.json")
                
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
        self.draw_socket.setsockopt(zmq.RCVHWM, 1000) # Increased to prevent drops during GIF bursts
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
            addr = _zmq.get('dis_status', 'ipc:///run/rnse_control/dis_status.ipc')
            self.status_pub.bind(addr)
            logger.info(f"ZMQ status pub socket bound to: {addr}")
        except Exception as e:
            logger.warning(f"Could not bind status pub socket: {e}")

        self.last_draw_time = 0.0
        self._screen_is_active = False
        self.inactivity_timeout_sec = 30.0 
        self.command_cache = {}
        center = self.config.get('display', {}).get('center_display', {})
        phone = self.config.get('display', {}).get('phone', {})
        context_only = bool(center.get('navigation', {}).get('claim_on_nav', False)
                            or phone.get('claim_on_phone', False))
        self.presentation_requested = not (center.get('start_inactive', False) or context_only)
        self._initial_presentation_requested = self.presentation_requested
        self.ENABLE_INACTIVITY_RELEASE = False

        # Default region: 'central'
        self.region_name = 'central'
        self.region_y_offset = 0x1B
        self.region_height = 0x30
        
        # Recovery state
        self.last_claim_attempt = 0.0
        self.claim_retry_count = 0
        self._pending_restore_request_generation = None
        self.init_cleanup_done = False # Track if upfront zombie cleanup was done

    @property
    def screen_is_active(self):
        return self._screen_is_active

    @screen_is_active.setter
    def screen_is_active(self, value):
        if not value:
            self._native_known_image = None
            self._native_7a_claim = None
            self._stock_mono_live_context = None
            self._stock_mono_pending_context = None
        if self._screen_is_active != value:
            self._screen_is_active = value

        if not self.ENABLE_INACTIVITY_RELEASE and value:
            logger.info("Inactivity auto-release is DISABLED (screen will stay claimed forever)")
        self._broadcast_status()

    def _broadcast_status(self, force=False):
        """Broadcast current DDP state via ZMQ."""
        now = time.time()
        current_state = getattr(self.ddp, 'state', None)
        generation = getattr(self.ddp, 'presentation_request_generation', 0)
        if current_state == DDPState.DISCONNECTED:
            # Reset ownership intent once per lost session. Without this, an
            # earlier auto-claim can make start-inactive claim on ignition-on.
            if getattr(self, 'last_pub_state', None) != DDPState.DISCONNECTED:
                self.presentation_requested = getattr(self, '_initial_presentation_requested', False)
                self.command_cache = {}
                self._pending_request_generation = None
                self._pending_restore_request_generation = None
                self._published_request_generation = generation
        elif generation > getattr(self, '_published_request_generation', 0):
            self._published_request_generation = generation
            #2E becomes a generation only after2F transport acknowledgement.
            # Existing desired content may restore once immediately; a bare
            # availability status never creates this pending request.
            if self.presentation_requested:
                self._pending_restore_request_generation = generation
            # Keep a confirmed request pending through intervening warnings.
            # Requests during a claimed/desired presentation are recovery,
            # not an instruction to override the client's ownership policy.
            if not self.presentation_requested and not self.screen_is_active:
                self._pending_request_generation = generation
        if self.presentation_requested:
            self._pending_request_generation = None
        pending = getattr(self, '_pending_request_generation', None)
        if (pending is not None and current_state == DDPState.READY
                and not self.presentation_requested and not self.screen_is_active
                and now - getattr(self, '_last_request_cast', 0) >= 1.0):
            # PUB has no delivery acknowledgement. Replay the same token at
            # heartbeat pace until resume/pause acknowledges it. The engine
            # deduplicates successful tokens, so this never repeats a claim.
            try:
                self.status_pub.send_string(f"DIS_REQUESTED {pending}", flags=zmq.NOBLOCK)
                self._last_request_cast = now
            except zmq.ZMQError as exc:
                logger.warning('Failed to publish display request: %s', exc)

        if not force and current_state == getattr(self, 'last_pub_state', None) and (now - getattr(self, 'last_status_cast', 0) < 1.0):
            return

        state_str = "DISCONNECTED"
        if current_state == DDPState.READY:
            state_str = "READY"
        elif current_state == DDPState.PAUSED:
            state_str = "PAUSED"
        elif current_state == DDPState.SESSION_ACTIVE:
            state_str = "INITIALIZING"
        
        msg = f"DIS_STATE {state_str}"
        try:
            if current_state != getattr(self, 'last_pub_state', None):
                logger.info(f"ZMQ Broadcast (State Change): {msg}")
            elif (now - getattr(self, 'last_heartbeat_log', 0) > 5.0):
                logger.info(f"ZMQ Broadcast (Heartbeat): {msg}")
                self.last_heartbeat_log = now
                
            self.status_pub.send_string(msg, flags=zmq.NOBLOCK)
        except Exception as e:
            logger.warning(f"ZMQ: Failed to send status: {e}")

        self.last_pub_state = current_state
        self.last_status_cast = now

    def parse_time(self, t: str) -> int:
        if not t: return 0
        parts = t.split(':')
        return sum(int(p) * (60 ** i) for i, p in enumerate(reversed(parts)))

    def translate_to_audscii(self, text: str) -> List[int]:
        return list(encode_audscii(text))

    def _presentation_control(self, command):
        if command in ('pause', 'resume'):
            self._pending_request_generation = None
            self._pending_restore_request_generation = None
            self._published_request_generation = getattr(self.ddp, 'presentation_request_generation', 0)
        if command == 'pause':
            self.presentation_requested = False
            self.command_cache = {}
            if self.screen_is_active:
                self.ddp.release_screen()
                self.screen_is_active = False
            return True
        if command == 'resume':
            self.presentation_requested = True
            return True
        return False

    def _restore_claim_due(self, now):
        """Use confirmed presentation intent once; retain ordinary5sec retry."""
        if (self.ddp.state != DDPState.READY or not self.presentation_requested
                or self.screen_is_active or not self.command_cache
                or not (self.ddp.renderer_ready() or self._native_7a_ready())):
            return False
        pending = getattr(self, '_pending_restore_request_generation', None)
        if pending is not None:
            self._pending_restore_request_generation = None
            if pending == getattr(self.ddp, 'presentation_request_generation', 0):
                return True
        return now - self.last_claim_attempt > 5.0

    def claim_nav_screen(self):
        """Request ownership once; busy is a normal asynchronous state."""
        if self.ddp.state != DDPState.READY or not self.presentation_requested:
            return False
        hicolor = self._native_7a_ready()
        if not self.ddp.renderer_ready() and not hicolor:
            logger.warning('No verified renderer for negotiated cluster capabilities%s',
                           getattr(self.ddp, 'cluster_capabilities', None))
            return False
        full = self.region_name in ['full', 'top_centre']
        y, height = (0, 0x58) if full else (0x1B, self.region_height)
        claim = [0x52, 0x05, 0x82, 0, y, 0x40, height]
        status_opcode = 0x53
        if hicolor:
            # Exact profile0 claim80554BB0/8055AE42, with no52 geometry reuse.
            claim = [0x7A, 9, 0x82, 0, 0, 0x78, 0, 0xDC, 0, 0xF0, 0]
            status_opcode = 0x7B
        self.screen_is_active = False
        self._pending_restore_request_generation = None
        claim_context = self._native_7a_context()
        receive_boundary = self.ddp._application_receive_boundary()
        try:
            if hicolor:
                # The eleven-byte claim is one logical control message; use
                #the sequence-checked, ACKed sender rather than one CAN frame.
                if not self.ddp._send_application_control_record(claim):
                    if self.ddp.state != DDPState.DISCONNECTED:
                        self.ddp._set_state(DDPState.PAUSED)
                    return False
            else:
                self.ddp.send_data_packet(claim)
            deadline = time.monotonic() + 1.0
            payload = []
            while self.ddp.state == DDPState.READY:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    break
                data = self.ddp._recv_and_ack_data(remaining_ms)
                if not data or self.ddp.state == DDPState.DISCONNECTED:
                    break
                payload = data[1:]
                if len(payload) >= 2 and payload[0] == status_opcode:
                    token = self.ddp._application_record_token(data)
                    if (not self.ddp._application_record_after_boundary(data, receive_boundary)
                            or token != getattr(self.ddp, '_last_window_status_token', None)):
                        # Already observed stale status must not grant a new
                        #claim or override a newer availability/fault record.
                        logger.debug('Retired uncorrelated ownership status%s', payload)
                        continue
                    status = self.ddp.window_status(payload)
                    if (status.outcome != 'granted'
                            or claim_context != self._native_7a_context()
                            or (hicolor and payload[1] == 5)):
                        self.ddp._data_inbox.appendleft(data)
                        break
                    self.ddp._set_state(DDPState.READY)
                    self.screen_is_active = True
                    if hicolor:
                        self._native_7a_claim = claim_context
                    self.last_draw_time = time.time()
                    self.claim_retry_count = 0
                    return True
                if payload == DDPMessages.CMD_REINIT_REQ or payload in (
                        DDPMessages.STAT_BUSY_HALF, DDPMessages.STAT_BUSY_WARN_HALF,
                        DDPMessages.STAT_BUSY_FULL, DDPMessages.STAT_BUSY_WARN_FULL,
                        DDPMessages.STAT_FREE_HALF, DDPMessages.STAT_FREE_FULL):
                    # Already ACKed by the receiver. Preserve the event for
                    # normal busy/free/reinit dispatch; never re-claim here.
                    self.ddp._data_inbox.appendleft(data)
                    break
                # Retained application records can precede this claim's reply.
                # They must not hide a later ownership grant or extend the wait.
                logger.debug("Ignoring unrelated record while awaiting center ownership: %s", payload)
            if self.ddp.state != DDPState.DISCONNECTED:
                logger.info("Center ownership pending; cluster response %s. Waiting for events.", payload)
                self.ddp._set_state(DDPState.PAUSED)
            return False
        except DDPError as exc:
            logger.warning("Center claim interrupted: %s", exc)
            if self.ddp.state != DDPState.DISCONNECTED:
                self.ddp._set_state(DDPState.PAUSED)
            return False

    def clear_screen_payload(self):
        if self.ddp.renderer_command_family() == 0x7A:
            # For internal initialization/restoration only: stock frame0 is
            #a window prelude, not proof of a pixel-clear operation.
            return self._send_graphics([0x7A, 9, 2, 0, 0, 0x78, 0, 0xDC, 0, 0xF0, 0], native=True)
        logger.info(f"Queueing Region Clear for {self.region_name}")
        payload = [0x52, 0x05, 0x02, 0x00, self.region_y_offset, 0x40, self.region_height]
        payload += [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        if not self._send_graphics(payload):
            logger.error("Failed to send clear payload.")

    def _native_7a_context(self):
        caps = getattr(self.ddp, 'cluster_capabilities', None)
        setup = getattr(self.ddp, 'application_setup_record', None)
        return (tuple(caps.raw) if caps is not None else None,
                tuple(setup) if setup is not None else None,
                getattr(self.ddp, 'state_generation', 0),
                getattr(self.ddp, 'application_error_generation', 0))

    def _native_7a_ready(self, owned=False):
        # Raw native coordinates are not converted from this mono region.
        # Restrict initial support to the exact profile0 configuration.
        ready = (self.ddp.renderer_command_family() == 0x7A
                 and self.ddp.renderer_ready(0x7A)
                 and (self.region_name, self.region_y_offset, self.region_height) == ('central', 27, 48))
        return ready and (not owned or (self.ddp.state == DDPState.READY and self.screen_is_active
                         and getattr(self, '_native_7a_claim', None) == self._native_7a_context()))

    def _stock_mono_context(self):
        caps = getattr(self.ddp, 'cluster_capabilities', None)
        setup = getattr(self.ddp, 'application_setup_record', None)
        return (tuple(caps.raw) if caps is not None else None,
                tuple(setup) if setup is not None else None,
                getattr(self.ddp, 'state_generation', None),
                getattr(self.ddp, 'application_error_generation', None),
                (self.region_name, self.region_y_offset, self.region_height))

    def _stock_mono_ready(self, owned=False):
        context = self._stock_mono_context()
        ready = (self.ddp.state == DDPState.READY
                 and self.ddp.renderer_command_family() == 0x52 and self.ddp.renderer_ready(0x52)
                 and context[0] is not None and len(context[0]) >= 2 and context[0][1] == 0x20
                 and context[1] is not None and context[4] == ('central', 27, 48)
                 and all(type(v) is int and v >= 0 for v in context[2:4]))
        return ready and (not owned or (self.screen_is_active
                and not getattr(self.ddp, 'screen_released_by_cluster', True)
                and getattr(getattr(self.ddp, '_last_window_status', None), 'outcome', None) == 'granted'))

    def _stock_mono_command(self, command):
        """Validate desired raw source before claims; compile again after grant."""
        from stock_mono_frame import StockMonoFrameCompiler
        if not self._stock_mono_ready():
            raise ValueError('Stock mono requires verified READY format20 central52 setup')
        budget = self._graphics_message_budget()
        if type(budget) is not int or budget < 49:
            raise ValueError('Stock mono needs the proven49-byte record budget')
        compiler = getattr(self, '_stock_mono_compiler', None)
        if compiler is None:
            compiler = self._stock_mono_compiler = StockMonoFrameCompiler()
        source = {key: value for key, value in command.items() if key != 'seq'}
        frame = compiler.compile_command(source)
        return dict(command='_stock_mono_frame', source=frame.source)

    def _send_stock_mono_frame(self, command):
        """Send a fresh owned body; the queue emits its one separate39."""
        self._stock_mono_pending_context = None
        if getattr(self, '_frame_failed', False) or not self._stock_mono_ready(owned=True):
            self._frame_failed = True
            return False
        before = self._stock_mono_context()
        try:
            # A claim/regrant may change context; never send preclaim payloads.
            prepared = self._stock_mono_command(command['source'])
            frame = self._stock_mono_compiler.compile_command(prepared['source'])
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self._frame_failed = True
            logger.error('Cannot compile owned stock mono frame: %s', exc)
            return False
        if before != self._stock_mono_context() or not self._stock_mono_ready(owned=True):
            self._frame_failed = True
            return False
        self._stock_mono_pending_context = before
        try:
            if getattr(self, '_stock_mono_live_context', None) != before:
                # Clear a previous custom layout or unknown pixels once. This
                # stays inside this transaction; no extra39 is emitted here.
                self.clear_screen_payload()
                self.ddp.poll_bus_events()
                self.ddp.send_keepalive_if_needed()
            for payload in frame.messages:
                if (getattr(self, '_frame_failed', False) or not self._stock_mono_ready(owned=True)
                        or before != self._stock_mono_context()
                        or not self._send_graphics(list(payload), native=True)):
                    self._frame_failed = True
                    return False
                self.ddp.poll_bus_events()
                self.ddp.send_keepalive_if_needed()
                if before != self._stock_mono_context() or not self._stock_mono_ready(owned=True):
                    self._frame_failed = True
                    return False
        except DDPError as exc:
            self._frame_failed = True
            logger.error('Stock mono body interrupted: %s', exc)
            return False
        return True

    @staticmethod
    def _verified_7a_payload(payload, stock_composition=False):
        """Accept frame0/positive69/39; composed path adds exact frame15/zero69."""
        if any(type(v) is not int or not 0 <= v <= 255 for v in payload):
            return False
        if list(payload) == [0x39]:
            return True
        if not 1 <= len(payload) <= 128:
            return False
        at = 0
        prelude = [0x7A, 9, 2, 0, 0, 0x78, 0, 0xDC, 0, 0xF0, 0]
        if list(payload[:11]) == prelude:
            at = 11
        while at < len(payload):
            if stock_composition:
                # Only the two exact recovered frame15 records. Arbitrary83
                # permission is not exposed by the public raw-symbol API.
                frames = (bytes.fromhex('8309005700290030000900'),
                          bytes.fromhex('8309005000420004002200'))
                if any(bytes(payload[at:at+11]) == frame for frame in frames):
                    at += 11
                    continue
                if list(payload[at:at+2]) == [0x69, 0]:
                    at += 2
                    continue
            if (at + 2 > len(payload) or payload[at] != 0x69
                    or not 4 <= payload[at + 1] <= 124 or payload[at + 1] % 4):
                return False
            at += 2 + payload[at + 1]
            if at > len(payload):
                return False
        return at == len(payload)

    def get_text_payload(self, text: str, x: int, y: int, flags: int = 0x06,
                         highlight_width=None, highlight_height=None) -> List[int]:
        if highlight_width is not None and (isinstance(highlight_width, bool)
                or not isinstance(highlight_width, int) or not 0 < highlight_width <= 64-x):
            raise ValueError('Text highlight width must fit within the drawing region')
        if highlight_height is not None and (isinstance(highlight_height, bool)
                or not isinstance(highlight_height, int) or not 0 < highlight_height <= self.region_height-y):
            raise ValueError('Text highlight height must fit within the drawing region')
        chars = self.translate_to_audscii(text) 
        # Empty desired fields have no font record. Their explicit update
        # clear rectangle and the enclosing frame commit remain independent.
        if not chars:
            return []
        is_inverted = (flags & 0x80) != 0
        protocol_flags = flags & 0x7C 
        
        if is_inverted:
            abs_y = y + self.region_y_offset
            width = highlight_width if highlight_width is not None else 64-x
            height = highlight_height if highlight_height is not None else min(9, self.region_height - y)
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

    def write_text(self, text: str, x: int, y: int, flags: int = 0x06,
                   highlight_width=None, highlight_height=None):
        options = {key: value for key, value in (('highlight_width', highlight_width),
                   ('highlight_height', highlight_height)) if value is not None}
        payload = self.get_text_payload(text, x, y, flags, **options)
        if payload:
            self._send_graphics(payload)

    def get_bitmap_payload(self, x: int, y: int, icon_name: str, mode_flag: int = 0x02) -> List[int]:
        if not icon_name or icon_name not in BITMAPS:
            return []
        icon = BITMAPS[icon_name]
        w, h, data = icon['w'], icon['h'], icon['data']
        payload = [0x52, 5, 0, x, y + self.region_y_offset, w, h]
        for record in self._bitmap_row_records(data, w, h, mode_flag):
            payload += record
        payload += [0x52, 5, 0, 0, self.region_y_offset, 64, self.region_height]
        return payload

    def draw_bitmap(self, x: int, y: int, icon_name: str, mode_flag: int = 0x02):
        if not icon_name or icon_name not in BITMAPS:
            return
        icon = BITMAPS[icon_name]
        w, h, data = icon['w'], icon['h'], icon['data']
        records = self._bitmap_row_records(data, w, h, mode_flag)
        payload_clip = [0x52, 5, 0, x, y + self.region_y_offset, w, h]
        if not self._send_graphics(payload_clip, pacing=False):
            return
        pending = []
        for record in records:
            if pending and len(pending) + len(record) > self._bitmap_message_budget():
                if not self._send_graphics(pending, pacing=False):
                    return
                pending = []
            pending += record
        if pending and not self._send_graphics(pending, pacing=False):
            return
        self._send_graphics([0x52, 5, 0, 0, self.region_y_offset, 64, self.region_height])

    def get_line_payload(self, x: int, y: int, length: int, vertical: bool = True, orientation: Optional[int] = None) -> List[int]:
        if orientation is None:
            orientation = 0x10 if vertical else 0x20
        # 0x63 uses region-relative coordinates (like 0x57 text), NOT absolute
        # coordinates (like 0x52 region commands). No offset needed.
        return [0x63, 0x04, orientation, x, y, length]

    def draw_line(self, x: int, y: int, length: int, vertical: bool = True, orientation: Optional[int] = None):
        payload = self.get_line_payload(x, y, length, vertical, orientation)
        self._send_graphics(payload)

    def get_clear_area_payload(self, x: int, y: int, w: int, h: int) -> List[int]:
        abs_y = y + self.region_y_offset
        payload = [0x52, 0x05, 0x02, x, abs_y, w, h]
        payload += [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        return payload

    def clear_area(self, x, y, w, h):
        payload = self.get_clear_area_payload(x, y, w, h)
        self._send_graphics(payload)

    def _send_graphics(self, payload, pacing=True, native=False, stock_composition=False):
        """Track failure across every command in a frame, including IPC batches."""
        if getattr(self, '_frame_failed', False):
            return False
        hicolor = self.ddp.renderer_command_family() == 0x7A
        allowed = (self._native_7a_ready(owned=True)
                   and (native or list(payload) == [0x39])
                   and self._verified_7a_payload(payload, stock_composition)) if hicolor else self.ddp.renderer_ready()
        if not allowed:
            self._frame_failed = True
            logger.warning('Refusing drawing outside the verified negotiated renderer')
            return False
        if not getattr(self, '_native_transfer_active', False) and list(payload) != [0x39]:
            self._native_known_image = None  # Overlay/clear changes actual pixels.
        try:
            error_generation = getattr(self.ddp, 'application_error_generation', 0)
            success = self.ddp.send_ddp_frame(payload, pacing=pacing)
            success = success and error_generation == getattr(self.ddp, 'application_error_generation', 0)
        except DDPError as exc:
            logger.warning("Graphics transfer interrupted: %s", exc)
            success = False
        if not success:
            self._frame_failed = True
            self._native_known_image = None
        return bool(success)

    def _publish_frame_result(self, seq, success):
        # ACK means graphics and commit were transport-acknowledged. It does
        # not certify that LCD scanout or presentation has completed.
        if seq:
            try:
                result = "DRAW_ACK" if success else "DRAW_NACK"
                self.status_pub.send_string(f"{result} {seq}", flags=zmq.NOBLOCK)
            except zmq.ZMQError as exc:
                logger.warning("Failed to publish frame result: %s", exc)

    def _graphics_message_budget(self):
        """Application-message cap, independent of TP2 transport ACK blocks."""
        #49 is stock805546E4's complete mono graphics-record budget. A valid
        #49-byte57 record crosses a six-frame/42-byte TP ACK boundary intact.
        # Retain the existing white105 compatibility policy, without inferring
        # a universal peer RX limit from RNSE's own128-byte receive buffer.
        mode = getattr(getattr(self, 'ddp', None), 'dis_mode', None)
        if (getattr(self, 'ddp', None) is not None
                and self.ddp.renderer_command_family() == 0x7A):
            # Native805546E4 internal30 uses128; a126-byte69 is indivisible.
            # This is the producer's budget, not a universal peer RX claim.
            return 128
        default = 49 if mode == DisMode.RED else 105
        value = getattr(self, 'config', {}).get('ddp_application_message_bytes', default)
        if type(value) is not int or not 49 <= value <= 105:
            raise ValueError('ddp_application_message_bytes must be an integer from 49 to 105')
        # Bitmap row batching has its own compatibility setting. Neither this
        # application bound nor that bitmap bound changes TP ACK block size.
        return value

    def get_text_update_payload(self, command):
        """Validate the entire wipe/replacement before writing any pixels."""
        payload = []
        rect = command.get('clear_rect')
        if rect is not None:
            values = [rect.get(k) for k in ('x', 'y', 'w', 'h')]
            if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
                raise ValueError('Text clear rectangle must use integer coordinates')
            x, y, w, h = values
            if not (0 <= x < 64 and 0 <= y < self.region_height
                    and 0 < w <= 64-x and 0 < h <= self.region_height-y):
                raise ValueError('Text clear rectangle is outside the drawing region')
            payload += self.get_clear_area_payload(x, y, w, h)
        if command.get('text', ''):
            options = {key: command[key] for key in ('highlight_width', 'highlight_height') if key in command}
            payload += self.get_text_payload(command['text'], command.get('x', 0),
                                             command.get('y', 0), command.get('flags', 6), **options)
        if len(payload) > self._graphics_message_budget():
            raise ValueError('Atomic text replacement exceeds application message budget')
        return payload

    def _bitmap_message_budget(self):
        """Internal bitmap cap, independent of TP2 ACK block sizes.

        White clusters retain the verified 105-byte policy; red clusters keep
        the conservative 42-byte bitmap limit. Neither is a user setting.
        """
        mode = getattr(getattr(self, 'ddp', None), 'dis_mode', None)
        return 42 if mode == DisMode.RED else 105

    def _bitmap_rows_per_command(self):
        """Opt in to native bitmap row wrapping; default keeps one-row commands."""
        value = getattr(self, 'config', {}).get('ddp_bitmap_rows_per_command', 1)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
            raise ValueError('ddp_bitmap_rows_per_command must be an integer from 1 to 12')
        if getattr(getattr(self, 'ddp', None), 'dis_mode', None) == DisMode.RED:
            return 1  # Multi-row wrapping has only been verified on white clusters.
        if value > 1 and getattr(self, 'coalesce_bitmaps', getattr(self, 'config', {}).get('ddp_coalesce_bitmaps', False)):
            raise ValueError('ddp_bitmap_rows_per_command > 1 is incompatible with bitmap coalescing')
        return value

    def _bitmap_row_records(self, data, w, h, mode_flag=0x02):
        width = (w + 7) // 8
        if not 0 < w <= 64 or not 0 < h <= self.region_height or len(data) != width * h:
            raise ValueError('Invalid bitmap dimensions or data length')
        budget = min(self._bitmap_message_budget(), 105)
        if 5 + width > budget:
            raise ValueError('Bitmap row command exceeds application message budget')
        rows = min(self._bitmap_rows_per_command(), (budget - 5) // width, 252 // width)
        # Per-row padding bits must not become the next row in a narrower window.
        if w % 8:
            rows = 1
        records = []
        for y in range(0, h, rows):
            raster = list(data[y * width:min(y + rows, h) * width])
            records.append([0x55, len(raster) + 3, mode_flag, 0, y] + raster)
        return records

    def _finish_frame(self, seq, pending_payload=None):
        # Native805546E4/8055B0AA queues39 as a separate application message,
        # after the data message completes. TP ACK blocks remain independent.
        stock_context = getattr(self, '_stock_mono_pending_context', None)
        if stock_context is not None and (not self._stock_mono_ready(owned=True)
                or stock_context != self._stock_mono_context()):
            self._frame_failed = True
        if pending_payload and not self._send_graphics(list(pending_payload)):
            success = False
        else:
            success = self.commit_frame()
        if stock_context is not None:
            try:
                self.ddp.poll_bus_events()
                self.ddp.send_keepalive_if_needed()
                success = (success and self._stock_mono_ready(owned=True)
                           and stock_context == self._stock_mono_context())
            except DDPError:
                success = False
            self._stock_mono_live_context = stock_context if success else None
        else:
            self._stock_mono_live_context = None
        self._stock_mono_pending_context = None
        self._publish_frame_result(seq, success)
        self._frame_failed = False
        return success

    def _raw_bitmap_payload(self, command):
        data = bytes.fromhex(command.get('data_hex', ''))
        w, h = command.get('w', 64), command.get('h', 88)
        x, y = command.get('x', 0), command.get('y', 0)
        width = (w + 7) // 8
        if not (0 < w <= 64 and 0 < h <= self.region_height
                and 0 <= x <= 64 - w and 0 <= y <= self.region_height - h
                and len(data) == width * h):
            raise ValueError('Invalid bitmap dimensions, position, or data length')
        payload = [0x52, 5, 0, x, self.region_y_offset + y, w, h]
        for record in self._bitmap_row_records(data, w, h, command.get('mode_flag', 2)):
            payload += record
        return payload

    def _coalesce_bitmap_commands(self, commands):
        # Bench opt-in until LCD presentation has been verified, not only ACKs.
        if not getattr(self, 'coalesce_bitmaps', self.config.get('ddp_coalesce_bitmaps', False) if hasattr(self, 'config') else False):
            return commands
        if self.ddp.dis_mode != DisMode.WHITE or self.UNSAFE_BATCHING_BYPASS:
            return commands
        result, group, size = [], [], 0
        def flush():
            if len(group) > 1:
                result.append({'command': 'draw_raw_bitmap_batch', 'commands': list(group)})
            else:
                result.extend(group)
            group.clear()
        for command in commands:
            if command.get('command') == 'draw_raw_bitmap':
                try:
                    part_size = len(self._raw_bitmap_payload(command))
                except (ValueError, TypeError):
                    flush()
                    size = 0
                    result.append(command)
                    continue
                # Bound the application message while keeping TP2 ACK blocks
                # independent. Larger individual bitmaps use the existing path.
                if size + part_size + 7 > 768:
                    flush()
                    size = 0
                group.append(command)
                size += part_size
            else:
                flush()
                size = 0
                result.append(command)
        flush()
        return result

    def _send_raw_bitmap_batch(self, commands, prefix=None):
        try:
            if self._bitmap_rows_per_command() > 1:
                raise ValueError('Native bitmap row grouping is incompatible with draw_raw_bitmap_batch')
            payload = list(prefix or [])
            for command in commands:
                payload += self._raw_bitmap_payload(command)
            # Each tile sets its own window. Only the final tile needs to
            # restore the normal drawing region before subsequent commands.
            payload += [0x52, 5, 0, 0, self.region_y_offset, 64, self.region_height]
            if self.ddp.dis_mode == DisMode.RED and len(payload) > self._bitmap_message_budget():
                raise ValueError('Red bitmap batch exceeds application message budget')
            return self._send_graphics(payload, pacing=False)
        except (ValueError, TypeError) as exc:
            self._frame_failed = True
            logger.error("Failed bitmap batch: %s", exc)
            return False

    def _native_bitmap_command(self, command):
        from native_bitmap import compile_native_payloads, validate_update_rect
        if (self.ddp.dis_mode != DisMode.WHITE or self.region_y_offset != 27
                or self.region_height != 48):
            raise ValueError('Native bitmaps require the white cluster central region')
        if (command.get('w', 128), command.get('h', 96),
                command.get('x', 0), command.get('y', 0)) != (128, 96, 0, 0):
            raise ValueError('Native bitmaps support only full128x96 center snapshots')
        render_order = command.get('render_order', 'planes')
        band_rows = command.get('band_rows', 12)
        delta = command.get('delta', False)
        if not isinstance(delta, bool) or (delta and render_order not in ('tiles', 'planes')):
            raise ValueError('Native delta is a boolean option for tiles or planes')
        update_rect = validate_update_rect(command.get('update_rect'), render_order, delta)
        delay = command.get('post_message_delay_s')
        if delay is not None and (isinstance(delay, bool)
                or not isinstance(delay, (int, float)) or not 0 <= delay <= .1):
            raise ValueError('Native post-message delay must be 0..100 ms')
        data = bytes.fromhex(command.get('data_hex', ''))
        payloads = compile_native_payloads(data, budget=105, rows_per_command=12,
                                          priming='each', selector_bytes=1,
                                          render_order=render_order, band_rows=band_rows, update_rect=update_rect)
        source = dict(command='draw_native_bitmap', x=0, y=0, w=128, h=96, data_hex=data.hex(),
                      render_order=render_order, band_rows=band_rows)
        if delay is not None:
            source['post_message_delay_s'] = delay
        if delta:
            source['delta'] = True
        if update_rect is not None:
            source['update_rect'] = update_rect
        return dict(command='_native_bitmap_frame', payloads=payloads, source=source)

    def _send_native_bitmap_frame(self, command):
        # Choose a delta at SEND time: preflight may precede a clear, another
        # snapshot or an ownership interruption in the same queued batch.
        generation = getattr(self.ddp, 'state_generation', None)
        prior = getattr(self, '_native_known_image', None)
        if generation != getattr(self, '_native_known_generation', None):
            prior = None
        source = command['source']
        data = bytes.fromhex(source['data_hex'])
        payloads = command['payloads']
        if source.get('delta', False) and prior is not None:
            if source.get('render_order') == 'planes':
                from native_bitmap import compile_plane_delta_payloads
                payloads = compile_plane_delta_payloads(data, prior)
            else:
                from native_tiles import compile_tile_payloads
                payloads = compile_tile_payloads(data, previous=prior)
        self._native_known_image = None
        self._native_transfer_active = True
        # Native icons have one renderer pause per complete application message.
        # Other snapshots retain their existing transport pacing behavior.
        message_delay = source.get('post_message_delay_s')
        pace_tiles = source.get('render_order', 'planes') == 'tiles' and message_delay is None
        try:
            for payload in payloads:
                if not self._send_graphics(payload, pacing=pace_tiles):
                    return False
                self.ddp.poll_bus_events()
                self.ddp.send_keepalive_if_needed()
                if generation != getattr(self.ddp, 'state_generation', None):
                    self._frame_failed = True
                    return False
                if message_delay:
                    time.sleep(message_delay)
            if source.get('update_rect') is None:
                self._native_known_image = data
                self._native_known_generation = generation
            else:
                self._native_known_generation = None  # Outside the patch is unknown.
            return True
        finally:
            self._native_transfer_active = False

    def _native_font_command(self, command):
        """Preflight exact stock57/69 records; coordinates remain raw bytes.

        No AUDSCII, glyph rasterization or region-offset transformation occurs.
        Numeric maneuver/direction selectors retain their raw ROM meanings.
        """
        from native_nav_glyphs import raw_graphics_record, raw_symbol_records, StockNavGlyphCatalog
        hicolor = self._native_7a_ready()
        if not self.ddp.renderer_ready() and not hicolor:
            raise ValueError('Native font drawing requires verified52 or profile0 raw7A setup')
        capability = self.ddp.cluster_capabilities
        kind = command.get('command')
        if kind == 'draw_native_symbols':
            if not hicolor:
                raise ValueError('Native69 symbols require verified profile0 raw7A setup')
            symbols = command.get('symbols')
            if not isinstance(symbols, (list, tuple)) or not 1 <= len(symbols) <= 512:
                raise ValueError('Native symbols require1..512 raw[x,y,symbol] entries')
            records = raw_symbol_records(capability, symbols)
            source = dict(command=kind, symbols=[list(row) for row in symbols])
        elif kind == 'draw_native_font':
            flags = command.get('flags', 0x0B)
            if type(flags) is not int or flags not in (0x0A, 0x0B):
                raise ValueError('Verified native graphics fonts are raw0A/0B')
            glyphs = command.get('glyphs')
            if not isinstance(glyphs, (list, tuple, bytes, bytearray)):
                raise ValueError('Native glyphs must be binary byte values')
            x, y = command.get('x', 0), command.get('y', 0)
            records = (raw_graphics_record(capability, x, y, glyphs, flags),)
            source = dict(command=kind, x=x, y=y, flags=flags, glyphs=list(glyphs))
            if 'field_id' in command:
                field_id = command['field_id']
                if (not isinstance(field_id, str) or not 1 <= len(field_id) <= 128
                        or any(not (c.isascii() and (c.isalnum() or c in '_.:-')) for c in field_id)):
                    raise ValueError('Native font field_id requires1..128 ASCII identifier characters')
                # OEM ring objects can layer several records at the same
                # anchor. Keep their identities and original insertion order.
                source['field_id'] = field_id
                if field_id.startswith('nav_bar_') and not self._is_native_bar_field(source):
                    raise ValueError('Reserved native bar identity requires exact bar cell')
        elif kind == 'draw_stock_nav_object':
            if not hicolor:
                raise ValueError('Stock source object requires verified profile0 raw7A setup')
            from stock_nav_composition import StockNavComposition
            composer = getattr(self, '_stock_nav_composer', None)
            if composer is None:
                composer = self._stock_nav_composer = StockNavComposition()
            raw_object = command.get('source_object')
            records = composer.object_records(capability, raw_object)
            source = dict(command=kind, source_object=list(raw_object))
        elif kind == 'draw_stock_nav_composition':
            if not hicolor:
                raise ValueError('Stock composition requires verified profile0 raw7A setup')
            from stock_nav_composition import StockNavComposition
            composer = getattr(self, '_stock_nav_composer', None)
            if composer is None:
                composer = self._stock_nav_composer = StockNavComposition()
            selector = command.get('maneuver_type')
            directions = command.get('directions')
            keys = command.get('auxiliary_keys', [])
            position = command.get('auxiliary_position', 'after')
            records = composer.records(capability, selector, directions, keys, position)
            source = dict(command=kind, maneuver_type=selector, directions=list(directions),
                          auxiliary_keys=list(keys), auxiliary_position=position)
        elif kind == 'draw_stock_nav_glyph':
            directions = command.get('directions')
            if not isinstance(directions, (list, tuple)):
                raise ValueError('Stock directions must be raw selector byte values')
            catalog = getattr(self, '_stock_nav_glyph_catalog', None)
            if catalog is None:
                catalog = self._stock_nav_glyph_catalog = StockNavGlyphCatalog()
            selector = command.get('maneuver_type')
            records = catalog.absolute_records(capability, selector, directions)
            source = dict(command=kind, maneuver_type=selector, directions=list(directions))
        else:
            raise ValueError('Native font compiler accepts only public verified commands')
        if not records:
            raise ValueError('Native font command has no verified glyph records')
        budget = self._graphics_message_budget()
        messages, pending = [], bytearray()
        if hicolor:
            # Stock8055B4A0 emits D102(0) before its initial symbol records.
            # Preserve exact metadata; no inferred clear/clip field names.
            catalog = getattr(self, '_stock_nav_glyph_catalog', None)
            if catalog is None:
                catalog = self._stock_nav_glyph_catalog = StockNavGlyphCatalog()
            pending.extend(b''.join(catalog.frame_records(capability, 0)))
        for record in records:
            # Bounds are command-anchor bounds, not a guessed glyph bounding
            #box or global-LCD interpretation of the raw stock coordinates.
            if not hicolor and not (record[3] < 64 and record[4] < self.region_height):
                raise ValueError('Native glyph anchor is outside the selected command region')
            if len(record) > budget:
                raise ValueError('One native font record exceeds application message budget')
            if pending and len(pending) + len(record) > budget:
                messages.append(bytes(pending)); pending.clear()
            pending.extend(record)
        if pending:
            messages.append(bytes(pending))
        return dict(command='_native_font_frame', source=source,
                    messages=tuple(messages), capability_record=tuple(capability.raw),
                    setup_record=tuple(self.ddp.application_setup_record),
                    compiled_generation=getattr(self.ddp, 'state_generation', 0),
                    region=(self.region_name, self.region_y_offset, self.region_height))

    def _coalesce_native_font_commands(self, commands):
        """Pack adjacent verified52 font records after desired-cache updates.

        Cache entries remain the original per-field public commands. This
        transient execution copy preserves record order, region and the exact
        capability/setup/generation; all normal send-time checks still apply.
        Raw7A metadata and other native command types retain their old path.
        """
        if (self.ddp.renderer_command_family() != 0x52
                or not self.ddp.renderer_ready()
                or getattr(self, 'UNSAFE_BATCHING_BYPASS', False)):
            return commands
        budget = self._graphics_message_budget()
        result, group = [], []
        context_keys = ('capability_record', 'setup_record', 'compiled_generation', 'region')
        def flush():
            if len(group) < 2:
                result.extend(group)
            else:
                messages, pending = [], bytearray()
                for frame in group:
                    for message in frame['messages']:
                        if pending and len(pending) + len(message) > budget:
                            messages.append(bytes(pending)); pending.clear()
                        pending.extend(message)
                if pending:
                    messages.append(bytes(pending))
                merged = dict(group[0])
                merged['messages'] = tuple(messages)
                result.append(merged)
            group.clear()
        for command in commands:
            eligible = (command.get('command') == '_native_font_frame'
                and command.get('source', {}).get('command') == 'draw_native_font'
                and command.get('messages')
                and all(isinstance(m, bytes) and 0 < len(m) <= budget
                        for m in command['messages']))
            if not eligible:
                flush(); result.append(command); continue
            if group and any(command.get(key) != group[0].get(key) for key in context_keys):
                flush()
            group.append(command)
        flush()
        return result

    def _send_native_font_frame(self, command):
        """Use ordinary ownership, error reporting and bounded TP packet path."""
        if (not self.screen_is_active or self.ddp.state != DDPState.READY
                or not (self.ddp.renderer_ready() or self._native_7a_ready(owned=True))
                or command['capability_record'] != tuple(self.ddp.cluster_capabilities.raw)
                or command.get('setup_record') != tuple(self.ddp.application_setup_record)
                or command.get('compiled_generation') != getattr(self.ddp, 'state_generation', 0)
                or command['region'] != (self.region_name, self.region_y_offset, self.region_height)):
            self._frame_failed = True
            return False
        generation = getattr(self.ddp, 'state_generation', 0)
        for payload in command['messages']:
            composition = command['source']['command'] in ('draw_stock_nav_composition', 'draw_stock_nav_object')
            success = (self._send_graphics(list(payload), native=True, stock_composition=True)
                       if composition else self._send_graphics(list(payload), native=True))
            if (not success
                    or getattr(self.ddp, 'state_generation', 0) != generation):
                self._frame_failed = True
                return False
            self.ddp.poll_bus_events()
            self.ddp.send_keepalive_if_needed()
            if self.ddp.state != DDPState.READY or getattr(self.ddp, 'state_generation', 0) != generation:
                self._frame_failed = True
                return False
        return True

    def _expand_draw_command(self, command):
        try:
            self._validate_native_bar_retirement(command)
        except (ValueError, TypeError):
            self._publish_frame_result(command.get('seq', 0), False)
            return []
        if command.get('command') in ('draw_stock_mono_frame', '_stock_mono_frame'):
            try:
                if command['command'] != 'draw_stock_mono_frame':
                    raise ValueError('Internal stock mono bodies are not public IPC')
                return [self._stock_mono_command(command), {'command': 'commit', 'seq': command.get('seq', 0)}]
            except (ValueError, TypeError, KeyError, OSError) as exc:
                logger.error('Rejected stock mono frame: %s', exc)
                self._publish_frame_result(command.get('seq', 0), False)
                return []
        if (self.ddp.renderer_command_family() == 0x7A
                and command.get('command') not in ('draw_native_symbols', 'draw_stock_nav_glyph', 'draw_stock_nav_composition', 'draw_stock_nav_object', 'frame', 'commit', 'pause', 'resume')):
            logger.warning('Raw7A consumer refuses unproved text/bitmap/clear/region command')
            self._publish_frame_result(command.get('seq', 0), False)
            return []
        if command.get('command') in ('draw_native_font', 'draw_native_symbols', 'draw_stock_nav_glyph', 'draw_stock_nav_composition', 'draw_stock_nav_object', '_native_font_frame'):
            try:
                return self._stock_custom_transition([self._native_font_command(command)])
            except (ValueError, TypeError, KeyError, OSError) as exc:
                logger.error('Rejected native glyph command: %s', exc)
                self._publish_frame_result(command.get('seq', 0), False)
                return []
        # Prepare the entire snapshot before a claim or any drawing writes.
        if command.get('command') in ('draw_native_bitmap', '_native_bitmap_frame'):
            try:
                if command['command'] == '_native_bitmap_frame':
                    raise ValueError('Internal native frame commands are not public IPC')
                body = self._native_bitmap_command(command)
                return self._stock_custom_transition([body, {'command': 'commit', 'seq': command.get('seq', 0)}])
            except (ValueError, TypeError) as exc:
                logger.error('Rejected native bitmap: %s', exc)
                self._publish_frame_result(command.get('seq', 0), False)
                return []
        if command.get('command') == 'frame':
            commands = command.get('commands', [])
            if isinstance(commands, list) and any(isinstance(c, dict) and c.get('command') == 'draw_stock_mono_frame' for c in commands):
                try:
                    if (len(commands) not in (1, 2) or not all(isinstance(c, dict) for c in commands)
                            or commands[-1].get('command') != 'draw_stock_mono_frame'
                            or (len(commands) == 2 and commands[0] != {'command': 'resume'})):
                        raise ValueError('Stock mono frame accepts one complete snapshot and optional leading resume only')
                    body = self._stock_mono_command(commands[-1])
                    return commands[:-1] + [body, {'command': 'commit', 'seq': command.get('seq', 0)}]
                except (ValueError, TypeError, KeyError, OSError) as exc:
                    logger.error('Rejected stock mono transaction: %s', exc)
                    self._publish_frame_result(command.get('seq', 0), False)
                    return []
            allowed = {'resume', 'set_region', 'clear', 'clear_payload',
                       'clear_area', 'draw_text', 'update_text', 'draw_bitmap',
                       'draw_raw_bitmap', 'draw_line', 'draw_native_bitmap',
                       'draw_native_font', 'draw_native_symbols', 'draw_stock_nav_glyph', 'draw_stock_nav_composition', 'draw_stock_nav_object'}
            if not isinstance(commands, list) or any(
                    not isinstance(c, dict) or c.get('command') not in allowed for c in commands):
                self._publish_frame_result(command.get('seq', 0), False)
                return []
            try:
                if (self.ddp.renderer_command_family() == 0x7A and any(
                        c.get('command') not in ('draw_native_symbols', 'draw_stock_nav_glyph', 'draw_stock_nav_composition', 'draw_stock_nav_object') for c in commands)):
                    raise ValueError('Raw7A frame accepts only verified symbol/font commands')
                if any(c.get('command') in ('draw_native_bitmap', 'draw_native_font', 'draw_native_symbols', 'draw_stock_nav_glyph', 'draw_stock_nav_composition', 'draw_stock_nav_object') for c in commands) and any(
                        c.get('command') == 'set_region' for c in commands):
                    raise ValueError('A native snapshot frame cannot change its region')
                for c in commands:
                    self._validate_native_bar_retirement(c)
                    if c.get('command') == 'update_text':
                        self.get_text_update_payload(c)
                if (any('retire_native_field_ids' in c for c in commands)
                        and any(c.get('command') == 'set_region' for c in commands)):
                    raise ValueError('Native bar retirement cannot change its region')
                expanded = [self._native_font_command(c) if c.get('command') in ('draw_native_font', 'draw_native_symbols', 'draw_stock_nav_glyph', 'draw_stock_nav_composition', 'draw_stock_nav_object')
                            else self._native_bitmap_command(c) if c.get('command') == 'draw_native_bitmap'
                            else c for c in commands]
            except (ValueError, TypeError, KeyError, OSError) as exc:
                logger.error('Rejected drawing frame: %s', exc)
                self._publish_frame_result(command.get('seq', 0), False)
                return []
            return self._stock_custom_transition(expanded + [{'command': 'commit', 'seq': command.get('seq', 0)}])
        if command.get('command') == 'update_text':
            try:
                self.get_text_update_payload(command)
            except (ValueError, TypeError) as exc:
                logger.error('Rejected atomic text: %s', exc)
                return []
        return self._stock_custom_transition([command])

    def _stock_custom_transition(self, expanded):
        """A custom update after a stock snapshot drops its cache and window."""
        drawable = ('draw_text', 'update_text', 'draw_bitmap', 'draw_line', 'draw_raw_bitmap',
                    'draw_raw_bitmap_batch', '_native_bitmap_frame', '_native_font_frame')
        if (any(c.get('command') == 'draw_stock_mono_frame' for c in self.command_cache.values())
                and any(c.get('command') in drawable for c in expanded)
                and not any(c.get('command') in ('clear', 'clear_payload', 'set_region') for c in expanded)):
            return [{'command': 'clear_payload'}] + expanded
        return expanded

    def _stock_queue_transitions(self, commands):
        """Normalize mode changes even when several IPC frames drain at once."""
        stock = any(c.get('command') == 'draw_stock_mono_frame' for c in self.command_cache.values())
        ordinary = ('draw_text', 'update_text', 'draw_bitmap', 'draw_line', 'draw_raw_bitmap',
                    'draw_raw_bitmap_batch', '_native_bitmap_frame', '_native_font_frame')
        result = []
        for command in commands:
            kind = command.get('command')
            if kind in ('clear', 'clear_payload', 'set_region', 'pause'):
                stock = False
            elif kind == '_stock_mono_frame':
                stock = True
            elif stock and kind in ordinary:
                result.append({'command': 'clear_payload'})
                stock = False
            result.append(command)
        return result

    def _reject_draw_commands(self, commands):
        # Ownership controls are not failed drawing frames. A standalone
        # resume while unclaimed must not poison the following valid update.
        if not commands or all(c.get('command') in ('pause', 'resume', 'set_region') for c in commands):
            return
        self._frame_failed = True
        for command in commands:
            if command.get('command') in ('commit', 'frame', 'draw_native_bitmap', 'draw_stock_mono_frame'):
                self._publish_frame_result(command.get('seq', 0), False)
                self._frame_failed = False

    def commit_frame(self):
        payload = [0x39]
        success = self._send_graphics(payload)
        if not success:
            logger.error("Failed to send commit packet.")
        return success

    def clear_screen(self):
        if self.ddp.renderer_command_family() == 0x7A:
            # Internal boot/recovery initialization uses the native frame0
            #prelude and distinct39; public7A clear commands are rejected.
            return self.clear_screen_payload() and self.commit_frame()
        logger.info("Executing full clear_screen command...")
        payload_clear = [0x52, 0x05, 0x02, 0x00, self.region_y_offset, 0x40, self.region_height]
        payload_reset = [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        if (not self._send_graphics(payload_clear + payload_reset)
                or not self.commit_frame()):
            logger.error("clear_screen: Failed to send frame.")
            

    def _invalidate_cached_lines(self, clear):
        """Drop fully erased axis-aligned lines before caching replacement bars."""
        x, y = clear.get('x', 0), clear.get('y', 0)
        w, h = clear.get('w', 64), clear.get('h', 9)
        for key, cached in list(self.command_cache.items()):
            if cached.get('command') != 'draw_line':
                continue
            orientation = cached.get('orientation')
            if orientation is None:
                orientation = 0x10 if cached.get('vertical', True) else 0x20
            length = cached.get('length', 0)
            if orientation not in (0x10, 0x20) or length <= 0:
                continue
            cx, cy = cached.get('x', 0), cached.get('y', 0)
            cw, ch = (1, length) if orientation == 0x10 else (length, 1)
            if x <= cx and y <= cy and cx + cw <= x + w and cy + ch <= y + h:
                self.command_cache.pop(key, None)

    @staticmethod
    def _is_native_bar_field(source):
        y = source.get('y')
        return (source.get('command') == 'draw_native_font' and type(y) is int
                and y in (3, 10, 17, 24, 31) and source.get('field_id') == 'nav_bar_%d' % y
                and type(source.get('x')) is int and source['x'] == 57
                and type(source.get('flags')) is int and source['flags'] == 0x0A
                and type(source.get('glyphs')) is list and len(source['glyphs']) == 1
                and type(source['glyphs'][0]) is int
                and source['glyphs'][0] in (0x3A, 0x69, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F))

    def _validate_native_bar_retirement(self, command):
        """Only the reserved five bar fields may accompany their exact erase."""
        if 'retire_native_field_ids' not in command:
            return
        expected = ['nav_bar_%d' % y for y in (3, 10, 17, 24, 31)]
        ids = command['retire_native_field_ids']
        if (command.get('command') != 'clear_area' or type(ids) is not list
                or ids != expected or any(type(value) is not str for value in ids)
                or any(type(command.get(k)) is not int for k in ('x', 'y', 'w', 'h'))
                or tuple(command[k] for k in ('x', 'y', 'w', 'h')) != (57, 3, 6, 36)
                or self.region_name != 'central' or self.region_y_offset != 27
                or self.region_height != 48 or not self.ddp.renderer_ready(0x52)):
            raise ValueError('Native bar retirement requires exact central52 bar erase')
        if any(c.get('field_id') in ids and not self._is_native_bar_field(c)
               for c in self.command_cache.values()):
            raise ValueError('Reserved bar identity contains an incompatible cached source')

    def _retire_native_bar_fields(self, command):
        ids = set(command.get('retire_native_field_ids', ()))
        for key, source in list(self.command_cache.items()):
            if source.get('command') == 'draw_native_font' and source.get('field_id') in ids:
                self.command_cache.pop(key, None)

    def _native_field_cache_bounded(self, commands):
        """Bound ordered field identities before mutating cache or drawing."""
        if (any('retire_native_field_ids' in c for c in commands)
                and any(c.get('command') == 'set_region' for c in commands)):
            return False
        fields = {c['field_id'] for c in self.command_cache.values()
                  if c.get('command') == 'draw_native_font' and 'field_id' in c}
        for command in commands:
            kind = command.get('command')
            if kind in ('clear', 'clear_payload', 'set_region', '_stock_mono_frame'):
                fields.clear()
            elif kind == '_native_bitmap_frame' and command['source'].get('update_rect') is None:
                fields.clear()
            elif kind == 'clear_area':
                fields.difference_update(command.get('retire_native_field_ids', ()))
            elif kind == '_native_font_frame':
                source = command['source']
                if source.get('command') == 'draw_native_font' and 'field_id' in source:
                    fields.add(source['field_id'])
                    if len(fields) > 512:
                        return False
        return True

    def handle_redraw(self):
        logger.info("Restoring screen content after interruption or clearing...")
        stock = [c for c in self.command_cache.values() if c.get('command') == 'draw_stock_mono_frame']
        if stock:
            # Cache contains desired source only. Rebuild after every grant,
            # and reject a mixed cache rather than restoring stale overlays.
            self._frame_failed = False
            if len(stock) != 1 or len(self.command_cache) != 1:
                self._frame_failed = True
                return self._finish_frame(0)
            try:
                self._send_stock_mono_frame(self._stock_mono_command(stock[0]))
            except (ValueError, TypeError, KeyError, OSError):
                self._frame_failed = True
            return self._finish_frame(0)
        if any(c.get('command') == 'draw_native_bitmap' or
               (c.get('command') == 'draw_native_font' and 'field_id' in c)
               for c in self.command_cache.values()):
            sorted_cmds = list(self.command_cache.values())
            nav_fonts = [c for c in sorted_cmds if c.get('command') == 'draw_native_font']
            nav_texts = [c for c in sorted_cmds if c.get('command') == 'draw_text']
            if (nav_fonts and nav_texts
                    and all(self._is_native_bar_field(c) or
                            str(c.get('field_id', '')).startswith('nav_icon_') for c in nav_fonts)
                    and all(c.get('field_id') in ('street:0', 'dist:0', 'dist:1') for c in nav_texts)):
                # Bars can be added after unchanged numeric text. Preserve
                # constituent order, then restore every text overlay last.
                sorted_cmds = ([c for c in sorted_cmds if c.get('command') != 'draw_text']
                               + [c for c in sorted_cmds if c.get('command') == 'draw_text'])
        else:
            sorted_cmds = sorted(self.command_cache.values(), key=lambda item: (item.get('y',0), item.get('x',0)))
        try:
            native_frames = {id(cmd): self._native_bitmap_command(cmd) for cmd in sorted_cmds
                             if cmd.get('command') == 'draw_native_bitmap'}
            native_fonts = {id(cmd): self._native_font_command(cmd) for cmd in sorted_cmds
                             if cmd.get('command') in ('draw_native_font', 'draw_native_symbols', 'draw_stock_nav_glyph', 'draw_stock_nav_composition', 'draw_stock_nav_object')}
            if (self.ddp.renderer_command_family() == 0x7A and any(
                    cmd.get('command') not in ('draw_native_symbols', 'draw_stock_nav_glyph', 'draw_stock_nav_composition', 'draw_stock_nav_object') for cmd in sorted_cmds)):
                raise ValueError('Cannot restore incompatible cached commands to raw7A')
        except (ValueError, TypeError, KeyError, OSError) as exc:
            self._frame_failed = True
            logger.error('Cannot restore native graphics: %s', exc)
            return False
        # Recovery starts a fresh frame; a failed previous restore must not
        # permanently suppress future writes through the failure latch.
        self._frame_failed = False
        if self.ddp.renderer_command_family() != 0x7A:
            self.clear_screen_payload()
        
        # Retain desired-cache identities; pack only transient compiled fonts.
        render_cmds = self._coalesce_native_font_commands([
            native_fonts[id(cmd)] if id(cmd) in native_fonts else cmd
            for cmd in sorted_cmds])
        for cmd in render_cmds:
            c = cmd.get('command')
            if c == 'draw_text':
                options = {key: cmd[key] for key in ('highlight_width', 'highlight_height') if key in cmd}
                self.write_text(cmd.get('text',''), cmd.get('x',0), cmd.get('y',0), cmd.get('flags', 0x06), **options)
            elif c == 'draw_bitmap':
                self.draw_bitmap(cmd.get('x',0), cmd.get('y',0), cmd.get('icon_name'), cmd.get('mode_flag', 0x02))
            elif c == 'draw_native_bitmap':
                self._send_native_bitmap_frame(native_frames[id(cmd)])
            elif c == '_native_font_frame':
                self._send_native_font_frame(cmd)
            elif c == 'draw_line':
                self.draw_line(cmd.get('x',0), cmd.get('y',0), cmd.get('length',0), cmd.get('vertical', True), cmd.get('orientation', None))
        
        return self._finish_frame(0)

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
        
        logger.info("Starting DisService main loop.")
        while self.running:
            try:
                # 0. Check for Ignition Status
                # (Logic previously handled inside while True)
                # --- CHECK IGNITION STATUS ---
                socks = dict(self.poller.poll(10)) # Short poll (10ms)
                if self.ignition_sub in socks:
                    try:
                        while True: # Drain queue
                            parts = self.ignition_sub.recv_multipart(flags=zmq.NOBLOCK)
                            if len(parts) == 2 and parts[0] == b'POWER_STATUS':
                                pwr = json.loads(parts[1])
                                new_ign = pwr.get('kl15', False) or pwr.get('bus_active', False)
                                
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

                # --- DIS ENABLED CHECK ---
                if not self.config.get('display', {}).get('center_display', {}).get('enabled', True):
                    # Enter dormant loop: drain draw_socket and wait
                    try:
                        while True:
                            self.draw_socket.recv_json(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        pass
                    
                    if getattr(self, 'last_enable_log', 0) < time.time() - 3600:
                        logger.info("DIS Service is DISABLED in config.json. Standing by...")
                        self.last_enable_log = time.time()
                    
                    time.sleep(1.0)
                    continue

                # --- NORMAL OPERATION (IGNITION ON) ---
                self._broadcast_status()

                if self.ddp.state == DDPState.DISCONNECTED:
                    self.screen_is_active = False
                    self.claim_retry_count = 0 
                    
                    # Proactive cleanup for first-run or after crash
                    if not getattr(self, 'init_cleanup_done', False):
                        logger.info("Service Startup: Sending proactive Close (A8) to clear zombie sessions.")
                        self.ddp.close_session()
                        self.init_cleanup_done = True
                        time.sleep(1.0) # Wait for cluster to settle

                    if self.ddp.detect_and_open_session():
                        logger.info(f"Session established (Mode: {self.ddp.dis_mode.name}).")
                    else:
                        time.sleep(1.0) # Faster retry when ON
                elif self.ddp.state == DDPState.SESSION_ACTIVE:
                    if not self.ddp.perform_initialization():
                        logger.error("DDP Initialization failed. Retrying.")
                        time.sleep(3)
                    else:
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
                            command = self.draw_socket.recv_json(flags=zmq.NOBLOCK)
                            self._presentation_control(command.get('command'))
                            self._reject_draw_commands([command])
                    except zmq.Again:
                        pass
                    time.sleep(0.05)
                elif self.ddp.state == DDPState.READY:
                    self.ddp.send_keepalive_if_needed()
                    self.ddp.poll_bus_events()
                    if getattr(self.ddp, 'screen_released_by_cluster', False):
                        logger.info("Screen release/re-init detected from cluster. Resetting screen_is_active flag.")
                        self.screen_is_active = False
                        self.ddp.screen_released_by_cluster = False
                        self.last_claim_attempt = time.time()
                    self._broadcast_status()
                    if self.ddp.state != DDPState.READY: continue
                    if self.presentation_requested and not self.screen_is_active and self.command_cache:
                         now = time.time()
                         if self._restore_claim_due(now):
                             logger.info("Auto-Restore triggered.")
                             self.last_claim_attempt = now
                             if self.claim_nav_screen():
                                 self.handle_redraw()
                    socks = dict(self.poller.poll(5))
                    if self.draw_socket in socks:
                        cmds = []
                        try:
                            while True:
                                cmds.extend(self._expand_draw_command(self.draw_socket.recv_json(flags=zmq.NOBLOCK)))
                        except zmq.Again: pass

                        cmds = self._stock_queue_transitions(cmds)
                        if not self._native_field_cache_bounded(cmds):
                            logger.error('Rejected ordered native font cache beyond512 fields')
                            self._reject_draw_commands(cmds)
                            cmds = []
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
                                elif c == 'clear_area':
                                    self._retire_native_bar_fields(cmd)
                                    self._invalidate_cached_lines(cmd)
                                elif c == '_native_bitmap_frame':
                                    # All entries belong to the currently selected region.
                                    # Preflight requires central; a full snapshot replaces it.
                                    rect = cmd['source'].get('update_rect')
                                    if rect is None:
                                        self.command_cache = {('draw_native_bitmap', 0, 0): cmd['source']}
                                    else:
                                        key = ('draw_native_bitmap', *rect)
                                        self.command_cache.pop(key, None)
                                        self.command_cache[key] = cmd['source']
                                elif c == '_native_font_frame':
                                    source = cmd['source']
                                    key = ((source['command'], 'field', source['field_id'])
                                           if 'field_id' in source else
                                           (source['command'], source.get('y', 0), source.get('x', 0)))
                                    self.command_cache[key] = source
                                elif c == '_stock_mono_frame':
                                    # Whole desired stock snapshot replaces custom history;
                                    # a failed transfer never becomes a known pixel cache.
                                    self.command_cache = {('draw_stock_mono_frame', 0, 0): cmd['source']}
                                elif self._presentation_control(c):
                                    continue
                                elif c in ['draw_text', 'update_text', 'draw_bitmap', 'draw_line']:
                                    k = (('draw_text', 'field', cmd['field_id']) if c == 'update_text' and 'field_id' in cmd
                                         else ('draw_text' if c == 'update_text' else c, cmd.get('y', 0), cmd.get('x', 0)))
                                    if any(c.get('command') == 'draw_native_bitmap' for c in self.command_cache.values()):
                                        self.command_cache.pop(k, None)  # Preserve overlay update order.
                                    if c == 'update_text':
                                        self.command_cache[k] = {key: value for key, value in cmd.items() if key != 'clear_rect'}
                                        self.command_cache[k]['command'] = 'draw_text'
                                    else:
                                        self.command_cache[k] = cmd
                            
                            # Control-only or stale batches cannot activate navigation.
                            drawable = any(cmd.get('command') in ('draw_text', 'update_text', 'draw_bitmap', 'draw_raw_bitmap', 'draw_line', '_native_bitmap_frame', '_native_font_frame', '_stock_mono_frame') for cmd in cmds)
                            if not self.presentation_requested or (not self.screen_is_active and not drawable):
                                self._reject_draw_commands(cmds)
                                continue
                            if not self.screen_is_active:
                                if not self.claim_nav_screen():
                                    logger.error("Failed to claim screen.")
                                    self._reject_draw_commands(cmds)
                                    continue
                            
                            self.last_draw_time = time.time()

                            # PROCESS COMMANDS WITH SIZE-LIMITED BATCHING
                            # We combine related commands (like wipe + text) into a single 
                            # application message when they fit the configured bounded budget. This avoids
                            # the 20ms inter-block pacing delay causing flicker.
                            current_payload = []
                            # must_colocate: True when current_payload ends with a clear_area
                            # whose paired draw command has not yet been appended.
                            # While True, the next drawable payload is always added to the
                            # same message as the clear (no exposed wipe allowed) and the
                            # Text pairs flush immediately; line pairs remain pending so
                            # subsequent bar strokes can share the same bounded message.
                            must_colocate = False
                            cmds = self._coalesce_bitmap_commands(cmds)
                            cmds = self._coalesce_native_font_commands(cmds)
                            for cmd in cmds:
                                c = cmd.get('command')
                                p = []
                                if c == 'clear':
                                    if current_payload:
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                        self.ddp.poll_bus_events()
                                        self.ddp.send_keepalive_if_needed()
                                    self.clear_screen()
                                    must_colocate = False
                                    continue
                                elif c == 'clear_payload':
                                    if current_payload:
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                        self.ddp.poll_bus_events()
                                        self.ddp.send_keepalive_if_needed()
                                    self.clear_screen_payload()
                                    must_colocate = False
                                    continue
                                elif c == 'set_region':
                                    if current_payload:
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                        self.ddp.poll_bus_events()
                                        self.ddp.send_keepalive_if_needed()
                                    must_colocate = False
                                    continue
                                elif c == 'update_text':
                                    # This complete unit is indivisible in the generic packer.
                                    try:
                                        p = self.get_text_update_payload(cmd)
                                    except (ValueError, TypeError) as exc:
                                        self._frame_failed = True
                                        logger.error('Rejected atomic text: %s', exc)
                                        continue
                                elif c == 'draw_text':
                                        options = {key: cmd[key] for key in ('highlight_width', 'highlight_height') if key in cmd}
                                        p = self.get_text_payload(cmd.get('text', ''), cmd.get('x', 0), cmd.get('y', 0), cmd.get('flags', 0x06), **options)
                                elif c == 'draw_bitmap':
                                    if current_payload:
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                    must_colocate = False
                                    self.draw_bitmap(cmd.get('x', 0), cmd.get('y', 0), cmd.get('icon_name'), cmd.get('mode_flag', 0x02))
                                    continue
                                elif c == 'draw_line':
                                    p = self.get_line_payload(
                                        cmd.get('x', 0),
                                        cmd.get('y', 0),
                                        cmd.get('length', 0),
                                        cmd.get('vertical', True),
                                        cmd.get('orientation', None)
                                    )
                                elif c == 'clear_area':
                                    # Flush whatever was pending BEFORE starting the clear,
                                    # so the clear begins a fresh frame with its paired draw.
                                    if current_payload:
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                        self.ddp.poll_bus_events()
                                        self.ddp.send_keepalive_if_needed()
                                    p = self.get_clear_area_payload(cmd.get('x', 0), cmd.get('y', 0), cmd.get('w', 64), cmd.get('h', 9))
                                    current_payload = p
                                    must_colocate = True  # next draw must share this frame
                                    continue
                                elif c == 'commit':
                                    seq = cmd.get('seq', 0)
                                    if current_payload:
                                        self._finish_frame(seq, pending_payload=current_payload)
                                        current_payload = []
                                        # Poll after drawing to keep session alive during burst.
                                        self.ddp.poll_bus_events()
                                        self.ddp.send_keepalive_if_needed()
                                    else:
                                        self._finish_frame(seq)
                                    must_colocate = False
                                    continue
                                elif c == 'draw_raw_bitmap_batch':
                                    if must_colocate:
                                        self._send_raw_bitmap_batch(cmd['commands'], prefix=current_payload)
                                    else:
                                        if current_payload:
                                            self._send_graphics(current_payload)
                                        self._send_raw_bitmap_batch(cmd['commands'])
                                    current_payload = []
                                    must_colocate = False
                                    self.ddp.poll_bus_events()
                                    self.ddp.send_keepalive_if_needed()
                                    continue
                                elif c == '_native_bitmap_frame':
                                    if current_payload:
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                    must_colocate = False
                                    self._send_native_bitmap_frame(cmd)
                                    continue
                                elif c == '_native_font_frame':
                                    if current_payload:
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                    must_colocate = False
                                    self._send_native_font_frame(cmd)
                                    continue
                                elif c == '_stock_mono_frame':
                                    if current_payload:
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                    must_colocate = False
                                    self._send_stock_mono_frame(cmd)
                                    continue
                                elif c == 'draw_raw_bitmap':
                                    try:
                                        raw_bytes = bytes.fromhex(cmd.get('data_hex', ''))
                                        w, h, x, y = cmd.get('w', 64), cmd.get('h', 88), cmd.get('x', 0), cmd.get('y', 0)
                                        mode_flag = cmd.get('mode_flag', 0x02)
                                        abs_y = y + self.region_y_offset
                                        if not (0 <= x <= 64 - w and 0 <= y <= self.region_height - h):
                                            raise ValueError('Invalid bitmap position')
                                        row_records = self._bitmap_row_records(raw_bytes, w, h, mode_flag)

                                        if self.UNSAFE_BATCHING_BYPASS:
                                            # If we are NOT batching, we flush the current payload to clear the queue,
                                            # then manually frame-out the clip, rows, and reset using pacing=False 
                                            # to aggressively override the 20ms cluster delay. This is known to cause 
                                            # tearing on some clusters if abused, but keeps frames cohesive.
                                            if current_payload:
                                                self._send_graphics(current_payload)
                                                current_payload = []
                                            must_colocate = False
                                            
                                            payload_clip = [0x52, 0x05, 0x00, x, abs_y, w, h]
                                            if self._send_graphics(payload_clip, pacing=False):
                                                block_payload = []
                                                for record in row_records:
                                                    if block_payload and len(block_payload) + len(record) > self._bitmap_message_budget():
                                                        if not self._send_graphics(block_payload, pacing=False):
                                                            break
                                                        block_payload = []
                                                    block_payload += record
                                                if block_payload:
                                                    self._send_graphics(block_payload, pacing=False)
                                                self._send_graphics([0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height])
                                        else:
                                            # Keep clip/reset and complete row commands within the
                                            # configured application-message budget. TP2 ACK sizes
                                            # remain independent transport settings.
                                            cmd_parts = [[0x52, 0x05, 0x00, x, abs_y, w, h]] + row_records
                                            cmd_parts.append([0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height])
                                            
                                            for part in cmd_parts:
                                                if current_payload and (len(current_payload) + len(part) > self._bitmap_message_budget()):
                                                    self._send_graphics(current_payload, pacing=False)
                                                    current_payload = []
                                                    self.ddp.poll_bus_events()
                                                    self.ddp.send_keepalive_if_needed()
                                                    must_colocate = False
                                                current_payload += part
                                            
                                            p = []  # Bypass generic append since we injected parts manually
                                    except Exception as e:
                                        self._frame_failed = True
                                        logger.error(f"Failed parsing raw bitmap: {e}")
                                
                                if p:
                                    if len(p) > self._graphics_message_budget():
                                        self._frame_failed = True
                                        logger.error('Drawing command exceeds application message budget')
                                        current_payload = []
                                        must_colocate = False
                                        continue
                                    if must_colocate:
                                        # This draw is the atomic pair for the preceding clear.
                                        # Never expose the wipe in a separate application message.
                                        if len(current_payload) + len(p) > self._graphics_message_budget():
                                            self._frame_failed = True
                                            logger.error('Clear/draw pair exceeds application message budget')
                                            current_payload = []
                                            must_colocate = False
                                            continue
                                        current_payload += p
                                        must_colocate = False
                                        # A bar is several adjacent strokes. Keep them with
                                        # its clear while they fit, avoiding a partial bar.
                                        if c != 'draw_line':
                                            self._send_graphics(current_payload)
                                            current_payload = []
                                            self.ddp.poll_bus_events()
                                            self.ddp.send_keepalive_if_needed()
                                    elif current_payload and (len(current_payload) + len(p) > self._graphics_message_budget()):
                                        self._send_graphics(current_payload)
                                        current_payload = p
                                        # Poll after drawing to keep session alive during burst
                                        self.ddp.poll_bus_events()
                                        self.ddp.send_keepalive_if_needed()
                                    else:
                                        current_payload += p

                            if current_payload:
                                self._send_graphics(current_payload)
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
    service = DisService(config_path='/home/pi/config.json')
    try:
        service.run()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
