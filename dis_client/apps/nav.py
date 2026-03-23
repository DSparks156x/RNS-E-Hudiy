from .base import BaseApp
from typing import List, Dict, Any
import logging
import json
import os

logger = logging.getLogger(__name__)

class NavApp(BaseApp):
    def __init__(self, config=None):
        super().__init__(config)
        self.maneuver_type = 0      # NavigationManeuverType
        self.maneuver_side = 3      # UNSPECIFIED
        self.maneuver_angle = 0     # 0-360 degrees
        self.description = ""       # "Turn left onto Main St"
        self.distance_label = ""    # "500 m" or "2.3 km"
        self.icon_data = b""        # Raw PNG from HUDIY (not used)
        
        # Cache previous state to prevent flickering logic if needed
        self.last_maneuver = -1
        self._meters = -1.0
        self.last_val_len = 0
        self.last_unit_len = 0
        
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

    def on_enter(self):
        super().on_enter()
        try:
            if os.path.exists('/tmp/current_nav.json'):
                with open('/tmp/current_nav.json', 'r') as f:
                    data = json.load(f)
                    self.update_hudiy(b'HUDIY_NAV', data)
        except Exception: pass

    def update_hudiy(self, topic: bytes, data: Dict[str, Any]):
        if topic == b'HUDIY_NAV':
            # Full maneuver update
            self.description = data.get('description', '')
            self.maneuver_type = data.get('maneuver_type', 0)
            self.maneuver_side = data.get('maneuver_side', 3)
            self.maneuver_angle = data.get('maneuver_angle', 0)
            if 'distance' in data:
                self.distance_label = data['distance']
                self._meters = self.parse_distance(self.distance_label)

        elif topic == b'HUDIY_NAV_DISTANCE':
            self.distance_label = data.get('label', '')
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
            a = angle % 360
            
            # Infer side_suffix if unspecified (3)
            # In CCW, 0-180 is Right, 180-360 is Left
            # In CW, 0-180 is Left, 180-360 is Right
            inferred_side = side_suffix
            if side == 3:
                if cw_ccw == "COUNTERCLOCKWISE":
                    inferred_side = "RIGHT" if a < 180 else "LEFT"
                else:
                    inferred_side = "LEFT" if a < 180 else "RIGHT"
            else:
                inferred_side = "LEFT" if side == 1 else "RIGHT"

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

    @staticmethod
    def parse_distance(label: Any) -> float:
        """Parses distance (number or string like '200 m', '1.2 km') into meters."""
        if label is None:
            return -1.0
        
        # If already a number, just return as float (assume meters)
        if isinstance(label, (int, float)):
            return float(label)
            
        try:
            s = str(label).lower().strip()
            if not s or 'now' in s or 'arrived' in s:
                return 0.0
            
            import re
            m = re.search(r'([\d.,]+)\s*([a-z]*)', s)
            if not m:
                return -1.0
            
            num_str = m.group(1)
            unit = m.group(2)
            
            # Clean thousands separators
            if ',' in num_str:
                if '.' in num_str:
                    num_str = num_str.replace(',', '')
                else:
                    if len(num_str.split(',')[-1]) == 3:
                        num_str = num_str.replace(',', '')
                    else:
                        num_str = num_str.replace(',', '.')
            
            val = float(num_str)
            if 'km' in unit: val *= 1000.0
            elif 'mi' in unit: val *= 1609.34
            elif 'ft' in unit: val *= 0.3048
            
            return val
        except Exception:
            return -1.0

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

    def _get_progress_height(self) -> int:
        """Convert distance string to bar height (0..36 px, configured m = full)"""
        val = self.parse_distance(self.distance_label)
        if val < 0:
            return 36 if self.distance_label else 0
        
        # "Approach Bar" Logic
        nav_cfg = self.config.get('display', {}).get('center_display', {}).get('navigation', {})
        max_dist = nav_cfg.get('approach_bar_max_distance', 300)
        
        if val > max_dist: return 0
        
        # Calculate fill ratio
        ratio = (max_dist - val) / max_dist
        return int(ratio * 47)

    def get_view(self) -> List[Dict]:
        # If no route, show text fallback
        if not self.description and not self.distance_label:
            return [
                {'type': 'nav_no_route', 'clear_on_update': True},
                {'group': 'no_route_1', 'cmd': 'draw_text', 'text': "No Route".center(11), 'x': 0, 'y': 21, 'flags': 0x06},
                {'group': 'no_route_2', 'cmd': 'draw_text', 'text': "" .ljust(16), 'x': 0, 'y': 31, 'flags': 0x06}
            ]

        icon_key = self._get_icon_name()
        # Ensure icon exists in icons.py mapping fallback
        # (Assuming dis_service handles missing keys gracefully or we check here?)
        # For now, rely on dis_service/icons.py having BITMAPS[key]
        
        bar_h = self._get_progress_height()

        # Clean distance: "500 m" -> "500m", but ONLY if we actually have a label
        dist_clean = ""
        if self.distance_label:
            dist_clean = str(self.distance_label).replace(" ", "").replace("km", "km").replace("m", "m")

        # Build graphical command list
        # The 'type' key is used by the engine for caching signatures
        # 'clear_on_update': False prevents the engine from sending 'clear_payload', avoid flicker
        commands = [{'type': 'nav_graphic_v2', 'clear_on_update': False}]

        # 1. Big arrow — moved UP to Y=1, and RIGHT to X=4
        commands.append({
            'group': 'arrow',
            'cmd': 'draw_bitmap',
            'icon': icon_key,
            'x': 4,
            'y': 1   # Moved up to maximize vertical space
        })

        # 2. Distance (top-right) — only draw if we have real data
        val_str, unit_str = self._split_distance(self.distance_label)
        
        # When bar_h == 0 (no bar), we can safely clear the entire remaining width (w=22, up to x=63).
        # This handles 4-digit distances that reach into the bar's empty coordinate space.
        # When bar_h > 0 (bar is drawn), we restrict clear width to w=19 to protect the bar at x=61.
        clear_w = 22 if bar_h == 0 else 19

        if val_str:
            x_pos = 42
            
            # If the string shrank, surgically clear the area so we don't ghost,
            # avoiding padding spaces that would overlap the progress bar.
            if len(val_str) < self.last_val_len:
                commands.append({
                    'group': 'dist',
                    'cmd': 'clear_area',
                    'x': x_pos,
                    'y': 8,
                    'w': clear_w,
                    'h': 9
                })
            
            self.last_val_len = len(val_str)

            # Draw numeric value on top
            commands.append({
                'group': 'dist',
                'cmd': 'draw_text',
                'text': val_str,
                'x': x_pos,
                'y': 8,
                'flags': 0x06 # Compact Font
            })
            
            # Draw units below if present
            if unit_str:
                if len(unit_str) < self.last_unit_len:
                    commands.append({
                        'group': 'dist',
                        'cmd': 'clear_area',
                        'x': x_pos,
                        'y': 17,
                        'w': clear_w,
                        'h': 9
                    })
                
                self.last_unit_len = len(unit_str)

                commands.append({
                    'group': 'dist',
                    'cmd': 'draw_text',
                    'text': unit_str,
                    'x': x_pos,
                    'y': 17,
                    'flags': 0x06
                })
            else:
                if self.last_unit_len > 0:
                     commands.append({
                         'group': 'dist',
                         'cmd': 'clear_area',
                         'x': x_pos,
                         'y': 17,
                         'w': clear_w,
                         'h': 9
                     })
                self.last_unit_len = 0
        else:
            if self.last_val_len > 0 or self.last_unit_len > 0:
                commands.append({
                    'group': 'dist',
                    'cmd': 'clear_area',
                    'x': 42,
                    'y': 8,
                    'w': clear_w,
                    'h': 18
                })
            self.last_val_len = 0
            self.last_unit_len = 0

        # 3. Street name (bottom, centered)
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
        
        # (Removed hardcoded truncation so _scroll_text can actually scroll it)
        pass
        # Scroll the street name if it's too long (limit to 12 chars as requested)
        # Use a unique key for the scroll state, explicitly set alignment to 'center'
        street_display = self._scroll_text(street, 'nav_street', 12, align='center')

        blank_char = chr(0x1F)
        
        # First clear the street name area surgically (x=0 to x=60)
        # This protects the progress bar starting at x=61
        commands.append({
            'group': 'street',
            'cmd': 'clear_area',
            'x': 0,
            'y': 39,
            'w': 61,
            'h': 9
        })

        # Then draw the actual centered text on top of the blank wiped area
        commands.append({
            'group': 'street',
            'cmd': 'draw_text',
            'text': street_display, 
            'x': 0, 
            'y': 39, 
            'flags': self.FLAG_ITEM_CENTERED
        })

        # 4. Red: Progress bar (Right Edge)
        # Independent group 'bar' so it only redraws when distance changes
        
        self.last_bar_h = bar_h

        bar_commands = []
        if bar_h > 0:
            start_y = 48 - bar_h # Anchor to bottom (Y=48)
            
            # Draw 3 vertical lines for a thick bar
            bar_commands = [
                {'group': 'bar', 'cmd': 'draw_line', 'x': 61, 'y': start_y, 'length': bar_h, 'vertical': True},
                {'group': 'bar', 'cmd': 'draw_line', 'x': 62, 'y': start_y, 'length': bar_h, 'vertical': True},
                {'group': 'bar', 'cmd': 'draw_line', 'x': 63, 'y': start_y, 'length': bar_h, 'vertical': True},
            ]

        commands += bar_commands

        return commands
