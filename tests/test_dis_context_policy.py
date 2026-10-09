import ast
import logging
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from collections import deque
from unittest.mock import Mock
from test_ddp_state import ddp
root=Path(__file__).resolve().parents[1]
def methods(file,class_name,names,namespace):
    tree=ast.parse(file.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==class_name)
    for fn in cls.body:
        if isinstance(fn,ast.FunctionDef) and fn.name in names:
            exec(compile(ast.Module(body=[fn],type_ignores=[]),str(file),'exec'),namespace)
    return namespace
ns=methods(root/'dis_client/dis_display.py','DisplayEngine',['_check_nav_availability_pause','_leave_empty_context_page'],{'logger':logging.getLogger(__name__),'time':time})
svc=methods(root/'dis_client/dis_service.py','DisService',['_presentation_control','claim_nav_screen'],{'logger':logging.getLogger(__name__),'DDPState':ddp.DDPState,'DDPError':ddp.DDPError,'DDPMessages':ddp.DDPMessages,'time':time})
class PolicyTests(unittest.TestCase):
    def engine(self,nav=False,phone=False):
        e=SimpleNamespace(pages=['app_media','app_nav','app_phone'],current_page_idx=0,pre_nav_app_name=None,nav_auto_triggered=False,
            apps={},current_app=None,nav_claim_on_nav=True,phone_claim_on_phone=True,phone_auto_overlay=phone,
            context_claim_only=True,user_paused=True,boot_inactive_hold=True,content_auto_claimed=False,service_ready=True)
        e.is_nav_available=lambda:nav;e.is_phone_available=lambda:phone
        self.commands=[];e._send_draw=lambda p:self.commands.append(p) or True
        e.switch_to_app=lambda name:setattr(e,'current_page_idx',e.pages.index(name))
        e._leave_empty_context_page=lambda name:ns['_leave_empty_context_page'](e,name)
        return e
    def test_media_does_not_auto_claim_without_context(self):
        e=self.engine();ns['_check_nav_availability_pause'](e)
        self.assertEqual(self.commands,[]);self.assertTrue(e.user_paused)
    def test_route_can_claim_from_inactive_media_and_select_nav(self):
        e=self.engine(nav=True);ns['_check_nav_availability_pause'](e)
        self.assertEqual(e.current_page_idx,0);self.assertEqual(e.pre_nav_app_name,'app_media')
        self.assertEqual(self.commands,[{'command':'resume'}]);self.assertTrue(e.content_auto_claimed)
    def test_connected_idle_phone_does_not_claim(self):
        e=self.engine(phone=False);ns['_check_nav_availability_pause'](e)
        self.assertEqual(self.commands,[])
    def test_live_phone_can_claim(self):
        e=self.engine(phone=True);ns['_check_nav_availability_pause'](e)
        self.assertEqual(self.commands,[{'command':'resume'}])
    def test_route_end_releases_even_when_service_busy(self):
        e=self.engine();e.user_paused=False;e.boot_inactive_hold=False;e.content_auto_claimed=True;e.service_ready=False
        ns['_check_nav_availability_pause'](e)
        self.assertEqual(self.commands,[{'command':'pause'}]);self.assertTrue(e.user_paused)
    def test_manual_media_page_is_not_forced_back_during_active_context(self):
        e=self.engine(nav=True);e.user_paused=False;e.boot_inactive_hold=False;e.content_auto_claimed=True
        ns['_check_nav_availability_pause'](e)
        self.assertEqual(e.current_page_idx,0);self.assertEqual(self.commands,[])
    def test_failed_resume_remains_inactive(self):
        e=self.engine(nav=True);e._send_draw=lambda p:False
        ns['_check_nav_availability_pause'](e)
        self.assertTrue(e.user_paused);self.assertTrue(e.boot_inactive_hold)
    def test_cluster_selected_session_remains_present_after_context_ends(self):
        e=self.engine();e.user_paused=False;e.boot_inactive_hold=False
        e.cluster_selected_session=True;e.content_auto_claimed=True
        ns['_check_nav_availability_pause'](e)
        self.assertEqual(self.commands,[]);self.assertFalse(e.user_paused)
    def service(self):
        d=SimpleNamespace(state=ddp.DDPState.PAUSED,release_screen=Mock())
        return SimpleNamespace(ddp=d,presentation_requested=False,command_cache={},screen_is_active=False)
    def test_resume_records_intent_without_overriding_cluster_busy(self):
        s=self.service();self.assertTrue(svc['_presentation_control'](s,'resume'))
        self.assertTrue(s.presentation_requested);self.assertEqual(s.ddp.state,ddp.DDPState.PAUSED)
    def test_pause_releases_ownership_and_clears_stale_media(self):
        s=self.service();s.screen_is_active=True;s.command_cache={'media':'old'}
        svc['_presentation_control'](s,'pause')
        self.assertFalse(s.presentation_requested);self.assertEqual(s.command_cache,{})
        s.ddp.release_screen.assert_called_once()
    def test_disabled_presentation_never_sends_claim(self):
        s=self.service();s.ddp.state=ddp.DDPState.READY;s.ddp.send_data_packet=Mock()
        self.assertFalse(svc['claim_nav_screen'](s));s.ddp.send_data_packet.assert_not_called()

if __name__=='__main__':unittest.main()
