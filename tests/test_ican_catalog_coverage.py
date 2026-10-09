"""Reference consistency plus semantic/validity regressions for passive values."""
import json
from pathlib import Path
import re
import unittest

from vehicle_data.catalog import CATALOG, decode_ican
from vehicle_data.ican_definitions import CONSUMER_FIELD_MAP, NOMINAL_CYCLE_MS, SIGNALS, coverage_summary


def provider(value_id, **criteria):
    return next(provider for provider in CATALOG[value_id]["providers"]
                if provider["kind"] == "ican" and all(provider.get(key) == value for key, value in criteria.items()))


def packed_frame(length=8, **signals):
    return sum(value << int(start[1:]) for start, value in signals.items()).to_bytes(length, "little")


def reading(value_id, can_id, data, **criteria):
    return decode_ican(can_id, data)[provider(value_id, can_id=can_id, **criteria)["id"]]


class ICANCatalogReferenceCoverageTests(unittest.TestCase):
    def test_every_dbc_provider_matches_source_layout_scale_and_documented_dlc(self):
        text = (Path(__file__).resolve().parents[1] / "references" / "PQ35_46_ICAN.dbc").read_text(encoding="cp1252")
        definitions = {}
        current_id = current_dlc = None
        for line in text.splitlines():
            message = re.match(r"BO_ (\d+) (\w+): (\d+)", line)
            if message:
                current_id, current_dlc = int(message[1]), int(message[3])
            signal = re.match(r' SG_ (\w+) : (\d+)\|(\d+)@([01])([+-]) \(([^,]+),([^\)]+)\)', line)
            if signal:
                definitions[current_id, signal[1]] = (int(signal[2]), int(signal[3]),
                    float(signal[6]), float(signal[7]), current_dlc, signal[4], signal[5])
        for signal in SIGNALS:
            if signal["reference"] != "PQ35_46_ICAN.dbc":
                continue
            with self.subTest(value_id=signal["value_id"], signal=signal["signal"]):
                expected = definitions[signal["can_id"], signal["signal"]]
                self.assertEqual((signal["start"], signal["length"], signal["factor"], signal["offset"], signal["frame_length"]), expected[:5])
                self.assertEqual(expected[5], "1")
                self.assertEqual(bool(signal.get("signed")), expected[6] == "-")
        for can_id, cycle in NOMINAL_CYCLE_MS.items():
            match = re.search(r'^BA_ "GenMsgCycleTime" BO_ ' + str(can_id) + r' (\d+);', text, re.M)
            self.assertIsNotNone(match)
            self.assertEqual(cycle, int(match[1]))

    def test_freshness_respects_slow_documented_frame_cycles(self):
        self.assertEqual(provider("vehicle.odometer_km")["stale_after_ms"], 3000)
        self.assertEqual(provider("climate.cabin_temperature")["stale_after_ms"], 2400)

    def test_breadth_consumer_coverage_and_global_provider_identity(self):
        summary = coverage_summary()
        json.dumps(summary, allow_nan=False)
        self.assertGreaterEqual(summary["value_ids"], 200)
        self.assertGreaterEqual(len(summary["frames"]), 20)
        for field, value_id in CONSUMER_FIELD_MAP.items():
            with self.subTest(field=field):
                self.assertIn(value_id, CATALOG)
                self.assertTrue(any(p["kind"] == "ican" for p in CATALOG[value_id]["providers"]))
        ids = [p["id"] for entry in CATALOG.values() for p in entry["providers"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(summary["excluded"])
        self.assertFalse({0x4A0, 0x0C2, 0x1A0, 0x280, 0x288, 0x4A8, 0x428}.intersection(s["can_id"] for s in SIGNALS))

    def test_full_documented_short_dlcs_and_truncation(self):
        battery = packed_frame(6, b0=142)
        self.assertAlmostEqual(reading("vehicle.battery_voltage", 0x571, battery)["value"], 12.1)
        self.assertEqual(reading("vehicle.battery_voltage", 0x571, battery[:5])["reason"], "short_frame")
        self.assertEqual(reading("vehicle.ignition_on_requested", 0x2C3, b"\x02")["value"], "Yes")
        self.assertEqual(reading("vehicle.ignition_on", 0x575, b"\x02\x00\x00\x00")["value"], "Yes")
        self.assertEqual(reading("vehicle.steering_angle", 0x3C3, b"\x01\x00\x00\x00")["reason"], "short_frame")
        self.assertEqual(reading("vehicle.yaw_rate", 0x2A1, b"\x01\x80")["reason"], "short_frame")

    def test_steering_sign_magnitude_and_sensor_initialization(self):
        angle = reading("vehicle.steering_angle", 0x3C3, packed_frame(b0=1600, b15=1))
        self.assertEqual(angle["value"], -70)
        self.assertEqual(reading("vehicle.steering_rate", 0x3C3, packed_frame(b16=1600, b31=1))["value"], -70)
        self.assertEqual(reading("vehicle.steering_angle", 0x3C3, packed_frame(b0=1600, b41=1))["reason"], "qualifier_mismatch")
        self.assertTrue(reading("vehicle.steering_angle", 0x3C3, packed_frame(b0=32767))["valid"])
        self.assertEqual(reading("vehicle.steering_sensor_state", 0x3C3, packed_frame(b41=3))["value"], "Permanent fault")

    def test_navigation_yaw_uses_opposite_sign_convention_and_error_flag(self):
        self.assertEqual(reading("vehicle.yaw_rate", 0x2A1, packed_frame(7, b0=125))["value"], -1.25)
        self.assertEqual(reading("vehicle.yaw_rate", 0x2A1, packed_frame(7, b0=125, b15=1))["value"], 1.25)
        self.assertEqual(reading("vehicle.yaw_rate", 0x2A1, packed_frame(7, b0=125, b14=1))["reason"], "invalid_flag")
        self.assertEqual(reading("vehicle.yaw_rate", 0x2A1, packed_frame(7, b0=16383))["reason"], "sentinel")

    def test_gateway_path_counter_uses_its_source_age_and_sensor_fault(self):
        self.assertEqual(reading("vehicle.front_axle_path_pulses", 0x359, packed_frame(b24=1234))["value"], 1234)
        for bit in (1, 39):
            self.assertEqual(reading("vehicle.front_axle_path_pulses", 0x359, packed_frame(**{"b24": 1234, f"b{bit}": 1}))["reason"], "invalid_flag")
        self.assertTrue(reading("vehicle.front_axle_path_pulses", 0x359, packed_frame(b24=1234, b2=1))["valid"])
        self.assertFalse(reading("vehicle.abs_active", 0x359, packed_frame(b50=1, b2=1))["valid"])

    def test_cluster_fuel_is_separate_from_engine_fan_and_counter(self):
        fuel = reading("vehicle.fuel_remaining", 0x621, packed_frame(7, b24=55))
        self.assertEqual(fuel["value"], 55)
        self.assertTrue(provider("vehicle.fuel_remaining")["estimated"])
        self.assertEqual(reading("vehicle.fuel_remaining", 0x621, packed_frame(7, b24=127))["reason"], "sentinel")
        self.assertEqual(reading("engine.cooling_fan_duty", 0x35B, packed_frame(b40=80))["value"], 32)
        self.assertFalse(any(p["kind"] == "ican" and p["can_id"] == 0x35B for p in CATALOG["vehicle.fuel_remaining"]["providers"]))

    def test_altitude_factor_and_pressure_estimate_have_separate_provider_identity(self):
        frame = packed_frame(b16=128)
        self.assertEqual(reading("engine.altitude_correction_factor.ratio", 0x555, frame)["value"], 1)
        self.assertEqual(reading("engine.atmospheric_pressure", 0x555, frame)["value"], 1013)
        self.assertFalse(any(p['kind'] == 'ican' for p in CATALOG['engine.altitude_correction_factor']['providers']))

    def test_dynamic_consumption_units_are_exclusive_and_not_guessed(self):
        lpk = "vehicle.fuel_consumption.instant.l_per_100km"
        kpl = "vehicle.fuel_consumption.instant.km_per_l"
        frame = packed_frame(7, b0=123, b12=1)
        self.assertAlmostEqual(reading(lpk, 0x629, frame)["value"], 12.3)
        self.assertEqual(reading(kpl, 0x629, frame)["reason"], "qualifier_mismatch")
        self.assertFalse(reading(lpk, 0x629, packed_frame(7, b0=123, b12=1, b13=1))["valid"])
        self.assertFalse(reading(lpk, 0x629, packed_frame(7, b0=123))["valid"])
        self.assertNotEqual(provider(lpk)["id"], provider(kpl)["id"])

    def test_range_miles_does_not_become_kilometres(self):
        frame = packed_frame(7, b16=100, b31=1)
        self.assertEqual(reading("vehicle.range_miles", 0x629, frame)["value"], 100)
        self.assertFalse(reading("vehicle.range_km", 0x629, frame)["valid"])

    def test_parking_no_obstacle_is_status_not_fake_distance_or_error(self):
        self.assertEqual(reading("parking.distance.front_left", 0x54B, packed_frame(b0=255))["value"], "No obstacle")
        self.assertEqual(reading("parking.distance.front_left", 0x54B, packed_frame(b0=100))["value"], 100)

    def test_custom_haldex_page_and_signed_encodings(self):
        frame = packed_frame(b0=0xD0, b8=1, b48=960)
        self.assertEqual(reading("awd.slip_control_torque", 0x6DA, frame)["value"], 60)
        self.assertEqual(reading("awd.active_mode", 0x6DA, frame)["value"], "Performance")
        self.assertFalse(reading("awd.measured_yaw_rate", 0x6DA, frame)["valid"])
        for tag in (0, 0xD7, 0xA0):
            self.assertFalse(reading("awd.active_mode", 0x6DA, packed_frame(b0=tag, b8=1))["valid"])
        for tag in range(0xD0, 0xD7):
            self.assertTrue(reading("awd.active_mode", 0x6DA, packed_frame(b0=tag, b8=1))["valid"])
        model = packed_frame(b0=65536 - 1787, b48=960)
        self.assertEqual(reading("awd.model_yaw_rate", 0x679, model)["value"], -100)
        self.assertEqual(reading("awd.model_yaw_raw", 0x679, model)["value"], -1787)
        self.assertEqual(reading("awd.commanded_torque", 0x679, model)["value"], 60)


if __name__ == "__main__":
    unittest.main()
