"""Captured white replies advance native setup without interpreting opaque tails."""
import unittest
from _native_opening_peer import load, exercise, CAR, GEOMETRY

class CapturedOpeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = load(name='captured_native_opening_under_test')

    def test_bench_and_car_combined_records_retain_actual_fragmentation(self):
        for prefix in ([9,32,11,80,8,11,80], CAR):
            for before_ack in (False, True):
                with self.subTest(prefix=prefix, before_ack=before_ack):
                    result = exercise(self.protocol, prefix + GEOMETRY, before_ack=before_ack)
                    self.assertTrue(result['result'])
                    self.assertEqual(result['rx'][:3], [[0x10,0,1], [0x21]+prefix, [0x12]+GEOMETRY])
                    self.assertEqual(result['commands'], [[0x15,1,1,2,0,0], [1,1,0], [8], [0x20,0x3B,0xA0,0], [0x33]])
                    self.assertEqual(result['last_capabilities'], tuple(prefix + GEOMETRY))
                    self.assertEqual(len(result['observations']), 1)
                    self.assertIsNone(result['geometry'])

    def test_setup_confirmation_still_required_for_captured_car_reply(self):
        result = exercise(self.protocol, CAR + GEOMETRY, setup_replies=[])
        self.assertFalse(result['result'])
        self.assertEqual(result['state'], 'DISCONNECTED')
        self.assertNotIn([0x33], result['commands'])

if __name__ == '__main__':
    unittest.main()
