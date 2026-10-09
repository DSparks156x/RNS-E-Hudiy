"""Offline policy and base-service checks; no hardware or CAN writes."""
import ast
import asyncio
import importlib.util
import json
import logging
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Dict
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rnse_control', ROOT / 'rns-e_can/rnse_control.py')
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
BrightnessSettings = MODULE.BrightnessSettings
RnseBrightnessController = MODULE.RnseBrightnessController
RnseCanBrightnessProtocol = MODULE.RnseCanBrightnessProtocol


class TestProtocol:
    """Synthetic bounds for policy testing, not an RNS-E protocol claim."""
    def validate_level(self, level):
        if not 2 <= level <= 8:
            raise ValueError('outside test protocol bounds')


class BrightnessPolicyTests(unittest.TestCase):
    def controller(self, **values):
        return RnseBrightnessController.from_config({'auto_brightness': values})

    def test_absent_settings_are_disabled_with_confirmed_native_defaults(self):
        controller = RnseBrightnessController.from_config({})
        self.assertEqual(controller.settings, BrightnessSettings())
        self.assertEqual((controller.settings.day_brightness, controller.settings.night_brightness), (10, 5))
        self.assertEqual(controller.status().state, 'disabled')
        self.assertIsNone(controller.target())

    def test_enabled_with_missing_protocol_never_proposes_a_command(self):
        controller = RnseBrightnessController(BrightnessSettings(enabled=True))
        for mode in (False, True, False):
            controller.observe_lights(mode)
            self.assertEqual(controller.status().state, 'waiting_protocol')
            self.assertFalse(controller.status().protocol_available)
            self.assertIsNone(controller.target())
            self.assertIsNone(controller.target(inhibited=True))

    def test_confirmed_native_bounds_and_exact_eight_byte_command(self):
        protocol = RnseCanBrightnessProtocol()
        self.assertEqual(protocol.encode(5), (0x7B0, bytes.fromhex('B705000000000000')))
        self.assertEqual(len(protocol.encode(0)[1]), 8)
        self.assertEqual(protocol.encode(10)[1], bytes.fromhex('B70A000000000000'))
        for level in (-1, 11, True, 5.5, '5', None):
            with self.subTest(level=level), self.assertRaises(ValueError):
                protocol.encode(level)
        for level in (-1, 11):
            with self.subTest(level=level), self.assertRaises(ValueError):
                self.controller(day_brightness=level)

    def test_config_types_are_strict_and_null_levels_are_supported(self):
        for values in ({'enabled': 1}, {'enabled': 'false'}, {'day_brightness': True},
                       {'night_brightness': 2.5}, {'day_brightness': '12'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.controller(**values)
        for rnse in (None, [], {'auto_brightness': None}, {'auto_brightness': []}):
            with self.subTest(rnse=rnse), self.assertRaises(ValueError):
                RnseBrightnessController.from_config(rnse)
        self.assertIsNone(self.controller(enabled=True, day_brightness=None).settings.day_brightness)

    def test_confirmed_mode_changes_select_the_matching_native_level(self):
        controller = self.controller(enabled=True, day_brightness=7, night_brightness=3)
        controller.protocol = TestProtocol()
        self.assertEqual(controller.status().state, 'waiting_vehicle_state')
        self.assertIsNone(controller.target())
        self.assertTrue(controller.observe_lights(False))
        self.assertEqual(controller.target(), ('day', 7))
        self.assertFalse(controller.observe_lights(False))
        self.assertTrue(controller.observe_lights(True))
        self.assertEqual(controller.target(), ('night', 3))
        with self.assertRaises(ValueError):
            controller.observe_lights(1)

    def test_inhibition_suppresses_target_and_resume_uses_latest_mode(self):
        controller = self.controller(enabled=True, day_brightness=7, night_brightness=3)
        controller.protocol = TestProtocol()
        controller.observe_lights(False)
        self.assertEqual(controller.status(inhibited=True).state, 'inhibited')
        self.assertIsNone(controller.target(inhibited=True))
        controller.observe_lights(True)
        self.assertIsNone(controller.target(inhibited=True))
        self.assertEqual(controller.target(), ('night', 3))

    def test_missing_or_out_of_protocol_range_level_is_not_ready(self):
        controller = self.controller(enabled=True, day_brightness=None, night_brightness=9)
        controller.protocol = TestProtocol()
        controller.observe_lights(False)
        self.assertEqual(controller.status().state, 'waiting_brightness')
        self.assertIsNone(controller.target())
        controller.observe_lights(True)
        self.assertEqual(controller.status().state, 'invalid_brightness')
        self.assertIn('test protocol', controller.status().error)
        self.assertIsNone(controller.target())

    def test_command_is_queued_once_and_rearmed_after_radio_sleep_or_inhibition(self):
        controller = self.controller(enabled=True)
        self.assertIsNone(controller.pending_command(True))
        controller.observe_lights(False)
        self.assertIsNone(controller.pending_command(False))
        command = controller.pending_command(True)
        self.assertEqual((command.mode, command.level), ('day', 10))
        controller.mark_queued(command)
        for _ in range(10):
            self.assertIsNone(controller.pending_command(True))
        controller.observe_lights(True)
        command = controller.pending_command(True)
        self.assertEqual(command.payload.hex(), 'b705000000000000')
        controller.mark_queued(command)
        self.assertIsNone(controller.pending_command(True))
        self.assertIsNone(controller.pending_command(True, inhibited=True))
        command = controller.pending_command(True)
        self.assertIsNotNone(command)
        controller.mark_queued(command)
        self.assertIsNone(controller.pending_command(False))
        self.assertIsNotNone(controller.pending_command(True))


class BaseServiceBrightnessTests(unittest.TestCase):
    def namespace(self):
        source = ROOT / 'rns-e_can/can_base_function.py'
        tree = ast.parse(source.read_text())
        names = {'load_and_initialize_config', 'handle_rnse_light_status_message',
                 'handle_nav_nm_message', 'reconcile_rnse_brightness', 'listen_for_can_messages_task'}
        nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
        namespace = dict(CONFIG={}, FEATURES={}, Dict=Dict, Any=Any,
                         RnseBrightnessController=RnseBrightnessController,
                         pytz=SimpleNamespace(timezone=lambda zone: zone),
                         json=json, logging=logging, logger=Mock(), send_can_message=Mock(return_value=True),
                         flashing_mode_enabled=Mock(return_value=False), AppState=SimpleNamespace,
                         time=SimpleNamespace(time=lambda: 100), publish_power_status=Mock(),
                         asyncio=asyncio, zmq=SimpleNamespace(SUB=1), RUNNING=True)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
        return namespace

    def fixture(self, **brightness):
        return {'rnse': {'auto_brightness': brightness},
                'features': {'day_night_mode': False},
                'can_ids': {'light_status': '0x635'},
                'interfaces': {'zmq': {'send_address': 'test-send',
                                      'can_raw_stream': 'test-stream',
                                      'system_events': 'test-events'}}}

    def load(self, namespace, config):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(config))
            return namespace['load_and_initialize_config'](str(path))

    def test_enabled_runtime_observes_lights_independently_without_transmitting(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True, day_brightness=10, night_brightness=5)))
        self.assertEqual(namespace['CONFIG']['can_ids']['light_status'], 0x635)
        controller = namespace['CONFIG']['rnse_brightness']
        handler = namespace['handle_rnse_light_status_message']
        handler({'dlc': 2, 'data_hex': '0000'})
        self.assertEqual(controller.status().mode, 'day')
        handler({'dlc': 2, 'data_hex': '0001'})
        self.assertEqual(controller.status().mode, 'night')
        self.assertEqual(controller.status().state, 'ready')
        namespace['send_can_message'].assert_not_called()

    def test_invalid_or_short_light_payload_does_not_guess_a_mode(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        handler = namespace['handle_rnse_light_status_message']
        for payload in ({'dlc': 1, 'data_hex': '00'}, {'dlc': 2, 'data_hex': '00'},
                        {'dlc': 8, 'data_hex': '0001'}, {'dlc': '2', 'data_hex': '0001'},
                        {'dlc': 2, 'data_hex': 'not-hex'}, {'dlc': 2, 'data_hex': None}):
            handler(payload)
        self.assertIsNone(namespace['CONFIG']['rnse_brightness'].mode)
        namespace['send_can_message'].assert_not_called()

    def test_reload_replaces_policy_and_disabling_stops_observation(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        previous = namespace['CONFIG']['rnse_brightness']
        self.assertTrue(self.load(namespace, self.fixture(enabled=False)))
        current = namespace['CONFIG']['rnse_brightness']
        self.assertIsNot(previous, current)
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        self.assertEqual(current.status().state, 'disabled')
        self.assertIsNone(current.mode)
        namespace['send_can_message'].assert_not_called()

    def test_enabled_requires_an_explicit_light_identifier(self):
        namespace = self.namespace()
        config = self.fixture(enabled=True)
        config['can_ids'] = {}
        self.assertFalse(self.load(namespace, config))

    def state(self, active=True):
        return SimpleNamespace(can_listen_only=False, desired_listen_only=False,
                               listen_only_transition_in_progress=False,
                               is_radio_active=Mock(return_value=active),
                               nav_sleep_ind=None, last_nav_nm_time=0)

    def test_runtime_queues_exact_frame_once_then_changed_mode(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        state = self.state()
        reconcile = namespace['reconcile_rnse_brightness']
        reconcile(state)
        namespace['send_can_message'].assert_not_called()
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0000'})
        reconcile(state)
        namespace['send_can_message'].assert_called_once_with(0x7B0, 'b70a000000000000')
        for _ in range(10):
            reconcile(state)
        self.assertEqual(namespace['send_can_message'].call_count, 1)
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        reconcile(state)
        self.assertEqual(namespace['send_can_message'].call_count, 2)
        namespace['send_can_message'].assert_called_with(0x7B0, 'b705000000000000')

    def test_runtime_gates_radio_listen_only_and_flashing_then_reapplies(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        state = self.state(active=False)
        reconcile = namespace['reconcile_rnse_brightness']
        reconcile(state)
        namespace['send_can_message'].assert_not_called()
        state.is_radio_active.return_value = True
        for flag in ('can_listen_only', 'desired_listen_only', 'listen_only_transition_in_progress'):
            setattr(state, flag, True)
            reconcile(state)
            namespace['send_can_message'].assert_not_called()
            setattr(state, flag, False)
        namespace['flashing_mode_enabled'].return_value = True
        reconcile(state)
        namespace['send_can_message'].assert_not_called()
        namespace['flashing_mode_enabled'].return_value = False
        reconcile(state)
        self.assertEqual(namespace['send_can_message'].call_count, 1)
        namespace['flashing_mode_enabled'].return_value = True
        reconcile(state)
        namespace['flashing_mode_enabled'].return_value = False
        reconcile(state)
        self.assertEqual(namespace['send_can_message'].call_count, 2)
        state.is_radio_active.return_value = False
        reconcile(state)
        state.is_radio_active.return_value = True
        reconcile(state)
        self.assertEqual(namespace['send_can_message'].call_count, 3)

    def test_queue_failure_retries_without_marking_queued(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        namespace['send_can_message'].return_value = False
        state = self.state()
        namespace['reconcile_rnse_brightness'](state)
        self.assertIsNone(namespace['CONFIG']['rnse_brightness'].last_queued)
        namespace['send_can_message'].return_value = True
        namespace['reconcile_rnse_brightness'](state)
        self.assertEqual(namespace['CONFIG']['rnse_brightness'].last_queued, ('night', 5))

    def test_reload_uses_new_levels_after_confirmed_state_without_a_heartbeat(self):
        namespace = self.namespace()
        state = self.state()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        namespace['reconcile_rnse_brightness'](state)
        self.assertTrue(self.load(namespace, self.fixture(enabled=True, night_brightness=3)))
        namespace['reconcile_rnse_brightness'](state)
        self.assertEqual(namespace['send_can_message'].call_count, 1)
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        namespace['reconcile_rnse_brightness'](state)
        namespace['send_can_message'].assert_called_with(0x7B0, 'b703000000000000')

    def test_explicit_radio_wake_rearms_even_between_periodic_checks(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        state = self.state()
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        namespace['reconcile_rnse_brightness'](state)
        state.is_radio_active.return_value = False
        namespace['handle_nav_nm_message']({'dlc': 2, 'data_hex': '0000'}, state)
        state.is_radio_active.return_value = True
        namespace['reconcile_rnse_brightness'](state)
        self.assertEqual(namespace['send_can_message'].call_count, 2)

    def test_listener_subscribes_to_radio_nm_when_listen_only_is_disabled(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        namespace['FEATURES']['power_management']['listen_only_mode']['enabled'] = False
        stream = SimpleNamespace(transport=SimpleNamespace(subscribe=Mock()), close=Mock())
        async def read():
            namespace['RUNNING'] = False
            return [b'CAN_635', b'{"arbitration_id":1589,"dlc":2,"data_hex":"0000"}']
        stream.read = read
        namespace['aiozmq'] = SimpleNamespace(create_zmq_stream=AsyncMock(return_value=stream))
        asyncio.run(namespace['listen_for_can_messages_task'](self.state()))
        subscriptions = [call.args[0] for call in stream.transport.subscribe.call_args_list]
        self.assertIn(b'CAN_635', subscriptions)
        self.assertIn(b'CAN_436', subscriptions)
        self.assertNotIn(b'CAN_42B', subscriptions)


if __name__ == '__main__':
    unittest.main()
