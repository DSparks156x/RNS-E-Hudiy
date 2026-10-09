import unittest

from tp2.group_scheduler import group_observation
from flasher.vag_protocols.tp2 import TP2MessageReassembler, segment_message


class MeasuringGroupObservationTests(unittest.TestCase):
    def test_eight_fields_survive_fragmentation_and_observation(self):
        response = bytes([0x61, 11] + [0x06, 50, 250] * 8)
        frames, _ = segment_message(response, start_sequence=14, block_size=2)
        receiver = TP2MessageReassembler(14)
        received = None
        for frame in frames:
            received, _ = receiver.feed(frame)
        self.assertEqual(received, response)
        payload, failure = group_observation(1, 11, received, 123, 25)
        self.assertIsNone(failure)
        self.assertEqual(payload["block_count"], 8)
        self.assertEqual(len(payload["data"]), 8)
        self.assertEqual(payload["raw_data_hex"], response[2:].hex())
        self.assertEqual(payload["acquisition_timestamp"], 123)
        self.assertEqual(payload["request_duration_ms"], 25)
        self.assertEqual(payload["trailing_bytes"], 0)
        self.assertTrue(payload["complete"])

    def test_partial_group_retains_legacy_fields_but_is_incomplete(self):
        payload, failure = group_observation(1, 3, [0x61, 3, 6, 50, 250, 26, 70], 123, 25)
        self.assertEqual(payload["data"], [{"value": 12.5, "unit": "V", "type": 6}])
        self.assertEqual(payload["block_count"], 1)
        self.assertEqual(payload["trailing_bytes"], 2)
        self.assertFalse(payload["complete"])
        self.assertEqual(failure["error_kind"], "malformed")

    def test_empty_short_and_wrong_echo_responses_are_failures(self):
        for response in [[], [0x61], [0x61, 3], [0x61, 4, 6, 50, 250], [0x7F]]:
            with self.subTest(response=response):
                _, failure = group_observation(1, 3, response, 123, 25)
                self.assertFalse(failure["complete"])
                self.assertEqual(failure["module"], 1)
                self.assertEqual(failure["group"], 3)

    def test_unsupported_nrc_and_temporary_failure_metadata(self):
        for nrc, transient in [(0x31, False), (0x11, False), (0x21, True), (0x22, True)]:
            payload, failure = group_observation(1, 3, [0x7F, 0x21, nrc], 123, 25)
            self.assertIsNone(payload)
            self.assertEqual(failure["nrc"], nrc)
            self.assertEqual(failure["transient"], transient)
            self.assertEqual(failure["error_kind"], "negative_response")

    def test_transport_error_is_explicit(self):
        payload, failure = group_observation(1, 3, None, 123, 2000, error=TimeoutError("timeout"))
        self.assertIsNone(payload)
        self.assertEqual(failure["error"], "timeout")
        self.assertEqual(failure["error_kind"], "transport")
        self.assertTrue(failure["transient"])


if __name__ == "__main__":
    unittest.main()
