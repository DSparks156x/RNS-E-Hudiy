import sys
import types
import unittest
from collections import deque
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dis_client'))
if 'can' not in sys.modules:
    fake=types.ModuleType('can'); fake.CanError=RuntimeError
    # Shared discovery can import the offline SocketCAN adapter afterward.
    fake.Message=lambda **kwargs: types.SimpleNamespace(**kwargs)
    sys.modules['can']=fake
import ddp_protocol as ddp

class CandidateTests(unittest.TestCase):
    def driver(self):
        d=ddp.DDPProtocol.__new__(ddp.DDPProtocol)
        d.state=ddp.DDPState.READY; d.dis_mode=ddp.DisMode.WHITE
        d._data_inbox=deque(); d._last_screen_status=None
        d.tx_id=0x6c0; d.send_seq_num=0; d.i_am_opener=True
        d._flashing_inhibited=lambda:False
        d.screen_released_by_cluster=False
        self.sent=[]; d.send_can=lambda cid,p:self.sent.append(list(p))
        d._recv=lambda timeout:None
        return d
    def test_status_before_ack_retained_and_acknowledged_once(self):
        d=self.driver(); incoming=deque([[0x12,0x53,0x84],[0xb1]])
        d._recv=lambda timeout:incoming.popleft() if incoming else None
        self.assertEqual(d._recv_specific([0xb1],50),[0xb1])
        self.assertEqual(d.state,ddp.DDPState.PAUSED)
        self.assertEqual(d._recv_and_ack_data(50),[0x12,0x53,0x84])
        self.assertEqual(self.sent,[[0xb3]])
    def test_capability_variant_fields_retained(self):
        d=self.driver()
        self.assertTrue(d.payload_is([0x21,9,32,11,80,8,11,80],[9,32,11,80,10,36,80]))
        self.assertEqual(d.capability_record,[9,32,11,80,8,11,80])
        self.assertFalse(d.payload_is([0x21,9,32],[9,32,11,80,10,36,80]))
    def test_status_is_async_during_initialization(self):
        d=self.driver(); d.state=ddp.DDPState.INITIALIZING
        incoming=deque([[0x10,0x53,4],[0x11,0,1]])
        d._recv=lambda timeout:incoming.popleft() if incoming else None
        self.assertEqual(d._recv_and_ack_data(50),[0x11,0,1])
        self.assertEqual(d._last_screen_status,4)
        self.assertEqual(self.sent,[[0xb1],[0xb2]])
    def test_busy_is_handled_when_polled_from_queue(self):
        d=self.driver(); d._retain_data([0x13,0x53,0x84])
        d.poll_bus_events()
        self.assertEqual(d.state,ddp.DDPState.PAUSED)
        self.assertEqual(self.sent.count([0xb4]),1)
    def test_reinit_without_ack_stays_paused(self):
        d=self.driver(); d.state=ddp.DDPState.PAUSED
        d._data_inbox.append([0x15,0x2e])
        def fail(payload): raise ddp.DDPAckTimeoutError('timeout')
        d.send_data_packet=fail
        d.poll_bus_events()
        self.assertEqual(d.state,ddp.DDPState.PAUSED)
    def test_failed_initialization_never_assumes_ready(self):
        d=self.driver()
        def fail(): raise ddp.DDPHandshakeError('timeout')
        d._init_common_start=fail
        d.close_session=lambda:setattr(d,'state',ddp.DDPState.DISCONNECTED)
        self.assertFalse(d.perform_initialization())
        self.assertEqual(d.state,ddp.DDPState.DISCONNECTED)
        self.assertFalse(d.was_handshake_assumed)

if __name__=='__main__':unittest.main()
