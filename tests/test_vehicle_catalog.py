import copy
import json
import unittest

from vehicle_data.catalog import CATALOG, decode_ican, diagnostic_readings, get_catalog


def provider(value_id, **criteria):
    return next(p for p in CATALOG[value_id]["providers"]
                if all(p.get(k) == v for k, v in criteria.items()))


def can_frame(**signals):
    """Use explicit DBC bit positions for fixture frames."""
    packed = 0
    for location, value in signals.items():
        packed |= value << int(location[1:])
    return packed.to_bytes(8, "little")


class VehicleCatalogTest(unittest.TestCase):
    def test_catalog_is_json_serializable_and_independent(self):
        catalog = get_catalog()
        json.dumps(catalog, allow_nan=False)
        catalog[0]["providers"][0]["verified"] = False
        self.assertTrue(CATALOG["engine.rpm"]["providers"][0]["verified"])
        all_ids = [p["id"] for entry in CATALOG.values() for p in entry["providers"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertTrue(all(p["block"] >= 1 for e in catalog for p in e["providers"] if p["kind"] == "diag"))

    def test_can_rpm_valid_zero_and_stale_or_error(self):
        pid = provider("engine.rpm", kind="ican")["id"]
        for raw, expected in ((0, 0), (3200, 800), (1, .25)):
            self.assertEqual(decode_ican(0x35B, can_frame(b8=raw))[pid],
                             {"value": expected, "valid": True, "reason": None})
        self.assertEqual(decode_ican(0x35B, can_frame(b8=65280))[pid]["reason"], "sentinel")
        self.assertEqual(decode_ican(0x35B, can_frame(b8=65535))[pid]["reason"], "out_of_range")
        self.assertEqual(decode_ican(0x35B, can_frame(b8=3200, b0=1))[pid]["reason"], "invalid_flag")

    def test_coolant_validity_uses_motor2_flag_and_sensor_flag(self):
        pid = provider("engine.coolant_temperature", kind="ican")["id"]
        self.assertEqual(decode_ican(0x35B, can_frame(b24=184))[pid]["value"], 90)
        for raw in (0, 255):
            self.assertFalse(decode_ican(0x35B, can_frame(b24=raw))[pid]["valid"])
        for bit in (1, 34):
            frame = (184 << 24 | 1 << bit).to_bytes(8, "little")
            self.assertEqual(decode_ican(0x35B, frame)[pid]["reason"], "invalid_flag")
        # Motor1 stale only invalidates RPM, not coolant from Motor2.
        self.assertTrue(decode_ican(0x35B, can_frame(b24=184, b0=1))[pid]["valid"])

    def test_oil_sentinels_and_flag(self):
        pid = provider("engine.oil_temperature", kind="ican")["id"]
        self.assertEqual(decode_ican(0x555, can_frame(b56=150))[pid]["value"], 90)
        for raw in (0, 1, 255):
            result = decode_ican(0x555, can_frame(b56=raw))[pid]
            self.assertFalse(result["valid"])
            self.assertIsNone(result["value"])
        self.assertFalse(decode_ican(0x555, can_frame(b56=150, b4=1))[pid]["valid"])

    def test_ambient_sources_remain_distinct_with_validity(self):
        filtered = provider("ambient.filtered_temperature", kind="ican")["id"]
        unfiltered = provider("ambient.unfiltered_temperature", kind="ican")["id"]
        frame = can_frame(b40=140, b48=144)
        readings = decode_ican(0x527, frame)
        self.assertEqual(readings[filtered]["value"], 20)
        self.assertEqual(readings[unfiltered]["value"], 22)
        for bit in (2, 56):
            readings = decode_ican(0x527, (int.from_bytes(frame, "little") | 1 << bit).to_bytes(8, "little"))
            self.assertFalse(readings[filtered]["valid"])
            self.assertFalse(readings[unfiltered]["valid"])
        for raw in (0, 1, 255):
            self.assertFalse(decode_ican(0x527, can_frame(b40=raw))[filtered]["valid"])

    def test_gateway_speed_bit_offset_and_reserved_encodings(self):
        pid = provider("vehicle.speed", can_id=0x351)["id"]
        self.assertAlmostEqual(decode_ican(0x351, can_frame(b9=12345))[pid]["value"], 123.45)
        self.assertEqual(decode_ican(0x351, can_frame(b9=0))[pid]["value"], 0)
        for raw in (32708, 32725, 32742, 32767):
            self.assertFalse(decode_ican(0x351, can_frame(b9=raw))[pid]["valid"])
        self.assertFalse(decode_ican(0x351, can_frame(b9=32700))[pid]["valid"])
        self.assertFalse(decode_ican(0x351, can_frame(b9=100, b0=1))[pid]["valid"])

    def test_generator_not_engine_load_and_no_fuel_estimate(self):
        readings = decode_ican(0x555, can_frame(b8=100, b16=128, b32=100, b56=140))
        self.assertEqual(readings[provider("engine.generator_duty", kind="ican")["id"]]["value"], 40)
        self.assertFalse(any(p["kind"] == "ican" for p in CATALOG["engine.load.actual"]["providers"]))
        self.assertFalse(any("fuel" in p for p in decode_ican(0x35B, can_frame(b40=80))))
        boost = provider("engine.boost.actual_absolute", kind="ican")
        self.assertFalse(boost["verified"])
        atmosphere = provider("engine.atmospheric_pressure", kind="ican")
        self.assertTrue(atmosphere["estimated"])
        self.assertEqual(readings[atmosphere["id"]]["value"], 1013)

    def test_battery_voltage_and_truncated_frames(self):
        pid = provider("vehicle.battery_voltage", kind="ican")["id"]
        self.assertAlmostEqual(decode_ican(0x571, can_frame(b0=150))[pid]["value"], 12.5)
        self.assertAlmostEqual(decode_ican(0x571, bytes([150, 0, 0, 0, 0, 0]))[pid]["value"], 12.5)
        self.assertFalse(decode_ican(0x571, can_frame(b0=255))[pid]["valid"])
        for can_id, size in ((0x35B, 4), (0x555, 7), (0x527, 7), (0x571, 1)):
            self.assertTrue(all(r["reason"] == "short_frame" for r in decode_ican(can_id, bytes(size)).values()))
        self.assertEqual(decode_ican(0x123, bytes(8)), {})

    def test_diagnostic_unit_conversion_and_rejection(self):
        data = [{"value": 800, "unit": "RPM", "type": 1},
                {"value": 40, "unit": "%", "type": 2},
                {"value": 2.2, "unit": "bar", "type": 83},
                {"value": 210, "unit": "kPa"}]
        readings = diagnostic_readings(1, 115, data)
        self.assertEqual(readings["diag:01:115:1"]["value"], 800)
        self.assertEqual(readings["diag:01:115:3"]["value"], 2200)
        self.assertEqual(readings["diag:01:115:4"]["value"], 2100)
        data[3] = {"value": 10, "unit": "V", "type": 6}
        self.assertEqual(diagnostic_readings(1, 115, data)["diag:01:115:4"]["reason"], "unit_mismatch")
        data[3] = {"value": 10, "unit": "mbar", "type": 254}
        self.assertEqual(diagnostic_readings(1, 115, data)["diag:01:115:4"]["reason"], "unknown_formula")
        data[3] = {"value": "0x0123", "unit": "Type_254"}
        self.assertEqual(diagnostic_readings(1, 115, data)["diag:01:115:4"]["reason"], "unknown_formula")

    def test_complete_eight_fields_preserved_and_candidates_extractable(self):
        data = [{"value": 800, "unit": "rpm"}, {"value": 90, "unit": "°C"},
                {"value": 30, "unit": "C"}, {"value": -5, "unit": "°"},
                {"value": 20, "unit": "C"}, {"value": 4.5, "unit": "g/s"},
                {"value": 25, "unit": "km/h"}, {"value": "undocumented", "unit": ""}]
        before = copy.deepcopy(data)
        readings = diagnostic_readings(1, 11, data)
        self.assertEqual(readings["diag:01:11:5"]["value"], 20)
        self.assertEqual(readings["diag:01:11:6"]["value"], 4.5)
        self.assertEqual(readings["diag:01:11:7"]["value"], 25)
        self.assertEqual(data, before)
        self.assertFalse(provider("engine.maf", group=11, block=6)["verified"])
        # The extractor also accepts extensions beyond the first four fields.
        catalog = {"extra": {"id": "extra", "unit": "V", "providers": [
            {"id": "custom:8", "kind": "diag", "module": 1, "group": 11, "block": 8}]}}
        data[7] = {"value": 12.5, "unit": "V"}
        self.assertEqual(diagnostic_readings(1, 11, data, catalog)["custom:8"]["value"], 12.5)

    def test_missing_non_numeric_non_finite_and_module_separation(self):
        self.assertEqual(diagnostic_readings(2, 115, []), {})
        self.assertEqual(diagnostic_readings(1, 115, [])["diag:01:115:1"]["reason"], "missing_field")
        for value in (None, True, "800", float("nan"), float("inf")):
            result = diagnostic_readings(1, 115, [{"value": value, "unit": "rpm"}])
            self.assertEqual(result["diag:01:115:1"]["reason"], "non_numeric")

    def test_throttle_percent_does_not_become_degrees(self):
        fields = [{"value": 800, "unit": "rpm"}, {"value": 4, "unit": "g/s"},
                  {"value": 12, "unit": "%"}, {"value": -5, "unit": "deg"}]
        result = diagnostic_readings(1, 3, fields)
        self.assertTrue(result["diag:01:3:3:position"]["valid"])
        self.assertFalse(result["diag:01:3:3:angle"]["valid"])


if __name__ == "__main__":
    unittest.main()
