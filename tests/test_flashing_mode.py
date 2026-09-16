"""Offline regression tests; no hardware access."""
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
from flasher import traffic
from test_haldex_backend import definitions
import ast
from contextlib import contextmanager
from enum import Enum, auto
from types import SimpleNamespace
from typing import List, Optional, Tuple, Dict, Union
from unittest.mock import Mock
from contextlib import nullcontext


class FlashingModeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.location = patch.object(traffic, '_directory', return_value=self.path)
        self.location.start()
        self.addCleanup(self.location.stop)

    def test_persistent_state_and_transmit_gate(self):
        self.assertFalse(traffic.flashing_mode_enabled())
        self.assertTrue(traffic.toggle_flashing_mode())
        self.assertEqual(json.loads((self.path / 'flashing_mode.json').read_text()), {'enabled': True})
        with traffic.transmission_guard() as allowed:
            self.assertFalse(allowed)
        # Reloaded disk state, not a cached process boolean.
        (self.path / 'flashing_mode.json').write_text('{"enabled":false}')
        with traffic.transmission_guard() as allowed:
            self.assertTrue(allowed)

    def test_activation_waits_for_actual_inflight_send(self):
        sending = threading.Event()
        finish_send = threading.Event()
        activated = threading.Event()
        def sender():
            with traffic.transmission_guard() as allowed:
                self.assertTrue(allowed)
                sending.set()
                self.assertTrue(finish_send.wait(2))
        thread = threading.Thread(target=sender)
        thread.start()
        self.assertTrue(sending.wait(2))
        enable = threading.Thread(target=lambda: (traffic.set_flashing_mode(True), activated.set()))
        enable.start()
        self.assertFalse(activated.wait(0.05))
        finish_send.set()
        thread.join(2); enable.join(2)
        self.assertTrue(activated.is_set())
        with traffic.transmission_guard() as allowed:
            self.assertFalse(allowed)

    def test_cannot_disable_during_operation_but_mode_persists_afterwards(self):
        with traffic.flashing_operation():
            traffic.set_flashing_mode(True)
            with self.assertRaisesRegex(RuntimeError, 'active'):
                traffic.toggle_flashing_mode()
            with self.assertRaisesRegex(RuntimeError, 'active'):
                traffic.set_flashing_mode(False)
        self.assertTrue(traffic.flashing_mode_enabled())
        self.assertFalse(traffic.toggle_flashing_mode())

    def test_recovery_and_corrupt_state_fail_closed(self):
        traffic.set_flashing_mode(True)
        (self.path / 'haldex_recovery_required.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'incomplete flash'):
            traffic.set_flashing_mode(False)
        (self.path / 'flashing_mode.json').write_text('')
        self.assertTrue(traffic.flashing_mode_enabled())

    def test_backend_automatically_enables_and_leaves_mode_on(self):
        class InlineThread:
            def __init__(self, target, **kw): self.target = target
            def start(self): self.target()
        engine = Mock()
        def flash(*args, **kwargs):
            self.assertTrue(traffic.flashing_mode_enabled())
            with self.assertRaises(RuntimeError):
                traffic.set_flashing_mode(False)
            return {'boot_verified': True, 'recovery_required': False}
        engine.flash_binary.side_effect = flash
        factory = Mock(return_value=engine)
        owner = Mock()
        ns = definitions('hudiy_dataview/app.py', {'handle_start_haldex_flash'}, {
            'emit': Mock(), 'socketio': types.SimpleNamespace(emit=Mock()),
            '_validated_artifacts': lambda: {'f'*64: {'_path': 'image.bin'}},
            '_flasher_lock': threading.Lock(), '_flasher_running': False, '_cfg': {},
            'threading': types.SimpleNamespace(Thread=InlineThread), 'HaldexFlasher': factory,
            'DiagnosticOwnership': lambda: owner, '_recovery_marker': Mock(),
            'FlashOperationLog': Mock(), 'logger': logging.getLogger('test'), 'json': json,
            'flashing_operation': traffic.flashing_operation, 'set_flashing_mode': traffic.set_flashing_mode})
        ns['handle_start_haldex_flash']({'artifact_id': 'f'*64, 'dry_run': False})
        owner.acquire.assert_called_once_with(allow_incomplete_flash=True)
        engine.flash_binary.assert_called_once()
        self.assertTrue(traffic.flashing_mode_enabled())
        self.assertFalse(traffic.toggle_flashing_mode())
        self.assertFalse(ns['_flasher_running'])


ROOT = Path(__file__).resolve().parents[1]


class SenderTests(unittest.TestCase):
    def load(self, path, names, allowed=False):
        active = []
        @contextmanager
        def gate():
            active.append(True)
            try:
                yield allowed
            finally:
                active.pop()
        ns = dict(transmission_guard=gate, Enum=Enum, auto=auto,
                  List=List, Optional=Optional, Tuple=Tuple, Dict=Dict, Union=Union,
                  can=SimpleNamespace(Message=lambda **kw: kw, CanError=RuntimeError),
                  logger=Mock(), time=Mock(), threading=threading)
        tree = ast.parse((ROOT / path).read_text())
        tree.body = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in names]
        exec(compile(tree, path, 'exec'), ns)
        return ns, active

    def test_diagnostic_sender_blocks_and_invalidates_session(self):
        ns, _ = self.load('tp2/tp2_protocol.py', {'TP2Error', 'TP2Protocol'})
        obj = ns['TP2Protocol']()
        obj.bus = Mock()
        obj.connected = True
        with self.assertRaises(ns['TP2Error']):
            obj._send(0x300, [1])
        obj.bus.send.assert_not_called()
        self.assertFalse(obj.connected)

    def test_openpilot_sender_blocks_and_clears_partial_frame(self):
        ns, _ = self.load('tp2/openpilot_receiver.py', {'OpenpilotReceiver'})
        obj = ns['OpenpilotReceiver']()
        obj.bus = Mock()
        obj.connected = True
        obj.rx_buffer.extend(b'old')
        obj.expected_len = 30
        obj._send_can(0x300, [1])
        obj.bus.send.assert_not_called()
        self.assertFalse(obj.connected)
        self.assertEqual(obj.rx_buffer, b'')
        self.assertEqual(obj.expected_len, 0)

    def test_dis_inhibit_closes_socket_and_clears_session(self):
        ns, _ = self.load('dis_client/ddp_protocol.py',
                         {'DDPProtocol', 'DDPState', 'DisMode', 'DDPError', 'DDPCANError'})
        obj = ns['DDPProtocol'].__new__(ns['DDPProtocol'])
        obj.bus = bus = Mock()
        obj.state = ns['DDPState'].READY
        obj._last_received_ack = [1]
        with self.assertRaises(ns['DDPCANError']):
            obj.send_can(0x6C0, [1])
        bus.send.assert_not_called()
        bus.shutdown.assert_called_once()
        self.assertIsNone(obj.bus)
        self.assertIsNone(obj._last_received_ack)
        self.assertEqual(obj.state, ns['DDPState'].DISCONNECTED)

    def test_enabled_sender_holds_guard_during_bus_send(self):
        ns, active = self.load('tp2/tp2_protocol.py', {'TP2Error', 'TP2Protocol'}, True)
        obj = ns['TP2Protocol']()
        obj.bus = Mock()
        obj.bus.send.side_effect = lambda *a, **kw: self.assertTrue(active)
        obj._send(0x300, [1])
        obj.bus.send.assert_called_once()
        self.assertFalse(active)


