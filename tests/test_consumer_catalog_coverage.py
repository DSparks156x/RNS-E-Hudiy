"""Keep the existing transmission/AWD displays bound to documented quantities."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vehicle_data.broker import VehicleDataBroker
from vehicle_data.catalog import CATALOG, diagnostic_readings
from vehicle_data.consumer_definitions import DEFINITIONS


# The groups/ONE-BASED fields used by the pre-migration DataView displays.
# Specified clutch torque and estimated Haldex torque are intentionally distinct
# from actual torque. Gear-selector pairs preserve the original bar orientation.
DISPLAY_BINDINGS = {
    'transmission.clutch1.shaft_speed': (2, 11, 1, 'rpm'),
    'transmission.clutch1.specified_torque': (2, 11, 2, 'Nm'),
    'transmission.clutch1.valve_current': (2, 11, 3, 'A'),
    'transmission.clutch1.actual_pressure': (2, 11, 4, 'bar'),
    'transmission.clutch2.shaft_speed': (2, 12, 1, 'rpm'),
    'transmission.clutch2.specified_torque': (2, 12, 2, 'Nm'),
    'transmission.clutch2.valve_current': (2, 12, 3, 'A'),
    'transmission.clutch2.actual_pressure': (2, 12, 4, 'bar'),
    'transmission.selector.1_3.travel_distance': (2, 16, 1, 'mm'),
    'transmission.selector.2_4.travel_distance': (2, 16, 2, 'mm'),
    'transmission.selector.5_n.travel_distance': (2, 16, 3, 'mm'),
    'transmission.selector.6_r.travel_distance': (2, 16, 4, 'mm'),
    'transmission.fluid_temperature': (2, 19, 1, 'C'),
    'transmission.module_temperature': (2, 19, 2, 'C'),
    'transmission.clutch_oil_temperature': (2, 19, 3, 'C'),
    'transmission.idle_status': (2, 19, 4, None),
    'awd.oil_temperature': (10, 1, 1, 'C'),
    'awd.plate_temperature': (10, 1, 2, 'C'),
    'awd.supply_voltage': (10, 1, 3, 'V'),
    'awd.oil_pressure': (10, 3, 1, 'bar'),
    'awd.estimated_torque': (10, 3, 2, 'Nm'),
    'awd.valve.opening': (10, 3, 3, '%'),
    'awd.valve.current': (10, 3, 4, 'mA'),
    'awd.can_output_signals': (10, 5, 1, None),
    'awd.vehicle_mode': (10, 5, 2, None),
    'awd.slip_control': (10, 5, 3, None),
    'awd.operating_mode_fault': (10, 5, 4, None),
}


def field(value, unit, formula=None):
    return {'value': value, 'unit': unit, **({'type': formula} if formula is not None else {})}


class ConsumerCatalogCoverageTests(unittest.TestCase):
    def test_every_display_field_has_the_original_module_block_binding(self):
        self.assertEqual({d['id'] for d in DEFINITIONS}, set(DISPLAY_BINDINGS))
        for value_id, (module, group, block, unit) in DISPLAY_BINDINGS.items():
            with self.subTest(value_id=value_id):
                self.assertIn(value_id, CATALOG)
                entry = CATALOG[value_id]
                self.assertEqual(entry['unit'], unit)
                providers = [p for p in entry['providers'] if p['kind'] == 'diag'
                             and (p['module'], p['group'], p['block']) == (module, group, block)]
                self.assertEqual(len(providers), 1)
                self.assertTrue(providers[0]['verified'])

    def test_awd_transport_destination_is_preserved_and_reference_mismatch_documented(self):
        for definition in DEFINITIONS:
            if definition['id'].startswith('awd.'):
                self.assertEqual(definition['module'], 0x0A)
                self.assertIn('22', definition['note'])
                self.assertIn('0x0A', definition['note'])

    def test_existing_display_values_require_only_shared_original_groups(self):
        broker = VehicleDataBroker(clock=lambda: 100, wall_clock=lambda: 1000)
        values = [value_id if value_id != 'awd.estimated_torque' else
                  {'id': value_id, 'allow_estimated': True} for value_id in DISPLAY_BINDINGS]
        self.assertEqual(broker.sync('pages', values)['status'], 'ok')
        self.assertEqual(broker.plan()['groups'], [
            {'module': 2, 'group': group, 'period_ms': 500} for group in (11, 12, 16, 19)
        ] + [{'module': 10, 'group': group, 'period_ms': 500} for group in (1, 3, 5)])

    def test_four_selector_travel_values_preserve_signs_and_distinct_bindings(self):
        broker = VehicleDataBroker(clock=lambda: 100, wall_clock=lambda: 1000)
        ids = [f'transmission.selector.{pair}.travel_distance' for pair in ('1_3', '2_4', '5_n', '6_r')]
        broker.sync('selectors', ids)
        broker.ingest_diagnostic({'module': 2, 'group': 16,
                                  'data': [field(value, 'mm') for value in (-7.5, -2, 4.5, 0)]})
        samples = broker.snapshot(client_id='selectors')
        self.assertEqual([sample['value'] for sample in samples], [-7.5, -2, 4.5, 0])
        self.assertEqual([sample['source']['block'] for sample in samples], [1, 2, 3, 4])
        component = (ROOT / 'hudiy_dataview/src/components/SelectorBars.tsx').read_text(encoding='utf-8')
        self.assertIn('index={valueIds ? 0 : i}', component)
        self.assertIn('valueId={valueIds?.[i]}', component)

    def test_textual_and_bit_looking_status_values_are_not_numerically_coerced(self):
        broker = VehicleDataBroker(clock=lambda: 100, wall_clock=lambda: 1000)
        ids = ['transmission.idle_status', 'awd.can_output_signals', 'awd.vehicle_mode',
               'awd.slip_control', 'awd.operating_mode_fault']
        broker.sync('statuses', ids)
        broker.ingest_diagnostic({'module': 2, 'group': 19,
                                  'data': [field(90, 'C')] * 3 + [field('00100100', 'bitval', 16)]})
        broker.ingest_diagnostic({'module': 10, 'group': 5, 'data': [
            field('00000001', 'bitval', 16), field('Offroad', '', 17),
            field('Regulating', '', 17), field('00000000', 'bitval', 16)]})
        samples = {sample['id']: sample for sample in broker.snapshot(client_id='statuses')}
        expected = ['00100100', '00000001', 'Offroad', 'Regulating', '00000000']
        self.assertEqual([samples[value_id]['value'] for value_id in ids], expected)
        self.assertTrue(all(samples[value_id]['status'] == 'ok' for value_id in ids))
        self.assertEqual(samples['awd.can_output_signals']['unit'], 'bitval')
        self.assertEqual(samples['awd.vehicle_mode']['unit'], '')

    def test_current_pressure_torque_and_speed_units_are_converted_without_changing_meaning(self):
        values = diagnostic_readings(2, 11, [field(1200, '/min'), field(15000, 'cNm'),
                                             field(750, 'mA'), field(6500, 'mbar')])
        self.assertEqual(values['diag:02:11:1']['value'], 1200)
        self.assertEqual(values['diag:02:11:2']['value'], 150)
        self.assertEqual(values['diag:02:11:3']['value'], .75)
        self.assertEqual(values['diag:02:11:4']['value'], 6.5)
        haldex = diagnostic_readings(10, 3, [field(30, 'bar'), field(300, 'Nm'),
                                            field(50, '%'), field(.8, 'A')])
        self.assertEqual(haldex['diag:0A:3:4']['value'], 800)

    def test_estimated_torque_requires_explicit_opt_in_and_is_not_actual_or_commanded(self):
        broker = VehicleDataBroker(clock=lambda: 100, wall_clock=lambda: 1000)
        broker.sync('normal', ['awd.estimated_torque'])
        broker.sync('existing_display', [{'id': 'awd.estimated_torque', 'allow_estimated': True}])
        broker.ingest_diagnostic({'module': 10, 'group': 3,
                                  'data': [field(30, 'bar'), field(300, 'Nm'), field(50, '%'), field(.8, 'A')]})
        self.assertEqual(broker.snapshot(client_id='normal')[0]['status'], 'unavailable')
        sample = broker.snapshot(client_id='existing_display')[0]
        self.assertEqual(sample['value'], 300)
        self.assertTrue(sample['quality']['estimated'])
        self.assertEqual(sample['source']['block'], 2)
        json.dumps(sample, allow_nan=False)

    def test_named_frontend_fields_cover_original_widgets_and_keep_raw_groups_for_mock_only(self):
        for prefix, filename in (('transmission.', 'TransmissionTab.tsx'), ('awd.', 'AWDTab.tsx')):
            source = (ROOT / 'hudiy_dataview/src/tabs' / filename).read_text(encoding='utf-8')
            displayed_ids = set(re.findall(r"['\"]((?:transmission|awd)\.[a-zA-Z0-9._]+)['\"]", source))
            expected = {value_id for value_id in DISPLAY_BINDINGS if value_id.startswith(prefix)}
            self.assertTrue(expected <= displayed_ids, expected - displayed_ids)
            self.assertNotIn('groupKey=', source)
        hook = (ROOT / 'hudiy_dataview/src/hooks/useSocket.ts').read_text(encoding='utf-8')
        self.assertIn('mockRef.current ? TAB_CONFIG[tab] || [] : []', hook)
        # Live/mock/tab/reconnect subscription behavior is exercised directly in
        # hudiy_dataview/tests/socket_subscriptions.test.cjs, without matching
        # the internal spelling of the values emitted by the hook.
        self.assertIn("{ id: 'awd.estimated_torque', allow_estimated: true }", hook)
        mock = (ROOT / 'hudiy_dataview/src/store/mockValues.ts').read_text(encoding='utf-8')
        for value_id in DISPLAY_BINDINGS:
            self.assertIn(value_id, mock)


if __name__ == '__main__':
    unittest.main()
