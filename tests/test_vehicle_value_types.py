"""Keep documented statuses and ECU-reported dimensions intact end to end."""
import unittest

from vehicle_data.catalog import decode_ican, diagnostic_readings
from vehicle_data.broker import VehicleDataBroker


def registry(kind='status', unit=None, **provider_options):
    return {'test.value': {'id': 'test.value', 'label': 'Test', 'type': kind,
        'unit': unit, 'unit_policy': 'reported' if unit is None else 'canonical',
        'providers': [{'id': 'test:field', 'kind': 'diag', 'module': 1, 'group': 1,
                       'block': 1, 'verified': True, **provider_options}]}}


class TypedValueTests(unittest.TestCase):
    def test_status_preserves_text_and_numeric_codes(self):
        for value, formula in [('WARM', 10), (3, 48), ('AB', 17)]:
            decoded = diagnostic_readings(1, 1, [{'value': value, 'unit': '', 'type': formula}], registry())
            self.assertEqual(decoded['test:field'], {'value': value, 'valid': True, 'reason': None, 'unit': ''})

    def test_bitfield_preserves_masked_bits(self):
        for value in ['10XX0011', 3, 0]:
            result = diagnostic_readings(1, 1, [{'value': value, 'unit': 'bitval', 'type': 16}], registry('bitfield'))
            self.assertTrue(result['test:field']['valid'])
            self.assertEqual(result['test:field']['value'], value)
        for value in ['unknown', -1, 1.5]:
            result = diagnostic_readings(1, 1, [{'value': value, 'unit': 'bitval'}], registry('bitfield'))
            self.assertFalse(result['test:field']['valid'])

    def test_unknown_formula_never_becomes_a_status(self):
        result = diagnostic_readings(1, 1, [{'value': '0x1234', 'unit': 'Type_254', 'type': 254}], registry())
        self.assertEqual(result['test:field']['reason'], 'unknown_formula')

    def test_reported_units_survive_broker_publication_and_failure(self):
        broker = VehicleDataBroker(catalog=registry('number'), clock=lambda: 100, wall_clock=lambda: 1000)
        broker.sync('display', ['test.value'])
        broker.ingest_diagnostic({'module': 1, 'group': 1, 'data': [{'value': 4.25, 'unit': 'Nm', 'type': 52}]})
        sample = broker.tick()[0]
        self.assertEqual((sample['value'], sample['unit'], sample['type'], sample['status']), (4.25, 'Nm', 'number', 'ok'))
        broker.ingest_observation({'module': 1, 'group': 1, 'error': 'timeout'})
        self.assertEqual(broker.tick()[0]['unit'], 'Nm')

    def test_current_conversion_is_dimensional(self):
        result = diagnostic_readings(1, 1, [{'value': .42, 'unit': 'A', 'type': 24}], registry('number', 'mA'))
        self.assertEqual(result['test:field']['value'], 420)
        result = diagnostic_readings(1, 1, [{'value': '0.42', 'unit': 'A', 'type': 17}], registry('status', 'mA'))
        self.assertEqual(result['test:field']['reason'], 'unit_mismatch')

    def test_can_sign_qualifier_and_enum(self):
        definition = {'test.value': {'id': 'test.value', 'providers': [{'id': 'test:can', 'kind': 'ican',
            'can_id': 1, 'start': 0, 'length': 7, 'frame_length': 1, 'factor': .5,
            'sign_bit': 7, 'sign_negative_when': 1, 'valid_when': [{'start': 8, 'length': 1, 'raw': 1}]}]}}
        self.assertEqual(decode_ican(1, bytes([0x84, 1]), definition)['test:can']['value'], -2)
        self.assertEqual(decode_ican(1, bytes([4, 0]), definition)['test:can']['reason'], 'qualifier_mismatch')
        self.assertEqual(decode_ican(1, bytes([4]), definition)['test:can']['reason'], 'short_frame')
        p = definition['test.value']['providers'][0]
        p.update(choices={'4': 'Park'})
        self.assertEqual(decode_ican(1, bytes([4, 1]), definition)['test:can']['value'], 'Park')

    def test_twos_complement_is_not_sign_magnitude(self):
        definition = {'test.value': {'id': 'test.value', 'providers': [{'id': 'test:can', 'kind': 'ican',
            'can_id': 1, 'start': 0, 'length': 8, 'frame_length': 1, 'signed': True, 'factor': .25}]}}
        self.assertEqual(decode_ican(1, bytes([252]), definition)['test:can']['value'], -1)

    def test_passive_alternative_retains_its_declared_unit(self):
        definition = registry('number')
        definition['test.value']['providers'] = [{'id': 'test:can', 'kind': 'ican', 'can_id': 1,
            'start': 0, 'length': 8, 'frame_length': 1, 'unit': '', 'verified': True}]
        broker = VehicleDataBroker(catalog=definition, clock=lambda: 100, wall_clock=lambda: 1000)
        broker.sync('display', ['test.value'])
        broker.ingest_can(1, bytes([1]))
        self.assertEqual(broker.tick()[0]['unit'], '')


if __name__ == '__main__':
    unittest.main()
