"""Measured navigation viewport and bar-transition regressions, offline."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'dis_client').is_dir():
    ROOT = Path(__file__).resolve().parent.parent / 'RNS-E-Hudiy'
sys.path.insert(0, str(ROOT / 'dis_client'))
from apps.nav import NavApp


def app_with_route(description='Main St', distance='10 m', profile='native'):
    app = NavApp({'display': {'center_display': {'high_resolution': profile == 'native'},
                  'units': {'speed': 'metric'}}})
    app.update_hudiy(b'HUDIY_NAV', {'description': description, 'distance': distance})
    return app


def text_item(view, group):
    return next(item for item in view if item.get('group') == group
                and item.get('cmd') == 'draw_text')


class NavigationMeasuredLayoutTests(unittest.TestCase):
    def test_street_manually_centers_inside_bar_viewport(self):
        for profile in ('native', 'legacy'):
            app = app_with_route(profile=profile)
            view = app.get_view()
            item = text_item(view, 'street')
            width = app.text_width(item['text'], flags=item['flags'])
            self.assertEqual(item['flags'] & 0x20, 0)
            self.assertGreaterEqual(item['x'], 1)
            self.assertLessEqual(item['x'] * 2 + width, 120)
            self.assertLessEqual(abs((item['x'] * 2 + width / 2) - 61), 2)

    def test_street_uses_measured_viewport_not_twelve_character_limit(self):
        app = app_with_route(description='i' * 20)
        self.assertLessEqual(app.text_width(app.description), 118)
        item = text_item(app.get_view(), 'street')
        self.assertEqual(item['text'], app.description)
        app.description = 'W' * 20
        item = text_item(app.get_view(), 'street')
        self.assertLess(len(item['text']), 20)
        self.assertLessEqual(app.text_width(item['text']), 118)
        self.assertEqual(item['x'], 1)

    def test_tighter_margins_fit_native_narrow_text_without_clipping(self):
        for count, distance, right in ((29, '10 m', 61), (31, '9999 km', 64)):
            with self.subTest(count=count):
                app = app_with_route(description='i' * count, distance=distance)
                item = text_item(app.get_view(), 'street')
                self.assertEqual(item['text'], 'i' * count)
                self.assertEqual(item['flags'] & 0x20, 0)
                end = item['x'] * 2 + app.text_width(item['text'])
                self.assertLessEqual(end, (right - 1) * 2)
                self.assertGreaterEqual(item['x'] * 2, 2)

    def test_bar_removed_is_cleared_before_text_uses_full_slot(self):
        app = app_with_route()
        app.get_view()
        app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': '9999 km'})
        view = app.get_view()
        bar_clear = next(i for i, item in enumerate(view)
                         if item.get('group') == 'bar' and item.get('cmd') == 'clear_area')
        for group in ('street', 'dist'):
            draw = next(i for i, item in enumerate(view)
                        if item.get('group') == group and item.get('cmd') == 'draw_text')
            self.assertLess(bar_clear, draw)
        self.assertTrue(any(c.get('group') == 'street' and c.get('cmd') == 'clear_area'
                            and c.get('x') == 0 and c.get('w') == 64 for c in view))

    def test_street_scroll_does_not_change_bar_signature(self):
        app = app_with_route(description='A long street running toward the edge')
        original = app.get_view()
        app.description = 'A completely different long street name'
        changed = app.get_view()
        self.assertEqual([c for c in original if c.get('group') == 'bar'],
                         [c for c in changed if c.get('group') == 'bar'])
        # Neither text group contains duplicated bar-clear/draw operations.
        self.assertFalse(any(c.get('x') == 61 and c.get('group') in ('dist', 'street')
                             for c in changed))

    def test_distance_numbers_are_complete_representations_and_fit(self):
        for profile in ('native', 'legacy'):
            for label in ('99.96 km', '9999.9 km', 1e100, '12500 km'):
                app = app_with_route(distance=label, profile=profile)
                view = app.get_view()
                for item in view:
                    if item.get('group') == 'dist' and item.get('cmd') == 'draw_text':
                        bar = app._get_progress_height() > 0
                        self.assertLessEqual(app.text_width(item['text']), 38 if bar else 44)
        app = app_with_route()
        # Force a narrow slot: the value must be rescaled, not sliced to123.
        result = app._fit_distance_value(12345, False, app.text_width('12k'))
        self.assertTrue(result.endswith('k'))
        self.assertNotEqual(result, '123')

    def test_no_route_is_measured_centered_without_padding(self):
        app = NavApp({})
        item = text_item(app.get_view(), 'no_route_1')
        self.assertEqual(item['text'], 'No Route')
        self.assertEqual(item['x'], (128 - app.text_width('No Route')) // 4)


if __name__ == '__main__':
    unittest.main()
