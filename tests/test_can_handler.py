"""CAN gateway (rns-e_can/can_handler.py): ZMQ <-> SocketCAN.

Every application CAN write in the car goes through send_worker(), and every
CAN read reaches the other services through the PUB loop in main(). These
tests run the real module with fake sockets and a fake bus; the Flashing Mode
gate is the real flasher.traffic implementation in a private HOME.
"""
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import can

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flasher import traffic  # noqa: E402


def load_can_handler():
    spec = importlib.util.spec_from_file_location(
        'can_handler_under_test', ROOT / 'rns-e_can' / 'can_handler.py')
    module = importlib.util.module_from_spec(spec)
    # setup_logging() opens /var/log/rnse_control/can_handler.log at import.
    with patch.object(logging, 'FileHandler', lambda *a, **k: logging.NullHandler()):
        spec.loader.exec_module(module)
    return module


class FakePull:
    """recv_multipart() yields queued parts, then stops the worker."""

    def __init__(self, module, parts, before_each=None):
        self.module = module
        self.parts = list(parts)
        self.before_each = before_each

    def recv_multipart(self):
        if not self.parts:
            self.module.RUNNING = False
            raise RuntimeError('drained')
        part = self.parts.pop(0)
        if self.before_each:
            self.before_each(part)
        return part


