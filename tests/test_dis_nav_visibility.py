import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "dis_client"))

# The production target has pyzmq; these tests exercise pure state logic and
# should remain runnable in lightweight development environments without it.
try:
    import zmq  # noqa: F401
except ImportError:
    sys.modules["zmq"] = types.ModuleType("zmq")

from apps.nav import NavApp
from apps.phone import PhoneApp
from dis_display import DisplayEngine
from dis_top_display_service import DISController


class NavAppRouteStateTests(unittest.TestCase):
    def test_empty_full_update_clears_stale_route(self):
        app = NavApp({})
        app.update_hudiy(
            b"HUDIY_NAV",
            {"description": "Turn right", "distance": "200 m"},
        )
        self.assertTrue(app.has_route)

        app.update_hudiy(b"HUDIY_NAV", {})

        self.assertFalse(app.has_route)
        self.assertEqual(app.meters, -1.0)

    def test_new_maneuver_details_clear_previous_distance(self):
        app = NavApp({})
        app.update_hudiy(
            b"HUDIY_NAV",
            {"description": "Turn right", "distance": "200 m"},
        )

        app.update_hudiy(
            b"HUDIY_NAV",
            {"description": "Continue straight", "maneuver_type": 0},
        )

        self.assertTrue(app.has_route)
        self.assertEqual(app.meters, -1.0)
        self.assertEqual(app.distance_label, "")


class CenterDisplayNavVisibilityTests(unittest.TestCase):
    def _engine(self, current="app_nav"):
        engine = DisplayEngine.__new__(DisplayEngine)
        engine.nav_active = True
        engine.apps = {
            "app_nav": SimpleNamespace(has_route=False),
            "app_phone": SimpleNamespace(has_phone=False),
            "app_media": object(),
        }
        engine.pages = ["app_nav", "app_phone", "app_media"]
        engine.current_page_idx = engine.pages.index(current)
        engine.pre_nav_app_name = None
        engine.nav_auto_triggered = False
        engine.boot_inactive_hold = False
        engine.nav_claim_on_nav = False
        engine.phone_claim_on_phone = False
        engine.phone_auto_overlay = False
        engine.content_auto_claimed = False
        engine.user_paused = False
        engine.service_ready = True
        engine._send_draw = lambda payload: True
        return engine

    def test_carplay_active_without_route_is_not_available(self):
        engine = self._engine()

        self.assertFalse(engine.is_nav_available())

    def test_selected_nav_page_returns_to_media_without_route(self):
        engine = self._engine()
        switched = []

        def switch_to_app(name):
            switched.append(name)
            engine.current_page_idx = engine.pages.index(name)

        engine.switch_to_app = switch_to_app
        engine._check_nav_availability_pause()

        self.assertEqual(switched, ["app_media"])

    def test_route_becomes_available_only_with_real_content(self):
        engine = self._engine()
        engine.apps["app_nav"].has_route = True

        self.assertTrue(engine.is_nav_available())

    def test_selected_phone_page_returns_to_media_without_phone(self):
        engine = self._engine(current="app_phone")
        switched = []

        def switch_to_app(name):
            switched.append(name)
            engine.current_page_idx = engine.pages.index(name)

        engine.switch_to_app = switch_to_app
        engine._check_nav_availability_pause()

        self.assertEqual(switched, ["app_media"])

    def test_empty_nav_under_call_changes_underlying_page_without_call_flicker(self):
        engine = self._engine(current="app_nav")
        engine.phone_auto_overlay = True
        engine.apps["app_phone"].has_phone = True
        engine.current_app = engine.apps["app_phone"]
        engine.publish_status = lambda *args, **kwargs: None

        engine._check_nav_availability_pause()

        self.assertEqual(engine.pages[engine.current_page_idx], "app_media")
        self.assertIs(engine.current_app, engine.apps["app_phone"])


class PhoneAvailabilityTests(unittest.TestCase):
    def test_disconnected_idle_phone_has_no_page_content(self):
        app = PhoneApp({})
        self.assertFalse(app.has_phone)

    def test_connected_idle_phone_has_no_page_content(self):
        app = PhoneApp({})
        app.update_hudiy(b"HUDIY_PHONE", {"connection_state": "CONNECTED"})
        self.assertFalse(app.has_phone)

    def test_dialing_call_is_active_content(self):
        app = PhoneApp({})
        app.update_hudiy(b"HUDIY_PHONE", {"state": "DIALING"})
        self.assertTrue(app.has_phone)
        self.assertTrue(app.has_active_call)


