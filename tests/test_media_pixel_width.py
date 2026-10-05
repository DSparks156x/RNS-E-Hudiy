"""Pixel-budget media and actual dictionary redraw regression tests; no IPC."""
import ast
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
if REPO.name != 'RNS-E-Hudiy':
    REPO = Path(r'C:\Users\raccoon\Documents\carstuff\RNS-E-Hudiy')
sys.path.insert(0, str(REPO / 'dis_client'))
from apps.media import MediaApp
from font_metrics import measure_text

SOURCE = REPO / 'dis_client/dis_display.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
names = {'_draw', '_queue_ui_frame', '_ui_frame_waiting', 'force_redraw', '_handle_ui_frame_result'}
namespace = {'logger': logging.getLogger(__name__)}
exec(compile(ast.Module(body=[n for n in ast.walk(tree)
    if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), str(SOURCE), 'exec'), namespace)
Engine = type('Engine', (), {name: namespace[name] for name in names})


class MediaPixelWidths(unittest.TestCase):
    def test_narrow_title_fits_more_than_sixteen_characters(self):
        app = MediaApp()
        app.title = 'i' * 32  # Captured4px advances: exactly128px.
        self.assertEqual(app.get_view()['line1'], ('i' * 32, 0x06))
        self.assertNotIn('media_title', app._scroll_state)

    def test_wide_title_scrolls_before_sixteen_characters(self):
        app = MediaApp()
        app.title = app.artist = app.album = 'W' * 11  # Captured12px advances:132px.
        with patch('apps.base.time.monotonic', return_value=1):
            view = app.get_view()
        for key in ('line1', 'line2', 'line3'):
            self.assertEqual(view[key], ('W' * 10, 0x06))
            self.assertLessEqual(measure_text(view[key][0]), 128)
        self.assertEqual(set(app._scroll_state), {'media_title', 'media_artist', 'media_album'})

    def test_time_field_is_fit_by_width_instead_of_character_count(self):
        app = MediaApp()
        app.time_str = 'i' * 25
        self.assertEqual(app.get_view()['line4'][0], 'i' * 25)
        app.time_str = 'W' * 25
        self.assertEqual(app.get_view()['line4'][0], 'W' * 10)

    def test_overflowing_scroll_is_left_aligned_and_width_limited(self):
        app = MediaApp({'display': {'text_centering': True}})
        app.title = 'W' * 10 + 'AB'
        with patch('apps.base.time.monotonic', return_value=0):
            initial = app.get_view()['line1']
        with patch('apps.base.time.monotonic', return_value=2):
            advanced = app.get_view()['line1']
        self.assertEqual(initial, ('W' * 10, 0x06))
        self.assertEqual(advanced[1], 0x06)
        self.assertLessEqual(measure_text(advanced[0], 0x26), 128)
        self.assertNotEqual(initial[0], advanced[0])

    def test_alignment_is_selected_independently_for_each_original_field(self):
        app = MediaApp({'display': {'text_centering': True}})
        app.title, app.artist, app.album, app.time_str = 'i' * 32, 'W' * 11, 'ABC', 'i' * 25
        view = app.get_view()
        self.assertEqual([view[key][1] for key in ('line1', 'line2', 'line3', 'line4')],
                         [0x26, 0x06, 0x26, 0x26])
        app.time_str = 'W' * 25
        self.assertEqual(app.get_view()['line4'], ('W' * 10, 0x06))

    def test_legacy_profile_uses_legacy_widths_for_media(self):
        app = MediaApp({'display': {'font_resolution': 'legacy'}})
        app.title = 'W' * 30
        view = app.get_view()['line1'][0]
        self.assertLess(len(view), 30)
        self.assertLessEqual(measure_text(view, profile='legacy'), 128)


class DictionaryTextLines(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.e.Y = {'line1': 1, 'line2': 11, 'line3': 21, 'line4': 31, 'line5': 41}
        self.e.cfg, self.e.last_sent, self.e.last_sent_flags = {}, {}, {}
        self.e.service_ready, self.e.user_paused, self.e.boot_inactive_hold = True, False, False
        self.e.nav_active = False
        self.e.frame_seq_counter, self.e._pending_ui_frame = 10, None
        self.e._send_draw = Mock(return_value=True)
        self.e.publish_status = Mock()
        self.e.current_app = SimpleNamespace(get_view=Mock(return_value={'line1': ('WWW', 0x06)}),
            on_frame_sent=Mock(), on_frame_acked=Mock(), on_display_reset=Mock(), on_frame_failed=Mock())

    def commands(self):
        return self.e._send_draw.call_args.args[0]['commands']

    def ack(self):
        self.assertTrue(self.e._handle_ui_frame_result(self.e.frame_seq_counter, True))
        self.e._send_draw.reset_mock()

    def test_equal_character_count_shrink_clears_old_proportional_pixels(self):
        self.e._draw()
        self.ack()
        self.e.current_app.get_view.return_value = {'line1': ('iii', 0x06)}
        self.e._draw()
        self.assertEqual(self.commands(), [dict(command='clear_area', x=0, y=1, w=64, h=9),
            dict(command='draw_text', text='iii', y=1, flags=0x06)])
        self.assertEqual(self.e._send_draw.call_count, 1)

    def test_every_dictionary_line_is_bounded_by_its_selected_font(self):
        for profile in ('native', 'legacy'):
            for flags in (0x02, 0x06, 0x0A, 0x26):
                self.e.force_redraw()
                self.e.cfg = {'display': {'font_resolution': profile}}
                self.e.current_app.get_view.return_value = {'line1': ('W' * 40, flags)}
                self.e._draw()
                command = next(c for c in self.commands() if c['command'] == 'draw_text')
                self.assertLessEqual(measure_text(command['text'], flags, profile), 128)
                self.assertNotIn('\x1f', command['text'])
                self.ack()

    def test_centering_and_inversion_changes_clear_without_config_center_switch(self):
        self.e.current_app.get_view.return_value = {'line1': ('A', 0xA6)}
        self.e._draw()
        self.ack()
        self.e.current_app.get_view.return_value = {'line1': ('A', 0x26)}
        self.e._draw()
        self.assertEqual([c['command'] for c in self.commands()], ['clear_area', 'draw_text'])
        self.assertEqual(self.commands()[1]['text'], 'A')

    def test_empty_and_omitted_lines_clear_without_padding_or_repeat_frames(self):
        self.e._draw()
        self.ack()
        self.e.current_app.get_view.return_value = {}
        self.e._draw()
        self.assertEqual(self.commands(), [dict(command='clear_area', x=0, y=1, w=64, h=9)])
        self.ack()
        self.e._draw()
        self.e._send_draw.assert_not_called()

    def test_clear_rectangles_stay_inside_central_or_full_region(self):
        self.e.current_app.get_view.return_value = {'line5': ('A', 0x06)}
        self.e._draw()
        clear = next(c for c in self.commands() if c['command'] == 'clear_area')
        self.assertEqual((clear['y'], clear['h']), (41, 7))
        self.ack()
        self.e.force_redraw()
        self.e.nav_active = True
        self.e._draw()
        clear = next(c for c in self.commands() if c['command'] == 'clear_area')
        self.assertEqual((clear['y'], clear['h']), (41, 9))

    def test_custom_to_dictionary_transition_is_one_atomic_frame(self):
        self.e.last_sent.update(groups={'icon': 'old'}, last_type='native')
        self.e._draw()
        self.assertEqual([c['command'] for c in self.commands()], ['clear', 'clear_area', 'draw_text'])
        self.e._send_draw.assert_called_once()
        self.assertIsNone(self.e.last_sent['groups'])

    def test_pending_frame_blocks_view_consumption_and_nack_rebuilds(self):
        self.e._draw()
        self.e.current_app.get_view.return_value = {'line1': ('NEW', 0x06)}
        self.e._draw()
        self.e.current_app.get_view.assert_called_once()
        self.e._send_draw.assert_called_once()
        self.assertTrue(self.e._handle_ui_frame_result(11, False))
        self.assertEqual(self.e.last_sent, {})
        self.e._draw()
        self.assertEqual(self.commands()[-1]['text'], 'NEW')

    def test_rejected_frame_leaves_no_cached_text_or_pending_ack(self):
        self.e._send_draw.return_value = False
        self.e._draw()
        self.assertEqual(self.e.last_sent, {})
        self.assertEqual(self.e.last_sent_flags, {})
        self.assertIsNone(self.e._pending_ui_frame)
        self.e.current_app.on_frame_sent.assert_not_called()

    def test_long_media_to_fitting_media_restores_center_after_clean_line_clear(self):
        app = MediaApp({'display': {'text_centering': True}})
        app.title = 'W' * 11
        self.e.cfg = app.config
        self.e.current_app = app
        self.e._draw()
        title = next(c for c in self.commands() if c['command'] == 'draw_text' and c['y'] == 1)
        self.assertEqual(title['flags'], 0x06)
        self.ack()
        app.title = 'iii'
        self.e._draw()
        self.assertEqual(self.commands(), [dict(command='clear_area', x=0, y=1, w=64, h=9),
            dict(command='draw_text', text='iii', y=1, flags=0x26)])
        self.assertNotIn('media_title', app._scroll_state)

    def test_profile_switch_redraws_even_if_text_is_identical(self):
        self.e._draw()
        self.ack()
        self.e.cfg = {'display': {'font_resolution': 'legacy'}}
        self.e._draw()
        self.assertEqual([c['command'] for c in self.commands()], ['clear_area', 'draw_text'])


if __name__ == '__main__':
    unittest.main()
