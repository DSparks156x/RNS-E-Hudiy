"""Regression checks for validated profiles, telemetry recovery and wheel ownership."""
import importlib.util
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tp2.group_scheduler import parse_group_periods
from vehicle_data.broker import VehicleDataBroker
from vehicle_data.service import LegacyCANAdapter, VehicleDataService
from vehicle_data.workspace import default_workspace, validate_workspace
from test_vehicle_service import FakeAgain, fake_zmq


class WorkspaceReviewTests(unittest.TestCase):
    def test_saved_profiles_use_the_same_period_limits_as_the_broker(self):
        for request in ({'period_ms': .5}, {'period_ms': 86400001},
                        {'rate_hz': 2000}, {'rate_hz': .000001}):
            with self.subTest(request=request):
                document = default_workspace()
                document['profiles'][0]['values'] = [{'id': 'engine.rpm', **request}]
                with self.assertRaises(ValueError):
                    validate_workspace(document)
        for period in (1, 86400000):
            document = default_workspace()
            document['profiles'][0]['values'] = [{'id': 'engine.rpm', 'period_ms': period}]
            clean = validate_workspace(document)
            result = VehicleDataBroker().sync('review', clean['profiles'][0]['values'])
            self.assertEqual(result['status'], 'ok')

    def test_malformed_identifiers_raise_validation_errors(self):
        for invalid in ([], {}, True, None):
            for target in ('value', 'slot', 'profile'):
                with self.subTest(invalid=invalid, target=target):
                    document = default_workspace()
                    if target == 'value':
                        document['profiles'][0]['values'] = [{'id': invalid}]
                    elif target == 'slot':
                        document['dis_pages'][0]['slots'][0]['value_id'] = invalid
                    else:
                        document['dis_pages'][0]['profile_id'] = invalid
                    with self.assertRaises(ValueError):
                        validate_workspace(document)

    def test_scheduler_rejects_boolean_and_fractional_group_ids(self):
        for invalid in (True, False, 3.1, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_group_periods({invalid: 500})
        self.assertEqual(parse_group_periods({'3': 500, 4: 1000}), {3: 500., 4: 1000.})


class TelemetryReviewTests(unittest.TestCase):
    def test_bad_commands_raise_clear_validation_errors(self):
        service = VehicleDataService.__new__(VehicleDataService)
        for request in (None, [], 'STATUS', 3):
            with self.subTest(request=request), self.assertRaisesRegex(ValueError, 'object'):
                service.command(request)

    def test_bad_frames_do_not_stop_valid_telemetry_or_socket_cleanup(self):
        zmq = fake_zmq()
        sockets = [Mock() for _ in range(5)]
        raw, diag, pub, legacy_pub, rep = sockets
        valid = {'module': 1, 'group': 3, 'data': [
            {'value': 800, 'unit': 'rpm'}, {'value': 4.5, 'unit': 'g/s'},
            {'value': 12, 'unit': '%'}, {'value': -5, 'unit': 'deg'}]}
        diag.recv_multipart.side_effect = [
            [b'HUDIY_DIAG'], [b'HUDIY_DIAG', b'{}', b'extra'],
            [b'HUDIY_DIAG', b'[]'], [b'HUDIY_DIAG', b'null'],
            [b'HUDIY_DIAG', b'\xff'],
            [b'HUDIY_DIAG', json.dumps(valid).encode()], FakeAgain()]
        service = VehicleDataService.__new__(VehicleDataService)
        service.context = Mock()
        service.context.socket.side_effect = sockets
        service.owns_context = False
        service.zmq = zmq
        service.addresses = {key: key for key in ('can_raw_stream', 'tp2_stream',
            'vehicle_data_stream', 'status_stream', 'vehicle_data_command')}
        service.sockets, service.observations = [], {}
        service.running = True
        service.legacy, service.broker, service.tp2 = LegacyCANAdapter(), VehicleDataBroker(), Mock()
        service.tp2.status.return_value = None
        service.broker.sync('review', ['engine.maf'])
        poller = Mock()
        def poll(_timeout):
            service.running = False
            return [(diag, zmq.POLLIN)]
        poller.poll.side_effect = poll
        zmq.Poller = Mock(return_value=poller)
        service.run()
        sample = service.broker.snapshot(client_id='review')[0]
        self.assertEqual(sample['value'], 4.5)
        self.assertEqual(len(service.observations), 1)
        service.tp2.close.assert_called_once()
        for socket in sockets:
            socket.close.assert_called_once()


class WheelReviewTests(unittest.TestCase):
    def test_losing_control_capability_returns_wheel_to_normal_mappings(self):
        path = Path(__file__).resolve().parents[1] / 'rns-e_can/wheel_controls.py'
        spec = importlib.util.spec_from_file_location('review_wheel_controls', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        emit, normal = Mock(), Mock()
        wheel = module.WheelControlRouter(emit, normal)
        wheel.context('app_car_info', True, controllable=True)
        wheel.toggle()
        self.assertEqual(wheel.owner, 'dis')
        wheel.context('app_car_info', True, controllable=False)
        self.assertEqual(wheel.owner, 'normal')
        wheel.handle('scroll_down')
        normal.assert_called_once_with('scroll_down')


class DiagnosticReceiveReviewTests(unittest.TestCase):
    def device(self, bus):
        # Loading this adapter does not open a hardware CAN interface.
        path = Path(__file__).resolve().parents[1] / 'tp2/tp2_protocol.py'
        spec = importlib.util.spec_from_file_location('review_tp2_protocol', path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'can': SimpleNamespace()}):
            spec.loader.exec_module(module)
        return module, module._WorkerCANDevice(SimpleNamespace(bus=bus))

    def test_continuous_receive_queue_is_bounded(self):
        frame = SimpleNamespace(arbitration_id=0x300, data=b'\xb0')
        bus = Mock()
        bus.recv.return_value = frame
        module, device = self.device(bus)
        with patch.object(module.time, 'monotonic', return_value=0):
            messages = device.can_recv()
        self.assertEqual(len(messages), 256)
        self.assertEqual(bus.recv.call_count, 256)

    def test_invalid_frames_are_filtered_before_transport(self):
        frames = [SimpleNamespace(arbitration_id=0x300, data=b'\xb0', **{flag: True})
                  for flag in ('is_extended_id', 'is_error_frame', 'is_remote_frame', 'is_fd')]
        frames += [SimpleNamespace(arbitration_id=0x300, data=b''),
                   SimpleNamespace(arbitration_id=0x800, data=b'\xb0'),
                   SimpleNamespace(arbitration_id=0x300, data=b'\xb1'), None]
        bus = Mock()
        bus.recv.side_effect = frames
        module, device = self.device(bus)
        with patch.object(module.time, 'monotonic', return_value=0):
            self.assertEqual(device.can_recv(), [(0x300, b'\xb1', 0)])

    def test_receive_stops_draining_at_deadline(self):
        frame = SimpleNamespace(arbitration_id=0x300, data=b'\xb0')
        bus = Mock()
        bus.recv.return_value = frame
        module, device = self.device(bus)
        with patch.object(module.time, 'monotonic', side_effect=(0, .03)):
            self.assertEqual(device.can_recv(20), [(0x300, b'\xb0', 0)])
        bus.recv.assert_called_once_with(.02)


if __name__ == '__main__':
    unittest.main()
