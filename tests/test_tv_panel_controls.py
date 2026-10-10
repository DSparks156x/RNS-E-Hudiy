"""Replay shared MMI panel presses without CAN hardware or Hudiy binaries."""
import ast
import importlib.util
import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import zmq
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rns-e_can'))
from tv_panel_controls import PANEL_BUTTONS
from hudiy_client.input_actions import InputActionDispatcher


def frame(pair, status=1, **overrides):
    msg = dict(arbitration_id=0x461, dlc=6,
               data_hex=bytes((0x37, 0x30, status, *pair, 0)).hex(),
               is_extended_id=False, is_remote_frame=False, is_error_frame=False)
    msg.update(overrides)
    return msg


def keyboard_module():
    spec = importlib.util.spec_from_file_location('tv_test_keyboard', ROOT / 'rns-e_can/can_keyboard_control.py')
    module = importlib.util.module_from_spec(spec)
    keys = {name: (1, number) for number, name in enumerate(
        ('KEY_F', 'KEY_G', 'KEY_J', 'KEY_H', 'KEY_UP', 'KEY_DOWN', 'KEY_ENTER'), 1)}
    with patch.dict(sys.modules, {'uinput': SimpleNamespace(**keys)}):
        spec.loader.exec_module(module)
    return module


class KeyboardPanelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.keyboard = keyboard_module()
        self.keyboard.CONFIG = dict(mmi_short_map={(0, 1): (1, 4), (1, 0): (1, 5),
            (8, 0): (1, 1), (0, 8): (1, 2), (0, 4): (1, 3),
            (4, 0): {'action': 'applications_menu'}, (0, 12): {'action': 'hudiy_diagnostics'},
            (12, 0): {'action': 'hudiy_manager'}},
            mmi_long_map={pair: None for pair in PANEL_BUTTONS},
            mmi_extended_map={pair: None for pair in PANEL_BUTTONS},
            mmi_scroll_cmds={(1, 0)}, cooldown=0, long_press_count=5,
            extended_press_count=30, mfsw_map={})
        self.keyboard.FEATURES = {}
        self.keyboard.UINPUT_DEVICE = Mock()
        self.keyboard.INPUT_PUB = Mock()
        self.state = self.keyboard.ControlState()

    def handle(self, pair, status=1, count=1, **overrides):
        for _ in range(count):
            self.keyboard.handle_mmi_message(frame(pair, status, **overrides), self.state)

    def actions(self):
        return [json.loads(call.args[0][1])['event']
                for call in self.keyboard.INPUT_PUB.send_multipart.call_args_list]

    def test_exact_masks_taps_and_default_holds_dispatch_once_on_release(self):
        self.assertEqual(PANEL_BUTTONS, {(8, 0): 'NAV', (0, 8): 'TEL', (0, 4): 'MEDIA',
                                       (4, 0): 'NAME', (0, 12): 'INFO', (12, 0): 'CAR'})
        for count in (1, 5, 30, 100):
            for pair in PANEL_BUTTONS:
                self.keyboard.UINPUT_DEVICE.reset_mock()
                self.keyboard.INPUT_PUB.reset_mock()
                self.handle(pair, count=count)
                self.keyboard.UINPUT_DEVICE.emit_click.assert_not_called()
                self.keyboard.INPUT_PUB.send_multipart.assert_not_called()
                self.assertFalse(self.state.mmi_long_action_fired.get(pair))
                self.assertFalse(self.state.mmi_extended_action_fired.get(pair))
                self.handle(pair, 4, count=10)
                binding = self.keyboard.CONFIG['mmi_short_map'][pair]
                if isinstance(binding, dict):
                    self.assertEqual(self.actions(), [binding['action']])
                    parts = self.keyboard.INPUT_PUB.send_multipart.call_args.args[0]
                    self.assertEqual(parts[0], b'HUDIY_ACTION')
                    self.assertIsInstance(json.loads(parts[1])['monotonic_timestamp'], float)
                else:
                    self.keyboard.UINPUT_DEVICE.emit_click.assert_called_once_with(binding)
                self.assertNotIn(pair, self.state.mmi_press_counters)

    def test_long_key_fires_at_five_once_and_suppresses_short_on_release(self):
        pair = (8, 0)
        self.keyboard.CONFIG['mmi_long_map'][pair] = (1, 7)
        self.handle(pair, count=4)
        self.keyboard.UINPUT_DEVICE.emit_click.assert_not_called()
        self.handle(pair)
        self.keyboard.UINPUT_DEVICE.emit_click.assert_called_once_with((1, 7))
        self.handle(pair, count=40)
        self.handle(pair, 4, count=4)
        self.keyboard.UINPUT_DEVICE.emit_click.assert_called_once_with((1, 7))
        self.handle(pair)
        self.handle(pair, 4)
        self.assertEqual(self.keyboard.UINPUT_DEVICE.emit_click.call_args.args, ((1, 1),))

    def test_long_action_and_extended_action_each_fire_at_configured_count(self):
        pair = (4, 0)
        self.keyboard.CONFIG['mmi_long_map'][pair] = {'action': 'long_menu'}
        self.keyboard.CONFIG['mmi_extended_map'][pair] = {'action': 'extended_menu'}
        self.handle(pair, count=4)
        self.assertEqual(self.actions(), [])
        self.handle(pair)
        self.assertEqual(self.actions(), ['long_menu'])
        self.handle(pair, count=24)
        self.assertEqual(self.actions(), ['long_menu'])
        self.handle(pair, count=20)
        self.handle(pair, 4, count=4)
        self.assertEqual(self.actions(), ['long_menu', 'extended_menu'])

    def test_extended_key_with_null_long_fires_at_thirty_and_suppresses_short(self):
        pair = (12, 0)
        self.keyboard.CONFIG['mmi_extended_map'][pair] = (1, 7)
        self.handle(pair, count=29)
        self.keyboard.UINPUT_DEVICE.emit_click.assert_not_called()
        self.handle(pair, count=15)
        self.handle(pair, 4)
        self.keyboard.UINPUT_DEVICE.emit_click.assert_called_once_with((1, 7))
        self.assertEqual(self.actions(), [])

    def test_extended_shell_uses_system_actions_gate_and_disabled_hold_keeps_short(self):
        pair = (8, 0)
        self.keyboard.CONFIG['mmi_extended_map'][pair] = 'systemctl restart example'
        with patch.object(self.keyboard, 'run_command') as run:
            self.handle(pair, count=35)
            self.handle(pair, 4)
            run.assert_not_called()
            self.keyboard.UINPUT_DEVICE.emit_click.assert_called_once_with((1, 1))
            self.keyboard.UINPUT_DEVICE.reset_mock()
            self.keyboard.FEATURES['system_actions'] = True
            self.handle(pair, count=35)
            self.handle(pair, 4, count=4)
            run.assert_called_once_with('systemctl restart example')
            self.keyboard.UINPUT_DEVICE.emit_click.assert_not_called()

    def test_existing_setup_supports_the_same_action_bindings_and_hold_fallback(self):
        pair = (0, 1)
        self.keyboard.CONFIG['mmi_short_map'][pair] = {'action': 'setup_short'}
        self.keyboard.CONFIG['mmi_long_map'][pair] = None
        self.keyboard.CONFIG['mmi_extended_map'][pair] = None
        self.handle(pair, count=40)
        self.handle(pair, 4, count=3)
        self.assertEqual(self.actions(), ['setup_short'])
        self.keyboard.CONFIG['mmi_long_map'][pair] = {'action': 'setup_long'}
        self.handle(pair, count=10)
        self.handle(pair, 4)
        self.assertEqual(self.actions(), ['setup_short', 'setup_long'])

    def test_setup_key_and_knob_repeats_remain_unchanged(self):
        self.handle((0, 1))
        self.keyboard.UINPUT_DEVICE.emit_click.assert_not_called()
        self.handle((0, 1), 4, count=3)
        self.keyboard.UINPUT_DEVICE.emit_click.assert_called_once_with((1, 4))
        self.keyboard.UINPUT_DEVICE.reset_mock()
        self.handle((1, 0), count=3)
        self.handle((1, 0), 4, count=3)
        self.assertEqual(self.keyboard.UINPUT_DEVICE.emit_click.call_count, 3)

    def test_release_dedupe_and_alternating_masks_keep_each_counter_separate(self):
        self.handle((8, 0))
        self.handle((0, 8))
        self.handle((8, 0), 4, count=4)
        self.assertEqual(self.state.mmi_press_counters[(0, 8)], 1)
        self.handle((0, 8), count=4)
        self.handle((0, 8), 4, count=4)
        self.assertEqual([call.args[0] for call in self.keyboard.UINPUT_DEVICE.emit_click.call_args_list],
                         [(1, 1), (1, 2)])
        self.assertEqual(self.state.mmi_press_counters, {})

    def test_strict_panel_envelopes_and_statuses_never_enter_common_counters(self):
        for pair in PANEL_BUTTONS:
            for overrides in (dict(arbitration_id=0x462), dict(dlc=5), dict(dlc=7),
                              dict(is_extended_id=True), dict(is_remote_frame=True), dict(is_error_frame=True)):
                for status in (1, 4):
                    self.handle(pair, status, **overrides)
            for status in (0, 2, 3, 5, 255):
                self.handle(pair, status)
            for header, trailer in (((0x36, 0x30), 0), ((0x37, 0x31), 0), ((0x37, 0x30), 1)):
                for status in (1, 4):
                    self.handle(pair, status, data_hex=bytes((*header, status, *pair, trailer)).hex())
        self.assertEqual(self.state.mmi_press_counters, {})
        self.keyboard.UINPUT_DEVICE.emit_click.assert_not_called()
        self.assertEqual(self.actions(), [])

    def test_malformed_data_never_raises_or_triggers_action(self):
        for msg in (None, {}, dict(dlc='6'), dict(dlc=6, data_hex=None),
                    dict(dlc=6, data_hex='zz'), dict(dlc=6, data_hex='37300108'),
                    frame((8, 0), dlc=True), frame((8, 0), dlc=5),
                    frame((8, 0), data_hex='37300108000000')):
            self.keyboard.handle_mmi_message(msg, self.state)
        self.keyboard.UINPUT_DEVICE.emit_click.assert_not_called()
        self.assertEqual(self.actions(), [])

    def test_publication_failure_and_null_short_binding_are_safe(self):
        self.keyboard.INPUT_PUB.send_multipart.side_effect = zmq.Again()
        self.handle((4, 0))
        self.handle((4, 0), 4, count=3)
        self.keyboard.INPUT_PUB.send_multipart.assert_called_once()
        self.keyboard.CONFIG['mmi_short_map'][(0, 8)] = None
        self.handle((0, 8), count=40)
        self.handle((0, 8), 4)
        self.keyboard.UINPUT_DEVICE.emit_click.assert_not_called()

    def load_config(self, mmi):
        cfg = dict(input_mappings=dict(mmi=mmi), can_ids={'mmi': '0x461', 'tv_presence': '0x'})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(cfg))
            self.assertTrue(self.keyboard.load_and_initialize_config(str(path)))

    def test_shared_config_binding_types_register_keys_in_all_three_tables(self):
        self.load_config({'short_press': {'8,0': 'KEY_F', '4,0': {'action': 'applications_menu'},
                                          '0,1': {'action': 'setup_menu'}, '12,0': None},
                          'long_press': {'8,0': 'KEY_G', '0,12': {'action': 'hudiy_diagnostics'}},
                          'extended_press': {'8,0': 'KEY_J', '0,1': 'old shell command',
                                             '12,0': {'action': 'hudiy_manager'}}})
        self.assertEqual(self.keyboard.CONFIG['can_ids'], {'mmi': 0x461})
        self.assertEqual(set(self.keyboard.get_all_possible_keys()), {(1, 1), (1, 2), (1, 3)})
        self.assertEqual(self.keyboard.CONFIG['mmi_short_map'][(0, 1)], {'action': 'setup_menu'})
        self.assertEqual(self.keyboard.CONFIG['mmi_extended_map'][(0, 1)], 'old shell command')
        self.assertIsNone(self.keyboard.CONFIG['mmi_short_map'][(12, 0)])

    def test_old_config_absence_and_invalid_bindings_are_safe(self):
        self.load_config({})
        for name in ('mmi_short_map', 'mmi_long_map', 'mmi_extended_map'):
            self.assertEqual(self.keyboard.CONFIG[name], {})
        self.load_config({'short_press': {'x': 'KEY_F', '1,2,3': 'KEY_F', '256,0': 'KEY_F',
            '8,0': 2, '0,8': 'KEY_MISSING', '4,0': {'action': ''}, '12,0': {'action': 12},
            '0,1': 'shell is invalid here', '0,2': {'action': 'menu', 'extra': True}},
            'long_press': ['invalid table'], 'extended_press': {'8,0': ''}})
        self.assertFalse(any(self.keyboard.CONFIG['mmi_short_map'].values()))
        self.assertEqual(self.keyboard.CONFIG['mmi_long_map'], {})
        self.assertIsNone(self.keyboard.CONFIG['mmi_extended_map'][(8, 0)])