class ContextClaimTests(unittest.TestCase):
    def _engine(self):
        engine = CenterDisplayNavVisibilityTests()._engine(current="app_media")
        sent = []
        engine._send_draw = lambda payload: sent.append(payload) or True
        return engine, sent

    def test_nav_claim_does_not_resume_without_route(self):
        engine, sent = self._engine()
        engine.current_page_idx = engine.pages.index("app_nav")
        engine.nav_claim_on_nav = True
        engine.boot_inactive_hold = True
        engine.user_paused = True
        engine.switch_to_app = lambda name: setattr(
            engine, "current_page_idx", engine.pages.index(name)
        )

        engine._check_nav_availability_pause()

        self.assertNotIn({"command": "resume"}, sent)
        self.assertTrue(engine.boot_inactive_hold)

    def test_nav_claim_resumes_only_with_real_route(self):
        engine, sent = self._engine()
        engine.current_page_idx = engine.pages.index("app_nav")
        engine.apps["app_nav"].has_route = True
        engine.nav_claim_on_nav = True
        engine.boot_inactive_hold = True
        engine.user_paused = True

        engine._check_nav_availability_pause()

        self.assertIn({"command": "resume"}, sent)
        self.assertTrue(engine.content_auto_claimed)

    def test_phone_claim_resumes_only_for_live_call_overlay(self):
        engine, sent = self._engine()
        engine.apps["app_phone"].has_phone = True
        engine.phone_claim_on_phone = True
        engine.phone_auto_overlay = True
        engine.boot_inactive_hold = True
        engine.user_paused = True

        engine._check_nav_availability_pause()

        self.assertIn({"command": "resume"}, sent)
        self.assertTrue(engine.content_auto_claimed)

    def test_auto_claim_releases_when_content_ends(self):
        engine, sent = self._engine()
        engine.content_auto_claimed = True

        engine._check_nav_availability_pause()

        self.assertIn({"command": "pause"}, sent)
        self.assertTrue(engine.user_paused)


class NavigationAutoSwitchTests(unittest.TestCase):
    def _engine(self, current="app_media", meters=2000):
        from navigation_policy import NavigationPolicy
        engine = DisplayEngine.__new__(DisplayEngine)
        engine.nav_auto_switch = True
        engine.nav_active = True
        engine.service_ready = True
        engine.pages = ["app_nav", "app_media", "app_car_info"]
        engine.current_page_idx = engine.pages.index(current)
        engine.apps = {"app_nav": SimpleNamespace(has_route=True, meters=meters, description='Main')}
        engine.nav_policy = NavigationPolicy()
        engine.pre_nav_app_name = None
        return engine

    def test_route_start_peeks_without_losing_manual_page(self):
        engine = self._engine()
        engine._handle_nav_auto_switch(engine.apps['app_nav'])
        self.assertEqual(engine.pre_nav_app_name, 'app_media')
        self.assertEqual(engine.pages[engine.current_page_idx], 'app_media')

    def test_manual_nav_stays_after_distant_next_maneuver(self):
        engine = self._engine(current='app_nav')
        engine._handle_nav_auto_switch(engine.apps['app_nav'])
        self.assertIsNone(engine.pre_nav_app_name)
        self.assertEqual(engine.pages[engine.current_page_idx], 'app_nav')

    def test_manual_escape_does_not_repeat_same_approach(self):
        engine = self._engine(meters=100)
        engine._handle_nav_auto_switch(engine.apps['app_nav'])
        engine.nav_policy.manual_select()
        engine.current_page_idx = engine.pages.index('app_car_info')
        engine._handle_nav_auto_switch(engine.apps['app_nav'])
        self.assertIsNone(engine.pre_nav_app_name)

    def test_new_maneuver_can_interrupt_after_manual_escape(self):
        engine = self._engine(meters=100)
        engine._handle_nav_auto_switch(engine.apps['app_nav'])
        engine.nav_policy.manual_select()
        engine.apps['app_nav'].description = 'Pine'
        engine._handle_nav_auto_switch(engine.apps['app_nav'])
        self.assertEqual(engine.pre_nav_app_name, 'app_media')

    def test_route_end_cancels_override(self):
        engine = self._engine(meters=100)
        engine._handle_nav_auto_switch(engine.apps['app_nav'])
        engine.apps['app_nav'].has_route = False
        engine._handle_nav_auto_switch(engine.apps['app_nav'])
        self.assertIsNone(engine.pre_nav_app_name)



class TopDisplayNavVisibilityTests(unittest.TestCase):
    def test_carplay_active_without_route_is_not_available(self):
        controller = DISController.__new__(DISController)
        controller._nav_active = True
        controller._nav_texts = ("", "")

        self.assertFalse(controller._is_nav_available())


if __name__ == "__main__":
    unittest.main()
