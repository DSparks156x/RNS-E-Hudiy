"""TP2 worker KWP_REQUEST/KWP_RESULT: one-off requests for other services.

Runs the real TP2Service main loop with a fake TP2Protocol. The worker must
reuse a session that is already polling the module, open one when there is
none, and close a channel it opened only for the request.
"""
import ast
import logging
from pathlib import Path
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tp2.group_scheduler import GroupScheduler, parse_group_periods, group_observation  # noqa: E402


class FakeProtocol:
    instances = []

    def __init__(self, channel=None, tester_id=None):
        self.bus = object()
        self.connected = False
        self.last_kwp_req = time.time()
        self.log = []
        FakeProtocol.instances.append(self)

    def connect(self, module):
        self.log.append(('connect', module))
        self.connected = True
        return True

    def send_kvp_request(self, payload):
        self.log.append(('kwp', bytes(payload).hex()))
        if payload[0] == 0x10:
            return [0x50, 0x89]
        if payload[0] == 0x21:
            return [0x7F, 0x21, 0x31]
        return [0x7B, 0xF0, 1, 1, 1, 3]

    def send_keep_alive(self):
        return True

    def maybe_send_keep_alive(self, force=False):
        return True

    def disconnect(self):
        self.log.append(('disconnect',))
        self.connected = False

    def close(self):
        # Worker shutdown; distinct from the idle disconnect under test.
        self.log.append(('close',))
        self.connected = False


class NoThread:
    """run() starts the REP command thread; the tests call its handlers directly."""

    def __init__(self, **kwargs):
        pass

    def start(self):
        pass


def load_service():
    tree = ast.parse((ROOT / 'tp2/tp2_worker.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TP2Service']
    namespace = {
        'logger': logging.getLogger('test'), 'time': time,
        'threading': type('Threading', (), {'Thread': NoThread}),
        'json': __import__('json'), 'os': __import__('os'),
        'TP2Protocol': FakeProtocol, 'TP2Error': RuntimeError,
        'GroupScheduler': GroupScheduler, 'parse_group_periods': parse_group_periods,
        'group_observation': group_observation,
        'flashing_mode_enabled': lambda: False,
        'OPENPILOT_TRANSPORT_ENABLED': False, 'OPENPILOT_DISABLED_REASON': '',
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'tp2_worker.py', 'exec'), namespace)
    service = namespace['TP2Service'].__new__(namespace['TP2Service'])
    service.lock = threading.Lock()
    service.shutdown_event = threading.Event()
    service.running = True
    service.diagnostic_owner = None
    service.config = {}
    service.can_interface = 'can0'
    service.sessions = {}
    service._tester_id_pool = list(range(0x300, 0x307))
    service.kwp_jobs = {}
    service.kwp_job_seq = 0
    service.process_ignition = lambda: None
    service.pub = type('Pub', (), {'send_multipart': lambda *a, **k: None})()
    return service


class KwpRequestTests(unittest.TestCase):
    def setUp(self):
        FakeProtocol.instances.clear()
        self.service = load_service()

    def run_until(self, done, seconds=3.0):
        service = self.service
        service.shutdown_event.clear()
        deadline = time.time() + seconds
        def watchdog():
            while time.time() < deadline and not done():
                time.sleep(0.005)
            service.shutdown_event.set()
        threading.Thread(target=watchdog, daemon=True).start()
        service.run()

    def result(self, job):
        return self.service._kwp_result({'job': job, 'timeout': 2.0})

    def test_opens_channel_answers_and_closes_when_idle(self):
        queued = self.service._queue_kwp({'module': 0x0A, 'payload': '3bf0'})
        self.assertEqual(queued['status'], 'queued')
        self.assertEqual(self.result(queued['job'])['status'], 'pending')
        self.run_until(lambda: self.service.kwp_jobs[queued['job']]['done'])
        self.assertEqual(self.result(queued['job']),
                         {'status': 'ok', 'response': '7bf001010103'})
        proto = FakeProtocol.instances[0]
        self.assertEqual(proto.log[:3], [('connect', 0x0A), ('kwp', '1089'), ('kwp', '3bf0')])
        # Held briefly for a follow-up, then dropped when nothing else uses it.
        proto.connected = True   # undo run_until's shutdown close
        self.service.sessions[0x0A]['kwp_hold_until'] = 0
        self.run_until(lambda: ('disconnect',) in proto.log)
        self.assertIn(('disconnect',), proto.log)
        self.assertEqual(self.result(queued['job'])['status'], 'error')   # collected once

    def test_reuses_a_session_that_is_already_polling(self):
        service = self.service
        service._get_or_create_session(0x0A)
        session = service.sessions[0x0A]
        session['client_subs'] = {'awd': {'groups': [1], 'low_groups': [],
                                          'group_periods_ms': {1: 500},
                                          'last_sync': time.monotonic()}}
        service._rebuild_groups_list(session)
        self.run_until(lambda: any(e == ('kwp', '2101') for e in FakeProtocol.instances[0].log))
        queued = service._queue_kwp({'module': 0x0A, 'payload': '3bf0a55a'})
        self.run_until(lambda: service.kwp_jobs[queued['job']]['done'])
        self.assertEqual(self.result(queued['job'])['status'], 'ok')
        self.assertEqual(len(FakeProtocol.instances), 1)
        proto = FakeProtocol.instances[0]
        self.assertEqual([e for e in proto.log if e[0] == 'connect'], [('connect', 0x0A)])
        self.assertIn(('kwp', '3bf0a55a'), proto.log)
        self.assertNotIn(('disconnect',), proto.log)

    def test_timed_out_job_is_withdrawn_and_never_sent(self):
        queued = self.service._queue_kwp({'module': 0x0A, 'payload': '3bf05aa5'})
        self.service.kwp_jobs[queued['job']]['queued_at'] -= 10
        self.assertEqual(self.result(queued['job'])['status'], 'error')
        self.assertEqual(self.service.sessions[0x0A]['kwp_jobs'], [])

    def test_refused_when_diagnostics_are_not_running(self):
        self.service.running = False
        self.assertEqual(self.service._queue_kwp({'module': 0x0A, 'payload': '3bf0'})['status'],
                         'error')
        with self.assertRaises(ValueError):
            load_service()._queue_kwp({'module': 0x0A, 'payload': ''})


if __name__ == '__main__':
    unittest.main()
