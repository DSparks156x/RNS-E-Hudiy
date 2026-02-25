from typing import List, Dict, Any
from .base import ScreenBase

class NavScreen(ScreenBase):
    def __init__(self):
        super().__init__()
        # Data state
        self.now_playing_title = "No Media"
        self.nav_desc = "Nav Inactive"
        self.nav_dist = ""
        self.nav_icon = "STRAIGHT" # using internal icon names
        self.ambient_temp = "--°C"

        # Ticker state
        self.tick_count = 0

    def handle_can_message(self, topic: str, payload_hex: bytes):
        # TODO: Hook up ambient temp from CAN if known
        pass

    def handle_hudiy_data(self, topic: str, data: dict):
        if topic == b'HUDIY_MEDIA':
            self.now_playing_title = data.get('title', 'No Media')
        elif topic == b'HUDIY_NAV':
            self.nav_desc = data.get('description', '')
            # A full implementation would map maneuver_type to icon_name here
            # exactly like dis_client/apps/nav.py did.
            m_type = data.get('maneuver_type', 0)
            if m_type == 1: self.nav_icon = "DEPART"
            elif m_type == 19: self.nav_icon = "DESTINATION"
            elif m_type in [4, 5]: self.nav_icon = "TURN_RIGHT" if data.get('maneuver_side', 3) == 2 else "TURN_LEFT"
            else: self.nav_icon = "STRAIGHT"
            
            if 'distance' in data:
                self.nav_dist = data.get('distance', '')
        elif topic == b'HUDIY_NAV_DISTANCE':
            self.nav_dist = data.get('label', '')

    def render(self) -> List[Dict[str, Any]]:
        self.tick_count += 1
        elements = []

        # -- Top Region (Y=0 to 10 approx): Now Playing + Temp --
        
        # We can simulate scrolling by slicing the text based on tick_count
        title_disp = self.now_playing_title
        if len(title_disp) > 10:
            offset = (self.tick_count // 5) % (len(title_disp) + 5)
            padded = title_disp + "     "
            title_disp = (padded * 2)[offset:offset+10]
        
        # Draw Top Left: Now Playing Title (Yellow/Red inverted text to make it stand out?) 
        # Using flags=0x86 for inverted/colored background (if supported) or 0x06 for normal
        elements.append(self.create_text(title_disp.ljust(10), 0, 1, flags=0x06))
        
        # Draw Top Right: Ambient Temp
        elements.append(self.create_text(self.ambient_temp.rjust(4), 48, 1, flags=0x06))

        # Divider line
        elements.append(self.create_line(0, 10, 64, vertical=False))

        # -- Center Region (Y=11 to 48): Nav Info --
        
        if not self.nav_desc:
            elements.append(self.create_text("No Route", 16, 21))
            return elements

        # Left: Big Arrow Icon
        elements.append(self.create_bitmap(self.nav_icon, 0, 13))

        # Right Top: Distance
        elements.append(self.create_text(self.nav_dist[:6].rjust(6), 40, 13, flags=0x06))

        # Bottom: Street Name
        street = self.nav_desc
        if len(street) > 16:
            offset = (self.tick_count // 5) % (len(street) + 5)
            padded = street + "     "
            street = (padded * 2)[offset:offset+16]
            
        elements.append(self.create_text(street.ljust(16), 0, 39, flags=0x06))

        return elements