def protobuf_api():
    # Hudiy's generated bindings are installed on the Pi, not committed here.
    # Build its real DispatchAction wire schema (required string action, field 1).
    descriptor = descriptor_pb2.FileDescriptorProto(name='tv_input_test.proto', syntax='proto2')
    message = descriptor.message_type.add(name='DispatchAction')
    message.field.add(name='action', number=1, label=2, type=9)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(descriptor)
    return SimpleNamespace(DispatchAction=message_factory.GetMessageClass(
        pool.FindMessageTypeByName('DispatchAction')), MESSAGE_DISPATCH_ACTION=43)


class HudiyInputActionTests(unittest.TestCase):
    def setUp(self):
        self.now = 20.0
        self.api = protobuf_api()
        self.dispatcher = InputActionDispatcher(self.api, clock=lambda: self.now, queue_size=2)
        self.client = Mock(_connected=True)
        self.dispatcher.set_client(self.client)
        self.now += .1

    def submit(self, event='hudiy_manager', **overrides):
        payload = dict(event=event, monotonic_timestamp=self.now)
        payload.update(overrides)
        return self.dispatcher.submit(payload)

    def test_success_dispatches_real_protobuf_using_existing_client(self):
        for event in ('applications_menu', 'hudiy_diagnostics', 'hudiy_manager'):
            self.assertTrue(self.submit(event))
            self.assertTrue(self.dispatcher.dispatch_one())
            kind, flags, payload = self.client.send.call_args.args
            self.assertEqual((kind, flags), (43, 0))
            message = self.api.DispatchAction.FromString(payload)
            self.assertEqual(message.action, event)

    def test_disconnected_actions_are_dropped_and_not_replayed(self):
        self.dispatcher.set_client(None)
        self.assertFalse(self.submit())
        self.dispatcher.set_client(Mock(_connected=False))
        self.assertFalse(self.submit())
        self.now += .1
        self.dispatcher.set_client(self.client)
        self.assertFalse(self.submit(monotonic_timestamp=self.now - .05))
        self.assertFalse(self.dispatcher.dispatch_one())
        self.client.send.assert_not_called()

    def test_pending_action_cannot_cross_reconnect_or_disconnection(self):
        self.assertTrue(self.submit())
        self.dispatcher.set_client(Mock(_connected=True))
        self.assertFalse(self.dispatcher.dispatch_one())
        self.client.send.assert_not_called()
        self.dispatcher.set_client(self.client)
        self.assertTrue(self.submit())
        self.client._connected = False
        self.assertFalse(self.dispatcher.dispatch_one())
        self.client.send.assert_not_called()

    def test_backlog_is_bounded_and_expires_instead_of_replaying(self):
        self.assertTrue(self.submit())
        self.assertTrue(self.submit())
        self.assertFalse(self.submit())
        self.now += 1.1
        self.assertFalse(self.dispatcher.dispatch_one())
        self.assertFalse(self.dispatcher.dispatch_one())
        self.client.send.assert_not_called()

    def test_bad_stale_future_events_are_rejected(self):
        for payload in (None, [], {}, dict(event='x'), dict(event='x', monotonic_timestamp=True),
                        dict(event='x', monotonic_timestamp=float('nan')),
                        dict(event='x', monotonic_timestamp=float('inf'))):
            self.assertFalse(self.dispatcher.submit(payload))
        for stamp in (self.now - 1.1, self.now + .1):
            self.assertFalse(self.submit(monotonic_timestamp=stamp))
        self.assertFalse(self.submit(''))
        self.assertFalse(self.submit('x' * 257))

    def test_send_error_drops_once_and_shutdown_rejects_pending_actions(self):
        self.client.send.side_effect = ConnectionError('lost')
        self.assertTrue(self.submit())
        self.assertFalse(self.dispatcher.dispatch_one())
        self.assertFalse(self.dispatcher.dispatch_one())
        self.client.send.assert_called_once()
        self.assertTrue(self.submit())
        self.dispatcher.stop()
        self.assertFalse(self.submit())
        self.assertFalse(self.dispatcher.dispatch_one())

    def test_blocked_api_send_leaves_input_queue_bounded_and_stop_discards_backlog(self):
        entered, release = threading.Event(), threading.Event()
        def send(*args):
            entered.set()
            release.wait(2)
        self.client.send.side_effect = send
        self.dispatcher.start()
        try:
            self.assertTrue(self.submit())
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.submit())
            self.assertTrue(self.submit())
            self.assertFalse(self.submit())
            self.dispatcher.stop()
            self.assertFalse(self.submit())
        finally:
            release.set()
            self.dispatcher.worker.join(1)
        self.assertFalse(self.dispatcher.worker.is_alive())
        self.client.send.assert_called_once()

    def test_subscriber_consumes_only_exact_topic_and_closes_on_shutdown(self):
        tree = ast.parse((ROOT / 'hudiy_client/hudiy_data.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'HudiyData')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'input_action_subscriber')
        namespace = dict(zmq=zmq, json=json, logger=logging.getLogger(__name__))
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'hudiy_data.py', 'exec'), namespace)
        context = zmq.Context()
        publisher = context.socket(zmq.XPUB)
        publisher.setsockopt(zmq.LINGER, 0)
        port = publisher.bind_to_random_port('tcp://127.0.0.1')
        service = SimpleNamespace(running=True, input_control_addr=f'tcp://127.0.0.1:{port}',
                                  input_actions=self.dispatcher)
        worker = threading.Thread(target=namespace['input_action_subscriber'], args=(service,))
        worker.start()
        try:
            self.assertTrue(publisher.poll(2000))
            self.assertEqual(publisher.recv(), b'\x01HUDIY_ACTION')
            payload = json.dumps(dict(event='hudiy_manager', monotonic_timestamp=self.now)).encode()
            publisher.send_multipart([b'HUDIY_ACTION_EXTRA', payload])
            publisher.send_multipart([b'HUDIY_ACTION', b'not json'])
            publisher.send_multipart([b'HUDIY_ACTION', payload])
            deadline = time.monotonic() + 2
            while self.dispatcher.queue.empty() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(self.dispatcher.queue.qsize(), 1)
            self.assertTrue(self.dispatcher.dispatch_one())
        finally:
            service.running = False
            worker.join(timeout=2)
            publisher.close()
            context.term()
        self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
