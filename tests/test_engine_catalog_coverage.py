"""Coverage audit against every meaningful field in the supplied engine PDF."""
import importlib.util
import json
from pathlib import Path
import re
import unittest

from vehicle_data.catalog import CATALOG, diagnostic_readings, get_catalog
from vehicle_data.broker import VehicleDataBroker
from vehicle_data.engine_definitions import DEFINITIONS, REFERENCE_ROWS, coverage_ledger


ROOT = Path(__file__).resolve().parents[1]


def location(entry):
    return {(provider['group'], provider['block']) for provider in entry['providers']
            if provider['kind'] == 'diag' and provider['module'] == 1 and provider['verified']}


class CompleteEngineCatalogCoverageTest(unittest.TestCase):
    def test_all_384_reference_slots_are_accounted_for(self):
        self.assertEqual(len(REFERENCE_ROWS), 384)
        self.assertEqual(len({(group, block) for group, block, _label in REFERENCE_ROWS}), 384)
        audit = coverage_ledger(CATALOG)
        self.assertEqual(audit['meaningful_count'], 328)
        self.assertEqual(audit['supported_count'], 328)
        self.assertEqual(audit['placeholder_count'], 56)
        self.assertEqual(audit['unmapped_count'], 0, [r for r in audit['fields'] if r['classification'] == 'unmapped'])
        for row in audit['fields']:
            if row['classification'] == 'placeholder':
                self.assertEqual(row['value_ids'], [], (row['group'], row['block']))
        self.assertEqual(audit['field_count'], 384)
        json.dumps(audit, allow_nan=False)

    def test_ledger_exactly_matches_pdf_transcription(self):
        if importlib.util.find_spec('pypdf') is None:
            self.skipTest('pypdf is optional outside the bundled document runtime')
        from pypdf import PdfReader
        parsed = []
        reader = PdfReader(ROOT / 'references' / 'Measuring Groups - Engine - 01.pdf')
        self.assertEqual(len(reader.pages), 13)
        for page in reader.pages:
            for line in page.extract_text().splitlines():
                match = re.match(r'^(\d+)\s+([1-4])(?:\s+(.*))?$', line)
                if match:
                    parsed.append((int(match[1]), int(match[2]), match[3] or ''))
        self.assertEqual(REFERENCE_ROWS, parsed)

    def test_every_additional_definition_is_registered_without_vacant_fields(self):
        reference = {(group, block): label for group, block, label in REFERENCE_ROWS}
        self.assertEqual(len(DEFINITIONS), 160)
        self.assertEqual(len({definition['id'] for definition in DEFINITIONS}), 160)
        new_slots = set()
        for definition in DEFINITIONS:
            self.assertIn(definition['id'], CATALOG)
            entry = CATALOG[definition['id']]
            self.assertEqual(entry['type'], definition['type'])
            self.assertEqual(entry['unit'], definition['unit'])
            for group, block in definition['locations']:
                self.assertTrue(reference[(group, block)], (definition['id'], group, block))
                self.assertIn((group, block), location(entry))
                new_slots.add((group, block))
            if definition['unit'] is None:
                self.assertEqual(definition['unit_policy'], 'reported')
                self.assertEqual(entry['unit_policy'], 'reported')
        self.assertEqual(len(new_slots), 193)

    def test_all_catalog_ids_and_provider_ids_are_unique_and_json_friendly(self):
        serialized = get_catalog()
        json.dumps(serialized, allow_nan=False)
        self.assertEqual(len({entry['id'] for entry in serialized}), len(serialized))
        providers = [provider['id'] for entry in serialized for provider in entry['providers']]
        self.assertEqual(len(providers), len(set(providers)))

    def test_complete_semantics_keep_cylinder_sensor_and_bank_distinctions(self):
        for cylinder, slot in enumerate(((15, 1), (15, 2), (15, 3), (16, 1)), 1):
            self.assertEqual(location(CATALOG[f'engine.misfire.cylinder{cylinder}.count']), {slot})
            self.assertEqual(location(CATALOG[f'engine.knock.cylinder{cylinder}.sensor_voltage']), {(26, cylinder)})
        self.assertEqual(location(CATALOG['engine.lambda.bank1.sensor1.voltage']), {(33, 2)})
        self.assertEqual(location(CATALOG['engine.lambda.bank1.sensor2.voltage']), {(36, 1), (37, 2)})
        self.assertEqual(location(CATALOG['engine.lambda.bank1.sensor1.lambda_voltage']), {(43, 3)})
        self.assertEqual(location(CATALOG['engine.camshaft.intake.bank1.specified']), {(91, 3)})
        self.assertEqual(location(CATALOG['engine.camshaft.intake.bank1.actual']), {(91, 4), (94, 2)})

    def test_partial_flags_and_diagnostic_aggregates_are_not_aliased(self):
        self.assertEqual(location(CATALOG['engine.obd.cycle_flags2.part1']), {(86, 3)})
        self.assertEqual(location(CATALOG['engine.obd.cycle_flags2']), {(88, 2)})
        self.assertEqual(location(CATALOG['engine.thermostat.integral_air_mass.actual']), {(139, 2)})
        self.assertNotIn((139, 2), location(CATALOG['engine.maf']))
        self.assertNotIn((139, 1), location(CATALOG['engine.coolant_temperature']))
        self.assertNotIn((143, 3), location(CATALOG['engine.runner_flap.bank1.position.actual']))
        self.assertEqual(location(CATALOG['engine.runner_flap.position.actual']), {(143, 3)})

    def test_reported_counter_unit_and_status_representations_are_retained(self):
        counters = diagnostic_readings(1, 85, [
            {'value': 100000, 'unit': 'km', 'type': 48},
            {'value': 123, 'unit': 'count', 'type': 54},
            {'value': 321, 'unit': '', 'type': 48},
            {'value': 20, 'unit': 'count', 'type': 54},
        ])
        self.assertTrue(counters['diag:01:85:2']['valid'])
        self.assertEqual(counters['diag:01:85:2']['value'], 123)
        self.assertEqual(counters['diag:01:85:2']['unit'], 'count')
        self.assertEqual(counters['diag:01:85:3']['unit'], '')
        for value in ('ADP OK', 0):
            alignment = diagnostic_readings(1, 60, [
                {'value': 12, 'unit': '%', 'type': 2},
                {'value': 87, 'unit': '%', 'type': 2},
                {'value': 42, 'unit': 'count', 'type': 54},
                {'value': value, 'unit': '', 'type': 17 if isinstance(value, str) else 48},
            ])
            self.assertTrue(alignment['diag:01:60:4']['valid'])
            self.assertEqual(alignment['diag:01:60:4']['value'], value)

    def test_bitfield_masks_are_preserved_as_strings(self):
        readiness = diagnostic_readings(1, 86, [
            {'value': '1010XX01', 'unit': 'bitval', 'type': 16},
            {'value': '10000000', 'unit': 'bitval', 'type': 16},
            {'value': '00000001', 'unit': 'bitval', 'type': 16},
        ])
        self.assertTrue(readiness['diag:01:86:1']['valid'])
        self.assertEqual(readiness['diag:01:86:1']['value'], '1010XX01')
        self.assertEqual(readiness['diag:01:86:1']['unit'], 'bitval')

    def test_unknown_formula_does_not_become_a_meaningful_identifier(self):
        identifiers = diagnostic_readings(1, 81, [
            {'value': '0x0123', 'unit': 'Type_254', 'type': 254},
            {'value': 'AB', 'unit': '', 'type': 17},
        ])
        self.assertFalse(identifiers['diag:01:81:1']['valid'])
        self.assertEqual(identifiers['diag:01:81:1']['reason'], 'unknown_formula')
        self.assertTrue(identifiers['diag:01:81:2']['valid'])

    def test_tentative_extra_fields_are_excluded_from_documented_coverage(self):
        audit = coverage_ledger(CATALOG)
        self.assertEqual({field['block'] for field in audit['tentative_fields']}, {5, 6, 7, 8})
        self.assertTrue(all(not field['verified'] for field in audit['tentative_fields']))
        self.assertTrue(all(row['block'] <= 4 for row in audit['fields']))
        for entry in CATALOG.values():
            for provider in entry['providers']:
                if provider.get('kind') == 'diag' and provider.get('group') == 11 and provider.get('block', 0) > 4:
                    self.assertFalse(provider['verified'])

    def test_calculated_temperatures_are_explicit_estimates_and_truncated_labels_stay_neutral(self):
        for value_id in ('engine.fuel_temperature.calculated', 'engine.exhaust_temperature.projected'):
            definition = next(definition for definition in DEFINITIONS if definition['id'] == value_id)
            self.assertTrue(definition['estimated'])
            self.assertTrue(all(provider['estimated'] for provider in CATALOG[value_id]['providers']))
        neutral = CATALOG['engine.cruise.shutoff.group67_field3']
        self.assertEqual(location(neutral), {(67, 3)})
        self.assertNotIn('irreversible', neutral['label'].lower())

    def test_new_values_participate_in_shared_group_planning(self):
        broker = VehicleDataBroker(clock=lambda: 100, wall_clock=lambda: 1000)
        interests = [f'engine.misfire.cylinder{cylinder}.count' for cylinder in range(1, 5)] + [
            'engine.lambda.bank1.sensor1.adaptation.idle',
            'engine.lambda.bank1.sensor1.adaptation.partial',
            'engine.basic_setting.requirements',
        ]
        self.assertEqual(broker.sync('expanded-screen', interests)['status'], 'ok')
        groups = {(group['module'], group['group']) for group in broker.plan()['groups']}
        self.assertEqual(groups, {(1, 1), (1, 15), (1, 16), (1, 32)})

    def test_broker_samples_preserve_reported_units_and_bitfield_strings(self):
        broker = VehicleDataBroker(clock=lambda: 100, wall_clock=lambda: 1000)
        broker.sync('status-screen', ['engine.misfire.cylinder1.count', 'engine.obd.readiness_bits'])
        broker.ingest_diagnostic({'module': 1, 'group': 15, 'timestamp': 1000, 'data': [
            {'value': 4, 'unit': 'count', 'type': 54},
            {'value': 0, 'unit': 'count', 'type': 54},
            {'value': 0, 'unit': 'count', 'type': 54},
            {'value': 'enabled', 'unit': '', 'type': 17},
        ]})
        # All three readiness providers are documented alternatives; group 100
        # is also useful when a screen requests temperature and run time.
        broker.ingest_diagnostic({'module': 1, 'group': 86, 'timestamp': 1000, 'data': [
            {'value': '10XX0001', 'unit': 'bitval', 'type': 16},
            {'value': '00000000', 'unit': 'bitval', 'type': 16},
            {'value': '00000000', 'unit': 'bitval', 'type': 16},
        ]})
        readings = {sample['id']: sample for sample in broker.snapshot(client_id='status-screen')}
        self.assertEqual(readings['engine.misfire.cylinder1.count']['unit'], 'count')
        self.assertEqual(readings['engine.misfire.cylinder1.count']['value'], 4)
        self.assertEqual(readings['engine.obd.readiness_bits']['value'], '10XX0001')
        self.assertEqual(readings['engine.obd.readiness_bits']['unit'], 'bitval')


if __name__ == '__main__':
    unittest.main()
