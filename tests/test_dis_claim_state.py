import ast
import unittest
from types import SimpleNamespace
from collections import deque
from pathlib import Path
from unittest.mock import Mock
import time
import logging
from test_ddp_state import ddp
source=ast.parse((Path(__file__).resolve().parents[1]/'dis_client/dis_service.py').read_text())
cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='DisService')
fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='claim_nav_screen')
namespace={'DDPState':ddp.DDPState,'DDPError':ddp.DDPError,'DDPMessages':ddp.DDPMessages,'time':time,'logger':logging.getLogger(__name__)}
exec(compile(ast.Module(body=[fn],type_ignores=[]),'claim_nav_screen','exec'),namespace)
claim=namespace['claim_nav_screen']
class ServiceTests(unittest.TestCase):
    def service(self,response):
        protocol=SimpleNamespace(state=ddp.DDPState.READY,send_data_packet=Mock(),_recv_and_ack_data=lambda ms:response,_data_inbox=deque())
        protocol._set_state=lambda state:setattr(protocol,'state',state)
        return SimpleNamespace(ddp=protocol,region_name='central',region_height=0x30,screen_is_active=False,claim_retry_count=0,presentation_requested=True)
    def test_busy_sends_one_claim_then_waits(self):
        s=self.service([0x17,0x53,0x84])
        self.assertFalse(claim(s)); self.assertEqual(s.ddp.state,ddp.DDPState.PAUSED)
        s.ddp.send_data_packet.assert_called_once_with([0x52,5,0x82,0,0x1b,0x40,0x30])
    def test_claim_requires_application_success(self):
        s=self.service([0x1a,0x53,0x85])
        self.assertTrue(claim(s));self.assertTrue(s.screen_is_active)
        s=self.service(None);self.assertFalse(claim(s));self.assertFalse(s.screen_is_active)
    def test_reinit_arriving_during_claim_is_not_discarded(self):
        s=self.service([0x12,0x2e]);self.assertFalse(claim(s))
        self.assertEqual(list(s.ddp._data_inbox),[[0x12,0x2e]])
    def test_unknown_status_does_not_mark_screen_active(self):
        s=self.service([0x12,0x53,0xff]);self.assertFalse(claim(s))
        self.assertEqual(s.ddp.state,ddp.DDPState.PAUSED)

if __name__=='__main__': unittest.main()
