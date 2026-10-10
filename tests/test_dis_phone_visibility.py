"""Call lifecycle eligibility at entry, priority resolution and ownership."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
try:
    import zmq  # noqa: F401
except ImportError:
    sys.modules['zmq'] = types.ModuleType('zmq')

from apps.base import BaseApp
from apps.nav import NavApp
from apps.phone import PhoneApp
from dis_display import DisplayEngine
from dis_top_display_service import DISController


class PhoneVisibilityTests(unittest.TestCase):
    def engine(self, pages=None, selected='app_media'):
        engine = DisplayEngine.__new__(DisplayEngine)
        engine.apps = {'app_phone': PhoneApp({}), 'app_media': BaseApp({}),
                       'app_nav': NavApp({})}
        engine.pages = pages or ['app_media', 'app_phone', 'app_nav']
        engine.current_page_idx = engine.pages.index(selected)
        engine.current_app = engine.apps[selected]
        engine.phone_active = False
        engine.phone_auto_overlay = False
        engine.pre_phone_app_name = None
        engine.nav_active = False
        engine.pre_nav_app_name = None
        engine.nav_auto_triggered = False
        engine.brief_cover_active = False
        engine.egg_active = False
        engine.nav_claim_on_nav = False
        engine.phone_claim_on_phone = True
        engine.context_claim_only = True
        engine.content_auto_claimed = False
        engine.cluster_selected_session = False
        engine.user_paused = True
        engine.boot_inactive_hold = True
        engine.service_ready = True
        engine.commands = []
        engine._send_draw = lambda payload: engine.commands.append(payload) or True
        engine.force_redraw = Mock()
        engine.publish_status = Mock()
        return engine

    def receive(self, engine, data):
        engine.apps['app_phone'].update_hudiy(b'HUDIY_PHONE', data)
        engine._handle_phone_status(data)

    def settle(self, engine):
        # Match the production loop: resolve and enter before checking claims.
        resolved = engine._resolve_app_priority()
        if resolved is not None and engine.apps[resolved] is not engine.current_app:
            engine.current_app.on_leave()
            engine.current_app = engine.apps[resolved]
            engine.current_app.on_enter()
        engine._check_nav_availability_pause()
        return resolved

    def live_nav(self, engine):
        engine.nav_active = True
        engine.apps['app_nav'].update_hudiy(b'HUDIY_NAV', {'description': 'Turn right'})
        engine.nav_claim_on_nav = True

    def test_idle_connectivity_has_no_view_claim_or_phone_priority(self):
        for data in ({}, {'connection_state': 'CONNECTED'},
                     {'connection_state': 'DISCONNECTED'}, {'state': 'CONNECTED'},
                     {'state': 'ACTIVE', 'call_active': False}):
            with self.subTest(data=data):
                engine = self.engine()
                self.receive(engine, data)
                self.assertEqual(self.settle(engine), 'app_media')
                self.assertEqual(engine.apps['app_phone'].get_view(), {})
                self.assertEqual(engine.commands, [])

    def test_live_update_survives_entry_despite_opposite_disk_snapshot(self):
        for live_state, cached_state in [('IDLE', 'ACTIVE'), ('INCOMING', 'IDLE')]:
            with self.subTest(live_state=live_state):
                phone = PhoneApp({})
                phone.update_hudiy(b'HUDIY_PHONE', {'state': live_state})
                with patch('os.path.exists', return_value=True), patch(
                        'builtins.open', mock_open(read_data=json.dumps({'state': cached_state}))):
                    phone.on_enter()
                self.assertEqual(phone.state, live_state)
                self.assertEqual(phone.has_phone, live_state != 'IDLE')

    def test_stale_disk_call_cannot_establish_call_on_startup(self):
        phone = PhoneApp({})
        with patch('os.path.exists', return_value=True), patch(
                'builtins.open', mock_open(read_data='{"state":"ACTIVE"}')):
            phone.on_enter()
        self.assertFalse(phone.has_phone)
        self.assertEqual(phone.get_view(), {})

    def test_all_live_call_states_overlay_and_claim_then_release(self):
        for state in PhoneApp.CALL_STATES:
            with self.subTest(state=state):
                engine = self.engine()
                self.receive(engine, {'state': state, 'call_active': True})
                self.assertEqual(self.settle(engine), 'app_phone')
                self.assertEqual(engine.commands, [{'command': 'resume'}])
                self.assertTrue(engine.apps['app_phone'].get_view())
                engine.apps['app_phone'].set_control_mode(True)
                self.receive(engine, {'state': 'IDLE', 'connection_state': 'CONNECTED'})
                self.assertEqual(self.settle(engine), 'app_media')
                self.assertEqual(engine.commands[-1], {'command': 'pause'})
                self.assertFalse(engine.apps['app_phone'].control_mode)

    def test_call_end_restores_live_nav_without_releasing_its_claim(self):
        engine = self.engine()
        self.live_nav(engine)
        engine.pre_nav_app_name = 'app_media'
        engine.user_paused = engine.boot_inactive_hold = False
        engine.content_auto_claimed = True
        self.receive(engine, {'state': 'ACTIVE'})
        self.assertEqual(self.settle(engine), 'app_phone')
        self.receive(engine, {'state': 'IDLE', 'connection_state': 'CONNECTED'})
        self.assertEqual(self.settle(engine), 'app_nav')
        self.assertIs(engine.current_app, engine.apps['app_nav'])
        self.assertEqual(engine.commands, [])

    def test_stale_phone_overlay_cannot_displace_live_navigation(self):
        engine = self.engine()
        self.live_nav(engine)
        engine.pre_nav_app_name = 'app_media'
        engine.phone_auto_overlay = True
        self.assertEqual(engine._resolve_app_priority(), 'app_nav')
        self.receive(engine, {'connection_state': 'CONNECTED'})
        self.assertFalse(engine.phone_auto_overlay)

    def test_remembered_phone_selection_moves_to_fallback_before_draw(self):
        engine = self.engine(selected='app_phone')
        self.assertEqual(self.settle(engine), 'app_media')
        self.assertEqual(engine.pages[engine.current_page_idx], 'app_media')
        self.assertIs(engine.current_app, engine.apps['app_media'])

    def test_direct_idle_phone_jump_is_rejected(self):
        engine = self.engine()
        engine.switch_to_app('app_phone')
        self.assertIs(engine.current_app, engine.apps['app_media'])
        self.assertEqual(engine.pages[engine.current_page_idx], 'app_media')
        engine.force_redraw.assert_not_called()

    def test_idle_phone_never_queues_a_draw(self):
        engine = self.engine(selected='app_phone')
        engine.user_paused = engine.boot_inactive_hold = False
        engine._queue_ui_frame = Mock()
        engine._ui_frame_waiting = Mock(return_value=False)
        engine._draw()
        engine._queue_ui_frame.assert_not_called()
        self.assertEqual(engine.commands, [])

    def test_context_only_pages_release_without_rendering_idle_phone(self):
        for pages in (['app_phone'], ['app_phone', 'app_nav']):
            with self.subTest(pages=pages):
                engine = self.engine(pages=pages, selected='app_phone')
                engine.user_paused = engine.boot_inactive_hold = False
                engine.content_auto_claimed = True
                self.assertIsNone(self.settle(engine))
                engine._draw()
                self.assertEqual(engine.commands, [{'command': 'pause'}])
                self.assertTrue(engine.user_paused)
                self.receive(engine, {'state': 'INCOMING'})
                self.assertEqual(self.settle(engine), 'app_phone')
                self.assertEqual(engine.commands[-1], {'command': 'resume'})

    def test_empty_phone_does_not_override_nav_claim_outside_rotation(self):
        engine = self.engine(pages=['app_phone'], selected='app_phone')
        self.live_nav(engine)
        engine._check_nav_availability_pause()
        self.assertEqual(engine.commands, [{'command': 'resume'}])
        self.assertEqual(engine._resolve_app_priority(), 'app_nav')
        engine.commands.clear()
        engine._check_nav_availability_pause()
        self.assertEqual(engine.commands, [])

    def test_phone_claim_disabled_is_preserved(self):
        engine = self.engine(pages=['app_phone'], selected='app_phone')
        engine.phone_claim_on_phone = False
        engine.context_claim_only = False
        engine.user_paused = engine.boot_inactive_hold = False
        self.settle(engine)
        self.receive(engine, {'state': 'ACTIVE'})
        self.settle(engine)
        self.assertEqual(engine.commands, [{'command': 'pause'}])

    def test_idle_phone_is_not_advertised_for_wheel_control(self):
        engine = self.engine(selected='app_phone')
        del engine.publish_status
        engine.pub_status = Mock()
        engine.publish_status()
        payload = json.loads(engine.pub_status.send_multipart.call_args.args[0][1])
        self.assertEqual(payload['app'], 'unknown')
        self.assertFalse(payload['wheel_supported'])

    def test_top_call_end_clears_phone_content_and_ownership(self):
        top = DISController.__new__(DISController)
        top._call_active = False
        top._last_phone_state = 'IDLE'
        top._phone_controls = PhoneApp({})
        top._phone_fields = Mock(return_value=('Caller', 'Active'))
        top._resolve = Mock()
        top._update_phone({'state': 'ACTIVE'})
        top._phone_control_mode = True
        top._phone_controls.set_control_mode(True)
        top._update_phone({'state': 'IDLE', 'connection_state': 'CONNECTED'})
        self.assertEqual(top._phone_texts, ('', ''))
        self.assertFalse(top._phone_control_mode)
        self.assertFalse(top._phone_controls.control_mode)
        self.assertFalse(top._call_active)
        self.assertEqual(top._resolve.call_count, 2)


if __name__ == '__main__':
    unittest.main()
