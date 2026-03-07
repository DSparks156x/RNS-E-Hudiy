from .base import BaseApp
from typing import List, Dict, Any
import logging
import json
import os

logger = logging.getLogger(__name__)

class NavApp(BaseApp):
    def __init__(self):
        super().__init__()
        self.maneuver_type = 0      # NavigationManeuverType
        self.maneuver_side = 3      # UNSPECIFIED
        self.maneuver_angle = 0     # 0-360 degrees
        self.description = ""       # "Turn left onto Main St"
        self.distance_label = ""    # "500 m" or "2.3 km"
        self.icon_data = b""        # Raw PNG from HUDIY (not used)
        
        # Cache previous state to prevent flickering logic if needed
        self.last_maneuver = -1
        
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
            # self.icon_data = data.get('icon', b"") 
            if 'distance' in data:
                self.distance_label = data['distance'] 

        elif topic == b'HUDIY_NAV_DISTANCE':
            self.distance_label = data.get('label', '')

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
        if t == 19: return "DESTINATION"
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
        if t == 10: return "MERGE" # Merge usually doesn't have side in icon name for now

        # 4. ROUNDABOUTS
        if t == 11: return f"ROUNDABOUT_{cw_ccw}" # Enter
        if t == 12: return f"ROUNDABOUT_EXIT_{cw_ccw}" # Exit
        
        if t == 13: # ROUNDABOUT_ENTER_AND_EXIT
            # Use Angle to determine shape
            # Buckets based on user snippet: 10(Slight), 45(Normal), 135(Sharp), 180(U-Turn)
            # NOTE: We need to determine if it's a Left or Right turn relative to entry.
            # But the Icon names (e.g. ROUNDABOUT_LEFT_CLOCKWISE) imply the exit is to the left/right.
            
            # Simple heuristic assumes standard 4-way roundabout
            # Angle 180 = Straight? Or U-Turn? 
            # User snippet: 180 = U-Turn.
            
            # Let's map roughly:
            # 0-25: Straight (or Slight if side implies turn?)
            # 26-65: Slight
            # 66-115: Normal (90 deg)
            # 116-155: Sharp
            # > 155: U-Turn
            
            # BUT we also need direction (Left vs Right). 
            # If side=1 (Left), then Slight Left, Sharpt Left etc.
            
            shape = "STRAIGHT"
            if angle > 155: shape = "U_TURN"
            elif angle > 115: shape = "SHARP" # e.g. SHARP_LEFT
            elif angle > 65: shape = "NORMAL" # means just _LEFT or _RIGHT
            elif angle > 25: shape = "SLIGHT"
            
            # Construct Key
            # Format: ROUNDABOUT_[SHAPE]_[SIDE]_[CW/CCW]
            # Exceptions: ROUNDABOUT_STRAIGHT_... (No side?)
            #             ROUNDABOUT_LEFT_... (Normal)
            #             ROUNDABOUT_U_TURN_... (No side?)
            
            if shape == "STRAIGHT":
                return f"ROUNDABOUT_STRAIGHT_{cw_ccw}"
            elif shape == "U_TURN":
                return f"ROUNDABOUT_U_TURN_{cw_ccw}"
            elif shape == "NORMAL":
                return f"ROUNDABOUT_{side_suffix}_{cw_ccw}"
            else:
                # Slight or Sharp
                return f"ROUNDABOUT_{shape}_{side_suffix}_{cw_ccw}"

        # Internal Fallback
        return "STRAIGHT"

    @staticmethod
    def parse_distance(label: str) -> float:
        """Parses distance string (e.g., '200 m', '1.2 km') into meters."""
        if not label:
            return -1.0
        try:
            s = label.lower().replace(',', '.')
            if 'now' in s or 'arrived' in s:
                return 0.0
            
            val = 0.0
            if 'km' in s:
                val = float(s.split('km')[0].strip()) * 1000.0
            elif 'mi' in s: # Matches 'mi' and 'miles'
                val = float(s.split('mi')[0].strip()) * 1609.34
            elif 'ft' in s: # Matches 'ft' and 'feet'
                val = float(s.split('ft')[0].strip()) * 0.3048
            elif 'm' in s:
                val = float(s.split('m')[0].strip())
            else:
                return -1.0 # Unknown unit
            return val
        except:
            return -1.0

    def _split_distance(self, label: str):
        """Splits distance string into (value, units) e.g. ('500', 'm')."""
        if not label: return "", ""
        import re
        # Capture numeric part and unit part
        m = re.search(r'([\d.,/]+)\s*([a-zA-Z]+)', label)
        if m:
            return m.group(1), m.group(2)
        return label, ""

    def _get_progress_height(self) -> int:
        """Convert distance string to bar height (0..36 px, 300 m = full)"""
        val = self.parse_distance(self.distance_label)
        if val < 0:
            return 36 if self.distance_label else 0
        
        # "Approach Bar" Logic:
        # >200m: Empty (0px)
        # 200m -> 0m: Fills up (0px -> 36px)
        if val > 200: return 0
        
        # Calculate fill ratio
        ratio = (200.0 - val) / 200.0
        return int(ratio * 47)

    def get_view(self) -> List[Dict]:
        # If no route, show text fallback
        if not self.description and not self.distance_label:
            return {
                'line3': ("No Route".center(11), self.FLAG_WIPE),
                'line4': ("" .ljust(16), self.FLAG_ITEM)
            }

        icon_key = self._get_icon_name()
        # Ensure icon exists in icons.py mapping fallback
        # (Assuming dis_service handles missing keys gracefully or we check here?)
        # For now, rely on dis_service/icons.py having BITMAPS[key]
        
        bar_h = self._get_progress_height()

        # Clean distance: "500 m" -> "500m", but ONLY if we actually have a label
        dist_clean = ""
        if self.distance_label:
            dist_clean = self.distance_label.replace(" ", "").replace("km", "km").replace("m", "m")

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
        
        if val_str:
            # Configurable horizontal center for the right-side informational area
            # Average character width approx 5px (including spacing)
            center_x = 49 
            
            # Use chr(0x1F) which is the full width space in AUDSCII, effectively wiping the background
            blank_char = chr(0x1F)
            val_padded = val_str.center(5, blank_char)
            val_x = center_x - (len(val_padded) * 5 // 2)

            # Draw numeric value on top
            commands.append({
                'group': 'dist',
                'cmd': 'draw_text',
                'text': val_padded,
                'x': val_x,
                'y': 10,
                'flags': 0x06 # Compact Font
            })
            # Draw units below if present
            if unit_str:
                unit_padded = unit_str.center(4, blank_char)
                unit_x = center_x - (len(unit_padded) * 5 // 2)
                commands.append({
                    'group': 'dist',
                    'cmd': 'draw_text',
                    'text': unit_padded,
                    'x': unit_x,
                    'y': 19,
                    'flags': 0x06
                })
        else:
            # Just push empty padded spaces to clear the old distance cleanly
            blank_char = chr(0x1F)
            commands.append({
                'group': 'dist',
                'cmd': 'draw_text',
                'text': blank_char * 5,
                'x': 49 - (5 * 5 // 2),
                'y': 10,
                'flags': 0x06
            })
            commands.append({
                'group': 'dist',
                'cmd': 'draw_text',
                'text': blank_char * 4,
                'x': 49 - (4 * 5 // 2),
                'y': 19,
                'flags': 0x06
            })

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
        # Scroll the street name if it's too long (limit to 14 chars as requested)
        # Use a unique key for the scroll state, explicitly set alignment to 'center'
        street_display = self._scroll_text(street, 'nav_street', 13, 400, align='center')

        blank_char = chr(0x1F)
        
        # First write a full-width blank block to wipe any previous ghosting artifacts 
        commands.append({
            'group': 'street_clear',
            'cmd': 'draw_text',
            'text': blank_char * 11, 
            'x': 0,
            'y': 39,
            'flags': self.FLAG_ITEM
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
        # To ensure the bar is drawn ON TOP of the text padding wipe, we group it with 'street'
        # so whenever the street updates (every tick due to scrolling), the bar is refreshed.
        
        last_bar_h = getattr(self, 'last_bar_h', 0)
        
        # If the bar SHRINKS (meaning distance increased, e.g. a new maneuver started)
        # We must clear the old pixels from the top.
        if bar_h < last_bar_h:
            commands.append({
                'group': 'street',
                'cmd': 'clear_area',
                'x': 61, 'y': 0, 'w': 3, 'h': 48
            })
            
        self.last_bar_h = bar_h

        if bar_h > 0:
            start_y = 48 - bar_h # Anchor to bottom (Y=48)
            
            # Draw 3 vertical lines for a thick bar
            commands += [
                {'group': 'street', 'cmd': 'draw_line', 'x': 61, 'y': start_y, 'len': bar_h, 'vert': True},
                {'group': 'street', 'cmd': 'draw_line', 'x': 62, 'y': start_y, 'len': bar_h, 'vert': True},
                {'group': 'street', 'cmd': 'draw_line', 'x': 63, 'y': start_y, 'len': bar_h, 'vert': True},
            ]

        return commands
