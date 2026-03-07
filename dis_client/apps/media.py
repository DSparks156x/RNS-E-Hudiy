from .base import BaseApp
import json
import os

class MediaApp(BaseApp):
    def __init__(self, config=None):
        super().__init__(config)
        self.title = ""
        self.artist = ""
        self.album = ""
        self.time_str = ""

    def on_enter(self):
        super().on_enter()
        try:
            if os.path.exists('/tmp/now_playing.json'):
                with open('/tmp/now_playing.json', 'r') as f:
                    data = json.load(f)
                    # Re-use update logic by mocking a ZMQ call
                    self.update_hudiy(b'HUDIY_MEDIA', data)
        except Exception: pass

    def update_hudiy(self, topic, data):
        if topic == b'HUDIY_MEDIA':
            self.title  = data.get('title', '')
            self.artist = data.get('artist', '')
            self.album  = data.get('album', '')
            
            pos = data.get('position', '0:00')
            dur = data.get('duration', '0:00')
            
            if dur == '0:00' and pos == '0:00':
                self.time_str = ""
            else:
                self.time_str = f"{pos} / {dur}"

    def handle_input(self, action):
        if action in ['hold_up', 'hold_down']: return 'BACK'
        return None

    def get_view(self):
        lines = {}
        
        centering = self.config.get('display', {}).get('text_centering', False)
        align = 'center' if centering else 'left'
        flag = self.FLAG_ITEM_CENTERED if centering else self.FLAG_ITEM
        
        title_scroll = self._scroll_text(self.title, 'media_title', 16, align=align)
        artist_scroll = self._scroll_text(self.artist, 'media_artist', 16, align=align)
        album_scroll = self._scroll_text(self.album, 'media_album', 16, align=align)

        lines['line1'] = (title_scroll, flag)
        lines['line2'] = (artist_scroll, flag)
        lines['line3'] = (album_scroll, flag)
        
        # Standard static fields
        lines['line4'] = (str(self.time_str)[:16], flag)

        return lines
