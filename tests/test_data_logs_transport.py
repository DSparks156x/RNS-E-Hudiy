"""Exercise the real vehicle PUB/SUB and DIS command transports without CAN."""
import json
import tempfile
import time
from pathlib import Path

import zmq

from hudiy_dataview.data_logs import DataLogs


def test_vehicle_stream_and_dis_commands_use_real_zmq_transport():
    context = zmq.Context()
    stream = context.socket(zmq.XPUB)
    stream.setsockopt(zmq.LINGER, 0)
    stream_port = stream.bind_to_random_port('tcp://127.0.0.1')
    # Reserve a random control port, then release it for the service's REP bind.
    reservation = context.socket(zmq.REP)
    control_port = reservation.bind_to_random_port('tcp://127.0.0.1')
    reservation.close(0)
    control = context.socket(zmq.REQ)
    control.setsockopt(zmq.LINGER, 0)
    control.setsockopt(zmq.RCVTIMEO, 3000)
    control.setsockopt(zmq.SNDTIMEO, 3000)
    control.connect('tcp://127.0.0.1:' + str(control_port))
    commands = []
    recorder = None
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'scratch') as directory:
        try:
            config = {'data_logs': {'directory': directory}, 'interfaces': {'zmq': {
                'vehicle_data_stream': 'tcp://127.0.0.1:' + str(stream_port),
                'data_logs_command': 'tcp://127.0.0.1:' + str(control_port)}}}
            def broker(command):
                commands.append(command)
                return {'status': 'ok', 'values': []}
            recorder = DataLogs(config, broker)
            recorder.start()
            # XPUB acknowledges the actual SUB subscription before publication.
            assert stream.poll(3000), 'Recording subscriber did not subscribe'
            assert stream.recv() == b'\x01HUDIY_VALUES'
            def request(command):
                control.send_json(command)
                return control.recv_json()
            for malformed in ({'cmd': None}, {'cmd': []}, {'cmd': 123}, [], None):
                assert request(malformed)['status'] == 'error'
                assert request({'cmd': 'STATUS'})['status'] == 'ok'
            started = request({'cmd': 'START', 'profile_id': 'daily'})
            assert started['status'] == 'ok'
            assert started['recording']['recording']
            session_id = started['recording']['session_id']
            acquisition_time = time.time()
            sample = {'id': 'engine.rpm', 'value': 1537.25, 'unit': 'rpm', 'status': 'ok',
                      'timestamp': acquisition_time, 'sample_sequence': 321, 'max_age_ms': 2000,
                      'quality': 'transport-test', 'source': {'kind': 'diag', 'id': 'diag:01:3:1'}}
            # Identity filtering: unrelated consumers' pinned readings must not enter the log.
            stream.send_multipart([b'HUDIY_VALUES', json.dumps(
                {'client_id': 'unrelated_display', 'values': [{**sample, 'value': 9999}]}).encode()])
            stream.send_multipart([b'HUDIY_VALUES', json.dumps(
                {'client_id': recorder.CLIENT_ID, 'values': [sample]}).encode()])
            deadline = time.monotonic()+3
            observed = False
            while time.monotonic() < deadline:
                # The request/reply round trip itself yields to the subscriber/writer.
                status = request({'cmd': 'STATUS'})
                if status['recording']['samples'] > 8:
                    observed = True
                    break
            assert observed, 'Transport sample was not captured'
            assert request({'cmd': 'MARK', 'note': 'Wheel marker'})['status'] == 'ok'
            stopped = request({'cmd': 'STOP'})
            assert stopped['status'] == 'ok'
            assert not stopped['recording']['recording']
            assert request({'cmd': 'STATUS'})['recording']['session_id'] == session_id
            saved = recorder.read_session(session_id)
            healthy = [row for row in saved['samples'] if row.get('status') == 'ok']
            assert len(healthy) == 1
            assert healthy[0]['value'] == 1537.25
            assert healthy[0]['timestamp'] == acquisition_time
            assert healthy[0]['event_at'] == acquisition_time
            assert healthy[0]['sample_sequence'] == 321
            assert saved['markers'][0]['note'] == 'Wheel marker'
            assert commands[0]['cmd'] == 'SYNC_VALUES'
            assert commands[-1] == {'cmd': 'UNSUBSCRIBE', 'client_id': recorder.CLIENT_ID}
        finally:
            if recorder is not None:
                recorder.close()
                assert not recorder.worker.is_alive()
                assert not recorder.control_worker.is_alive()
            control.close(0)
            stream.close(0)
            context.term()
