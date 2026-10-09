"""DIS priority consistency and recovery when a top-display send fails."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
from apps.phone import PhoneApp
from dis_display import DisplayEngine
from dis_top_display_service import DISController, LineController
from icons import WHEEL_CONTROL_GLYPH, encode_audscii


class PhonePriorityTests(unittest.TestCase):
    def test_phone_native_wheel_indicator_is_present_only_during_ownership(self):
        phone = PhoneApp({'display': {'center_display': {'high_resolution': True}}})
        phone.update_hudiy(b'HUDIY_PHONE', {'state': 'INCOMING', 'call_active': True})
        self.assertNotIn(WHEEL_CONTROL_GLYPH, phone.get_view()['line1'][0])
        phone.set_control_mode(True)
        for _ in range(30):
            status = phone.get_view()['line1'][0]
            self.assertTrue(status.startswith(WHEEL_CONTROL_GLYPH))
            self.assertLessEqual(phone.text_width(status, 6), 128)
        phone.set_control_mode(False)
        self.assertNotIn(WHEEL_CONTROL_GLYPH, phone.get_view()['line1'][0])

    def test_center_releases_overlay_on_explicit_inactive_call(self):
        engine = DisplayEngine.__new__(DisplayEngine)
        engine.phone_active = False
        engine.phone_auto_overlay = False
        engine.pages = ['app_media']
        engine.current_page_idx = 0
        engine._handle_phone_status({'state': 'active'})
        self.assertTrue(engine.phone_auto_overlay)
        engine._handle_phone_status({'state': 'ACTIVE', 'call_active': False})
        self.assertFalse(engine.phone_active)
        self.assertFalse(engine.phone_auto_overlay)
        self.assertIsNone(engine.pre_phone_app_name)

    def test_top_priority_and_phone_page_use_same_canonical_call_activity(self):
        top = DISController.__new__(DISController)
        top._call_active = False
        top._last_phone_state = 'IDLE'
        top._phone_controls = PhoneApp({})
        top._phone_fields = Mock(return_value=('Caller', 'Active'))
        top._resolve = Mock()
        top._update_phone({'state': 'active'})
        self.assertTrue(top._call_active)
        self.assertEqual(top._last_phone_data['state'], 'ACTIVE')
        top._update_phone({'state': 'ACTIVE', 'call_active': False})
        self.assertFalse(top._call_active)
        self.assertFalse(top._phone_controls.has_active_call)
        self.assertEqual(top._last_phone_data['state'], 'IDLE')
        self.assertEqual(top._resolve.call_count, 2)


class TopSendRecoveryTests(unittest.TestCase):
    def test_top_phone_wheel_prefix_survives_scroll_and_clears_atomically(self):
        line = LineController(None, '', 0, 'test', .01, 0, 0, 0,
                              False, 3, False, SimpleNamespace(running=False))
        line.set_text(WHEEL_CONTROL_GLYPH + ' A long caller name')
        prefix = encode_audscii(WHEEL_CONTROL_GLYPH + ' ')
        self.assertEqual(line.scroller.width, 6)
        for _ in range(20):
            line.scroller.last_tick = -100
            line.scroller.wait_timer = 0
            line.scroller.tick()
            snapshot = line.snapshot()
            self.assertTrue(snapshot.startswith(prefix))
            self.assertEqual(len(snapshot), 8)
        line.set_text('A long caller name')
        self.assertEqual(line.scroller.width, 8)
        self.assertNotEqual(line.snapshot()[:2], prefix)
        line.set_text(WHEEL_CONTROL_GLYPH + ' Active')
        self.assertTrue(line.clear())
        self.assertEqual(line.snapshot(), b' ' * 8)

    def test_failed_heartbeat_is_retried_at_next_interval(self):
        line = LineController.__new__(LineController)
        line._zmq_ctx = Mock()
        line._can_send_addr = 'inproc://unused-test'
        line.ctrl = SimpleNamespace(running=True)
        line._watcher = SimpleNamespace(tv_active=True)
        line.no_scroll = True
        line.hb_interval = .1
        line._last_sent = b'old text'
        line._last_force = 0
        line._next_write = 0
        line._debounce_until = 0
        line.snapshot = Mock(return_value=b'new text')
        line.unfreeze_scroll = Mock()
        line._send = Mock(side_effect=[False, True])
        sleeps = [0]
        def sleep(_):
            sleeps[0] += 1
            if sleeps[0] == 2:
                line.ctrl.running = False
        with patch('dis_top_display_service.time.monotonic', side_effect=[0, 1, 1.2]), \
                patch('dis_top_display_service.time.sleep', side_effect=sleep):
            line.run()
        self.assertEqual([call.args for call in line._send.call_args_list],
                         [(b'new text',), (b'new text',)])
        self.assertEqual(line._last_sent, b'new text')
        self.assertEqual(line._last_force, 1.2)


if __name__ == '__main__':
    unittest.main()
