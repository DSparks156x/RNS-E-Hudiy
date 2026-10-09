"""Route lifecycle regressions using real DIS consumers and no live sockets."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
from apps.nav import NavApp
from dis_top_display_service import DISController
from navigation_state import has_route_content


class RouteLifecycleTests(unittest.TestCase):
    def app(self):
        app = NavApp({'display': {'center_display': {'high_resolution': False}}})
        app.update_hudiy(b'HUDIY_NAV', {'description': 'Turn right', 'distance': '200 m'})
        return app

    def test_route_end_blocks_delayed_distance_until_new_maneuver(self):
        for topic, payload in ((b'HUDIY_NAV', {}),
                               (b'HUDIY_NAV', {'has_route': False, 'description': 'Stale'}),
                               (b'HUDIY_NAV_STATUS', {'active': False}),
                               (b'HUDIY_NAV_DISTANCE', {'label': 'No route'})):
            with self.subTest(topic=topic, payload=payload):
                app = self.app()
                app.update_hudiy(topic, payload)
                app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': '50 m'})
                app.update_hudiy(b'HUDIY_NAV_STATUS', {'active': True})
                self.assertFalse(app.has_route)
                self.assertEqual(app.meters, -1)
                self.assertEqual(app.get_view()[0]['type'], 'nav_no_route')
                app.update_hudiy(b'HUDIY_NAV', {'description': 'New maneuver'})
                app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': '50 m'})
                self.assertTrue(app.has_route)
                self.assertEqual(app.meters, 50)

    def test_invalid_distances_do_not_become_approach_distances(self):
        for value in (True, False, float('nan'), float('inf'), -10, '-10 m',
                      'No route 500 m', 'In 5 minutes', '12 minutes', '1/0 mi'):
            with self.subTest(value=value):
                self.assertEqual(NavApp.parse_distance(value), -1)
                app = self.app()
                app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': value})
                app.get_view()  # Non-finite input must not crash rendering.

    def test_known_maneuver_attributes_wait_for_route_content(self):
        app = NavApp({})
        app.update_hudiy(b'HUDIY_NAV', {'maneuver_type': 4, 'maneuver_side': 2})
        self.assertFalse(app.has_route)
        app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': '200 m'})
        self.assertTrue(app.has_route)
        app.update_hudiy(b'HUDIY_NAV', {'has_route': False})
        app.update_hudiy(b'HUDIY_NAV', {'maneuver_type': 4})
        app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': '50 m'})
        self.assertFalse(app.has_route)

    def test_shared_content_checks_reject_attributes_and_invalid_units(self):
        for payload in ({'maneuver_type': 4}, {'maneuver_type': 14, 'distance': ''},
                        {'distance': '123bananas'}, {'distance': '1/0 mi'},
                        {'distance': '-5 m'}, {'description': 'No Route .'}):
            with self.subTest(payload=payload):
                self.assertFalse(has_route_content(payload))
        for label, meters in (('1,5 km', 1500), ('1,234.5 m', 1234.5),
                              ('1.234,5 m', 1234.5), ('1/4 mi', 402.336)):
            with self.subTest(label=label):
                self.assertTrue(has_route_content({'distance': label}))
                self.assertAlmostEqual(NavApp.parse_distance(label), meters)

    def test_bad_approach_bar_settings_fall_back(self):
        for value in ('300', True, float('nan'), float('inf'), None, -1):
            with self.subTest(value=value):
                app = self.app()
                app.config['display']['center_display']['navigation'] = {
                    'approach_bar_max_distance': value}
                self.assertEqual(app._get_progress_height(), 16)


class TopNavigationTests(unittest.TestCase):
    def controller(self):
        top = DISController.__new__(DISController)
        top._ctrl_l1 = object()
        top._ctrl_l2 = object()
        top._nav_l1_mode = 'description'
        top._nav_l2_mode = 'distance'
        top._nav_active = True
        top._nav_texts = ('Old route', '200 m')
        top._resolve = Mock()
        top._load_nav_state = Mock()
        return top

    def test_route_absence_overrides_cached_fields_and_provider_placeholder(self):
        for payload in ({'has_route': False, 'description': 'Old route', 'distance': '200 m'},
                        {'description': 'No Route'}, {'distance': 'No navigation'}, {}):
            with self.subTest(payload=payload):
                top = self.controller()
                top._update_navigation(b'HUDIY_NAV', payload)
                self.assertEqual(top._nav_texts, ('', ''))
                self.assertFalse(top._is_nav_available())

    def test_new_active_status_does_not_resurrect_old_disk_cache(self):
        top = self.controller()
        top._update_navigation(b'HUDIY_NAV_STATUS', {'active': False})
        top._update_navigation(b'HUDIY_NAV_STATUS', {'active': True})
        self.assertFalse(top._is_nav_available())
        top._load_nav_state.assert_not_called()
        top._update_navigation(b'HUDIY_NAV', {'description': 'New route', 'distance': 0})
        self.assertTrue(top._is_nav_available())
        self.assertEqual(top._nav_texts, ('New route', '0'))

    def test_status_requires_boolean_activity(self):
        top = self.controller()
        top._update_navigation(b'HUDIY_NAV_STATUS', {'active': 'false'})
        self.assertFalse(top._is_nav_available())


if __name__ == '__main__':
    unittest.main()
