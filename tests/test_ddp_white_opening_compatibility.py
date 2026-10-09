"""Framed opening compatibility and rejection guards, entirely offline."""
import json
import unittest
from collections import deque
import _ddp_white_opening_peer as env

candidate = env.protocol


class OpeningRegressionTests(unittest.TestCase):
    def test_all_sequences_and_ack_orders_preserve_valid_openings(self):
        for shape in ('long', 'compound'):
            for prefetch in (False, True):
                for start_seq in range(16):
                    for prefix in (env.BENCH, env.TABLE_ALT, [9, 32, 11, 80, 10, 36, 80]):
                        with self.subTest(shape=shape, prefetch=prefetch, start_seq=start_seq,
                                          prefix=prefix):
                            result = env.opening(candidate, shape, prefetch, prefix,
                                                 start_seq=start_seq)
                            self.assertTrue(result['result'])
                            self.assertEqual(result['state'], 'READY')
                            self.assertEqual(result['geometry'], env.GEOMETRY)
                            if shape == 'compound':
                                self.assertEqual(result['commands'],
                                                 [[21, 1, 1, 2, 0, 0], [1, 1, 0],
                                                  [8], [32, 59, 160, 0]])
                            self.assertFalse(any(p[:3] == [11, 1, 48]
                                                 for p in result['commands']))

    def test_required_setup_response_is_not_bypassed(self):
        for shape in ('long', 'compound'):
            result = env.opening(candidate, shape, True, setup_reply=False)
            self.assertFalse(result['result'])
            self.assertEqual(result['state'], 'DISCONNECTED')

    def test_unverified_separate_geometry_prefetch_policy_is_preserved(self):
        result = env.opening(candidate, 'separate_prefetched', True)
        self.assertFalse(result['result'])
        self.assertEqual(result['state'], 'DISCONNECTED')
        self.assertIn([11, 1, 48], result['commands'])

    def test_final_error_mode_change_and_new_capability_are_not_ready(self):
        for late in ([11, 1, 32], [0, 1], [0, 2], [0x53], [9, 16, 3, 80, 10, 36]):
            with self.subTest(late=late):
                result = env.opening(candidate, 'compound', True, late=late)
                self.assertFalse(result['result'])
                self.assertEqual(result['state'], 'DISCONNECTED')

    def test_malformed_or_other_family_compounds_do_not_invent_geometry(self):
        for prefix, geometry, extra in (
            (env.TABLE_ALT[:-1], env.GEOMETRY, ()),
            (env.TABLE_ALT, env.GEOMETRY[:-1], ()),
            (env.TABLE_ALT, env.GEOMETRY, (0,)),
            ([9, 16, 3, 80, 9, 36, 74], env.GEOMETRY, ()),
            ([9, 240, 11, 80, 9, 36, 74], env.GEOMETRY, ()),
            (env.TABLE_ALT, [49, 57, 0, 50, 0], ()),
            (env.TABLE_ALT, [48, 57, 0, 49, 0], ()),
        ):
            with self.subTest(prefix=prefix, geometry=geometry, extra=extra):
                result = env.opening(candidate, 'compound', True, prefix,
                                     geometry=geometry, compound_extra=extra)
                self.assertFalse(result['result'])
                self.assertIsNone(result['geometry'])

    def receiver(self, initial=True, state=None, mode=None, application_mode=1, scope=None):
        d = candidate.DDPProtocol.__new__(candidate.DDPProtocol)
        d.state = state or candidate.DDPState.INITIALIZING
        d.dis_mode = mode or candidate.DisMode.WHITE
        d.state_generation = d.send_seq_num = 0
        d.tx_id, d.rx_id = 0x6C0, 0x6C1
        d.config = {}
        d._data_inbox = deque()
        d._reset_receive_transport()
        d._reset_application_session()
        d._application_mode = application_mode
        d._initial_application_handshake = initial
        d._geometry_compatibility_scope = scope
        d.send_can = lambda *args: None
        return d

    def retain(self, driver, payload, seq=0):
        frames, _ = env.tp.segment_message(bytes(payload), seq, block_size=6,
                                           length_prefixed=False)
        for frame in frames:
            driver._retain_data(list(frame))
        return (seq + len(frames)) & 15

    def test_compound_role_is_exact_receive_identity_and_keeps_full_capability(self):
        d = self.receiver(scope='white common configuration/fork')
        payload = env.TABLE_ALT + env.GEOMETRY
        self.retain(d, payload)
        record = d._data_inbox[0]
        self.assertIs(d._observed_white_compound_fork_record, record)
        self.assertEqual(record[1:], payload)
        self.assertEqual(d.last_capability_record, tuple(payload))
        self.assertEqual(len(d._data_inbox), 1)
        self.assertEqual(d._geometry_compatibility_records, {})
        d._reset_application_session()
        self.assertIsNone(d._observed_white_compound_fork_record)

    def test_compound_role_cannot_escape_opening_mode_and_scope(self):
        for args in (
            {},
            {'scope': 'white geometry'},
            {'scope': 'white common configuration/fork', 'initial': False},
            {'scope': 'white common configuration/fork', 'state': candidate.DDPState.READY},
            {'scope': 'white common configuration/fork', 'mode': candidate.DisMode.RED},
            {'scope': 'white common configuration/fork', 'application_mode': 2},
        ):
            with self.subTest(args=args):
                d = self.receiver(**args)
                self.retain(d, env.TABLE_ALT + env.GEOMETRY)
                self.assertIsNone(d._observed_white_compound_fork_record)
                self.assertIsNone(d.geometry_record)

    def test_unsolicited_runtime_geometry_still_rejects_as_unknown_request(self):
        d = self.receiver(initial=False, state=candidate.DDPState.READY)
        self.retain(d, env.GEOMETRY)
        self.assertEqual(d._geometry_compatibility_records, {})
        self.assertEqual(d._deferred_application_requests[0]['reply'], (11, 1, 48))
        self.assertIsNone(d.geometry_record)


if __name__ == '__main__':
    unittest.main(verbosity=2)
