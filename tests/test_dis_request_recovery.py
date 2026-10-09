"""Session ownership and confirmed-request delivery survive startup/busy races."""
import ast
import logging
import time
import unittest
from enum import Enum, auto
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
class State(Enum):
    DISCONNECTED=auto();READY=auto();PAUSED=auto();SESSION_ACTIVE=auto()
class ZMQError(Exception):pass
ZMQ=SimpleNamespace(NOBLOCK=1,ZMQError=ZMQError)
def extract(file, cls_name, names, env):
    tree=ast.parse(file.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls_name)
    funcs=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=funcs,type_ignores=[]),str(file),'exec'),env)
    return type(cls_name,(),{name:env[name] for name in names})
Service=extract(ROOT/'dis_client/dis_service.py','DisService',('_broadcast_status','_presentation_control'),
    {'time':time,'DDPState':State,'zmq':ZMQ,'logger':logging.getLogger(__name__)})
Engine=extract(ROOT/'dis_client/dis_display.py','DisplayEngine',('_handle_service_disconnect','_handle_cluster_request'),
    {'logger':logging.getLogger(__name__)})

class RequestDeliveryTests(unittest.TestCase):
    def service(self,state=State.READY):
        s=Service();s.ddp=SimpleNamespace(state=state,presentation_request_generation=0,release_screen=Mock())
        s.presentation_requested=False;s._initial_presentation_requested=False
        s.screen_is_active=False;s.command_cache={'old':'view'}
        s.status_pub=Mock();s.last_pub_state=state;s.last_status_cast=0
        return s
    def tick(self,s,now):
        with patch.object(time,'time',return_value=now):s._broadcast_status()
    def requests(self,s):
        return [c.args[0] for c in s.status_pub.send_string.call_args_list if c.args[0].startswith('DIS_REQUESTED')]
    def test_initial_ready_is_not_selection(self):
        s=self.service();self.tick(s,100)
        self.assertEqual(self.requests(s),[])
    def test_busy_does_not_consume_pending_selection(self):
        s=self.service(State.PAUSED);s.ddp.presentation_request_generation=1
        self.tick(s,100)
        self.assertEqual(self.requests(s),[])
        self.assertEqual(s._pending_request_generation,1)
        s.ddp.state=State.READY;self.tick(s,101)
        self.assertEqual(self.requests(s),['DIS_REQUESTED 1'])
    def test_replays_same_token_at_heartbeat_until_resume(self):
        s=self.service();s.ddp.presentation_request_generation=1
        self.tick(s,100);self.tick(s,100.1);self.tick(s,101)
        self.assertEqual(self.requests(s),['DIS_REQUESTED 1','DIS_REQUESTED 1'])
        s._presentation_control('resume');self.tick(s,102)
        self.assertEqual(len(self.requests(s)),2)
        self.assertIsNone(s._pending_request_generation)
    def test_request_during_existing_presentation_is_not_manual_selection(self):
        s=self.service();s.presentation_requested=True;s.ddp.presentation_request_generation=1
        self.tick(s,100);s._presentation_control('pause');self.tick(s,101)
        self.assertEqual(self.requests(s),[])
    def test_explicit_pause_acknowledges_pending_token(self):
        s=self.service();s.ddp.presentation_request_generation=1
        self.tick(s,100);s._presentation_control('pause');self.tick(s,101)
        self.assertEqual(self.requests(s),['DIS_REQUESTED 1'])
    def test_failed_publish_retries_same_pending_request(self):
        s=self.service();s.ddp.presentation_request_generation=1
        s.status_pub.send_string.side_effect=[ZMQError('not delivered'),None,None,None]
        self.tick(s,100);self.tick(s,100.1)
        self.assertEqual(s._pending_request_generation,1)
        self.assertEqual(self.requests(s),['DIS_REQUESTED 1','DIS_REQUESTED 1'])
    def test_newer_pending_request_survives_warning_and_coalesces(self):
        s=self.service(State.PAUSED);s.ddp.presentation_request_generation=1;self.tick(s,100)
        s.ddp.presentation_request_generation=2;self.tick(s,101)
        s.ddp.state=State.READY;self.tick(s,102)
        self.assertEqual(self.requests(s),['DIS_REQUESTED 2'])
    def test_disconnect_restores_initial_intent_and_discards_old_request(self):
        s=self.service();s.presentation_requested=True;s._pending_request_generation=1
        s.ddp.presentation_request_generation=1;s.ddp.state=State.DISCONNECTED
        self.tick(s,100)
        self.assertFalse(s.presentation_requested);self.assertEqual(s.command_cache,{})
        self.assertIsNone(s._pending_request_generation)
        s.ddp.state=State.READY;self.tick(s,101)
        self.assertEqual(self.requests(s),[])
    def test_disconnect_keeps_default_active_configuration(self):
        s=self.service();s._initial_presentation_requested=True;s.ddp.state=State.DISCONNECTED
        self.tick(s,100);self.assertTrue(s.presentation_requested)
    def test_disconnected_heartbeat_does_not_overwrite_fresh_context_intent(self):
        s=self.service();s.ddp.state=State.DISCONNECTED;self.tick(s,100)
        s._presentation_control('resume');self.tick(s,101)
        self.assertTrue(s.presentation_requested)

class EngineReconnection(unittest.TestCase):
    def engine(self,inactive):
        e=Engine();e.start_inactive=inactive;e.boot_inactive_hold=False;e.user_paused=False
        e.content_auto_claimed=True;e.cluster_selected_session=True;e._last_cluster_request=8
        e._context_nav_peek_until=20;e.pre_nav_app_name='app_media'
        e.nav_policy=SimpleNamespace(reset=Mock());e.force_redraw=Mock();e._send_draw=Mock(return_value=True)
        return e
    def test_inactive_reconnect_restores_hold_and_invalidates_old_view(self):
        e=self.engine(True);e._handle_service_disconnect()
        self.assertTrue(e.boot_inactive_hold);self.assertTrue(e.user_paused)
        self.assertFalse(e.content_auto_claimed);self.assertFalse(e.cluster_selected_session)
        e.force_redraw.assert_called_once_with(send_clear=False);e.nav_policy.reset.assert_called_once()
    def test_active_reconnect_restores_active_client_intent(self):
        e=self.engine(False);e.user_paused=True;e._handle_service_disconnect()
        self.assertFalse(e.boot_inactive_hold);self.assertFalse(e.user_paused)
    def test_replayed_positive_request_only_resumes_once(self):
        e=self.engine(True);e._handle_service_disconnect()
        e._handle_cluster_request(9);e._handle_cluster_request(9)
        e._send_draw.assert_called_once_with({'command':'resume'})
        self.assertFalse(e.boot_inactive_hold);self.assertFalse(e.user_paused)

if __name__=='__main__':unittest.main()
