/** Adapt simulated group messages only; production widgets consume the value API. */
import { DiagnosticMessage, VehicleValue } from '../types';

const FIELDS: Record<string, Array<string | null>> = {
    '0:0': ['engine.oil_temperature', 'ambient.filtered_temperature', 'engine.coolant_temperature', 'engine.intake_temperature'],
    '1:3': ['engine.rpm', 'engine.maf', null, 'engine.ignition_timing'],
    '1:20': [1, 2, 3, 4].map(c => `engine.timing_retard.cylinder${c}`),
    '1:106': ['engine.fuel_rail.spec', 'engine.fuel_rail.actual', 'engine.fuel_pump_duty'],
    '1:115': ['engine.rpm', null, 'engine.boost.spec_absolute', 'engine.boost.actual_absolute'],
    '1:102': ['engine.rpm', 'engine.coolant_temperature', 'engine.intake_temperature', 'engine.injection_time'],
    '2:11': ['transmission.clutch1.shaft_speed', 'transmission.clutch1.specified_torque',
        'transmission.clutch1.valve_current', 'transmission.clutch1.actual_pressure'],
    '2:12': ['transmission.clutch2.shaft_speed', 'transmission.clutch2.specified_torque',
        'transmission.clutch2.valve_current', 'transmission.clutch2.actual_pressure'],
    '2:16': ['transmission.selector.1_3.travel_distance', 'transmission.selector.2_4.travel_distance',
        'transmission.selector.5_n.travel_distance', 'transmission.selector.6_r.travel_distance'],
    '2:19': ['transmission.fluid_temperature', 'transmission.module_temperature',
        'transmission.clutch_oil_temperature', 'transmission.idle_status'],
    '10:1': ['awd.oil_temperature', 'awd.plate_temperature', 'awd.supply_voltage'],
    '10:3': ['awd.oil_pressure', 'awd.estimated_torque', 'awd.valve.opening', 'awd.valve.current'],
    '10:5': ['awd.can_output_signals', 'awd.vehicle_mode', 'awd.slip_control', 'awd.operating_mode_fault'],
};

export function mockValues(msg: DiagnosticMessage): VehicleValue[] {
    const result: VehicleValue[] = [];
    (FIELDS[`${msg.module}:${msg.group}`] || []).forEach((id, index) => {
        const field = msg.data[index];
        if (!id || !field) return;
        result.push({ version: 1, id, value: field.value, unit: field.unit, status: 'ok',
            timestamp: Date.now() / 1000, age_ms: 0, max_age_ms: 5000, sample_sequence: 0,
            source: { id: 'mock', kind: 'diag' },
            quality: { valid: true, fresh: true, verified: false,
                estimated: id === 'awd.estimated_torque', reason: 'simulated data' } });
    });
    return result;
}
