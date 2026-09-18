import math
import unittest

from tp2.tp2_coding import TP2Coding


class TestTP2CodingConfirmedVagFormulas(unittest.TestCase):
    def assert_decoded(self, formula, a, b, expected, unit):
        value, actual_unit = TP2Coding.decode_value(formula, a, b)
        self.assertEqual(actual_unit, unit)
        if isinstance(expected, float):
            self.assertTrue(math.isclose(value, expected, rel_tol=0, abs_tol=1e-12))
        else:
            self.assertEqual(value, expected)

    def test_gen4_group_001_formulas(self):
        self.assert_decoded(0x1A, 70, 105, 35, "°C")
        self.assert_decoded(0x06, 50, 250, 12.5, "V")

    def test_gen4_group_003_formulas(self):
        self.assert_decoded(0x0E, 20, 150, 10.0, "bar")
        self.assert_decoded(0x5E, 16, 0x80, 0.0, "Nm")
        self.assert_decoded(0x5E, 16, 0x90, 25.6, "Nm")
        self.assert_decoded(0x5E, 16, 0x70, -25.6, "Nm")
        self.assert_decoded(0x21, 80, 50, 40.0, "%")
        self.assert_decoded(0x18, 10, 123, 1.23, "A")

    def test_signed_big_endian_0x51(self):
        self.assert_decoded(0x51, 0x12, 0x34, 203.875, "")
        self.assert_decoded(0x51, 0x80, 0x00, -1433.6, "")
        self.assert_decoded(0x51, 0xFF, 0xFF, -0.04375, "")
        self.assert_decoded(0x51, 0x00, 0x00, 0.0, "")

    def test_protocol_decoder_preserves_precision(self):
        value, _ = TP2Coding.decode_value(0x51, 0x12, 0x34)
        self.assertEqual(value, 203.875)

    def test_low_rpm_is_not_heuristically_multiplied(self):
        self.assertEqual(TP2Coding.normalize_display_value(8.25, "rpm"), 8.25)


class TestTP2CodingBlockContract(unittest.TestCase):
    def test_payload_only_multiple_triples(self):
        decoded = TP2Coding.decode_block([
            0x1A, 70, 105,
            0x06, 50, 250,
            0x5E, 16, 0x80,
            0x18, 10, 123,
        ])
        self.assertEqual(len(decoded), 4)
        self.assertEqual([item["type"] for item in decoded], [0x1A, 0x06, 0x5E, 0x18])
        self.assertEqual([item["value"] for item in decoded], [35, 12.5, 0.0, 1.23])

    def test_truncated_trailing_tuple_is_ignored(self):
        decoded = TP2Coding.decode_block([0x06, 50, 250, 0x1A, 70])
        self.assertEqual(decoded, [{"value": 12.5, "unit": "V", "type": 0x06}])

    def test_empty_and_short_payloads(self):
        self.assertEqual(TP2Coding.decode_block([]), [])
        self.assertEqual(TP2Coding.decode_block([0x06]), [])
        self.assertEqual(TP2Coding.decode_block([0x06, 50]), [])

    def test_unknown_formula_is_explicit(self):
        self.assertEqual(
            TP2Coding.decode_block([0xFE, 0x12, 0x34]),
            [{"value": "0x1234", "unit": "Type_254", "type": 0xFE}],
        )


if __name__ == "__main__":
    unittest.main()
