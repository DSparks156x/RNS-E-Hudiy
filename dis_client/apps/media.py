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
        def field_flags(text):
            # Center a fitting field, but anchor overflowing scroll windows at
            # the left edge so changing proportional widths cannot recenter it.
            fits = self.text_fits(text or '', 128, self.FLAG_ITEM)
            return self.FLAG_ITEM_CENTERED if centering and fits else self.FLAG_ITEM

        for key, field in (('line1', 'title'), ('line2', 'artist'), ('line3', 'album')):
            text = getattr(self, field)
            flag = field_flags(text)
            align = 'center' if flag & 0x20 else 'left'
            scroll = self._scroll_text(text, 'media_' + field, align=align,
                max_width_px=128, font_flags=flag)
            lines[key] = (scroll, flag)

        # The time field is bounded without scrolling.
        time_text = str(self.time_str)
        flag = field_flags(time_text)
        lines['line4'] = (self.fit_text(time_text, 128, flag), flag)

        return lines