class GatewayTestCase(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        env = patch.dict(os.environ, {'HOME': home.name})
        env.start()
        self.addCleanup(env.stop)
        self.home = Path(home.name)
        self.gw = load_can_handler()
        self.gw.RUNNING = True
        self.bus = Mock()
        self.gw.CAN_BUS = self.bus

    def run_worker(self, parts, before_each=None):
        self.gw.ZMQ_PULL_SOCKET = FakePull(self.gw, parts, before_each)
        self.gw.send_worker()

    def sent(self):
        return [(c.args[0].arbitration_id, bytes(c.args[0].data), c.args[0].is_extended_id)
                for c in self.bus.send.call_args_list]


class SendWorkerTests(GatewayTestCase):
    def test_sender_wire_format_becomes_exact_standard_frame(self):
        # Senders push [decimal ID, hex payload]: base_function TV/brightness,
        # haldex_manager 0x67A bursts, rnse ADC frames.
        self.run_worker([
            [str(0x67A).encode(), b'5aa5000000000000'],
            [str(0x602).encode(), b'0912302020202020'],
            [str(0x7B0).encode(), b'BB05000000000000'],
        ])
        self.assertEqual(self.sent(), [
            (0x67A, bytes.fromhex('5aa5000000000000'), False),
            (0x602, bytes.fromhex('0912302020202020'), False),
            (0x7B0, bytes.fromhex('BB05000000000000'), False),
        ])

    def test_malformed_requests_never_reach_the_bus_and_worker_survives(self):
        self.run_worker([
            [b'0x67A', b'5aa5'],          # hex ID is not the wire contract
            [b'1658', b'5aa5zz'],         # bad payload
            [b'1658'],                    # missing payload
            [b'1658', b'00', b'extra'],   # not a frame, not a barrier
            [b'1658', b'5aa5000000000000'],
        ])
        self.assertEqual(self.sent(), [(0x67A, bytes.fromhex('5aa5000000000000'), False)])

    def test_flashing_mode_discards_frames_instead_of_queueing_them(self):
        traffic.set_flashing_mode(True)
        self.run_worker([[b'1658', b'5aa5000000000000'], [b'1538', b'0912302020202020']])
        self.bus.send.assert_not_called()
        # Nothing stale is replayed once flashing ends.
        traffic.set_flashing_mode(False)
        self.run_worker_again([[b'1538', b'0912302020202020']])
        self.assertEqual(self.sent(), [(0x602, bytes.fromhex('0912302020202020'), False)])

    def run_worker_again(self, parts):
        self.gw.RUNNING = True
        self.run_worker(parts)

    def test_incomplete_flash_marker_inhibits_even_if_mode_file_says_off(self):
        (self.home / '.hudiy').mkdir(exist_ok=True)
        (self.home / '.hudiy' / 'flashing_mode.json').write_text('{"enabled": false}')
        (self.home / '.hudiy' / 'haldex_recovery_required.json').write_text('{}')
        self.run_worker([[b'1658', b'5aa5000000000000']])
        self.bus.send.assert_not_called()

    def test_corrupt_flashing_state_fails_closed(self):
        (self.home / '.hudiy').mkdir(exist_ok=True)
        (self.home / '.hudiy' / 'flashing_mode.json').write_text('{"enab')
        self.run_worker([[b'1658', b'5aa5000000000000']])
        self.bus.send.assert_not_called()

    def test_frames_while_bus_down_are_dropped_not_replayed(self):
        bus = self.bus

        def reconnect_after_first(part):
            self.gw.CAN_BUS = None if part[1] == b'01' else bus
        self.run_worker([[b'1658', b'01'], [b'1658', b'02']], reconnect_after_first)
        self.assertEqual(self.sent(), [(0x67A, b'\x02', False)])

    def test_bus_send_error_does_not_stop_the_worker(self):
        self.bus.send.side_effect = [can.CanOperationError('No buffer space'), None]
        self.run_worker([[b'1658', b'01'], [b'1658', b'02']])
        self.assertEqual(len(self.bus.send.call_args_list), 2)
        self.assertEqual(self.sent()[-1], (0x67A, b'\x02', False))


class BarrierTests(GatewayTestCase):
    def test_haldex_barrier_is_acknowledged_in_fifo_order_and_never_transmitted(self):
        token = '0123456789abcdef' * 2
        endpoint = f'ipc:///run/rnse_control/haldex_barrier_{token}.ipc'
        events = []
        reply = Mock()
        reply.send_json.side_effect = lambda body: events.append(('ack', body))
        self.gw.ZMQ_CONTEXT = Mock(socket=Mock(return_value=reply))
        self.bus.send.side_effect = lambda msg, timeout=None: events.append(
            ('tx', msg.arbitration_id))
        self.run_worker([[b'1658', b'5aa5000000000000'],
                         [b'BARRIER', token.encode(), endpoint.encode()]])
        self.assertEqual(events, [('tx', 0x67A),
                                  ('ack', {'status': 'ok', 'token': token, 'quiescent': True})])
        reply.connect.assert_called_once_with(endpoint)

    def test_barrier_to_foreign_endpoint_is_refused(self):
        token = 'a' * 32
        self.gw.ZMQ_CONTEXT = Mock()
        with self.assertRaises(ValueError):
            self.gw.acknowledge_barrier([b'BARRIER', token.encode(), b'tcp://10.0.0.1:1'])
        self.gw.ZMQ_CONTEXT.socket.assert_not_called()


class FakeRxBus:
    def __init__(self, gw, frames):
        self.gw = gw
        self.frames = list(frames)
        self.shutdown = Mock()

    def recv(self, timeout=None):
        if not self.frames:
            self.gw.RUNNING = False
            return None
        item = self.frames.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ReceivePublishTests(GatewayTestCase):
    def run_main(self, buses):
        published = []
        pub = Mock()
        pub.send_multipart.side_effect = lambda parts: published.append(
            (parts[0].decode(), json.loads(parts[1])))
        connects = []

        def init_bus(*args, **kwargs):
            self.gw.CAN_BUS = buses[len(connects)]
            connects.append(self.gw.CAN_BUS)
            return True

        def init_zmq():
            self.gw.ZMQ_PUB_SOCKET = pub
            return True
        self.gw.CAN_BUS = None
        with patch.object(self.gw, 'load_and_initialize_config', return_value=True), \
                patch.object(self.gw, 'setup_signal_handlers'), \
                patch.object(self.gw, 'initialize_zmq_sockets', side_effect=init_zmq), \
                patch.object(self.gw, 'initialize_can_bus', side_effect=init_bus), \
                patch.object(self.gw, 'teardown_resources'), \
                patch.object(self.gw.threading, 'Thread'), \
                patch.object(self.gw.time, 'sleep') as sleep:
            self.gw.main()
        return published, connects, sleep

    def test_frames_are_published_on_the_topics_consumers_subscribe_to(self):
        frames = [
            can.Message(arbitration_id=0x2C3, data=b'\x03', is_extended_id=False, timestamp=1.5),
            can.Message(arbitration_id=0x6DA, data=bytes.fromhex('d041100020003000'),
                        is_extended_id=False),
            can.Message(arbitration_id=0x0AB, data=b'\x01', is_extended_id=False),
        ]
        published, _, _ = self.run_main([FakeRxBus(self.gw, frames)])
        # can_base_function subscribes f"CAN_{id:03X}"; haldex_manager b"CAN_6DA".
        self.assertEqual([topic for topic, _ in published], ['CAN_2C3', 'CAN_6DA', 'CAN_0AB'])
        topic, body = published[0]
        self.assertEqual(body['arbitration_id'], 0x2C3)
        self.assertEqual(body['dlc'], 1)
        self.assertEqual(body['data_hex'], '03')
        self.assertEqual(body['timestamp'], 1.5)
        self.assertFalse(body['is_extended_id'])
        self.assertEqual(published[1][1]['data_hex'], 'd041100020003000')

    def test_can_error_recovers_by_reopening_the_bus(self):
        first = FakeRxBus(self.gw, [can.CanError('bus-off')])
        second = FakeRxBus(self.gw, [can.Message(arbitration_id=0x2C3, data=b'\x02',
                                                 is_extended_id=False)])
        published, connects, sleep = self.run_main([first, second])
        first.shutdown.assert_called_once()
        self.assertEqual(connects, [first, second])
        self.assertEqual([t for t, _ in published], ['CAN_2C3'])
        sleep.assert_any_call(5)


class ConfigTests(GatewayTestCase):
    def test_interface_and_addresses_come_from_config(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump({'interfaces': {'can': {'infotainment': 'can1'}, 'zmq': {
                'can_raw_stream': 'ipc:///run/x/stream.ipc',
                'send_address': 'ipc:///run/x/send.ipc'}}}, handle)
        self.addCleanup(os.unlink, handle.name)
        self.assertTrue(self.gw.load_and_initialize_config(handle.name))
        self.assertEqual(self.gw.CONFIG, {
            'infotainment_can_interface': 'can1',
            'zmq_publish_address': 'ipc:///run/x/stream.ipc',
            'zmq_send_address': 'ipc:///run/x/send.ipc'})
        self.assertFalse(self.gw.load_and_initialize_config(handle.name + '.missing'))


if __name__ == '__main__':
    unittest.main()
