import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dis_client'))
from navigation_policy import NavigationPolicy
try:
    import zmq
except ImportError:
    import types
    sys.modules['zmq']=types.ModuleType('zmq')
from dis_display import DisplayEngine

class NavigationSequences(unittest.TestCase):
    def test_start_far_peek_then_return_manual_app(self):
        p=NavigationPolicy(peek_s=5)
        self.assertTrue(p.update(True,'right',2000,10))
        self.assertFalse(p.update(True,'right',1900,15))
    def test_manual_escape_waits_for_fresh_maneuver_or_next_approach(self):
        p=NavigationPolicy()
        p.update(True,'right',400,0)
        p.manual_select()
        self.assertFalse(p.update(True,'right',100,1))
        self.assertFalse(p.update(True,'right',1100,2))
        self.assertTrue(p.update(True,'right',500,3))
        p.manual_select()
        self.assertTrue(p.update(True,'left',-1,4))
    def test_approach_hysteresis_and_unknown_distance(self):
        p=NavigationPolicy()
        p.update(True,'right',2000,0)
        self.assertFalse(p.update(True,'right',501,6))
        self.assertTrue(p.update(True,'right',500,7))
        self.assertTrue(p.update(True,'right',800,8))
        self.assertTrue(p.update(True,'right',-1,9))
        self.assertTrue(p.update(True,'right',1000,10))
        self.assertFalse(p.update(True,'right',1001,11))
    def test_no_route_resets_and_repeated_details_do_not_rearm(self):
        p=NavigationPolicy()
        p.update(True,'right',2000,0)
        self.assertFalse(p.update(True,'right',1500,6))
        self.assertFalse(p.update(False,'right',100,7))
        self.assertTrue(p.update(True,'right',2000,8))
    def test_disabled_auto_never_overrides_manual_page(self):
        p=NavigationPolicy()
        self.assertFalse(p.update(True,'right',10,1,enabled=False))

class EnginePolicy(unittest.TestCase):
    def engine(self):
        e=DisplayEngine.__new__(DisplayEngine)
        e.cfg={'display':{'center_display': {'high_resolution': True}}}
        e.pages=['app_media','app_nav','app_car_info']
        e.current_page_idx=0
        e.nav_active=True
        e.nav_auto_switch=True
        e.nav_policy=NavigationPolicy()
        e.apps={'app_nav':SimpleNamespace(has_route=True,meters=2000,description='Main',maneuver_type=4)}
        e.pre_nav_app_name=None
        e._send_draw=Mock(return_value=True)
        e.force_redraw=Mock()
        e.boot_inactive_hold=True;e.user_paused=True
        e.content_auto_claimed=False
        return e
    def test_overlay_preserves_manual_selection_and_manual_nav_never_returns(self):
        e=self.engine()
        with patch('dis_display.time.monotonic',return_value=10):e._handle_nav_auto_switch(e.apps['app_nav'])
        self.assertEqual(e.current_page_idx,0)
        self.assertEqual(e.pre_nav_app_name,'app_media')
        with patch('dis_display.time.monotonic',return_value=16):e._handle_nav_auto_switch(e.apps['app_nav'])
        self.assertIsNone(e.pre_nav_app_name)
        e.current_page_idx=1
        with patch('dis_display.time.monotonic',return_value=20):e._handle_nav_auto_switch(e.apps['app_nav'])
        self.assertIsNone(e.pre_nav_app_name)
        self.assertEqual(e.current_page_idx,1)
    def test_positive_cluster_request_resumes_once_without_route(self):
        e=self.engine();e.apps['app_nav'].has_route=False
        e._handle_cluster_request(1);e._handle_cluster_request(1)
        e._send_draw.assert_called_once_with({'command':'resume'})
        self.assertFalse(e.boot_inactive_hold)
        self.assertTrue(e.cluster_selected_session)
    def test_failed_cluster_request_can_retry(self):
        e=self.engine();e._send_draw.return_value=False
        e._handle_cluster_request(1)
        self.assertTrue(e.boot_inactive_hold)
        e._send_draw.return_value=True;e._handle_cluster_request(1)
        self.assertFalse(e.boot_inactive_hold)
    def test_nav_claim_peek_works_with_routine_auto_switch_disabled(self):
        e=self.engine();e.nav_auto_switch=False
        e.apps['app_phone']=SimpleNamespace(has_phone=False)
        e.nav_claim_on_nav=True;e.phone_claim_on_phone=False
        e.phone_auto_overlay=False;e.context_claim_only=True;e.service_ready=True
        with patch('dis_display.time.monotonic',return_value=10):
            e._check_nav_availability_pause()
            e._handle_nav_auto_switch(e.apps['app_nav'])
        self.assertEqual(e.pre_nav_app_name,'app_media')
        self.assertEqual(e.current_page_idx,0)
        with patch('dis_display.time.monotonic',return_value=16):
            e._handle_nav_auto_switch(e.apps['app_nav'])
        self.assertIsNone(e.pre_nav_app_name)

    def test_custom_text_shrink_is_one_atomic_measured_update(self):
        e=self.engine()
        old=[dict(cmd='draw_text',text='MMMMMMMM',x=2,y=39,flags=6)]
        new=[dict(cmd='clear_area',x=0,y=39,w=61,h=9),dict(cmd='draw_text',text='iii',x=2,y=39,flags=6)]
        commands=e._prepare_text_group(new,old,'native','street')
        self.assertEqual(len(commands),1)
        self.assertEqual(commands[0]['cmd'],'update_text')
        self.assertLessEqual(commands[0]['clear_rect']['x']+commands[0]['clear_rect']['w'],61)
        self.assertEqual(commands[0]['text'],'iii')
    def test_growing_text_overwrites_without_clear_and_preserves_bar(self):
        e=self.engine()
        old=[dict(cmd='draw_text',text='i',x=2,y=39,flags=6)]
        new=[dict(cmd='clear_area',x=0,y=39,w=61,h=9),dict(cmd='draw_text',text='MMMM',x=2,y=39,flags=6),dict(cmd='draw_line',x=63,y=39,length=8)]
        commands=e._prepare_text_group(new,old,'native','street')
        self.assertNotIn('clear_rect',commands[0])
        self.assertEqual(commands[1]['cmd'],'draw_line')

if __name__=='__main__':unittest.main()

