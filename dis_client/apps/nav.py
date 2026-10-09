from .base import BaseApp
from typing import List, Dict, Any
import logging
import json
import os
import math
import re
from nav_icons import canvas_for_icon
try:
    from ..navigation_state import MANEUVER_TYPES, distance_meters, has_route_content, is_no_route
    from ..display_resolution import high_resolution
except ImportError:
    from navigation_state import MANEUVER_TYPES, distance_meters, has_route_content, is_no_route
    from display_resolution import high_resolution

logger = logging.getLogger(__name__)

class NavApp(BaseApp):
    def _text_profile(self):
        from enhanced_navigation import white_navigation_enabled
        navigation = (((self.config.get('display') or {}).get('center_display') or {}).get('navigation') or {})
        return 'native' if self.has_route and white_navigation_enabled(self.config, navigation) else super()._text_profile()

    def __init__(self, config=None):
        super().__init__(config)
        self.maneuver_type = 0      # NavigationManeuverType
        self.maneuver_side = 3      # UNSPECIFIED
        self.maneuver_angle = 0     # 0-360 degrees
        self.maneuver_angle_present = False
        self.description = ""       # "Turn left onto Main St"
        self.distance_label = ""    # "500 m" or "2.3 km"
        self.icon_data = b""        # Raw PNG from HUDIY (not used)
        
        # Cache previous state to prevent flickering logic if needed
        self.last_maneuver = -1
        self._meters = -1.0
        self._route_absent = False
        
        self.road_side = "right"
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(base_dir, 'config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    cfg = json.load(f)
                    self.road_side = cfg.get('display', {}).get('road_side', 'right')
        except Exception as e:
            logger.error(f"Failed to load config for road_side: {e}")

        # The running service configuration takes precedence over the file.
        configured_side = (self.config.get('display') or {}).get('road_side')
        if configured_side in ('left', 'right'):
            self.road_side = configured_side

    def on_enter(self):
        super().on_enter()
        try:
            if os.path.exists('/tmp/current_nav.json'):
                with open('/tmp/current_nav.json', 'r') as f:
                    data = json.load(f)
                    self.update_hudiy(b'HUDIY_NAV', data)
        except Exception: pass

    def update_hudiy(self, topic: bytes, data: Dict[str, Any]):
        if topic == b'HUDIY_NAV_STATUS':
            if data.get('active') is False:
                self.update_hudiy(b'HUDIY_NAV', {'has_route': False})
            return
        if topic == b'HUDIY_NAV':
            # An empty full update is the producer's explicit "route ended"
            # payload.  Clear every route-bearing field so a previous distance
            # cannot keep navigation visible after the maneuver is gone.
            pending_maneuver = (data.get('has_route') is not False
                and data.get('maneuver_type') in MANEUVER_TYPES
                and not is_no_route(data.get('description'))
                and not is_no_route(data.get('distance')) and not self._route_absent)
            if not has_route_content(data) and not pending_maneuver:
                self._route_absent = True
                self.description = ""
                self.distance_label = ""
                self._meters = -1.0
                self.maneuver_type = 0
                self.maneuver_side = 3
                self.maneuver_angle = 0
                self.maneuver_angle_present = False
                return

            # Full maneuver update
            self._route_absent = False
            self.description = str(data.get('description') or '')
            self.maneuver_type = data.get('maneuver_type', 0)
            self.maneuver_side = data.get('maneuver_side', 3)
            self.maneuver_angle = data.get('maneuver_angle', 0)
            self.maneuver_angle_present = (data.get('maneuver_angle_present') is True
                and isinstance(self.maneuver_angle, (int, float))
                and not isinstance(self.maneuver_angle, bool)
                and 0 <= self.maneuver_angle <= 0xFFFFFFFF
                and math.isfinite(self.maneuver_angle))
            if 'distance' in data:
                self.distance_label = self._normalize_distance_label(data['distance'])
                self._meters = self.parse_distance(self.distance_label)
            else:
                # Maneuver details arrive before their matching distance. Do
                # not evaluate the new maneuver using the previous distance.
                self.distance_label = ''
                self._meters = -1.0

        elif topic == b'HUDIY_NAV_DISTANCE':
            if data.get('has_route') is False or is_no_route(data.get('label')):
                self.update_hudiy(b'HUDIY_NAV', {'has_route': False})
                return
            # A delayed distance callback must not revive an ended route.
            if self._route_absent:
                return
            self.distance_label = self._normalize_distance_label(data.get('label', ''))
            self._meters = self.parse_distance(self.distance_label)

    def handle_input(self, action):
        if action in ['hold_up', 'hold_down']:
            return 'BACK'
        return None

    def _get_icon_name(self) -> str:
        """
        Map HUDIY maneuver type + side + angle -> icon key.
        Matches keys in new_icons_data.py / icons.py.
        """
        t = self.maneuver_type
        side = self.maneuver_side # 1=Left, 2=Right, 3=Unspecified
        angle = self.maneuver_angle
        
        # Helper strings
        side_suffix = "LEFT" if side == 1 else "RIGHT"
        
        # Roundabout Direction: Counterclockwise if road_side is right, clockwise if road_side is left
        if getattr(self, 'road_side', 'right') == 'left':
            cw_ccw = "CLOCKWISE"
        else:
            cw_ccw = "COUNTERCLOCKWISE"

        # --- MAPPING LOGIC ---
        
        # 1. SPECIAL / SIMPLE
        if t == 1: return "DEPART"
        if t == 19:
            return f"DESTINATION_{side_suffix}" if side in (1, 2) else "DESTINATION"
        if t == 16: return "FERRY_BOAT"
        if t == 17: return "FERRY_TRAIN"
        if t == 0 or t == 14: return "STRAIGHT"
        if t == 2: return "STRAIGHT" # Name change -> Straight usually
        
        # 2. TURNS
        if t == 3: return f"TURN_SLIGHT_{side_suffix}"
        if t == 4: return f"TURN_{side_suffix}"
        if t == 5: return f"TURN_SHARP_{side_suffix}"
        if t == 6: return f"TURN_U_TURN_{cw_ccw}" # U-Turn uses CW/CCW
        
        # 3. RAMPS / FORK / MERGE
        if t == 7: return f"RAMP_ON_{side_suffix}"  # On Ramp
        if t == 8: return f"RAMP_OFF_{side_suffix}" # Off Ramp
        if t == 9: return f"FORK_{side_suffix}"
        if t == 10:
            return f"MERGE_{side_suffix}" if side in (1, 2) else "MERGE"

        # 4. ROUNDABOUTS
        if t == 11: return f"ROUNDABOUT_{cw_ccw}" # Enter
        if t == 12: return f"ROUNDABOUT_EXIT_{cw_ccw}" # Exit
        
        if t == 13: # ROUNDABOUT_ENTER_AND_EXIT
            if not self.maneuver_angle_present:
                # An absent proto2 angle looks like0; do not invent a U-turn.
                return f"ROUNDABOUT_{cw_ccw}"
            a = angle % 360
            
            # Determine overall maneuver side based strictly on angle.
            # Navigation apps often send maneuver_side=2 (Right) for all CCW 
            # roundabouts because the physical exit is a right turn, which 
            # previously overrode our macro icon selection.
            if cw_ccw == "COUNTERCLOCKWISE":
                inferred_side = "RIGHT" if a < 180 else "LEFT"
            else:
                inferred_side = "LEFT" if a < 180 else "RIGHT"

            shape = "U_TURN"
            if 22.5 <= a < 67.5:
                shape = "SHARP"
            elif 67.5 <= a < 112.5:
                shape = "NORMAL"
            elif 112.5 <= a < 157.5:
                shape = "SLIGHT"
            elif 157.5 <= a < 202.5:
                shape = "STRAIGHT"
            elif 202.5 <= a < 247.5:
                shape = "SLIGHT"
            elif 247.5 <= a < 292.5:
                shape = "NORMAL"
            elif 292.5 <= a < 337.5:
                shape = "SHARP"

            if shape == "STRAIGHT":
                return f"ROUNDABOUT_STRAIGHT_{cw_ccw}"
            elif shape == "U_TURN":
                return f"ROUNDABOUT_U_TURN_{cw_ccw}"
            elif shape == "NORMAL":
                return f"ROUNDABOUT_{inferred_side}_{cw_ccw}"
            else:
                return f"ROUNDABOUT_{shape}_{inferred_side}_{cw_ccw}"

        # Internal Fallback
        return "STRAIGHT"

    @property
    def meters(self) -> float:
        """Cached unit-aware distance in meters."""
        return self._meters

    @property
    def has_route(self) -> bool:
        """Whether Hudiy has supplied actual maneuver data."""
        return has_route_content({
            'description': self.description, 'distance': self.distance_label,
            'maneuver_type': self.maneuver_type,
        })

    @staticmethod
    def _normalize_distance_label(label: Any):
        """Blank labels are absent; numeric zero remains a real distance."""
        if label is None:
            return ""
        if isinstance(label, str):
            return label.strip()
        return label

    @staticmethod
    def parse_distance(label: Any) -> float:
        """Parses distance (number or string like '200 m', '1.2 km') into meters."""
        return distance_meters(label)

    def _split_distance(self, label: Any):
        """Splits distance into (value, units)."""
        if label is None or label == "": return "", ""
        
        # If it's a number, return it with empty string for units
        if isinstance(label, (int, float)):
            return str(label), ""

        import re
        s = str(label).strip()
        # Capture numeric part and unit part
        m = re.search(r'([\d.,/]+)\s*([a-zA-Z]*)', s)
        if m:
            return m.group(1), m.group(2)
        return s, ""

    @staticmethod
    def _format_distance_value(value, fractional=False, max_chars=4):
        """Bound numbers to the bench-confirmed slot, in the displayed unit.

        Keep small km/mi fractions; k/M/G/T multiply the unit shown below.
        When a value cannot fit even compact notation, show a lower bound.
        """
        import math
        if not math.isfinite(value) or value < 0:
            return "?"
        if fractional and value < 100:
            number = f"{value:.1f}"
            if len(number) <= max_chars:
                return number
        number = str(int(round(value)))
        if len(number) <= max_chars:
            return number

        largest_suffix = ""
        for scale, suffix in ((1000, 'k'), (1000000, 'M'),
                              (1000000000, 'G'), (1000000000000, 'T')):
            scaled = value / scale
            if scaled < 1 and round(scaled, 1) < 1:
                break
            largest_suffix = suffix
            if scaled < 10:
                number = f"{scaled:.1f}" + suffix
                if len(number) <= max_chars:
                    return number
            number = str(int(round(scaled))) + suffix
            if len(number) <= max_chars:
                return number
        # Explicitly bounded saturation is preferable to clipping significant
        # digits or accidentally displaying zero after scaling too far.
        return '>' + '9' * (max_chars - 2) + largest_suffix

    @staticmethod
    def _bound_distance_label(text, max_chars=3):
        """Unknown text uses a conservative three-wide-glyph slot."""
        text = str(text).strip()
        return text if len(text) <= max_chars else text[:max_chars - 1] + '.'

    def _fit_distance_value(self, value, fractional, width_px):
        """Choose complete rounded numbers; never clip significant digits."""
        import math
        if not math.isfinite(value) or value < 0:
            return "?"

        def fits(candidate):
            return self.text_width(candidate, flags=0x06) <= width_px

        if fractional and value < 100:
            candidate = f"{value:.1f}"
            if fits(candidate):
                return candidate
        candidate = str(int(round(value)))
        if fits(candidate):
            return candidate
        for scale, suffix in ((1000, 'k'), (1000000, 'M'),
                              (1000000000, 'G'), (1000000000000, 'T')):
            scaled = value / scale
            if scaled < 1 and round(scaled, 1) < 1:
                break
            if scaled < 10:
                candidate = f"{scaled:.1f}" + suffix
                if fits(candidate):
                    return candidate
            candidate = str(int(round(scaled))) + suffix
            if fits(candidate):
                return candidate
        # State an explicit lower bound instead of clipping an enormous value.
        for digits in range(8, 0, -1):
            candidate = '>' + '9' * digits + 'T'
            if fits(candidate):
                return candidate
        return "?"

    def _get_progress_height(self) -> int:
        """Convert distance string to bar height (0..48 px, configured m = full)"""
        val = self._meters
        if val < 0:
            return 36 if self.distance_label else 0
        
        # "Approach Bar" Logic
        nav_cfg = {}
        if self.config:
            display = self.config.get('display') or {}
            center_display = display.get('center_display') or {}
            nav_cfg = center_display.get('navigation') or {}
        
        max_dist = nav_cfg.get('approach_bar_max_distance', 300)
        if (isinstance(max_dist, bool) or not isinstance(max_dist, (int, float))
                or not math.isfinite(max_dist) or max_dist <= 0):
            max_dist = 300
        
        if val > max_dist: return 0
        
        # Calculate fill ratio
        ratio = (max_dist - val) / max_dist
        if ratio < 0.0:
            ratio = 0.0
        return int(ratio * 48)

    def get_view(self) -> List[Dict]:
        # If no route, show text fallback
        if not self.has_route:
            return [
                {'type': 'nav_no_route', 'clear_on_update': True},
                {'group': 'no_route_1', 'cmd': 'draw_text', 'text': "No Route", 'x': max(0, (128 - self.text_width("No Route", flags=0x06)) // 4), 'y': 21, 'flags': 0x06},
                {'group': 'no_route_2', 'cmd': 'draw_text', 'text': "" .ljust(16), 'x': 0, 'y': 31, 'flags': 0x06}
            ]

        navigation = ((self.config.get('display') or {}).get('center_display') or {}).get('navigation') or {}
        from enhanced_navigation import global_white_view
        white_view = global_white_view(self, navigation)
        if white_view is not None:
            return white_view

        icon_key = self._get_icon_name()
        # Ensure icon exists in icons.py mapping fallback
        # (Assuming dis_service handles missing keys gracefully or we check here?)
        # For now, rely on dis_service/icons.py having BITMAPS[key]
        
        bar_h = self._get_progress_height()

        # Build graphical command list
        # The 'type' key is used by the engine for caching signatures
        # 'clear_on_update': False prevents the engine from sending 'clear_payload', avoid flicker
        display = self.config.get('display') or {}
        center_display = display.get('center_display') or {}
        navigation = center_display.get('navigation') or {}
        native = high_resolution(self.config)
        commands = [{
            'type': 'nav_graphic_native' if native else 'nav_graphic_v2',
            'clear_on_update': False,
        }]

        if native:
            order = navigation.get('native_render_order', 'planes')
            if order not in ('planes', 'tiles'):
                order = 'planes'
            delay_ms = navigation.get('native_message_delay_ms', 5)
            if (isinstance(delay_ms, bool) or not isinstance(delay_ms, (int, float))
                    or not 0 <= delay_ms <= 100):
                delay_ms = 5
            # Only replace the72x72 icon at physical(6,2); its reserved rectangle
            # leaves distance/street/bar pixels intact on maneuver changes.
            commands.append({
                'group': 'icon',
                'cmd': 'native_bitmap',
                'update_rect': [6, 2, 72, 72],
                'preserves_overlays': True,
                'data_hex': canvas_for_icon(icon_key).hex(),
                'render_order': order,
                'post_message_delay_s': delay_ms / 1000,
            })
        else:
            commands.append({
                'group': 'arrow',
                'cmd': 'draw_bitmap',
                'icon': icon_key,
                'x': 4,
                'y': 1,
            })

        # 2. Distance (top-right) â€” only draw if we have real data
        speed_unit = self.get_effective_unit('speed', 'imperial')
        
        # Legacy compatibility still reserves a fixed column independently
        # of bar progress; the white path above uses the same32px width.
        distance_width = 32
        if self._meters >= 0:
            fractional = False
            if speed_unit == 'imperial':
                if self._meters < 160.9: # 0.1 mile is 160.934 meters
                    value = self._meters * 3.28084
                    unit_str = "ft"
                else:
                    value = self._meters / 1609.344
                    unit_str = "mi"
                    fractional = True
            else: # metric
                if self._meters < 1000.0:
                    value = self._meters
                    unit_str = "m"
                else:
                    value = self._meters / 1000.0
                    unit_str = "km"
                    fractional = True
            val_str = self._fit_distance_value(value, fractional, distance_width)
        else:
            val_str, unit_str = self._split_distance(self.distance_label)
            val_str = self.fit_text(val_str, distance_width, flags=0x06)
            unit_str = self.fit_text(unit_str, distance_width, flags=0x06)
        
        # Fixed field width keeps old numeric/unit footprints independent of
        # whether the compatibility approach strip is filled or empty.
        clear_w = 16

        dist_commands = []
        if val_str:
            x_pos = 40 + max(0, (distance_width - self.text_width(val_str, flags=0x06)) // 4)
            
            # Always clear the value area first to prevent ghosting
            dist_commands.append({
                'cmd': 'clear_area',
                'x': 40,
                'y': 8,
                'w': clear_w,
                'h': 9
            })
            

            # Draw numeric value on top
            dist_commands.append({
                'cmd': 'draw_text',
                'text': val_str,
                'x': x_pos,
                'y': 8,
                'flags': 0x06 # Compact Font
            })
            
            # Draw units below if present
            if unit_str:
                dist_commands.append({
                    'cmd': 'clear_area',
                    'x': 40,
                    'y': 17,
                    'w': clear_w,
                    'h': 9
                })
                

                dist_commands.append({
                    'cmd': 'draw_text',
                    'text': unit_str,
                    'x': 40 + max(0, (distance_width - self.text_width(unit_str, flags=0x06)) // 4),
                    'y': 17,
                    'flags': 0x06
                })
            else:
                dist_commands.append({
                    'cmd': 'clear_area',
                    'x': 40,
                    'y': 17,
                    'w': clear_w,
                    'h': 9
                })
        else:
            dist_commands.append({
                'cmd': 'clear_area',
                'x': 40,
                'y': 8,
                'w': clear_w,
                'h': 18
            })

        # Assign group='dist' to dist_commands
        for cmd in dist_commands:
            cmd['group'] = 'dist'

        # 3. Street name (bottom, centered/scrolling)
        # Extract just the street name if possible
        street = self.description
        prefixes = [
            "Turn left onto ", "Turn right onto ", "Turn left into ", "Turn right into ",
            "Keep left onto ", "Keep right onto ", "Head onto ", "Continue onto ",
            "Take the ", " toward ", " towards "
        ]
        for p in prefixes:
            if p.lower() in street.lower():
                street = street.lower().split(p.lower(), 1)[-1]
                break

        # The compatibility strip ends above this row. Text advances are
        # physical pixels; command coordinates remain logical.
        street_right = 64
        street_width = (street_right - 2) * 2
        scrolling = not self.text_fits(street, street_width, flags=0x06)
        street_display = self._scroll_text(
            street, 'nav_street', max_width_px=street_width, font_flags=0x06,
            align='left')
        street_flags = self.FLAG_ITEM
        # Manual centering respects the viewport, unlike full-screen 0x20.
        street_x = 1 if scrolling else 1 + max(
            0, (street_width - self.text_width(street_display, flags=0x06)) // 4)

        street_commands = [
            # The whole street row is available beneath the approach strip.
            {
                'group': 'street',
                'cmd': 'clear_area',
                'x': 0,
                'y': 39,
                'w': street_right,
                'h': 9
            },
            # Then draw the actual centered/scrolling text on top
            {
                'group': 'street',
                'cmd': 'draw_text',
                'text': street_display, 
                'x': street_x, 
                'y': 39, 
                'flags': street_flags
            }
        ]

        # 4. Red: Progress bar (Right Edge)

        bar_commands = []
        # A changed bar replaces its own strip; unchanged bars are skipped by the engine.
        bar_commands.append({'cmd': 'clear_area', 'x': 61, 'y': 3, 'w': 3, 'h': 35})
        
        if bar_h > 0:
            # Unproved legacy/red graphics font keeps safe existing line
            # primitives, above the full street row, growing from the top.
            bar_h = (bar_h * 35 + 24) // 48
            start_y = 3
            
            # Draw 3 vertical lines for a thick bar
            bar_commands.append({'cmd': 'draw_line', 'x': 61, 'y': start_y, 'length': bar_h, 'vertical': True})
            bar_commands.append({'cmd': 'draw_line', 'x': 62, 'y': start_y, 'length': bar_h, 'vertical': True})
            bar_commands.append({'cmd': 'draw_line', 'x': 63, 'y': start_y, 'length': bar_h, 'vertical': True})

        # The bar has its own signature and changes only with approach height.
        # Fixed text reservations never depend on fill or disappearance.
        for command in bar_commands:
            command['group'] = 'bar'
        commands += bar_commands
        commands += dist_commands
        commands += street_commands

        return commands

    def _get_stock_view(self):
        """Native mono style for supported maneuvers; custom handles the rest.

        This is an explicit presentation adapter, not equivalence between
        HUDIY maneuver enums and RNSE raw type bytes. Do not map unsupported
        turns, forks, ramps or roundabouts by their enum numeric value.
        """
        if type(self.maneuver_type) is not int or type(self.maneuver_side) is not int:
            return None
        if self.maneuver_type in (2, 14):
            # Existing HUDIY mapper presents name-change/straight as STRAIGHT.
            direction = 0x00
        elif self.maneuver_type == 4 and self.maneuver_side in (1, 2):
            direction = 0x40 if self.maneuver_side == 1 else 0xC0
        else:
            key = (self.maneuver_type, self.maneuver_side)
            if getattr(self, '_stock_unmapped', None) != key:
                logger.info('Stock maneuver mapping unproved for%s; retaining custom renderer', key)
                self._stock_unmapped = key
            return None
        from icons import encode_audscii
        street = self.description
        # Same extraction policy as the existing custom road field.
        prefixes = ["Turn left onto ", "Turn right onto ", "Turn left into ", "Turn right into ",
                    "Keep left onto ", "Keep right onto ", "Head onto ", "Continue onto ",
                    "Take the ", " toward ", " towards "]
        for prefix in prefixes:
            if prefix.lower() in street.lower():
                street = street.lower().split(prefix.lower(), 1)[-1]
                break
        road = bytes(encode_audscii(street))[:20]
        if 0 in road:
            # Avoid a possible57 terminator; do not rewrite the native glyph.
            return None
        height = self._get_progress_height()
        progress = max(0, min(255, (height * 255 + 24) // 48))
        return [dict(type='nav_stock_mono', clear_on_update=False),
                dict(group='stock_frame', cmd='draw_stock_mono_frame',
                     source_object=[0, 2, 1, 0x0D, direction, 0], object_stage='render',
                     screen_selector=4, raw_progress=progress, road_bytes=list(road))]
