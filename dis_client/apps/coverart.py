from .base import BaseApp

class CoverArtApp(BaseApp):
    def __init__(self, config=None):
        super().__init__(config)
        self.bitmap_hex = ""
        self.title = "Now Playing"

    def update_hudiy(self, topic, data):
        if topic == b'HUDIY_COVERART':
            self.bitmap_hex = data.get('bitmap_hex', '')
            # If we wanted to also show title/artist here, we could, 
            # but the user just asked for the cover art app.

    def get_view(self):
        # Return a list of draw commands
        if not self.bitmap_hex:
            # If no bitmap, just show a placeholder or nothing
            return [
                {'type': 'cover_art', 'cmd': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48},
                {'cmd': 'draw_text', 'text': 'No Cover Art', 'x': 0, 'y': 20, 'flags': self.FLAG_ITEM_CENTERED}
            ]
        
        return [
            {'type': 'cover_art', 'cmd': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48},
            {
                'cmd': 'draw_raw_bitmap', 
                'data_hex': self.bitmap_hex, 
                'w': 64, 'h': 48, 'x': 0, 'y': 0, 
                'mode_flag': 0x02 # Draw Mode
            }
        ]
