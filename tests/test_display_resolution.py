"""One display setting governs native font metrics, icons, covers and readings."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
from display_resolution import high_resolution
from font_metrics import font_profile
from apps.base import BaseApp
from apps.car_info import CarInfoApp, create_car_info_app
from apps.nav import NavApp
from apps.readings import ReadingsApp


class ResolutionTests(unittest.TestCase):
    def test_canonical_boolean_wins_every_conflicting_old_switch(self):
        for enabled in (False, True):
            cfg = {'display': {'font_resolution': 'legacy' if enabled else 'native',
                'center_display': {'high_resolution': enabled,
                    'navigation': {'high_resolution': not enabled},
                    'coverart': {'native_resolution': not enabled},
                    'car_info': {'high_resolution': not enabled}}}}
            self.assertEqual(high_resolution(cfg), enabled)
            self.assertEqual(font_profile(cfg), 'native' if enabled else 'legacy')

    def test_canonical_must_be_boolean_even_if_legacy_alias_is_valid(self):
        for invalid in ('true', 'false', 0, 1, None, [], {}):
            cfg = {'display': {'font_resolution': 'native',
                              'center_display': {'high_resolution': invalid}}}
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'must be a boolean'):
                high_resolution(cfg)

    def test_old_font_profile_migrates_first_then_present_graphics_flags(self):
        self.assertTrue(high_resolution({}))
        self.assertTrue(high_resolution({'display': {'font_resolution': 'bad'}}))
        for profile, expected in [('native', True), ('legacy', False)]:
            cfg = {'display': {'font_resolution': profile,
                'center_display': {'navigation': {'high_resolution': not expected}}}}
            self.assertEqual(high_resolution(cfg), expected)
        for section, key in [('navigation','high_resolution'), ('coverart','native_resolution'),
                             ('car_info','high_resolution')]:
            for enabled in (False, True):
                cfg = {'display': {'center_display': {section: {key: enabled}}}}
                self.assertEqual(high_resolution(cfg), enabled)
        self.assertTrue(high_resolution({'display': {'center_display': {
            'navigation': {'high_resolution': False}, 'coverart': {'native_resolution': True}}}}))
        self.assertTrue(high_resolution({'display': {'center_display': {
            'navigation': {'high_resolution': 'false'}, 'coverart': None}}}))

    def test_on_off_changes_native_text_metrics_navigation_and_readings_together(self):
        with tempfile.TemporaryDirectory() as folder:
            for enabled in (False, True):
                cfg = {'display': {'center_display': {'high_resolution': enabled}},
                       'data_logs': {'workspace_path': str(Path(folder) / 'workspace.json')}}
                text = BaseApp(cfg)
                self.assertEqual(text.text_width('111'), 30 if enabled else 18)
                navigation = NavApp(cfg)
                navigation.update_hudiy(b'HUDIY_NAV', {'description':'Main St', 'distance':'200 m',
                    'maneuver_type':4, 'maneuver_side':2})
                kinds = {item.get('cmd') for item in navigation.get_view()}
                self.assertIn('native_bitmap' if enabled else 'draw_bitmap', kinds)
                self.assertNotIn('draw_bitmap' if enabled else 'native_bitmap', kinds)
                readings = create_car_info_app(cfg)
                self.assertIsInstance(readings, ReadingsApp if enabled else CarInfoApp)


if __name__ == '__main__':
    unittest.main()
