"""Distance slot regressions against the selected measured font profile."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
from apps.nav import NavApp


def render(distance, units='metric', approach_max=300):
    app = NavApp({'display': {'road_side': 'right', 'units': {'speed': units},
                  'center_display': {'high_resolution': True, 'navigation': {
                                      'approach_bar_max_distance': approach_max}}}})
    app.update_hudiy(b'HUDIY_NAV', {'description': 'Main St', 'distance': distance,
                                  'maneuver_type': 4, 'maneuver_side': 2})
    view = app.get_view()
    labels = [item['text'] for item in view
              if item.get('group') == 'dist' and item.get('cmd') == 'draw_text']
    bars = [item['length'] for item in view
            if item.get('group') == 'bar' and item.get('cmd') == 'draw_line']
    return app, view, labels, max(bars or [0])


class NavigationDistanceFormattingTests(unittest.TestCase):
    def test_small_metric_distances_preserve_precision_and_units(self):
        for distance, labels in [('99 m', ['99', 'm']), ('999 m', ['999', 'm']),
                                 ('1 km', ['1.0', 'km']), ('1.2 km', ['1.2', 'km']),
                                 ('9.9 km', ['9.9', 'km']), ('99.9 km', ['99.9', 'km'])]:
            with self.subTest(distance=distance):
                self.assertEqual(render(distance)[2], labels)

    @staticmethod
    def numeric_value(label):
        scales = {'k': 1000, 'M': 1000000, 'G': 1000000000, 'T': 1000000000000}
        return float(label[:-1]) * scales[label[-1]] if label[-1] in scales else float(label)

    def assert_slot(self, app, labels, bar):
        self.assertTrue(all(app.text_width(label, flags=0x06) <= (38 if bar else 44)
                            for label in labels))

    def test_large_metric_distances_keep_meaning_and_remain_bounded(self):
        for value in (100, 1000, 9999, 10000, 12500, 100000, 1000000, 1000000000):
            with self.subTest(value=value):
                app, _, labels, bar = render(f'{value} km')
                self.assertEqual(labels[1], 'km')
                self.assertLessEqual(abs(self.numeric_value(labels[0]) - value), value * .05)
                self.assert_slot(app, labels, bar)

    def test_rounding_boundary_uses_complete_fitting_number(self):
        for label, expected in (('99.96 km', 100), ('9999.9 km', 10000)):
            app, _, labels, bar = render(label)
            self.assertEqual(self.numeric_value(labels[0]), expected)
            self.assert_slot(app, labels, bar)

    def test_imperial_distances_follow_the_same_physical_bounds(self):
        for distance in ('10 ft', '0.5 mi', '99.9 mi', '100 mi', '1000 mi', '10000 mi'):
            with self.subTest(distance=distance):
                app, _, labels, bar = render(distance, units='imperial')
                self.assert_slot(app, labels, bar)
                self.assertEqual(labels[1], 'ft' if distance.endswith('ft') else 'mi')
                value = float(distance.split()[0])
                self.assertLessEqual(abs(self.numeric_value(labels[0]) - value), max(.1, value * .05))

    def test_unknown_value_and_unit_labels_use_measured_bound(self):
        for distance in ('Unknown', 'Soon', 'WWWWWWWWWWWWWW', '1//4 enormouslylongunit'):
            with self.subTest(distance=distance):
                app, _, labels, bar = render(distance)
                self.assertEqual(app.meters, -1)
                self.assertTrue(labels)
                self.assert_slot(app, labels, bar)
                self.assertNotEqual(labels, ['0', 'm'])
                self.assertNotEqual(bar, 48)

    def test_extreme_finite_values_explicitly_saturate_without_clipping(self):
        app, _, labels, bar = render(1e100)
        self.assertTrue(labels[0].startswith('>'))
        self.assertTrue(labels[0].endswith('T'))
        self.assertEqual(labels[1], 'km')
        self.assertEqual(bar, 0)
        self.assert_slot(app, labels, bar)

    def test_custom_approach_bar_preserves_its_reserved_slot(self):
        app, view, labels, bar = render('9999 km', approach_max=20000000)
        self.assertGreater(bar, 0)
        self.assert_slot(app, labels, bar)
        self.assertTrue(any(item.get('cmd') == 'clear_area' and item.get('group') == 'dist'
                            and item.get('x') == 42 and item.get('w') == 19 for item in view))

    def test_zero_empty_and_arrival_behavior_is_preserved(self):
        for distance in (0, '0 m', 'Now', 'Arrived'):
            self.assertEqual(render(distance)[2:], (['0', 'm'], 48))
        for distance in ('', ' ', None):
            self.assertEqual(render(distance)[2:], ([], 0))

    def test_long_to_short_distance_keeps_layout_and_clears_old_value(self):
        app, before, _, _ = render('1000 km')
        app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': '5 m'})
        after = app.get_view()
        self.assertEqual(before[1], after[1])
        labels = [c for c in after if c.get('group') == 'dist' and c.get('cmd') == 'draw_text']
        self.assertEqual([(c['text'], c['x'], c['y']) for c in labels], [('5', 42, 8), ('m', 42, 17)])
        first = next(c for c in after if c.get('group') == 'dist')
        self.assertEqual(first['cmd'], 'clear_area')


if __name__ == '__main__':
    unittest.main()
