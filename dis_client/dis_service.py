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
        # Set to True to disable the new 42-byte DDP block batching for raw bitmaps. 
        # Batching speeds up GIFs drastically by combining rows into single CAN frames,
        # but some clusters may need pacing=False (unbatched) to prevent tearing.
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
        self.ENABLE_INACTIVITY_RELEASE = False

        # Default region: 'central'
        self.region_name = 'central'
        self.region_y_offset = 0x1B
        self.region_height = 0x30
        
        # Recovery state
        self.last_claim_attempt = 0.0
        self.claim_retry_count = 0
        self.init_cleanup_done = False # Track if upfront zombie cleanup was done

    @property
    def screen_is_active(self):
        return self._screen_is_active

    @screen_is_active.setter
    def screen_is_active(self, value):
        if not value:
            self._native_known_image = None
        if self._screen_is_active != value:
            self._screen_is_active = value

        if not self.ENABLE_INACTIVITY_RELEASE and value:
            logger.info("Inactivity auto-release is DISABLED (screen will stay claimed forever)")
        self._broadcast_status()

    def _broadcast_status(self, force=False):
        """Broadcast current DDP state via ZMQ."""
        now = time.time()
        current_state = getattr(self.ddp, 'state', None)
        
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

    def claim_nav_screen(self):
        """Request ownership once; busy is a normal asynchronous state."""
        if self.ddp.state != DDPState.READY or not self.presentation_requested:
            return False
        full = self.region_name in ['full', 'top_centre']
        y, height = (0, 0x58) if full else (0x1B, self.region_height)
        claim = [0x52, 0x05, 0x82, 0, y, 0x40, height]
        self.screen_is_active = False
        try:
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
                if payload in ([0x53, 0x85], [0x53, 0x8A]):
                    self.ddp._set_state(DDPState.READY)
                    self.screen_is_active = True
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
        logger.info(f"Queueing Region Clear for {self.region_name}")
        payload = [0x52, 0x05, 0x02, 0x00, self.region_y_offset, 0x40, self.region_height]
        payload += [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        if not self._send_graphics(payload):
            logger.error("Failed to send clear payload.")

    def clear_area(self, x, y, w, h):
        """
        Explicitly clears a specific rectangle to BLACK.
        Used to erase artifacts or Red Highlights.
        """
        abs_y = y + self.region_y_offset
        # Flag 0x02: Clear(Bit 7=0), Clear(Bit 1=1), Black(Bit 0=0)
        payload = [0x52, 0x05, 0x02, x, abs_y, w, h]
        self._send_graphics(payload)
        
        # Reset Window
        payload_reset = [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        self._send_graphics(payload_reset)

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

    def _send_graphics(self, payload, pacing=True):
        """Track failure across every command in a frame, including IPC batches."""
        if getattr(self, '_frame_failed', False):
            return False
        if not getattr(self, '_native_transfer_active', False) and list(payload) != [0x39]:
            self._native_known_image = None  # Overlay/clear changes actual pixels.
        try:
            success = self.ddp.send_ddp_frame(payload, pacing=pacing)
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

    def _bitmap_message_budget(self):
        """Bound whole bitmap commands independently of TP2 ACK block sizes."""
        value = getattr(self, 'config', {}).get('ddp_bitmap_message_bytes', 42)
        if isinstance(value, bool) or not isinstance(value, int) or not 13 <= value <= 195:
            raise ValueError('ddp_bitmap_message_bytes must be an integer from 13 to 195')
        return value

    def _bitmap_rows_per_command(self):
        """Opt in to native bitmap row wrapping; default keeps one-row commands."""
        value = getattr(self, 'config', {}).get('ddp_bitmap_rows_per_command', 1)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
            raise ValueError('ddp_bitmap_rows_per_command must be an integer from 1 to 12')
        if value > 1 and self._bitmap_message_budget() > 105:
            raise ValueError('ddp_bitmap_rows_per_command > 1 requires ddp_bitmap_message_bytes <= 105')
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
        if pending_payload:
            if len(pending_payload) + 1 <= self._bitmap_message_budget():
                success = self._send_graphics(list(pending_payload) + [0x39])
            else:
                self._send_graphics(pending_payload)
                success = self.commit_frame()
        else:
            success = self.commit_frame()
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
        if not isinstance(delta, bool) or (delta and render_order != 'tiles'):
            raise ValueError('Native delta is a boolean option for completed tiles only')
        update_rect = validate_update_rect(command.get('update_rect'), render_order, delta)
        data = bytes.fromhex(command.get('data_hex', ''))
        payloads = compile_native_payloads(data, budget=105, rows_per_command=12,
                                          priming='each', selector_bytes=1,
                                          render_order=render_order, band_rows=band_rows, update_rect=update_rect)
        source = dict(command='draw_native_bitmap', x=0, y=0, w=128, h=96, data_hex=data.hex(),
                      render_order=render_order, band_rows=band_rows)
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
            from native_tiles import compile_tile_payloads
            payloads = compile_tile_payloads(data, previous=prior)
        self._native_known_image = None
        self._native_transfer_active = True
        # Completed tiles need renderer time between messages even after TP2 ACK.
        # Keep the existing transport delay configurable; planes/bands bypass it.
        pace_tiles = source.get('render_order', 'planes') == 'tiles'
        try:
            for payload in payloads:
                if not self._send_graphics(payload, pacing=pace_tiles):
                    return False
                self.ddp.poll_bus_events()
                self.ddp.send_keepalive_if_needed()
                if generation != getattr(self.ddp, 'state_generation', None):
                    self._frame_failed = True
                    return False
            if source.get('update_rect') is None:
                self._native_known_image = data
                self._native_known_generation = generation
            else:
                self._native_known_generation = None  # Outside the patch is unknown.
            return True
        finally:
            self._native_transfer_active = False

    def _expand_draw_command(self, command):
        # Prepare the entire snapshot before a claim or any drawing writes.
        if command.get('command') in ('draw_native_bitmap', '_native_bitmap_frame'):
            try:
                if command['command'] == '_native_bitmap_frame':
                    raise ValueError('Internal native frame commands are not public IPC')
                body = self._native_bitmap_command(command)
                return [body, {'command': 'commit', 'seq': command.get('seq', 0)}]
            except (ValueError, TypeError) as exc:
                logger.error('Rejected native bitmap: %s', exc)
                self._publish_frame_result(command.get('seq', 0), False)
                return []
        if command.get('command') == 'frame':
            commands = command.get('commands', [])
            allowed = {'resume', 'set_region', 'clear', 'clear_payload',
                       'clear_area', 'draw_text', 'draw_bitmap',
                       'draw_raw_bitmap', 'draw_line', 'draw_native_bitmap'}
            if not isinstance(commands, list) or any(
                    not isinstance(c, dict) or c.get('command') not in allowed for c in commands):
                self._publish_frame_result(command.get('seq', 0), False)
                return []
            try:
                if any(c.get('command') == 'draw_native_bitmap' for c in commands) and any(
                        c.get('command') == 'set_region' for c in commands):
                    raise ValueError('A native snapshot frame cannot change its region')
                expanded = [self._native_bitmap_command(c) if c.get('command') == 'draw_native_bitmap'
                            else c for c in commands]
            except (ValueError, TypeError) as exc:
                logger.error('Rejected native bitmap frame: %s', exc)
                self._publish_frame_result(command.get('seq', 0), False)
                return []
            return expanded + [{'command': 'commit', 'seq': command.get('seq', 0)}]
        return [command]

    def _reject_draw_commands(self, commands):
        self._frame_failed = True
        for command in commands:
            if command.get('command') in ('commit', 'frame', 'draw_native_bitmap'):
                self._publish_frame_result(command.get('seq', 0), False)
                self._frame_failed = False

    def commit_frame(self):
        payload = [0x39]
        success = self._send_graphics(payload)
        if not success:
            logger.error("Failed to send commit packet.")
        return success

    def clear_screen(self):
        logger.info("Executing full clear_screen command...")
        payload_clear = [0x52, 0x05, 0x02, 0x00, self.region_y_offset, 0x40, self.region_height]
        payload_reset = [0x52, 0x05, 0x00, 0x00, self.region_y_offset, 0x40, self.region_height]
        payload_commit = [0x39]
        if not self._send_graphics(payload_clear + payload_reset + payload_commit):
            logger.error("clear_screen: Failed to send frame.")
            

    def handle_redraw(self):
        logger.info("Restoring screen content after interruption or clearing...")
        if any(c.get('command') == 'draw_native_bitmap' for c in self.command_cache.values()):
            sorted_cmds = list(self.command_cache.values())
        else:
            sorted_cmds = sorted(self.command_cache.values(), key=lambda item: (item.get('y',0), item.get('x',0)))
        try:
            native_frames = {id(cmd): self._native_bitmap_command(cmd) for cmd in sorted_cmds
                             if cmd.get('command') == 'draw_native_bitmap'}
        except (ValueError, TypeError) as exc:
            self._frame_failed = True
            logger.error('Cannot restore native bitmap: %s', exc)
            return False
        # Recovery starts a fresh frame; a failed previous restore must not
        # permanently suppress future writes through the failure latch.
        self._frame_failed = False
        self.clear_screen_payload()
        
        for cmd in sorted_cmds:
            c = cmd.get('command')
            if c == 'draw_text':
                self.write_text(cmd.get('text',''), cmd.get('x',0), cmd.get('y',0), cmd.get('flags', 0x06))
            elif c == 'draw_bitmap':
                self.draw_bitmap(cmd.get('x',0), cmd.get('y',0), cmd.get('icon_name'), cmd.get('mode_flag', 0x02))
            elif c == 'draw_native_bitmap':
                self._send_native_bitmap_frame(native_frames[id(cmd)])
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
                         if now - self.last_claim_attempt > 5.0:
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
                                elif self._presentation_control(c):
                                    continue
                                elif c in ['draw_text', 'draw_bitmap', 'draw_line']:
                                    k = (c, cmd.get('y', 0), cmd.get('x', 0))
                                    if any(c.get('command') == 'draw_native_bitmap' for c in self.command_cache.values()):
                                        self.command_cache.pop(k, None)  # Preserve overlay update order.
                                    self.command_cache[k] = cmd
                            
                            # Control-only or stale batches cannot activate navigation.
                            drawable = any(cmd.get('command') in ('draw_text', 'draw_bitmap', 'draw_raw_bitmap', 'draw_line', '_native_bitmap_frame') for cmd in cmds)
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
                            # DDP frame IF they fit in one block (42 bytes). This eliminates 
                            # the 20ms inter-block pacing delay causing flicker.
                            current_payload = []
                            # must_colocate: True when current_payload ends with a clear_area
                            # whose paired draw command has not yet been appended.
                            # While True, the next drawable payload is always added to the
                            # same frame as the clear (no 42-byte split allowed) and the
                            # combined pair is flushed immediately afterward.
                            must_colocate = False
                            cmds = self._coalesce_bitmap_commands(cmds)
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
                                elif c == 'draw_text':
                                        p = self.get_text_payload(cmd.get('text', ''), cmd.get('x', 0), cmd.get('y', 0), cmd.get('flags', 0x06))
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
                                    if must_colocate:
                                        # This draw is the atomic pair for the preceding clear.
                                        # Append regardless of size, then flush the combined pair.
                                        current_payload += p
                                        must_colocate = False
                                        self._send_graphics(current_payload)
                                        current_payload = []
                                        self.ddp.poll_bus_events()
                                        self.ddp.send_keepalive_if_needed()
                                    elif current_payload and (len(current_payload) + len(p) > 42):
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