class BarrierTests(unittest.TestCase):
    def load(self):
        source = Path(__file__).resolve().parents[1] / 'rns-e_can/can_handler.py'
        tree = ast.parse(source.read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('acknowledge_barrier', 'send_worker')]
        ns = dict(transmission_guard=lambda: nullcontext(True), CAN_SEND_LOCK=threading.Lock(), CAN_BUS=Mock(), ZMQ_CONTEXT=Mock(),
                  zmq=SimpleNamespace(PUSH=1, LINGER=2, SNDTIMEO=3, IMMEDIATE=4),
                  can=SimpleNamespace(Message=lambda **kw: kw), logger=Mock(), RUNNING=True)
        exec(compile(tree, str(source), 'exec'), ns)
        return ns

    def test_fifo_transmit_precedes_barrier_without_transmitting_barrier(self):
        ns = self.load()
        events = []
        token = 'a' * 32
        endpoint = f'ipc:///run/rnse_control/haldex_barrier_{token}.ipc'
        parts = iter([[b'1658', b'5aa500ff00000000'],
                      [b'BARRIER', token.encode(), endpoint.encode()]])
        def receive():
            try:
                return next(parts)
            except StopIteration:
                ns['RUNNING'] = False
                return []
        ns['ZMQ_PULL_SOCKET'] = Mock(recv_multipart=receive)
        ns['CAN_BUS'].send.side_effect = lambda *a, **kw: events.append('transmit')
        reply = ns['ZMQ_CONTEXT'].socket.return_value
        reply.send_json.side_effect = lambda _: events.append('ack')
        ns['send_worker']()
        self.assertEqual(events, ['transmit', 'ack'])
        reply.send_json.assert_called_once_with({'status': 'ok', 'token': token, 'quiescent': True})
        reply.close.assert_called_once()

    def test_inhibited_gateway_discards_frames_but_acknowledges_barrier(self):
        ns = self.load()
        ns['transmission_guard'] = lambda: nullcontext(False)
        token = 'b' * 32
        parts = iter([[b'1658', b'0102'], [b'BARRIER', token.encode(),
                      f'ipc:///run/rnse_control/haldex_barrier_{token}.ipc'.encode()]])
        def receive():
            try:
                return next(parts)
            except StopIteration:
                ns['RUNNING'] = False
                return []
        ns['ZMQ_PULL_SOCKET'] = Mock(recv_multipart=receive)
        ns['send_worker']()
        ns['CAN_BUS'].send.assert_not_called()
        ns['ZMQ_CONTEXT'].socket.return_value.send_json.assert_called_once()

    def test_barrier_rejects_external_or_mismatched_endpoint(self):
        ns = self.load()
        for endpoint in ('tcp://example.com:1234', 'ipc:///tmp/not-authorized'):
            with self.assertRaises(ValueError):
                ns['acknowledge_barrier']([b'BARRIER', b'a' * 32, endpoint.encode()])
        ns['ZMQ_CONTEXT'].socket.assert_not_called()

    def test_missing_can_never_acknowledges_quiescence(self):
        ns = self.load()
        ns['CAN_BUS'] = None
        token = 'a' * 32
        ns['acknowledge_barrier']([b'BARRIER', token.encode(),
            f'ipc:///run/rnse_control/haldex_barrier_{token}.ipc'.encode()])
        ns['ZMQ_CONTEXT'].socket.return_value.send_json.assert_called_once_with(
            {'status': 'error', 'token': token, 'quiescent': False})


if __name__ == "__main__":
    unittest.main()
