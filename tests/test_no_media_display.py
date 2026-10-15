"""No-media behaviour of the center Media page and the top lines; no IPC."""
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
try:
    import zmq  # noqa: F401
except ImportError:
    sys.modules['zmq'] = types.ModuleType('zmq')

from apps.media import MediaApp
from dis_top_display_service import DISController, NO_MEDIA_TEXT


class MediaPageClock(unittest.TestCase):
    def update(self, **data):
        app = MediaApp()
        app.update_hudiy(b'HUDIY_MEDIA', data)
        return app.time_str

    def test_zero_padded_labels_hide_clock(self):
        self.assertEqual(self.update(title='Song', position='00:00', duration='00:00'), '')

    def test_no_track_hides_clock(self):
        self.assertEqual(self.update(position='00:00', duration='03:21'), '')

    def test_track_shows_clock(self):
        self.assertEqual(self.update(title='Song', position='00:12', duration='03:21'), '00:12 / 03:21')


def Top(center_app='app_media', src_state='NONE', media=('', '', ''), label=''):
    top = DISController.__new__(DISController)
    top._center_msg_t = time.monotonic()
    top._center_ready = True
    top._center_app = center_app
    top._call_active = False
    top._nav_active = False
    top._nav_texts = ('', '')
    top._src_state = src_state
    top._media_texts = media
    top._source_label = label
    top._applist = ['phone', 'nav', 'media']
    top._prio = None
    top._resolve_dirty = Mock()
    top._no_media = (NO_MEDIA_TEXT, '')
    top._set_lines = Mock()
    return top


class TopLinesNoMedia(unittest.TestCase):
    def test_no_source_on_media_page_shows_no_media(self):
        top = Top()
        top._resolve()
        top._set_lines.assert_called_once_with(NO_MEDIA_TEXT, '')

    def test_idle_source_without_text_on_media_page_shows_no_media(self):
        top = Top(src_state='IDLE')
        top._resolve()
        top._set_lines.assert_called_once_with(NO_MEDIA_TEXT, '')

    def test_idle_source_label_still_wins(self):
        top = Top(src_state='IDLE', label='Bluetooth')
        top._resolve()
        top._set_lines.assert_called_once_with('Bluetooth', '')

    def test_other_center_app_keeps_top_blank(self):
        top = Top(center_app='app_readings')
        top._resolve()
        top._set_lines.assert_called_once_with('', '')


if __name__ == '__main__':
    unittest.main()
