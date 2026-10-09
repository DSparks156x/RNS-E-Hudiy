"""Transport orchestration checks with fake sockets; no ECU or ZMQ needed."""
import copy
import json
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

from vehicle_data.broker import VehicleDataBroker
from vehicle_data.service import LegacyCANAdapter, TP2PlanClient, VehicleDataService, group_plan


class FakeAgain(Exception):
    pass


def fake_zmq():
    return types.SimpleNamespace(REQ=1, SUB=2, PUB=3, REP=4, LINGER=5,
                                 RCVTIMEO=6, SNDTIMEO=7, NOBLOCK=8, POLLIN=9,
                                 Again=FakeAgain)


class Clock:
    def __init__(self, value=0):
        self.now = value

    def __call__(self):
        return self.now


class LegacyCANAdapterTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.adapter = LegacyCANAdapter(clock=self.clock, wall_clock=lambda: 1000 + self.clock.now)

    def test_no_fake_load_or_fuel_and_absent_values_are_null(self):
        self.assertEqual(self.adapter.groups(), [])
        self.adapter.ingest(0x555, bytes([0, 100, 128, 0, 110, 0, 0, 150]), 1000)
        self.adapter.ingest(0x35B, bytes([0, 128, 12, 184, 0, 100, 0, 0]), 1000)
        self.adapter.ingest(0x571, bytes([150, 0, 0, 0, 0, 0, 0, 0]), 1000)
        groups = {message['group']: message for message in self.adapter.groups()}
        self.assertEqual(groups[0]['data'][0]['value'], 90)
        self.assertEqual(groups[0]['data'][2]['value'], 90)
        self.assertIsNone(groups[0]['data'][3]['value'])
        self.assertEqual(groups[1]['data'][0]['value'], 800)
        self.assertIsNone(groups[1]['data'][2]['value'])
        self.assertIsNone(groups[1]['data'][3]['value'])
        self.assertAlmostEqual(groups[2]['data'][0]['value'], 12.5)
        self.assertIsNone(groups[2]['data'][1]['value'])

    def test_sentinel_and_elapsed_freshness_produce_null_keep_timestamp(self):
        self.adapter.ingest(0x555, bytes([0, 0, 128, 0, 100, 0, 0, 150]), 1000)
        self.assertTrue(self.adapter.value('engine.oil_temperature')['valid'])
        self.clock.now = 2
        value = self.adapter.value('engine.oil_temperature')
        self.assertIsNone(value['value'])
        self.assertFalse(value['valid'])
        self.assertEqual(value['timestamp'], 1000)
        self.adapter.ingest(0x555, bytes([0, 0, 128, 0, 100, 0, 0, 255]), 1002)
        self.assertIsNone(self.adapter.value('engine.oil_temperature')['value'])
        self.assertFalse(self.adapter.value('engine.oil_temperature')['valid'])

    def test_delayed_acquisition_is_already_stale_at_receipt(self):
        self.adapter.ingest(0x555, bytes([0, 0, 128, 0, 100, 0, 0, 150]), 990)
        value = self.adapter.value('engine.oil_temperature')
        self.assertFalse(value['valid'])
        self.assertIsNone(value['value'])
        self.assertEqual(value['timestamp'], 990)


class ServiceCommandsTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.service = VehicleDataService.__new__(VehicleDataService)
        self.service.broker = VehicleDataBroker(clock=self.clock, wall_clock=lambda: 1000)
        self.service.tp2 = Mock()
        self.service.tp2.status.return_value = None
        self.service.observations = {}

    def test_catalog_snapshot_plan_and_unsubscribe(self):
        catalog = self.service.command({'cmd': 'CATALOG'})
        self.assertEqual(catalog['version'], 1)
        self.assertIn('engine.maf', {entry['id'] for entry in catalog['values']})
        result = self.service.command({'cmd': 'SYNC_VALUES', 'client_id': 'one',
                                       'values': ['engine.maf', 'engine.ignition_timing']})
        self.assertEqual(result['status'], 'ok')
        plan = self.service.command({'cmd': 'PLAN'})['plan']
        self.assertEqual([(g['module'], g['group']) for g in plan['groups']], [(1, 3)])
        self.service.broker.ingest_diagnostic({'module': 1, 'group': 3, 'timestamp': 1000,
            'data': [{'value': 800, 'unit': 'rpm'}, {'value': 4.5, 'unit': 'g/s'},
                     {'value': 12, 'unit': '%'}, {'value': -5, 'unit': 'deg'}]})
        snapshot = self.service.command({'cmd': 'SNAPSHOT', 'client_id': 'one'})
        readings = {value['id']: value for value in snapshot['values']}
        self.assertEqual(readings['engine.maf']['value'], 4.5)
        self.assertEqual(readings['engine.ignition_timing']['value'], -5)
        self.assertEqual(self.service.command({'cmd': 'STATUS'})['broker']['client_count'], 1)
        self.assertEqual(self.service.command({'cmd': 'UNSUBSCRIBE', 'client_id': 'one'})['status'], 'ok')
        self.assertEqual(self.service.command({'cmd': 'PLAN'})['plan']['groups'], [])

    def test_command_validation_and_atomic_subscription(self):
        self.assertEqual(self.service.command({'cmd': 'not_a_command'})['status'], 'error')
        for command in ({'cmd': 'SYNC_VALUES'},
                        {'cmd': 'SYNC_VALUES', 'client_id': 'one', 'values': ['unknown']},
                        {'cmd': 'SYNC_VALUES', 'client_id': 'one', 'values': [{'id': 'engine.rpm', 'period_ms': 0}]},
                        {'cmd': 'SYNC_VALUES', 'client_id': 'one', 'values': None}):
            self.assertEqual(self.service.command(command)['status'], 'error')
        self.assertEqual(self.service.command({'cmd': 'STATUS'})['broker']['client_count'], 0)
        with self.assertRaises(ValueError):
            self.service.command({'cmd': 'UNSUBSCRIBE'})

    def test_group_plan_uses_period_only_contract(self):
        self.assertEqual(group_plan([{'module': 1, 'group': 3, 'period_ms': 500},
                                     {'module': 1, 'group': 118, 'period_ms': 250},
                                     {'module': 2, 'group': 1, 'period_ms': 1000}]),
                         {1: {'3': 500, '118': 250}, 2: {'1': 1000}})

    def test_run_preserves_complete_extra_field_observation_metadata(self):
        zmq = fake_zmq()
        sockets = [Mock() for _ in range(5)]
        raw, diag, _pub, _legacy_pub, _rep = sockets
        fields = [{'value': 800, 'unit': 'rpm'}, {'value': 90, 'unit': 'C'},
                  {'value': 30, 'unit': 'C'}, {'value': -5, 'unit': 'deg'},
                  {'value': 20, 'unit': 'C'}, {'value': 4.5, 'unit': 'g/s'},
                  {'value': 25, 'unit': 'km/h'}, {'value': '0x0102', 'unit': 'Type_254'}]
        payload = {'module': 1, 'group': 11, 'block_count': 8, 'data': fields,
                   'raw_data_hex': '061234' * 8, 'trailing_bytes': [], 'complete': True,
                   'acquisition_timestamp': 1000}
        diag.recv_multipart.side_effect = [(b'HUDIY_DIAG', json.dumps(payload).encode()), FakeAgain()]
        poller = Mock()
        def poll(_timeout):
            self.service.running = False
            return [(diag, zmq.POLLIN)]
        poller.poll.side_effect = poll
        zmq.Poller = Mock(return_value=poller)
        self.service.context = Mock()
        self.service.context.socket.side_effect = sockets
        self.service.owns_context = False
        self.service.zmq = zmq
        self.service.addresses = {key: key for key in ('can_raw_stream', 'tp2_stream',
            'vehicle_data_stream', 'status_stream', 'vehicle_data_command')}
        self.service.sockets = []
        self.service.running = True
        self.service.legacy = LegacyCANAdapter(clock=self.clock)
        self.service.broker.sync('extra', [{'id': 'engine.maf', 'source': 'diag:01:11:6',
                                          'allow_unverified': True}])
        with patch('vehicle_data.service.time.monotonic', self.clock):
            self.service.run()
        observations = self.service.command({'cmd': 'STATUS'})['observed_groups']
        self.assertEqual(len(observations), 1)
        for key in ('module', 'group', 'block_count', 'raw_data_hex', 'trailing_bytes', 'complete', 'acquisition_timestamp'):
            self.assertEqual(observations[0][key], payload[key])
        sample = self.service.broker.snapshot(client_id='extra')[0]
        self.assertEqual(sample['value'], 4.5)
        self.assertEqual(sample['source']['id'], 'diag:01:11:6')
        self.assertEqual(fields, payload['data'])


