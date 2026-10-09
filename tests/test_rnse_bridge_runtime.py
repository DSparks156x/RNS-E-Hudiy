"""Bridge request and leased projection integration without CAN or IPC sockets."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

try:
    import test_rnse_control as CONTROL
except ModuleNotFoundError:
    from tests import test_rnse_control as CONTROL


SPEC = importlib.util.spec_from_file_location('offline_rnse_bridge_runtime', CONTROL.ROOT / 'rns-e_can/rnse_bridge_runtime.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {'aiozmq': SimpleNamespace(), 'zmq': SimpleNamespace(REP=1, SUB=2)}):
    SPEC.loader.exec_module(RUNTIME)


class BridgeRequestTests(unittest.TestCase):
    def setUp(self):
        helper = CONTROL.BaseServiceBrightnessTests()
        self.namespace = helper.namespace()
        self.state = helper.state()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'config.json'
        self.document = helper.fixture(enabled=True, day_brightness=10, night_brightness=3)
        self.document['rnse'].update(auto_lcd_brightness={'enabled': True, 'day_brightness': 90, 'night_brightness': 2},
                                     source_label={'enabled': True})
        self.path.write_text(json.dumps(self.document))
        self.assertTrue(self.namespace['load_and_initialize_config'](str(self.path)))
        self.request = lambda data: self.namespace['process_rnse_bridge_request'](data, self.state)
        self.lights = self.namespace['handle_rnse_light_status_message']
        self.send = self.namespace['send_can_message']

    def test_status_does_not_queue_even_when_target_ready(self):
        self.lights({'dlc': 2, 'data_hex': '0000'})
        for _ in range(4):
            snapshot = self.request({'action': 'status'})
            self.assertEqual(snapshot['state'], 'ready')
            json.dumps(snapshot)
        self.send.assert_not_called()

    def test_partial_live_tests_keep_auto_enabled_and_clear_at_real_edge(self):
        self.lights({'dlc': 2, 'data_hex': '0000'})
        original = self.path.read_bytes()
        self.request({'action': 'manual', 'values': {'brightness': 6}})
        self.send.assert_called_once_with(0x7B0, 'bb06005a00000000')
        self.request({'action': 'manual', 'values': {'lcd_brightness': 30}})
        self.send.assert_called_with(0x7B0, 'bb06001e00000000')
        self.lights({'dlc': 2, 'data_hex': '0000'})
        self.namespace['reconcile_rnse_brightness'](self.state)
        self.assertEqual(self.send.call_count, 2)
        policy = self.namespace['CONFIG']['rnse_brightness']
        self.assertTrue(policy.settings.enabled)
        self.lights({'dlc': 2, 'data_hex': '0001'})
        self.namespace['reconcile_rnse_brightness'](self.state)
        self.send.assert_called_with(0x7B0, 'bb03000200000000')
        self.assertEqual(policy.manual_overrides, {'brightness': None, 'lcd_brightness': None})
        self.assertEqual(self.path.read_bytes(), original)

    def test_reload_only_policy_preserves_features_transports_source_and_lights(self):
        self.lights({'dlc': 2, 'data_hex': '0001'})
        self.namespace['observe_rnse_source'](2, 'reported_provider', self.state)
        self.request({'action': 'manual', 'values': {'brightness': 8}})
        features = self.namespace['FEATURES']
        address = self.namespace['CONFIG']['zmq_send_address']
        self.document['features'] = {'debug_mode': True, 'day_night_mode': True}
        self.document['interfaces']['zmq']['send_address'] = 'untrusted-new-address'
        self.document['rnse']['auto_brightness']['night_brightness'] = 4
        self.path.write_text(json.dumps(self.document))
        self.request({'action': 'reload'})
        self.send.assert_called_with(0x7B0, 'bb04020200000000')
        self.assertIs(self.namespace['FEATURES'], features)
        self.assertEqual(self.namespace['CONFIG']['zmq_send_address'], address)
        policy = self.namespace['CONFIG']['rnse_brightness']
        self.assertEqual(policy.mode, 'night')
        self.assertEqual(policy.source, 2)
        self.assertIsNone(policy.manual_overrides['brightness'])
        count = self.send.call_count
        self.request({'action': 'reload'})
        self.assertEqual(self.send.call_count, count)

    def test_inhibited_manual_changes_only_queue_newest_then_radio_wake_once(self):
        for flag in ('can_listen_only', 'desired_listen_only', 'listen_only_transition_in_progress'):
            setattr(self.state, flag, True)
            self.request({'action': 'manual', 'values': {'brightness': 6, 'lcd_brightness': 50}})
            self.send.assert_not_called()
            setattr(self.state, flag, False)
        self.namespace['flashing_mode_enabled'].return_value = True
        self.request({'action': 'manual', 'values': {'brightness': 7}})
        self.send.assert_not_called()
        self.namespace['flashing_mode_enabled'].return_value = False
        reconcile = self.namespace['reconcile_rnse_brightness']
        reconcile(self.state)
        self.send.assert_called_once_with(0x7B0, 'bb07003200000000')
        self.state.can_listen_only = True
        reconcile(self.state)
        self.state.can_listen_only = False
        reconcile(self.state)
        self.assertEqual(self.send.call_count, 1)
        self.state.is_radio_active.return_value = False
        reconcile(self.state)
        self.state.is_radio_active.return_value = True
        reconcile(self.state)
        reconcile(self.state)
        self.assertEqual(self.send.call_count, 2)

    def test_invalid_manual_is_atomic_and_reload_requires_existing_light_id(self):
        policy = self.namespace['CONFIG']['rnse_brightness']
        with self.assertRaises(ValueError):
            self.request({'action': 'manual', 'values': {'brightness': 6, 'lcd_brightness': 101}})
        self.assertEqual(policy.manual_overrides, {'brightness': None, 'lcd_brightness': None})
        self.namespace['CONFIG']['can_ids']['light_status'] = None
        with self.assertRaises(ValueError):
            self.request({'action': 'reload'})
        self.assertIs(self.namespace['CONFIG']['rnse_brightness'], policy)
        self.send.assert_not_called()


class BridgeTransportTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_rejects_malformed_and_untrusted_requests(self):
        for parts in ([], [b'{}', b'{}'], [b'x' * 4097], [b'[]'], [b'{bad'], [b'\xff'],
                      [b'{"action":"resume"}'], [b'{"action":"reload","path":"other"}'],
                      [b'{"action":"status","values":{}}'], [b'{"action":"manual","values":NaN}']):
            with self.subTest(parts=parts), self.assertRaises((ValueError, UnicodeDecodeError)):
                RUNTIME.parse_request(parts)
        self.assertEqual(RUNTIME.parse_request([b'{"action":"manual","values":{"brightness":5}}']),
                         {'action': 'manual', 'values': {'brightness': 5}})

    async def test_command_server_replies_to_bad_request_and_closes_transport(self):
        messages = [[b'[]'], [b'{"action":"status"}']]
        stream = SimpleNamespace(read=AsyncMock(side_effect=messages), write=Mock(), close=Mock())
        process = Mock(return_value={'state': 'ready'})
        with patch.object(RUNTIME.aiozmq, 'create_zmq_stream', AsyncMock(return_value=stream), create=True) as create:
            await RUNTIME.serve_commands('ipc:///test', process, lambda: stream.read.call_count < 2)
        create.assert_awaited_once_with(RUNTIME.zmq.REP, bind='ipc:///test')
        replies = [json.loads(call.args[0][0]) for call in stream.write.call_args_list]
        self.assertEqual(replies[0]['status'], 400)
        self.assertEqual(replies[1], {'state': 'ready'})
        process.assert_called_once_with({'action': 'status'})
        stream.close.assert_called_once()

    async def test_projection_heartbeats_dedup_can_and_expire_lease_once(self):
        helper = CONTROL.BaseServiceBrightnessTests()
        namespace = helper.namespace()
        config = helper.fixture(enabled=False)
        config['rnse'] = {'source_label': {'enabled': True}}
        self.assertTrue(helper.load(namespace, config))
        state = helper.state()
        observed = []
        def observe(source, evidence):
            observed.append((source, evidence))
            namespace['observe_rnse_source'](source, evidence, state)
        message = [b'HUDIY_PROJECTION', b'{"source":2,"evidence":"reported_provider"}']
        clock = Mock(return_value=0)
        messages = [(0, message), (1, message), (8, asyncio.TimeoutError()), (10, asyncio.TimeoutError())]
        async def read():
            now, result = messages.pop(0)
            clock.return_value = now
            if isinstance(result, Exception):
                raise result
            return result
        stream = SimpleNamespace(read=AsyncMock(side_effect=read),
                                 transport=SimpleNamespace(subscribe=Mock()), close=Mock())
        with patch.object(RUNTIME.aiozmq, 'create_zmq_stream', AsyncMock(return_value=stream), create=True):
            await RUNTIME.listen_projection('ipc:///metrics', observe,
                lambda: stream.read.call_count < 4, clock=clock)
        self.assertEqual(observed, [(2, 'reported_provider'), (2, 'reported_provider'), (0, 'producer_unavailable')])
        self.assertEqual(namespace['send_can_message'].call_count, 2)
        namespace['send_can_message'].assert_called_with(0x7B0, 'bb0a000000000000')
        stream.transport.subscribe.assert_called_once_with(b'HUDIY_PROJECTION')
        stream.close.assert_called_once()

    async def test_inherited_source_expires_even_without_a_fresh_valid_frame(self):
        clock = Mock(return_value=0)
        async def read():
            clock.return_value = 8
            return [b'HUDIY_PROJECTION', b'{"source":2,"evidence":"invalid"}']
        stream = SimpleNamespace(read=AsyncMock(side_effect=read),
                                 transport=SimpleNamespace(subscribe=Mock()), close=Mock())
        observe = Mock()
        with patch.object(RUNTIME.aiozmq, 'create_zmq_stream', AsyncMock(return_value=stream), create=True):
            await RUNTIME.listen_projection('ipc:///metrics', observe,
                lambda: stream.read.call_count < 3, clock=clock)
        observe.assert_called_once_with(0, 'producer_unavailable')

    async def test_invalid_snapshot_flood_cannot_keep_an_old_provider_alive(self):
        clock = Mock(return_value=0)
        frames = [(0, [b'HUDIY_PROJECTION', b'{"source":1,"evidence":"reported_provider"}']),
                  (8, [b'HUDIY_PROJECTION', b'{"source":true,"evidence":"reported_provider"}']),
                  (9, [b'OTHER', b'{}'])]
        async def read():
            now, result = frames.pop(0)
            clock.return_value = now
            return result
        stream = SimpleNamespace(read=AsyncMock(side_effect=read),
                                 transport=SimpleNamespace(subscribe=Mock()), close=Mock())
        observe = Mock()
        with patch.object(RUNTIME.aiozmq, 'create_zmq_stream', AsyncMock(return_value=stream), create=True):
            await RUNTIME.listen_projection('ipc:///metrics', observe,
                lambda: stream.read.call_count < 3, clock=clock)
        self.assertEqual(observe.call_args_list, [unittest.mock.call(1, 'reported_provider'), unittest.mock.call(0, 'producer_unavailable')])

    async def test_projection_ignores_invalid_snapshots_without_guessing_source(self):
        invalid = [[b'OTHER', b'{}'], [b'HUDIY_PROJECTION', b'[]'],
                   [b'HUDIY_PROJECTION', b'{"source":true,"evidence":"reported_provider"}'],
                   [b'HUDIY_PROJECTION', b'{"source":2,"evidence":"visible"}'],
                   [b'HUDIY_PROJECTION', b'x' * 4097]]
        stream = SimpleNamespace(read=AsyncMock(side_effect=invalid),
                                 transport=SimpleNamespace(subscribe=Mock()), close=Mock())
        observe = Mock()
        with patch.object(RUNTIME.aiozmq, 'create_zmq_stream', AsyncMock(return_value=stream), create=True):
            await RUNTIME.listen_projection('ipc:///metrics', observe, lambda: stream.read.call_count < len(invalid))
        observe.assert_not_called()
        stream.close.assert_called_once()
