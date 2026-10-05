"""Real navigation transitions with a controlled monotonic clock, no renderer."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'dis_client'))

from apps.base import BaseApp
from apps.nav import NavApp


def nav_config(native=True, units='metric'):
    return {'display': {'road_side': 'right', 'units': {'speed': units},
                        'center_display': {'navigation': {'high_resolution': native}}}}


def distance_text(view):
    return [item['text'] for item in view
            if item.get('group') == 'dist' and item.get('cmd') == 'draw_text']


def bar_height(view):
    return max([item['length'] for item in view
                if item.get('group') == 'dist' and item.get('cmd') == 'draw_line'] or [0])


def route(app, description='Main St', distance='200 m'):
    app.update_hudiy(b'HUDIY_NAV', {'description': description, 'distance': distance,
                                   'maneuver_type': 4, 'maneuver_side': 2})


class NavigationDistanceTransitionTests(unittest.TestCase):
    def test_blank_partial_update_clears_distance_and_bar_but_keeps_route(self):
        for native in (False, True):
            for label in ('', '   ', '\t\n', None):
                with self.subTest(native=native, label=label):
                    app = NavApp(nav_config(native))
                    route(app)
                    original = app.get_view()
                    app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': label})
                    changed = app.get_view()
                    self.assertEqual(app.distance_label, '')
                    self.assertEqual(app.meters, -1)
                    self.assertTrue(app.has_route)
                    self.assertEqual(distance_text(changed), [])
                    self.assertEqual(bar_height(changed), 0)
                    self.assertEqual(original[1], changed[1])
                    before_street = [c['text'] for c in original if c.get('group') == 'street' and c.get('cmd') == 'draw_text']
                    after_street = [c['text'] for c in changed if c.get('group') == 'street' and c.get('cmd') == 'draw_text']
                    self.assertEqual(before_street, after_street)

    def test_missing_or_blank_full_distance_waits_for_matching_label(self):
        for data in ({'description': 'Pine'}, {'description': 'Pine', 'distance': ''},
                     {'description': 'Pine', 'distance': '  '}):
            app = NavApp(nav_config())
            route(app)
            app.update_hudiy(b'HUDIY_NAV', data)
            self.assertEqual(app.meters, -1)
            self.assertEqual(distance_text(app.get_view()), [])
            self.assertEqual(bar_height(app.get_view()), 0)
            app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': '50 m'})
            self.assertEqual(distance_text(app.get_view()), ['50', 'm'])

    def test_explicit_zero_and_arrival_tokens_keep_zero_distance(self):
        for label in (0, 0.0, '0', '0 m', 'Now', ' arrived ', 'NOW'):
            with self.subTest(label=label):
                app = NavApp(nav_config())
                route(app, distance=label)
                self.assertEqual(app.meters, 0)
                self.assertEqual(distance_text(app.get_view()), ['0', 'm'])
                self.assertEqual(bar_height(app.get_view()), 48)

    def test_numeric_zero_is_content_without_a_street_description(self):
        for label in (0, 0.0):
            app = NavApp(nav_config())
            app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': label})
            self.assertEqual(app.distance_label, label)
            self.assertTrue(app.has_route)
            self.assertEqual(distance_text(app.get_view()), ['0', 'm'])

    def test_blank_label_without_street_is_not_route_content(self):
        for label in ('', ' ', None):
            app = NavApp(nav_config())
            app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': label})
            self.assertFalse(app.has_route)
            self.assertEqual(app.get_view()[0]['type'], 'nav_no_route')

    def test_unknown_labels_do_not_match_now_as_a_substring(self):
        for label in ('Unknown', 'Not known', 'Soon', 'not arrived'):
            self.assertEqual(NavApp.parse_distance(label), -1)
            app = NavApp(nav_config())
            route(app, distance=label)
            self.assertNotEqual(distance_text(app.get_view()), ['0', 'm'])
            self.assertNotEqual(bar_height(app.get_view()), 48)

    def test_numeric_and_fractional_unit_conversion_is_preserved(self):
        for label, expected in ((150, 150), (0.5, 0.5), ('1.2 km', 1200),
                                ('1/4 mi', 402.336), ('10 ft', 3.048)):
            self.assertAlmostEqual(NavApp.parse_distance(label), expected, places=2)
        app = NavApp(nav_config(units='imperial'))
        route(app, distance=100)
        self.assertEqual(distance_text(app.get_view()), ['328', 'ft'])


class ScrollTransitionTests(unittest.TestCase):
    LONG = 'Northwest International Airport Access Road'

    def setUp(self):
        self.app = BaseApp({})
        self.patch = patch('apps.base.time.monotonic')
        self.clock = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.clock.return_value = 0

    def window(self, text, **kwargs):
        options = {'max_len': 12, 'speed_ms': 100, 'start_pause_ms': 0,
                   'end_pause_ms': 0, 'continuous': False}
        options.update(kwargs)
        return self.app._scroll_text(text, 'nav_street', **options)

    def advance(self, text, count, **kwargs):
        for _ in range(count):
            self.clock.return_value += .2
            self.window(text, **kwargs)

    def test_changed_long_text_restarts_both_scroll_modes(self):
        for continuous in (False, True):
            with self.subTest(continuous=continuous):
                self.app._scroll_state.clear()
                self.window(self.LONG, continuous=continuous)
                self.advance(self.LONG, 5, continuous=continuous)
                self.assertEqual(self.window('South University Medical Center Drive', continuous=continuous),
                                 'South Univer')

    def test_shorter_long_text_recovers_from_old_offset_beyond_its_length(self):
        self.window(self.LONG, continuous=True)
        self.advance(self.LONG, 30, continuous=True)
        new = '1234567890123'
        self.assertEqual(self.window(new, continuous=True), new[:12])
        self.clock.return_value += .2
        self.assertEqual(self.window(new, continuous=True), new[1:13])

    def test_unchanged_text_keeps_scroll_phase(self):
        self.window(self.LONG, continuous=True)
        self.advance(self.LONG, 5, continuous=True)
        self.assertEqual(self.window(self.LONG, continuous=True), self.LONG[5:17])
        self.clock.return_value += .2
        self.assertEqual(self.window(self.LONG, continuous=True), self.LONG[6:18])

    def test_changed_text_gets_its_own_start_pause(self):
        self.window(self.LONG)
        self.advance(self.LONG, 5)
        start = self.clock.return_value
        new = 'South University Medical Center Drive'
        self.assertEqual(self.window(new, start_pause_ms=1000), new[:12])
        self.clock.return_value = start + .8
        self.assertEqual(self.window(new, start_pause_ms=1000), new[:12])
        self.clock.return_value = start + 1.1
        self.assertEqual(self.window(new, start_pause_ms=1000), new[1:13])

    def test_text_change_during_old_end_pause_resets(self):
        old = 'ABCDEFGHIJKLM'
        self.window(old, end_pause_ms=1000)
        self.clock.return_value = .2
        self.assertEqual(self.window(old, end_pause_ms=1000), old[1:13])
        self.clock.return_value = .3
        new = 'South University Medical Center Drive'
        self.assertEqual(self.window(new, end_pause_ms=1000), new[:12])

    def test_empty_and_short_text_remove_state_before_next_long(self):
        for text in ('', 'Oak'):
            self.window(self.LONG, continuous=True)
            self.advance(self.LONG, 10, continuous=True)
            self.assertEqual(self.window(text, continuous=True), text)
            self.assertNotIn('nav_street', self.app._scroll_state)
            self.assertEqual(self.window(self.LONG, continuous=True), self.LONG[:12])

    def test_window_or_continuous_mode_change_restarts(self):
        self.window(self.LONG)
        self.advance(self.LONG, 5)
        self.assertEqual(self.window(self.LONG, max_len=10), self.LONG[:10])
        self.advance(self.LONG, 4, max_len=10)
        self.assertEqual(self.window(self.LONG, max_len=10, continuous=True), self.LONG[:10])

    def test_defensive_wrap_recovers_offset_past_cycle_boundary(self):
        text = 'ABCDEFGHIJKLM'
        self.window(text, continuous=True)
        self.app._scroll_state['nav_street']['offset'] = 30
        self.clock.return_value = .2
        self.assertEqual(self.window(text, continuous=True), text[:12])

    def test_real_nav_long_to_long_transition_restarts_street_window(self):
        app = NavApp(nav_config())
        route(app, description=self.LONG)
        app.get_view()
        for step in range(1, 7):
            self.clock.return_value = step * .4
            app.get_view()
        new = 'South University Medical Center Drive'
        route(app, description=new)
        street = [item['text'] for item in app.get_view()
                  if item.get('group') == 'street' and item.get('cmd') == 'draw_text']
        expected = app.fit_text(new, (61 - 2) * 2, flags=0x06)
        self.assertEqual(street, [expected])


if __name__ == '__main__':
    unittest.main()
