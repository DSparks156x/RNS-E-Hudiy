import logging
import time
from typing import List, Dict, Any

from ddp_protocol import DDPProtocol, DDPState, DisMode, DDPError, DDPHandshakeError
from icons import audscii_trans, BITMAPS

logger = logging.getLogger(__name__)

class SmartDriver:
    """
    Intelligent display driver that minimizes CAN traffic by tracking the
    currently drawn 'elements' and only emitting diff updates (clears/redraws).
    """

    def __init__(self, config: dict, claim_full_screen: bool = False):
        self.config = config
        self.ddp = DDPProtocol(self.config)
        self.claim_full_screen = claim_full_screen
        self.screen_is_active = False
        self.last_draw_time = 0.0
        
        # We track elements drawn on screen to perform diffing.
        # Format: [{'type': 'text/bitmap/line', 'x': 0, 'y': 0, ...}, ...]
        self.current_elements: List[Dict[str, Any]] = []

    def start_session(self) -> bool:
        """Attempt to boot the CAN session if not active."""
        if self.ddp.state == DDPState.DISCONNECTED:
            if not self.ddp.detect_and_open_session():
                return False
        
        if self.ddp.state == DDPState.SESSION_ACTIVE:
            if not self.ddp.perform_initialization():
                return False

        if self.ddp.state == DDPState.READY and not self.screen_is_active:
            return self.claim_screen()
            
        return self.screen_is_active

    def stop_session(self):
        self.ddp._set_state(DDPState.DISCONNECTED)
        self.screen_is_active = False

    def claim_screen(self) -> bool:
        if self.ddp.state != DDPState.READY:
            return False

        # Area definitions (x, y, w, h)
        if self.claim_full_screen:
            area_bytes = [0x00, 0x00, 0x40, 0x58] # 0,0,64,88
        else:
            area_bytes = [0x00, 0x1B, 0x40, 0x30] # 0,27,64,48

        payload_claim = [0x52, 0x05, 0x82] + area_bytes
        
        # White cluster flow 
        payload_busy  = [0x53, 0x84]
        payload_free  = [0x53, 0x05]
        payload_ready = [0x2E]
        payload_clear = [0x2F]
        payload_ok    = [0x53, 0x85]

        try:
            if self.ddp.dis_mode == DisMode.RED:
                self.ddp.send_data_packet(payload_claim)
                data = self.ddp._recv_and_ack_data(1000)
                if not self.ddp.payload_is(data, payload_ok):
                    logger.warning("Red claim missing 53 85, proceeding anyways")
            else:
                self.ddp.send_data_packet(payload_claim)
                data = self.ddp._recv_and_ack_data(1000)
                if self.ddp.payload_is(data, payload_ok):
                    self.screen_is_active = True
                    return True
                if not self.ddp.payload_is(data, payload_busy):
                    return False
                data = self.ddp._recv_and_ack_data(1000)
                if not self.ddp.payload_is(data, payload_free):
                    return False
                data = self.ddp._recv_and_ack_data(1000)
                if not self.ddp.payload_is(data, payload_ready):
                    return False
                self.ddp.send_data_packet(payload_clear)
                self.ddp.send_data_packet(payload_claim)
                self.ddp._recv_and_ack_data(1000)
                
            self.screen_is_active = True
            logger.info(f"Screen claimed successfully (Full Screen: {self.claim_full_screen})")
            return True
        except Exception as e:
            logger.error(f"Failed to claim screen: {e}")
            return False

    def _get_bbox(self, element: Dict[str, Any]) -> tuple:
        """Calculate the absolute (x, y, w, h) bounding box for an element."""
        etype = element.get('type')
        x = element.get('x', 0)
        y = element.get('y', 0)
        
        if not self.claim_full_screen:
            y += 0x1B # Add Top Offset if not claiming full screen
            
        if etype == 'text':
            text = element.get('text', '')
            w = len(text) * 4  # Approximation (6 is max, 4 is safe clear metric)
            if w > 64: w = 64
            h = 9
            return (x, y, w, h)
        elif etype == 'bitmap':
            name = element.get('icon_name')
            if name in BITMAPS:
                return (x, y, BITMAPS[name]['w'], BITMAPS[name]['h'])
            return (x, y, 0, 0)
        elif etype == 'line':
            l = element.get('length', 0)
            if element.get('vertical', True):
                return (x, y, 1, l)
            return (x, y, l, 1)
        return (0, 0, 0, 0)

    def _elements_equal(self, e1: Dict, e2: Dict) -> bool:
        """Compare two elements to see if they are visually identical."""
        if e1.get('type') != e2.get('type'): return False
        if e1.get('x') != e2.get('x') or e1.get('y') != e2.get('y'): return False
        
        etype = e1.get('type')
        if etype == 'text':
            return e1.get('text') == e2.get('text') and e1.get('flags', 0) == e2.get('flags', 0)
        elif etype == 'bitmap':
            return e1.get('icon_name') == e2.get('icon_name')
        elif etype == 'line':
            return e1.get('length') == e2.get('length') and e1.get('vertical') == e2.get('vertical')
        return False

    def clear_area(self, x: int, y: int, w: int, h: int, color_flag: int = 0x02):
        """
        Clears a bounding box. 
        color_flag rules:
        0x02 = Clear to Black
        0x03 = Clear to Red
        """
        if w <= 0 or h <= 0: return
        payload = [0x52, 0x05, color_flag, x, y, w, h]
        self.ddp.send_ddp_frame(payload)
        self._reset_clip_region()

    def _reset_clip_region(self):
        """Restores the clip region to the main claimed area so W/U commands clip correctly."""
        if self.claim_full_screen:
            payload = [0x52, 0x05, 0x00, 0x00, 0x00, 0x40, 0x58]
        else:
            payload = [0x52, 0x05, 0x00, 0x00, 0x1B, 0x40, 0x30]
        self.ddp.send_ddp_frame(payload)

    def force_clear_screen(self):
        """Full clean screen sweep."""
        if self.claim_full_screen:
            self.clear_area(0, 0, 64, 88)
        else:
            self.clear_area(0, 27, 64, 48)
        self.current_elements = []
        self.commit()

    def _translate_to_audscii(self, text: str) -> List[int]:
        return [audscii_trans[ord(c) % 256] for c in text]

    def _draw_element(self, el: Dict):
        etype = el.get('type')
        x, y = el.get('x', 0), el.get('y', 0)

        # Coordinate shift handled inside drawing functions
        if etype == 'text':
            text = el.get('text', '')
            flags = el.get('flags', 0x06)
            self._draw_text(text, x, y, flags)
        elif etype == 'bitmap':
            name = el.get('icon_name')
            self._draw_bitmap(x, y, name)
        elif etype == 'line':
            self._draw_line(x, y, el.get('length', 0), el.get('vertical', True))

    def _draw_text(self, text: str, x: int, y: int, flags: int):
        chars = self._translate_to_audscii(text)
        is_inverted = (flags & 0x80) != 0
        protocol_flags = flags & 0x7C 
        
        abs_y = y if self.claim_full_screen else y + 0x1B

        if is_inverted:
            # Clear Background to Red
            width = 64 # usually full row for selection
            height = 9
            self.clear_area(x, abs_y, width, height, 0x03)
            
            # XOR Text
            final_text_flags = protocol_flags | 0x00
            payload = [0x57, len(chars) + 3, final_text_flags, x, abs_y] + chars
            self.ddp.send_ddp_frame(payload)
            self._reset_clip_region()
        else:
            # Normal text
            final_text_flags = protocol_flags | 0x02
            payload = [0x57, len(chars) + 3, final_text_flags, x, abs_y] + chars
            self.ddp.send_ddp_frame(payload)

    def _draw_bitmap(self, x: int, y: int, icon_name: str):
        if icon_name not in BITMAPS: return
        icon = BITMAPS[icon_name]
        w, h, data = icon['w'], icon['h'], icon['data']
        abs_y = y if self.claim_full_screen else y + 0x1B

        # Define clip constraint
        payload_clip = [0x52, 0x05, 0x00, x, abs_y, w, h]
        if not self.ddp.send_ddp_frame(payload_clip): return

        bytes_per_row = (w + 7) // 8
        rows_per_chunk = max(1, 37 // bytes_per_row)
        
        for i in range(0, h, rows_per_chunk):
            start_byte = i * bytes_per_row
            rows_to_send = min(rows_per_chunk, h - i)
            end_byte = start_byte + (rows_to_send * bytes_per_row)
            chunk_data = data[start_byte:end_byte]
            
            payload_bmp = [0x55, len(chunk_data) + 3, 0x02, 0x00, i] + chunk_data
            self.ddp.send_ddp_frame(payload_bmp)

        self._reset_clip_region()

    def _draw_line(self, x: int, y: int, length: int, vertical: bool):
        abs_y = y if self.claim_full_screen else y + 0x1B
        orientation = 0x10 if vertical else 0x20
        payload = [0x63, 0x04, orientation, x, abs_y, length]
        self.ddp.send_ddp_frame(payload)

    def commit(self):
        self.ddp.send_ddp_frame([0x39])

    def render(self, new_elements: List[Dict[str, Any]], force_full_redraw: bool = False):
        """
        Takes a new layout frame composed of elements and computes the diff
        required to push to the physical display, minimizing CAN traffic.
        """
        if not self.screen_is_active: return

        if force_full_redraw:
            self.force_clear_screen()
            self.current_elements = []

        elements_to_erase = []
        elements_to_draw = []

        # Find elements that were removed or changed significantly
        for old_el in self.current_elements:
            # Did it change?
            matched = False
            for new_el in new_elements:
                if self._elements_equal(old_el, new_el):
                    matched = True
                    break
            
            if not matched:
                # Need to check if a new element essentially overwrites this space completely.
                # If a new string is shorter than the old string at the same X/Y, we must erase the overhang.
                overhang_erase_needed = False
                for new_el in new_elements:
                    if new_el.get('type') == 'text' and old_el.get('type') == 'text' \
                       and new_el.get('x') == old_el.get('x') and new_el.get('y') == old_el.get('y'):
                        
                        # Same spot, different text.
                        # If normal to inverted transition, or vice versa, we must clear bounds!
                        old_inv = (old_el.get('flags', 0) & 0x80) != 0
                        new_inv = (new_el.get('flags', 0) & 0x80) != 0
                        if old_inv != new_inv:
                            elements_to_erase.append(old_el)
                            break
                        
                        old_len = len(old_el.get('text', '').rstrip())
                        new_len = len(new_el.get('text', '').rstrip())
                        if new_len < old_len:
                            # Erase the overhang
                            char_width = 4
                            clear_x = new_el.get('x', 0) + (new_len * char_width)
                            clear_w = (old_len * char_width) - (new_len * char_width)
                            
                            # A partial clear is inserted directly
                            _, y, _, h = self._get_bbox(old_el)
                            self.clear_area(clear_x, y, clear_w, h)
                        
                        break
                else:
                    # No new element overwrote this exactly, erase it entirely.
                    elements_to_erase.append(old_el)

        # Clear removed areas
        for el in elements_to_erase:
            bx, by, bw, bh = self._get_bbox(el)
            self.clear_area(bx, by, bw, bh)

        # Find elements to draw (new or changed)
        for new_el in new_elements:
            matched = False
            for old_el in self.current_elements:
                if self._elements_equal(old_el, new_el):
                    matched = True
                    break
            if not matched:
                elements_to_draw.append(new_el)

        # Draw updates
        for el in elements_to_draw:
            self._draw_element(el)

        if elements_to_erase or elements_to_draw:
            self.commit()
            
        self.current_elements = new_elements.copy()
        self.last_draw_time = time.time()
