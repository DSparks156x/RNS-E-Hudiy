"""Documented quantities already displayed by DataView outside the engine page.

Locations are one-based measuring-block fields. The AWD reference is headed
"22", while this project's established TP2 destination is 0x0A. Their address
relationship has not been established here. Preserve the working destination;
do not reinterpret the PDF filename as a transport address. Status encodings are supplied by
the ECU because the references name these fields without defining their enums.
"""

DEFINITIONS = []


def _add(value_id, label, unit, module, locations, *, value_type='number', **metadata):
    definition = {'id': value_id, 'label': label, 'unit': unit, 'type': value_type,
                  'module': module, 'locations': locations, 'verified': True,
                  'reference': ('Measuring Groups - Transmission - 02.pdf' if module == 2
                                else 'Measuring Groups - AWD - 22.pdf')}
    if module == 0x0A:
        definition['note'] = ('Reference filename ends in 22; provider preserves the existing '
                              'DataView TP2 destination 0x0A. The address relationship is unconfirmed.')
    if unit is None:
        definition['unit_policy'] = 'reported'
    definition.update(metadata)
    DEFINITIONS.append(definition)


for clutch, group in ((1, 11), (2, 12)):
    prefix = f'transmission.clutch{clutch}'
    _add(prefix + '.shaft_speed', f'Driveshaft {clutch} speed (G{501 if clutch == 1 else 502})',
         'rpm', 2, [(group, 1), (8, clutch + 1)])
    _add(prefix + '.specified_torque', f'Specified clutch torque K{clutch}', 'Nm', 2, [(group, 2)])
    _add(prefix + '.valve_current', f'Clutch valve {clutch} current', 'A', 2,
         [(group, 3), (5 + clutch, 2), (12 + clutch, 1)])
    _add(prefix + '.actual_pressure', f'Actual clutch {clutch} pressure (G{193 if clutch == 1 else 194})',
         'bar', 2, [(group, 4)])

for block, gears in enumerate(('1_3', '2_4', '5_n', '6_r'), 1):
    _add(f'transmission.selector.{gears}.travel_distance',
         f'Gear selector {gears.replace("_", "-").upper()} travel distance', 'mm', 2, [(16, block)])

for block, value_id, label in ((1, 'fluid_temperature', 'Transmission fluid temperature'),
                              (2, 'module_temperature', 'Transmission control module temperature'),
                              (3, 'clutch_oil_temperature', 'Clutch oil temperature (G509)')):
    _add('transmission.' + value_id, label, 'C', 2, [(19, block)])
_add('transmission.idle_status', 'Transmission idle status', None, 2, [(19, 4)], value_type='status')

_add('awd.oil_temperature', 'Haldex oil temperature', 'C', 0x0A, [(1, 1)])
_add('awd.plate_temperature', 'Haldex plate temperature', 'C', 0x0A, [(1, 2)])
_add('awd.supply_voltage', 'Haldex terminal 30 voltage', 'V', 0x0A, [(1, 3)])
_add('awd.oil_pressure', 'Haldex oil pressure', 'bar', 0x0A, [(3, 1)])
_add('awd.estimated_torque', 'Haldex estimated torque', 'Nm', 0x0A, [(3, 2)], estimated=True)
_add('awd.valve.opening', 'Haldex clutch valve N273 opening', '%', 0x0A, [(3, 3)])
_add('awd.valve.current', 'Haldex clutch valve N273 current', 'mA', 0x0A, [(3, 4)])
for block, value_id, label in ((1, 'can_output_signals', 'Haldex CAN output signals'),
                              (2, 'vehicle_mode', 'Haldex vehicle mode'),
                              (3, 'slip_control', 'Haldex slip control'),
                              (4, 'operating_mode_fault', 'Haldex operating mode malfunction')):
    _add('awd.' + value_id, label, None, 0x0A, [(5, block)], value_type='status')