class TP2PlanClientTest(unittest.TestCase):
    def test_plan_heartbeat_renews_and_removed_module_is_cleared(self):
        clock = Clock()
        socket = Mock()
        commands = []
        socket.send_json.side_effect = lambda command: commands.append(copy.deepcopy(command))
        socket.recv_json.return_value = {'status': 'ok'}
        context = Mock()
        context.socket.return_value = socket
        client = TP2PlanClient(context, 'fake')
        client.set_plan([{'module': 1, 'group': 3, 'period_ms': 500}])
        iterations = iter((0, 2.1, 5.1, 5.2, 10.3))
        def wait(_timeout):
            try:
                clock.now = next(iterations)
            except StopIteration:
                return True
            if clock.now == 5.2:
                client.set_plan([])
            return False
        client.stop_event = Mock()
        client.stop_event.is_set.return_value = False
        client.stop_event.wait.side_effect = wait
        with patch.dict(sys.modules, {'zmq': fake_zmq()}), patch('vehicle_data.service.time.monotonic', clock):
            client._run()
        sync = [command for command in commands if command['cmd'] == 'SYNC']
        self.assertEqual(len(sync), 3)
        self.assertEqual(sync[0]['group_periods_ms'], {'3': 500})
        self.assertEqual(sync[1]['group_periods_ms'], {'3': 500})
        self.assertEqual(sync[2]['group_periods_ms'], {})
        self.assertTrue(all(command['client_id'] == 'vehicle_data' for command in sync))
        self.assertIsNotNone(client.status())
        socket.close.assert_called_once()

    def test_timeout_recreates_req_socket_and_retries_plan(self):
        clock = Clock()
        broken, recovered = Mock(), Mock()
        broken.recv_json.side_effect = TimeoutError('ECU command service timeout')
        recovered.recv_json.return_value = {'status': 'ok'}
        context = Mock()
        context.socket.side_effect = [broken, recovered]
        client = TP2PlanClient(context, 'fake')
        client.set_plan([{'module': 1, 'group': 3, 'period_ms': 500}])
        iterations = iter((0, .05))
        def wait(_timeout):
            try:
                clock.now = next(iterations)
                return False
            except StopIteration:
                return True
        client.stop_event = Mock()
        client.stop_event.is_set.return_value = False
        client.stop_event.wait.side_effect = wait
        with patch.dict(sys.modules, {'zmq': fake_zmq()}), patch('vehicle_data.service.time.monotonic', clock):
            client._run()
        broken.close.assert_called_once()
        recovered.close.assert_called_once()
        self.assertEqual(recovered.send_json.call_args.args[0]['group_periods_ms'], {'3': 500})


class ValueBridgeTest(unittest.TestCase):
    def make_bridge(self):
        # ZMQ is optional in the test host; the bridge never creates sockets here.
        with patch.dict(sys.modules, {'zmq': fake_zmq()}):
            from hudiy_dataview.value_bridge import ValueBridge
        bridge = ValueBridge.__new__(ValueBridge)
        bridge.clients, bridge.generations = {}, {}
        bridge.lock = threading.Lock()
        bridge.emit = Mock()
        return bridge

    def test_release_during_pending_replace_cannot_resurrect_client(self):
        bridge = self.make_bridge()
        calls = []
        def request(command, wait=True):
            calls.append(command)
            if command['cmd'] == 'SYNC_VALUES':
                bridge.release('sid')
            return {'status': 'ok'}
        bridge.request = request
        result = bridge.replace('sid', ['engine.rpm'])
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('sid', bridge.clients)
        self.assertEqual([command['cmd'] for command in calls], ['SYNC_VALUES', 'UNSUBSCRIBE'])
        bridge.emit.assert_not_called()

    def test_browser_interests_are_independent_and_snapshot_routes_to_owner(self):
        bridge = self.make_bridge()
        bridge.request = Mock(return_value={'status': 'ok', 'values': [{'id': 'engine.rpm', 'value': 800}]})
        self.assertEqual(bridge.replace('one', ['engine.rpm'])['status'], 'ok')
        self.assertEqual(bridge.replace('two', ['engine.maf'])['status'], 'ok')
        self.assertEqual(bridge.clients, {'one': ['engine.rpm'], 'two': ['engine.maf']})
        self.assertEqual(bridge.emit.call_args.kwargs['to'], 'two')
        bridge.release('one')
        self.assertEqual(bridge.clients, {'two': ['engine.maf']})
        self.assertEqual(bridge.request.call_args.args[0]['client_id'], 'dataview_values:one')
        self.assertFalse(bridge.request.call_args.kwargs['wait'])


if __name__ == '__main__':
    unittest.main()
