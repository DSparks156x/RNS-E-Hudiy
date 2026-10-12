import sys
import types
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dis_client'))
if 'can' not in sys.modules:
    fake=types.ModuleType('can'); fake.CanError=RuntimeError
    # Shared discovery can import the offline SocketCAN adapter afterward.
    fake.Message=lambda **kwargs: types.SimpleNamespace(**kwargs)
    sys.modules['can']=fake
import ddp_protocol as ddp

# Format20 capabilities as reported by the reference car: family52 renderer.
CAR_CAPABILITIES=[9,0x20,11,80,9,36,74]


def make_driver(state=ddp.DDPState.READY, *, configured=True, **config):
    """A real DDPProtocol (real __init__ + session reset) with no CAN socket.

    Built through the production constructor so new instance attributes never
    have to be mirrored by hand. Callers replace send_can/_recv as needed.
    configured=True gives a confirmed mode1/format20/setup21 application, the
    state perform_initialization leaves behind before READY.
    """
    config={'ddp_frame_gap_s':0,'ddp_white_post_message_delay_s':0,**config}
    with patch.object(ddp.DDPProtocol,'reconnect_bus',return_value=True):
        d=ddp.DDPProtocol(config)
    d._reset_application_session()  # Normally run by the SESSION_ACTIVE transition.
    d.state=state; d.dis_mode=ddp.DisMode.WHITE; d.i_am_opener=True
    d._flashing_inhibited=lambda:False
    d.send_can=lambda cid,payload:None
    d._recv=lambda timeout:None
    if configured:
        d._application_mode=1
        d.cluster_capabilities=ddp.ClusterCapabilities.parse(CAR_CAPABILITIES)
        d.capability_record=list(CAR_CAPABILITIES)
        d.application_setup_record=ddp.validate_priority([0x21,0x3B,0xA0,0])
        d.application_setup_full=False
        d._application_setup_pending=False
    return d


class CandidateTests(unittest.TestCase):
    def driver(self, **kwargs):
        d=make_driver(**kwargs)
        self.sent=[]; d.send_can=lambda cid,p:self.sent.append(list(p))
        return d
    def test_status_before_ack_retained_and_acknowledged_once(self):
        d=self.driver(); incoming=deque([[0x10,0x53,0x84],[0xb5]])
        d._recv=lambda timeout:incoming.popleft() if incoming else None
        self.assertEqual(d._recv_specific([0xb5],50),[0xb5])
        self.assertEqual(d.state,ddp.DDPState.PAUSED)
        self.assertEqual(d._recv_and_ack_data(50),[0x10,0x53,0x84])
        self.assertEqual(self.sent,[[0xb1]])
    def test_out_of_sequence_status_is_not_retained(self):
        d=self.driver(); d._retain_data([0x13,0x53,0x84])
        self.assertEqual(list(d._data_inbox),[])
        self.assertEqual(d.state,ddp.DDPState.READY)
        self.assertEqual(self.sent,[[0xb0]])  # Re-requests the expected nibble.
    def test_capability_variant_fields_retained(self):
        d=self.driver()
        self.assertTrue(d.payload_is([0x21,9,32,11,80,8,11,80],[9,32,11,80,10,36,80]))
        self.assertEqual(d.capability_record,[9,32,11,80,8,11,80])
        self.assertFalse(d.payload_is([0x21,9,32],[9,32,11,80,10,36,80]))
    def test_status_is_async_during_initialization(self):
        d=self.driver(); d.state=ddp.DDPState.INITIALIZING
        incoming=deque([[0x10,0x53,4],[0x11,0x21,0x3B,0xA0,0]])
        d._recv=lambda timeout:incoming.popleft() if incoming else None
        self.assertEqual(d._recv_and_ack_data(50),[0x11,0x21,0x3B,0xA0,0])
        self.assertEqual(d._last_screen_status,4)
        self.assertEqual(d.state,ddp.DDPState.INITIALIZING)
        self.assertEqual(self.sent,[[0xb1],[0xb2]])
    def test_busy_is_handled_when_polled_from_queue(self):
        d=self.driver(); d._retain_data([0x10,0x53,0x84])
        d.poll_bus_events()
        self.assertEqual(d.state,ddp.DDPState.PAUSED)
        self.assertEqual(self.sent.count([0xb1]),1)
        self.assertEqual(list(d._data_inbox),[])
    def test_reinit_without_ack_stays_paused(self):
        d=self.driver(); d.state=ddp.DDPState.PAUSED
        d._data_inbox.append([0x15,0x2e])
        def fail(payload): raise ddp.DDPAckTimeoutError('timeout')
        d.send_data_packet=fail
        d.poll_bus_events()
        self.assertEqual(d.state,ddp.DDPState.PAUSED)
    def test_failed_initialization_never_assumes_ready(self):
        d=self.driver(state=ddp.DDPState.SESSION_ACTIVE,configured=False)
        def fail(): raise ddp.DDPHandshakeError('timeout')
        d._init_common_start=fail
        d.close_session=lambda:setattr(d,'state',ddp.DDPState.DISCONNECTED)
        self.assertFalse(d.perform_initialization())
        self.assertEqual(d.state,ddp.DDPState.DISCONNECTED)
        self.assertFalse(d.was_handshake_assumed)

if __name__=='__main__':unittest.main()
