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

    def bridge(self, **values):
        return RnseBrightnessController.from_config(values)

    def commit(self, controller):
        command = controller.pending_command(True)
        self.assertIsNotNone(command)
        controller.mark_queued(command)
        return command

    def test_absent_settings_are_disabled_with_confirmed_native_defaults(self):
        controller = self.bridge()
        self.assertEqual(controller.settings, BrightnessSettings())
        self.assertEqual((controller.settings.day_brightness, controller.settings.night_brightness), (10, 5))
        self.assertEqual(controller.status().state, 'disabled')
        self.assertFalse(controller.enabled)
        self.assertFalse(controller.needs_lights)
        self.assertIsNone(controller.target())

    def test_enabled_with_missing_protocol_never_proposes_a_command(self):
        controller = RnseBrightnessController(BrightnessSettings(enabled=True))
        for mode in (False, True, False):
            controller.observe_lights(mode)
            self.assertEqual(controller.status().state, 'waiting_protocol')
            self.assertFalse(controller.status().protocol_available)
            self.assertIsNone(controller.target())
            self.assertIsNone(controller.target(inhibited=True))

    def test_combined_confirmed_eight_byte_command_and_strict_bounds(self):
        protocol = RnseCanBrightnessProtocol()
        self.assertEqual(protocol.encode(5), (0x7B0, bytes.fromhex('BB05000000000000')))
        self.assertEqual(protocol.encode(10, 2, 100), (0x7B0, bytes.fromhex('BB0A026400000000')))
        self.assertEqual(protocol.encode(0, 1, 1)[1], bytes.fromhex('BB00010100000000'))
        for level in (-1, 11, True, 5.5, '5', None):
            with self.subTest(level=level), self.assertRaises(ValueError):
                protocol.encode(level)
        for source in (-1, 3, True, 1.5, '1', None):
            with self.subTest(source=source), self.assertRaises(ValueError):
                protocol.encode(5, source)
        for lcd in (-1, 101, True, 2.5, '6', None):
            with self.subTest(lcd=lcd), self.assertRaises(ValueError):
                protocol.encode(5, 0, lcd)
        for level in (-1, 11):
            with self.subTest(level=level), self.assertRaises(ValueError):
                self.controller(day_brightness=level)

    def test_config_types_and_missing_values_are_strict(self):
        for values in ({'enabled': 1}, {'enabled': 'false'}, {'day_brightness': True},
                       {'night_brightness': 2.5}, {'day_brightness': '12'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.controller(**values)
        for rnse in (None, [], {'auto_brightness': None}, {'auto_brightness': []},
                     {'auto_lcd_brightness': None}, {'auto_lcd_brightness': {'enabled': 1}},
                     {'auto_lcd_brightness': {'day_brightness': 101}},
                     {'auto_lcd_brightness': {'night_brightness': False}},
                     {'manual_brightness': None}, {'manual_lcd_brightness': True},
                     {'source_label': True}, {'source_label': {'enabled': 1}}):
            with self.subTest(rnse=rnse), self.assertRaises(ValueError):
                RnseBrightnessController.from_config(rnse)
        self.assertIsNone(self.controller(enabled=True, day_brightness=None).settings.day_brightness)

    def test_confirmed_mode_changes_select_matching_dial_level(self):
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

    def test_manual_baselines_activate_explicitly_without_lights(self):
        controller = self.bridge(manual_brightness=4, manual_lcd_brightness=40)
        self.assertTrue(controller.enabled)
        self.assertFalse(controller.needs_lights)
        command = self.commit(controller)
        self.assertEqual(command.payload, bytes.fromhex('BB04002800000000'))
        self.assertEqual(command.mode, 'manual')
        self.assertIsNone(controller.pending_command(True))

    def test_lcd_auto_independent_from_dial_auto(self):
        controller = self.bridge(manual_brightness=8,
                                 auto_lcd_brightness={'enabled': True, 'day_brightness': 80, 'night_brightness': 2})
        self.assertFalse(controller.settings.enabled)
        self.assertTrue(controller.enabled)
        self.assertTrue(controller.needs_lights)
        self.assertEqual(controller.status().state, 'waiting_vehicle_state')
        controller.observe_lights(False)
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB08005000000000'))
        controller.observe_lights(True)
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB08000200000000'))
        snapshot = controller.snapshot()
        self.assertEqual(snapshot['lcd_brightness'], 2)
        self.assertEqual(snapshot['effective_lcd_brightness'], 6)
        self.assertTrue(snapshot['queued'])
        json.dumps(snapshot)

    def test_partial_live_override_preserves_other_channel_and_no_config_write(self):
        controller = self.bridge(auto_brightness={'enabled': True, 'day_brightness': 10},
                                 auto_lcd_brightness={'enabled': True, 'day_brightness': 90})
        controller.observe_lights(False)
        settings = controller.settings
        self.commit(controller)
        self.assertTrue(controller.set_manual({'brightness': 6}))
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB06005A00000000'))
        self.assertTrue(controller.set_manual({'lcd_brightness': 30}))
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB06001E00000000'))
        self.assertIs(controller.settings, settings)
        self.assertFalse(controller.set_manual({'brightness': 6}))
        self.assertIsNone(controller.pending_command(True))

    def test_live_testing_resumes_on_real_light_edge_not_repeated_state(self):
        controller = self.bridge(auto_brightness={'enabled': True, 'night_brightness': 3},
                                 auto_lcd_brightness={'enabled': True, 'night_brightness': 7},
                                 source_label={'enabled': True})
        controller.observe_lights(False)
        controller.set_manual({'brightness': 8, 'lcd_brightness': 70})
        self.commit(controller)
        for _ in range(10):
            self.assertFalse(controller.observe_lights(False))
            self.assertIsNone(controller.pending_command(True))
        controller.observe_source(2)
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB08024600000000'))
        self.assertEqual(controller.manual_overrides, {'brightness': 8, 'lcd_brightness': 70})
        self.assertTrue(controller.observe_lights(True))
        self.assertEqual(controller.manual_overrides, {'brightness': None, 'lcd_brightness': None})
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB03020700000000'))
        self.assertIsNone(controller.pending_command(True))

    def test_light_edge_only_resumes_automatic_channel(self):
        controller = self.bridge(auto_brightness={'enabled': True}, manual_lcd_brightness=0)
        controller.observe_lights(False)
        controller.set_manual({'brightness': 7, 'lcd_brightness': 40})
        self.commit(controller)
        controller.observe_lights(True)
        self.assertEqual(controller.manual_overrides, {'brightness': None, 'lcd_brightness': 40})
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB05002800000000'))

    def test_live_override_before_first_light_observation_survives_initial_state(self):
        controller = self.bridge(auto_brightness={'enabled': True})
        controller.set_manual({'brightness': 7})
        self.assertEqual(self.commit(controller).level, 7)
        controller.observe_lights(False)
        self.assertEqual(controller.manual_overrides['brightness'], 7)
        self.assertIsNone(controller.pending_command(True))
        controller.observe_lights(True)
        self.assertIsNone(controller.manual_overrides['brightness'])
        self.assertEqual(self.commit(controller).level, 5)

    def test_live_override_validates_atomically_and_can_resume_configured_policy(self):
        controller = self.bridge()
        controller.set_manual({'brightness': 6})
        self.assertTrue(controller.enabled)
        for values in (None, [], {}, {'unknown': 1}, {'brightness': True},
                       {'lcd_brightness': 101}, {'brightness': 4, 'lcd_brightness': -1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                controller.set_manual(values)
            self.assertEqual(controller.manual_overrides, {'brightness': 6, 'lcd_brightness': None})
        controller.set_manual({'brightness': None})
        self.assertFalse(controller.enabled)

    def test_source_connection_changes_send_one_exact_tuple(self):
        controller = self.bridge(source_label={'enabled': True})
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB0A000000000000'))
        self.assertTrue(controller.observe_source(1))
        self.assertEqual(self.commit(controller).payload, bytes.fromhex('BB0A010000000000'))
        self.assertFalse(controller.observe_source(1))
        self.assertIsNone(controller.pending_command(True))
        self.assertTrue(controller.observe_source(2))
        self.assertEqual(self.commit(controller).source, 2)
        self.assertTrue(controller.observe_source(0))
        self.assertEqual(self.commit(controller).source, 0)
        for source in (True, '1', 3):
            with self.assertRaises(ValueError):
                controller.observe_source(source)

    def test_disabled_source_feature_does_not_send_for_source_changes(self):
        controller = self.bridge(manual_brightness=10)
        self.commit(controller)
        controller.observe_source(2)
        self.assertIsNone(controller.pending_command(True))
        self.assertEqual(controller.snapshot()['source'], 0)
        self.assertEqual(controller.snapshot()['observed_source'], 2)

    def test_identical_day_night_payload_is_not_repeated(self):
        controller = self.bridge(auto_brightness={'enabled': True, 'day_brightness': 6, 'night_brightness': 6},
                                 auto_lcd_brightness={'enabled': True, 'day_brightness': 30, 'night_brightness': 30})
        controller.observe_lights(False)
        self.commit(controller)
        controller.observe_lights(True)
        self.assertIsNone(controller.pending_command(True))
        controller.observe_lights(False)
        self.assertIsNone(controller.pending_command(True))

    def test_inhibition_does_not_rearm_unchanged_payload_but_newest_change_sends_once(self):
        controller = self.controller(enabled=True)
        controller.observe_lights(False)
        self.commit(controller)
        for _ in range(10):
            self.assertIsNone(controller.pending_command(True, inhibited=True))
            self.assertIsNone(controller.pending_command(True))
        controller.set_manual({'brightness': 4})
        self.assertIsNone(controller.pending_command(True, inhibited=True))
        controller.set_manual({'brightness': 2})
        self.assertIsNone(controller.pending_command(True, inhibited=True))
        self.assertEqual(self.commit(controller).level, 2)
        self.assertIsNone(controller.pending_command(True))

    def test_radio_sleep_wake_rearms_one_command(self):
        controller = self.controller(enabled=True)
        controller.observe_lights(False)
        self.commit(controller)
        for _ in range(10):
            self.assertIsNone(controller.pending_command(True))
        for _ in range(10):
            self.assertIsNone(controller.pending_command(False))
        self.commit(controller)
        self.assertIsNone(controller.pending_command(True))
        controller.force_reapply()
        self.commit(controller)
        self.assertIsNone(controller.pending_command(True))

    def test_queue_failure_can_retry_before_first_success(self):
        controller = self.bridge(manual_brightness=5)
        first = controller.pending_command(True)
        self.assertIsNone(controller.last_queued)
        self.assertEqual(controller.pending_command(True).payload, first.payload)
        controller.mark_queued(first)
        self.assertEqual(controller.last_queued, first.payload)
        self.assertIsNone(controller.pending_command(True))

    def test_reload_preserves_observed_state_and_dedup_but_clears_live_tests(self):
        previous = self.bridge(auto_brightness={'enabled': True}, source_label={'enabled': True})
        previous.observe_lights(True)
        previous.observe_source(2)
        self.commit(previous)
        unchanged = self.bridge(auto_brightness={'enabled': True}, source_label={'enabled': True})
        unchanged.inherit_state(previous)
        self.assertEqual(unchanged.mode, 'night')
        self.assertEqual(unchanged.source, 2)
        self.assertIsNone(unchanged.pending_command(True))
        previous.set_manual({'brightness': 8})
        self.commit(previous)
        restored = self.bridge(auto_brightness={'enabled': True}, source_label={'enabled': True})
        restored.inherit_state(previous)
        self.assertEqual(restored.manual_overrides, {'brightness': None, 'lcd_brightness': None})
        self.assertEqual(self.commit(restored).payload, bytes.fromhex('BB05020000000000'))

    def test_effective_lcd_minimum_does_not_change_raw_payload(self):
        for lcd in range(0, 8):
            controller = self.bridge(manual_lcd_brightness=lcd)
            self.assertEqual(self.commit(controller).payload[3], lcd)
            self.assertEqual(controller.snapshot()['effective_lcd_brightness'], max(6, lcd) if lcd else 0)


class BaseServiceBrightnessTests(unittest.TestCase):
    def test_gateway_absence_is_bounded_and_does_not_accept_stale_frames(self):
        import socket
        import time as wall_clock
        import zmq as real_zmq
        # Reserve a loopback port without listening. Unlike inproc, TCP follows
        # libzmq's IMMEDIATE handshake behavior used by deployed IPC transports.
        reservation = socket.socket()
        reservation.bind(('127.0.0.1', 0))
        context = real_zmq.Context()
        proxy = SimpleNamespace(Context=SimpleNamespace(instance=lambda: context),
            PUSH=real_zmq.PUSH, SNDTIMEO=real_zmq.SNDTIMEO, IMMEDIATE=real_zmq.IMMEDIATE,
            LINGER=real_zmq.LINGER, ZMQError=real_zmq.ZMQError)
        source = ROOT / 'rns-e_can/can_base_function.py'
        nodes = [node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef)
                 and node.name in ('initialize_zmq_sender', 'send_can_message')]
        namespace = dict(zmq=proxy, CONFIG={'zmq_send_address': f'tcp://127.0.0.1:{reservation.getsockname()[1]}'},
                         ZMQ_CONTEXT=None, ZMQ_PUSH_SOCKET=None, logger=Mock())
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
        try:
            self.assertTrue(namespace['initialize_zmq_sender']())
            start = wall_clock.monotonic()
            self.assertFalse(namespace['send_can_message'](0x7B0, 'bb0a000000000000'))
            self.assertLess(wall_clock.monotonic() - start, 1)
        finally:
            if namespace['ZMQ_PUSH_SOCKET'] is not None:
                namespace['ZMQ_PUSH_SOCKET'].close()
            context.term()
            reservation.close()

    def namespace(self):
        from hudiy_manager.rnse_adc_protocol import AdcController, DEFAULT_REPLY_ID, reply_identifier
        source = ROOT / 'rns-e_can/can_base_function.py'
        tree = ast.parse(source.read_text())
        names = {'load_and_initialize_config', 'handle_rnse_light_status_message',
                 'observe_rnse_adc_message',
                 'send_adc_frame', 'advance_rnse_adc',
                 'handle_nav_nm_message', 'reconcile_rnse_brightness', 'listen_for_can_messages_task',
                 'rnse_bridge_snapshot', 'process_rnse_bridge_request', 'observe_rnse_source',
                 'normalize_tv_simulation_payload', 'send_periodic_messages_task'}
        nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
        namespace = dict(CONFIG={}, FEATURES={}, Dict=Dict, Any=Any,
                         RnseBrightnessController=RnseBrightnessController,
                         AdcController=AdcController, DEFAULT_REPLY_ID=DEFAULT_REPLY_ID, reply_identifier=reply_identifier,
                         pytz=SimpleNamespace(timezone=lambda zone: zone),
                         json=json, logging=logging, logger=Mock(), send_can_message=Mock(return_value=True),
                         flashing_mode_enabled=Mock(return_value=False), AppState=SimpleNamespace,
                         time=SimpleNamespace(time=lambda: 100), publish_power_status=Mock(), re=__import__('re'),
                         DEFAULT_TV_SIMULATION_PAYLOAD='0912302020202020',
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

    def test_tv_payload_defaults_normalizes_and_only_sends_valid_configured_bytes(self):
        namespace = self.namespace()
        config = self.fixture(enabled=False)
        config['features']['tv_simulation'] = {'enabled': True, 'payload': 'aa BB 0c'}
        config['can_ids']['tv_presence'] = '0x602'
        self.assertTrue(self.load(namespace, config))
        self.assertEqual(namespace['FEATURES']['tv_simulation']['payload'], 'AABB0C')

        # Run one periodic iteration with a controlled sleep boundary.
        async def run_sender_once():
            async def stop_after_send(_delay):
                namespace['RUNNING'] = False
            namespace['asyncio'] = SimpleNamespace(sleep=stop_after_send, CancelledError=asyncio.CancelledError)
            namespace['reconcile_rnse_brightness'] = Mock()
            await namespace['send_periodic_messages_task'](SimpleNamespace(
                can_listen_only=False, desired_listen_only=False,
                listen_only_transition_in_progress=False))
        asyncio.run(run_sender_once())
        namespace['send_can_message'].assert_called_once_with(0x602, 'AABB0C')

        legacy = self.fixture(enabled=False)
        legacy['features']['tv_simulation'] = {'enabled': True}
        legacy['can_ids']['tv_presence'] = '0x602'
        self.assertTrue(self.load(namespace, legacy))
        self.assertEqual(namespace['FEATURES']['tv_simulation']['payload'], '0912302020202020')

        prior_features = namespace['FEATURES']
        legacy['features']['tv_simulation']['payload'] = '0 9'
        self.assertFalse(self.load(namespace, legacy))
        self.assertIs(namespace['FEATURES'], prior_features)
        self.assertEqual(namespace['FEATURES']['tv_simulation']['payload'], '0912302020202020')
        namespace['RUNNING'] = True
        asyncio.run(run_sender_once())
        namespace['send_can_message'].assert_called_with(0x602, '0912302020202020')

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
        self.assertEqual(current.mode, 'night')
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
                               nav_sleep_ind=None, last_nav_nm_time=0,
                               rnse_source_evidence='producer_unavailable')

    def test_runtime_queues_exact_frame_once_then_changed_mode(self):
        namespace = self.namespace()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        state = self.state()
        reconcile = namespace['reconcile_rnse_brightness']
        reconcile(state)
        namespace['send_can_message'].assert_not_called()
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0000'})
        reconcile(state)
        namespace['send_can_message'].assert_called_once_with(0x7B0, 'bb0a000000000000')
        for _ in range(10):
            reconcile(state)
        self.assertEqual(namespace['send_can_message'].call_count, 1)
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        reconcile(state)
        self.assertEqual(namespace['send_can_message'].call_count, 2)
        namespace['send_can_message'].assert_called_with(0x7B0, 'bb05000000000000')

    def test_runtime_gates_radio_listen_only_and_flashing_without_duplicate_resume(self):
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
        self.assertEqual(namespace['send_can_message'].call_count, 1)
        state.is_radio_active.return_value = False
        reconcile(state)
        state.is_radio_active.return_value = True
        reconcile(state)
        self.assertEqual(namespace['send_can_message'].call_count, 2)

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
        self.assertEqual(namespace['CONFIG']['rnse_brightness'].last_queued, bytes.fromhex('BB05000000000000'))

    def test_reload_uses_new_levels_after_confirmed_state_without_a_heartbeat(self):
        namespace = self.namespace()
        state = self.state()
        self.assertTrue(self.load(namespace, self.fixture(enabled=True)))
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        namespace['reconcile_rnse_brightness'](state)
        self.assertTrue(self.load(namespace, self.fixture(enabled=True, night_brightness=3)))
        namespace['reconcile_rnse_brightness'](state)
        self.assertEqual(namespace['send_can_message'].call_count, 2)
        namespace['handle_rnse_light_status_message']({'dlc': 2, 'data_hex': '0001'})
        namespace['reconcile_rnse_brightness'](state)
        self.assertEqual(namespace['send_can_message'].call_count, 2)
        namespace['send_can_message'].assert_called_with(0x7B0, 'bb03000000000000')

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

    def test_lcd_only_auto_listens_and_observes_lights_with_dial_auto_off(self):
        namespace = self.namespace()
        config = self.fixture(enabled=False)
        config['rnse']['auto_lcd_brightness'] = {'enabled': True, 'day_brightness': 80, 'night_brightness': 2}
        self.assertTrue(self.load(namespace, config))
        stream = SimpleNamespace(transport=SimpleNamespace(subscribe=Mock()), close=Mock())
        async def read():
            namespace['RUNNING'] = False
            return [b'CAN_635', b'{"arbitration_id":1589,"dlc":2,"data_hex":"0001"}']
        stream.read = read
        namespace['aiozmq'] = SimpleNamespace(create_zmq_stream=AsyncMock(return_value=stream))
        state = self.state()
        asyncio.run(namespace['listen_for_can_messages_task'](state))
        subscriptions = [call.args[0] for call in stream.transport.subscribe.call_args_list]
        self.assertIn(b'CAN_635', subscriptions)
        self.assertEqual(namespace['CONFIG']['rnse_brightness'].mode, 'night')
        namespace['reconcile_rnse_brightness'](state)
        namespace['send_can_message'].assert_called_once_with(0x7B0, 'bb0a000200000000')


if __name__ == '__main__':
    unittest.main()
