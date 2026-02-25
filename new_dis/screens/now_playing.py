from typing import List, Dict, Any
from .base import ScreenBase

class NowPlayingScreen(ScreenBase):
    def __init__(self):
        super().__init__()
        self.title = "Unknown Title"
        self.artist = "Unknown Artist"
        self.album = "Unknown Album"
        self.time_str = "0:00"
        
        self.nav_desc = ""
        self.ambient_temp = "--°C"
        self.tick_count = 0

    def handle_hudiy_data(self, topic: str, data: dict):
        if topic == b'HUDIY_MEDIA':
            self.title = data.get('title', '')
            self.artist = data.get('artist', '')
            self.album = data.get('album', '')
            pos = data.get('position', '0:00')
            dur = data.get('duration', '0:00')
            if dur != '0:00':
                self.time_str = f"{pos}/{dur}"
        elif topic == b'HUDIY_NAV':
            self.nav_desc = data.get('description', '')

    def render(self) -> List[Dict[str, Any]]:
        self.tick_count += 1
        elements = []

        # -- Top Region: Nav Description + Temp --
        nav_disp = self.nav_desc if self.nav_desc else "No Route"
        if len(nav_disp) > 10:
            offset = (self.tick_count // 5) % (len(nav_disp) + 5)
            padded = nav_disp + "     "
            nav_disp = (padded * 2)[offset:offset+10]
            
        elements.append(self.create_text(nav_disp.ljust(10), 0, 1, flags=0x06))
        elements.append(self.create_text(self.ambient_temp.rjust(4), 48, 1, flags=0x06))
        elements.append(self.create_line(0, 10, 64, vertical=False))

        # -- Center Region: Media --
        def scroll(text: str, w: int):
            if not text: return " " * w
            if len(text) <= w: return text.ljust(w)
            offset = (self.tick_count // 5) % (len(text) + 5)
            padded = text + (" " * 5)
            return (padded * 2)[offset:offset+w]

        elements.append(self.create_text(scroll(self.title, 16), 0, 13))
        elements.append(self.create_text(scroll(self.artist, 16), 0, 23))
        # elements.append(self.create_text(scroll(self.album, 16), 0, 33))
        
        # Time string at bottom right
        elements.append(self.create_text(self.time_str.rjust(10), 24, 38))

        return elements
