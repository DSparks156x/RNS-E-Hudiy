import csv
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hudiy_dataview.data_logger import (  # noqa: E402
    DataLogger,
    HALDEX_PROFILE,
    HALDEX_STATE_ID,
    ICAN_BRAKES_TRANSMISSION_ID,
    ICAN_ENGINE_AUX_ID,
    ICAN_ENGINE_ID,
    ICAN_GATEWAY_SPEED_ID,
    ICAN_NAVIGATION_YAW_ID,
    ICAN_STEERING_ID,
    _decode_haldex_state,
    _decode_haldex_yaw,
)


class DataLoggerTests(unittest.TestCase):
    def test_haldex_profile_uses_new_state_id_and_decodes_it(self):
        self.assertEqual(HALDEX_STATE_ID, 0x6DA)
        self.assertIn('raw_0x6da', HALDEX_PROFILE.columns)
        self.assertNotIn('raw_0x6dd', HALDEX_PROFILE.columns)

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'haldex.csv'
            recorder = DataLogger({'data_logger': {
                'log_directory': temporary,
                'profiles': {'haldex': {'measuring_groups': [
                    {'module': '0x01', 'groups': [7]},
                ]}},
            }})
            recorder.start_recording(output_path=str(output))
            recorder.ingest_diagnostic({
                'module': 0x01, 'group': 7,
                'data': [{'value': 20.1, 'unit': 'km/h'}, {'value': 20.2, 'unit': 'km/h'}],
            }, timestamp=999.5)
            brake_bits = (
                (12345 << 9) | (1 << 8) | (321 << 24) | (1 << 35) |
                (48 << 40) | (1 << 47) | (1 << 50) | (1 << 58) | (4 << 60)
            )
            recorder.ingest_can(ICAN_BRAKES_TRANSMISSION_ID,
                                brake_bits.to_bytes(8, 'little'), timestamp=999.6)
            recorder.ingest_can(ICAN_GATEWAY_SPEED_ID,
                                (4321 << 9).to_bytes(3, 'little'), timestamp=999.7)
            engine_aux = bytearray(8)
            engine_aux[4] = 75  # 1.5 bar according to the ICAN DBC.
            engine_aux[7] = 150  # 90 C oil.
            recorder.ingest_can(ICAN_ENGINE_AUX_ID, bytes(engine_aux), timestamp=999.8)
            # Page 0: A72=16, A74=32, A7C=48; mode=Performance, token valid.
            recorder.ingest_can(0x6DA, bytes.fromhex('d041100020003000'), timestamp=1000.25)
            recorder.add_marker('DRIVER: Test')
            status = recorder.stop_recording()

            self.assertFalse(status['recording'])
            self.assertEqual(status['rows_written'], 2)
            with output.open(newline='', encoding='utf-8') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]['can_id'], '0x6DA')
            self.assertEqual(rows[0]['raw_0x6da'], 'd041100020003000')
            self.assertEqual(rows[0]['haldex_page'], '0')
            self.assertEqual(rows[0]['haldex_mode_name'], 'Performance')
            self.assertEqual(rows[0]['a7c_slip_torque_nm'], '3.0')
            self.assertEqual(rows[0]['m01_g7_i1'], '20.2')
            self.assertEqual(rows[0]['vehicle_speed_kmh'], '123.45')
            self.assertEqual(rows[0]['gateway_vehicle_speed_kmh'], '43.21')
            self.assertEqual(rows[0]['front_axle_path_pulses'], '321')
            self.assertEqual(rows[0]['path_pulses_per_revolution'], '48')
            self.assertEqual(rows[0]['abs_active'], '1')
            self.assertEqual(rows[0]['esp_active'], '1')
            self.assertEqual(rows[0]['selector_position'], '4')
            self.assertEqual(rows[0]['boost_pressure_mbar'], '1500.0')
            self.assertEqual(rows[0]['engine_oil_temp_c'], '90.0')
            self.assertEqual(rows[1]['event_marker'], 'DRIVER: Test')
            self.assertEqual(rows[1]['source'], 'marker')

    def test_haldex_mux_decodes_wheels_acceleration_and_protection_pages(self):
        page1 = _decode_haldex_state(bytes.fromhex('d1c2ffff0200fdff'))
        self.assertEqual(page1['haldex_mode'], 2)
        self.assertEqual(page1['haldex_token_ok'], 1)
        self.assertEqual(page1['haldex_abs_braking'], 1)
        self.assertEqual(page1['c9e_demanded_accel_raw'], -1)
        self.assertEqual(page1['c9c_actual_accel_raw'], 2)
        self.assertEqual(page1['haldex_measured_yaw_raw'], -3)
        self.assertAlmostEqual(page1['haldex_measured_yaw_deg_s'], -3 / 17.87,
                               places=3)
        self.assertNotIn('ca2_total_accel_raw', page1)

        page2 = _decode_haldex_state(bytes.fromhex('d241f6ff34120b00'))
        self.assertEqual(page2['b26_lateral_feedforward_raw'], -10)
        self.assertEqual(page2['bc4_curvature_raw'], 0x1234)
        self.assertEqual(page2['bb6_computed_axle_slip_raw'], 11)

        page3 = _decode_haldex_state(bytes.fromhex('d341881390139813'))
        self.assertEqual(page3['wheel_vl_kmh'], 50.0)
        self.assertEqual(page3['wheel_vr_kmh'], 50.08)
        self.assertEqual(page3['wheel_hl_kmh'], 50.16)

        page4 = _decode_haldex_state(bytes.fromhex('d441a01385ff347f'))
        self.assertEqual(page4['wheel_hr_kmh'], 50.24)
        self.assertEqual(page4['lat_accel_measured_raw'], -123)
        self.assertEqual(page4['haldex_throttle_raw'], 0x34)
        self.assertEqual(page4['haldex_bls_raw'], 0x7F)

        page5 = _decode_haldex_state(bytes.fromhex('d54196000c00f9ff'))
        self.assertEqual(page5['hold_a7e_timer'], 150)
        self.assertEqual(page5['c10_liftoff_hold_raw'], 12)
        self.assertEqual(page5['cd4_axle_ratio_adaptation_raw'], -7)

        page6 = _decode_haldex_state(bytes.fromhex('d641010002000300'))
        self.assertEqual(page6['c3a_slip_energy_raw'], 1)
        self.assertEqual(page6['c26_energy_ceiling_raw'], 2)
        self.assertEqual(page6['afe_fault_ceiling_raw'], 3)

        self.assertEqual(_decode_haldex_state(bytes.fromhex('0041100020003000')), {})

    def test_current_679_is_model_yaw_not_b1a(self):
        decoded = _decode_haldex_yaw(bytes.fromhex('12008806370b371b'))
        self.assertEqual(decoded['model_yaw_raw'], 18)
        self.assertAlmostEqual(decoded['model_yaw_deg_s'], 18 / 17.87, places=3)
        self.assertNotIn('yaw_model_or_b1a', decoded)

    def test_haldex_profile_only_decodes_relevant_ican_ids(self):
        old_acan_ids = {0x4A0, 0x0C2, 0x1A0, 0x280, 0x288, 0x4A8, 0x428}
        self.assertTrue(old_acan_ids.isdisjoint(HALDEX_PROFILE.can_ids))
        self.assertTrue({
            ICAN_BRAKES_TRANSMISSION_ID, ICAN_ENGINE_ID,
            ICAN_GATEWAY_SPEED_ID, ICAN_STEERING_ID, ICAN_NAVIGATION_YAW_ID,
        }.issubset(HALDEX_PROFILE.can_ids))

    def test_default_haldex_profile_has_no_measuring_groups(self):
        self.assertEqual(HALDEX_PROFILE.measuring_groups, ())

    def test_measuring_groups_are_configurable_across_modules(self):
        recorder = DataLogger({'data_logger': {'profiles': {'haldex': {
            'measuring_groups': [
                {'module': '0x01', 'groups': [7, 8]},
                {'module': 10, 'groups': [3], 'low_priority_groups': [5]},
            ],
        }}}})
        groups = recorder.get_status()['measuring_groups']
        self.assertEqual(groups, [
            {'module': 1, 'group': 7, 'priority': 'normal'},
            {'module': 1, 'group': 8, 'priority': 'normal'},
            {'module': 10, 'group': 3, 'priority': 'normal'},
            {'module': 10, 'group': 5, 'priority': 'low'},
        ])

    def test_raw_can_profile_records_arbitrary_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'raw.csv'
            recorder = DataLogger({'data_logger': {'log_directory': temporary}})
            recorder.start_recording(profile_name='raw_can', output_path=str(output))
            recorder.ingest_can(0x123, b'\x01\x02\x03', timestamp=10, topic='CAN_123')
            status = recorder.stop_recording()

            self.assertEqual(status['profile'], 'raw_can')
            with output.open(newline='', encoding='utf-8') as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row['can_id'], '0x123')
            self.assertEqual(row['dlc'], '3')
            self.assertEqual(row['data_hex'], '010203')

    def test_unknown_profile_is_rejected(self):
        recorder = DataLogger()
        with self.assertRaisesRegex(ValueError, 'Unknown logger profile'):
            recorder.start_recording(profile_name='missing')


if __name__ == '__main__':
    unittest.main()
