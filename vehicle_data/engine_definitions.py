"""Complete meaningful field coverage of the owner's engine measuring-group PDF.

These declarations supplement the original display values. Locations are
one-based fields in module 01; the first four fields are documented. A missing
unit in the reference stays unspecified via ``unit_policy='reported'`` rather
than imposing a guess. Status values preserve the ECU's numeric or text form.
The provider registry, transport, and decoder live in ``catalog.py``.
"""


DEFINITIONS = []


def _add(value_id, label, locations, *, unit=None, value_type="number", note=None, estimated=False):
    definition = {"id": value_id, "label": label, "unit": unit, "type": value_type,
                  "locations": list(locations), "module": 1,
                  "reference": "Measuring Groups - Engine - 01.pdf"}
    if unit is None:
        definition["unit_policy"] = "reported"
    if note:
        definition["note"] = note
    if estimated:
        definition["estimated"] = True
    DEFINITIONS.append(definition)


_add("engine.lambda.control.bank1", "Lambda control bank 1", [(1, 3), (107, 2)])
_add("engine.basic_setting.requirements", "Basic setting requirements", [(1, 4)], value_type="bitfield")
_add("engine.load.status", "Engine load status", [(5, 4), (54, 2)], value_type="status")
_add("engine.altitude_correction_factor", "Altitude correction factor", [(6, 4)])
_add("engine.operating_mode", "Engine operating mode (group 7)", [(7, 4)], value_type="status")
_add("engine.operating_mode.group48", "Operating mode (group 48)", [(48, 1)], value_type="status",
     note="Equivalence to group 7 operating mode is not documented; kept separate.")
_add("engine.misfire.count", "Misfire counter", [(14, 3)])
_add("engine.misfire.recognition", "Misfire recognition", [(14, 4), (15, 4), (16, 4)], value_type="status")
for _cylinder, _location in enumerate(((15, 1), (15, 2), (15, 3), (16, 1)), 1):
    _add(f"engine.misfire.cylinder{_cylinder}.count", f"Misfire counter cylinder {_cylinder}", [_location])
for _bound, _block in (("lower", 1), ("upper", 2)):
    _add(f"engine.misfire.rpm_barrier.{_bound}", f"Misfire RPM barrier ({_bound})", [(18, _block)], unit="rpm")
for _bound, _block in (("lower", 3), ("upper", 4)):
    _add(f"engine.misfire.load_barrier.{_bound}", f"Misfire load barrier ({_bound})", [(18, _block)])
for _cylinder in range(1, 5):
    _add(f"engine.knock.cylinder{_cylinder}.sensor_voltage", f"Knock sensor voltage cylinder {_cylinder}",
         [(26, _cylinder)], unit="V")
_add("engine.knock.sensor_test_result", "Knock sensor test result", [(28, 4)], value_type="status")
for _sensor in (1, 2):
    _add(f"engine.lambda.bank1.sensor{_sensor}.condition", f"Lambda sensor condition bank 1 sensor {_sensor}",
         [(30, _sensor)], value_type="bitfield",
         note="Reference identifies the sensor only; bit meanings are not supplied.")
_add("engine.lambda.bank1.actual", "Lambda control bank 1 (actual)", [(31, 1)],
     note="Keep distinct from lambda correction percentages; reported unit is authoritative.")
_add("engine.lambda.bank1.specified", "Lambda control bank 1 (specified)", [(31, 2)],
     note="Keep distinct from lambda correction percentages; reported unit is authoritative.")
_add("engine.lambda.bank1.sensor1.adaptation.idle", "Lambda adaptation bank 1 sensor 1 (idle)", [(32, 1)])
_add("engine.lambda.bank1.sensor1.adaptation.partial", "Lambda adaptation bank 1 sensor 1 (partial)", [(32, 2)])
_add("engine.lambda.bank1.sensor1.control", "Lambda control bank 1 sensor 1", [(33, 1)])
_add("engine.lambda.bank1.sensor1.voltage", "Lambda sensor voltage bank 1 sensor 1", [(33, 2)], unit="V")
_add("engine.catalyst.bank1.temperature", "Catalytic converter temperature bank 1", [(34, 2), (43, 2), (46, 2)], unit="C")
_add("engine.lambda.bank1.sensor1.dynamic_factor", "Dynamic factor bank 1 sensor 1", [(34, 3)])
_add("engine.lambda.aging_result", "Lambda aging result", [(34, 4)], value_type="status")
_add("engine.lambda.bank1.sensor2.voltage", "Lambda sensor voltage bank 1 sensor 2", [(36, 1), (37, 2)], unit="V")
_add("engine.lambda.availability_result", "Lambda availability result", [(36, 2)], value_type="status")
_add("engine.lambda.bank1.sensor2.delta", "Delta lambda bank 1 sensor 2", [(37, 3)])
_add("engine.lambda.bank1.delta_result", "Delta lambda result bank 1", [(37, 4)], value_type="status")
for _sensor, _resistance_block, _condition_block in ((1, 1, 2), (2, 3, 4)):
    _add(f"engine.lambda.bank1.sensor{_sensor}.resistance", f"Lambda sensor resistance bank 1 sensor {_sensor}",
         [(41, _resistance_block)], unit="ohm")
    _add(f"engine.lambda.bank1.sensor{_sensor}.heater_condition", f"Lambda heater condition bank 1 sensor {_sensor}",
         [(41, _condition_block)], value_type="status")
_add("engine.lambda.bank1.sensor1.lambda_voltage", "Lambda voltage bank 1 sensor 1", [(43, 3)], unit="V",
     note="Reference uses Lambda Voltage instead of Sensor Voltage; equivalence to group 33 is unconfirmed.")
_add("engine.lambda.bank1.sensor2.aging_test", "Lambda sensor aging test bank 1 sensor 2", [(43, 4)], value_type="status")
_add("engine.catalyst.bank1.conversion", "Catalytic conversion bank 1", [(46, 3)])
_add("engine.catalyst.bank1.conversion_test", "Catalytic conversion test bank 1", [(46, 4)], value_type="status")
_add("engine.rpm.specified", "Engine speed (specified)", [(50, 2), (51, 2), (52, 2), (53, 2), (56, 2), (57, 2)], unit="rpm")
_add("engine.ac.readiness", "A/C readiness", [(50, 3), (52, 3), (137, 1)], value_type="status")
_add("engine.ac.compressor", "A/C compressor", [(50, 4), (57, 3), (137, 2)], value_type="status")
_add("engine.selected_gear", "Selected gear (engine ECU)", [(51, 3), (68, 3)], value_type="status")
_add("engine.window_heater.condition", "Front/rear window heater", [(52, 4)], value_type="status")
_add("engine.idle.regulator", "Idle regulator", [(55, 2), (56, 3)])
_add("engine.idle.stabilization_adaptation", "Idle stabilization self-adaptation", [(55, 3)])
_add("engine.operating_condition", "Engine operating condition", [(55, 4), (56, 4), (61, 4)], value_type="status")
_add("engine.ac.compressor_load", "A/C compressor load", [(57, 4)])
_add("engine.throttle.sensor1.position", "Throttle valve sensor 1 (G187)", [(60, 1), (62, 1), (117, 3)],
     note="Sensor output is distinct from the generic throttle angle/position value; retain its reported unit.")
_add("engine.throttle.sensor2.position", "Throttle valve sensor 2 (G188)", [(60, 2), (62, 2)])
_add("engine.throttle.steps_count", "Throttle valve steps counter", [(60, 3)])
_add("engine.throttle.alignment_status", "Throttle body alignment status", [(60, 4)], value_type="status")
_add("engine.pedal.sensor2.position", "Accelerator pedal position sensor 2 (G185)", [(62, 4)])
_add("engine.pedal.kickdown.alignment_value", "Kick-down alignment value", [(63, 2)])
_add("engine.pedal.kickdown.switch", "Kick-down switch", [(63, 3)], value_type="status")
_add("engine.pedal.kickdown.alignment_status", "Kick-down alignment status", [(63, 4)], value_type="status")
for _sensor, _block in ((1, 1), (2, 2)):
    _add(f"engine.throttle.sensor{_sensor}.lower_adaptation", f"Throttle sensor {_sensor} lower adaptation", [(64, _block)])
for _sensor, _block in ((1, 3), (2, 4)):
    _add(f"engine.throttle.sensor{_sensor}.emergency_air_gap", f"Throttle sensor {_sensor} emergency air gap", [(64, _block)])
_add("engine.cruise.switch_positions1", "Cruise switch positions I", [(66, 2), (67, 2)], value_type="bitfield")
_add("engine.cruise.speed.specified", "Cruise vehicle speed (specified)", [(66, 3)], unit="km/h")
_add("engine.cruise.switch_positions2", "Cruise switch positions II", [(66, 4)], value_type="bitfield")
_add("engine.cruise.shutoff.reversible", "Cruise shut-off criteria (reversible)", [(67, 1)], value_type="bitfield")
_add("engine.cruise.shutoff.group67_field3", "Cruise shut-off criteria (group 67 field 3)", [(67, 3)], value_type="bitfield",
     note="Reference label is visibly truncated at Shut-Off Crit. (irre...; the expanded name and bit meanings are unconfirmed.")
_add("engine.torque_converter_clutch.condition", "Torque converter/clutch", [(68, 4)], value_type="status")
_add("engine.evap.valve.open", "EVAP emissions solenoid valve (open)", [(70, 1)])
_add("engine.evap.lambda_control", "Lambda control during EVAP test", [(70, 2)],
     note="Bank/sensor and equivalence to other lambda control values are not specified.")
_add("engine.evap.valve.flow", "EVAP emissions solenoid valve (flow)", [(70, 3)])
_add("engine.evap.valve.test", "EVAP valve test", [(70, 4)], value_type="status")
_add("engine.evap.leak.reed_contact_condition", "Leak detection reed contact condition", [(71, 1)], value_type="status")
_add("engine.evap.leak.malfunction_message", "Leak detection malfunction message", [(71, 2)], value_type="status")
_add("engine.evap.leak.test_status", "Leak test status", [(71, 3)], value_type="status")
_add("engine.evap.leak.diagnostic_test_status", "Leak diagnostic test status", [(71, 4)], value_type="status")
_add("engine.identification.advanced1", "Advanced identification I", [(80, 1)], value_type="string",
     note="Raw documented field; no multi-field identifier assembly is assumed.")
_add("engine.identification.vin", "Vehicle identification number field (VIN)", [(81, 1)], value_type="string",
     note="Raw documented field only; an ASCII pair is not a complete 17-character VIN.")
_add("engine.identification.immobilizer", "Immobilizer identification field", [(81, 2)], value_type="string",
     note="Raw documented field only; no multi-field identifier assembly is assumed.")
_add("engine.identification.advanced3", "Advanced identification III", [(82, 1)], value_type="string")
_add("engine.vehicle_mileage", "Vehicle mileage (engine ECU)", [(85, 1)], unit="km")
_add("engine.obd.iumpr_record_count", "IUMPR record counter", [(85, 2)])
_add("engine.obd.general_denominator", "OBD general denominator", [(85, 3)])
_add("engine.obd.ignition_cycle_count", "OBD ignition cycle counter", [(85, 4)])
_add("engine.obd.readiness_bits", "OBD readiness bits", [(86, 1), (87, 1), (100, 1)], value_type="bitfield")
_add("engine.obd.cycle_flags1", "OBD cycle flags I", [(86, 2), (88, 1)], value_type="bitfield")
_add("engine.obd.cycle_flags2.part1", "OBD cycle flags II (part 1)", [(86, 3)], value_type="bitfield",
     note="Partial flags must not be substituted for the complete Cycle Flags II field.")
_add("engine.obd.error_flags1", "OBD error flags I", [(87, 2)], value_type="bitfield")
_add("engine.obd.error_flags2.part1", "OBD error flags II (part 1)", [(87, 3)], value_type="bitfield")
_add("engine.obd.cycle_flags2", "OBD cycle flags II", [(88, 2)], value_type="bitfield")
_add("engine.obd.cycle_flags3", "OBD cycle flags III", [(88, 3)], value_type="bitfield")
_add("engine.obd.mil_distance", "Distance driven with MIL on", [(89, 1)], unit="km")
_add("engine.obd.tank_condition", "OBD tank condition", [(89, 2)], value_type="status")
_add("engine.camshaft.intake.bank1.adjustment", "Camshaft adjustment intake bank 1", [(91, 2)],
     note="Reference does not say angular target, actual angle, or duty; keep distinct from adjacent angle fields.")
_add("engine.camshaft.intake.bank1.specified", "Camshaft intake bank 1 adjustment (specified)", [(91, 3)], unit="deg")
_add("engine.camshaft.intake.bank1.actual", "Camshaft intake bank 1 adjustment (actual)", [(91, 4), (94, 2)], unit="deg")
_add("engine.camshaft.intake.bank1.phase_position", "Camshaft phase position intake bank 1", [(93, 3)], unit="deg")
_add("engine.camshaft.intake.bank1.test", "Camshaft adjustment test intake bank 1", [(94, 3)], value_type="status")
_add("engine.lambda.control.generic", "Lambda control (group 99)", [(99, 3)],
     note="Bank/sensor and equivalence to bank 1 control are not specified.")
_add("engine.lambda.control_status", "Lambda control status", [(99, 4)], value_type="status")
_add("engine.time_since_start", "Time since engine start", [(100, 3)], unit="s")
_add("engine.obd.status", "OBD status", [(100, 4)], value_type="status")
_add("engine.start_temperature", "Engine start temperature", [(104, 1), (138, 1)], unit="C")
for _factor in range(1, 4):
    _add(f"engine.temperature.adaptation_factor{_factor}", f"Temperature adaptation factor {_factor}", [(104, _factor + 1)])
_add("engine.fuel_temperature.calculated", "Fuel temperature (calculated)", [(106, 4)], unit="C", estimated=True)
_add("engine.lambda.control_result", "Lambda control result", [(107, 4)], value_type="status")
for _range in range(1, 5):
    _add(f"engine.adaptation.rpm_range{_range}", f"Adaptation RPM range {_range}", [(111, _range)],
         note="RPM range names the adaptation band; the adapted quantity and unit are not documented.")
_add("engine.lambda.bank1.enrichment_factor", "Enrichment factor sensor bank 1", [(112, 2)])
_add("engine.exhaust_temperature.projected", "Exhaust temperature (projected)", [(112, 3)], unit="C", estimated=True)
_add("engine.correction_factor.fuel", "Fuel correction factor", [(116, 2)])
_add("engine.correction_factor.coolant_temperature", "Coolant temperature correction factor", [(116, 3)])
_add("engine.correction_factor.intake_temperature", "Intake air temperature correction factor", [(116, 4)])
_add("engine.boost.control_adaptation", "Boost pressure control adaptation", [(119, 2)])
_add("engine.torque.asr_specified", "Engine torque specified by ASR", [(120, 2), (122, 2)], unit="Nm")
_add("engine.torque.actual", "Engine torque (actual)", [(120, 3), (122, 3)], unit="Nm")
_add("engine.traction_control.status", "Traction control status", [(120, 4)], value_type="status")
_add("engine.transmission.status", "Transmission status (engine ECU)", [(122, 4)], value_type="status")
for _name, _label, _locations in (
    ("transmission", "Transmission electronics (J217)", [(125, 1)]),
    ("brakes", "Brake electronics (J104)", [(125, 2)]),
    ("instruments", "Instrument cluster (J285)", [(125, 3), (129, 2)]),
    ("hvac", "Heating/air conditioning (J255)", [(125, 4)]),
    ("airbag", "Airbag (J234)", [(126, 3)]),
    ("steering_wheel", "Steering wheel electronics (J527)", [(127, 3)]),
    ("gateway", "CAN gateway (J533)", [(129, 3)]),
):
    _add(f"engine.module_communication.{_name}", _label + " communication", _locations, value_type="status",
         note="ECU-reported module field; reference supplies module identity but no status-code meanings.")
_add("engine.cooling.status", "Cooling status", [(132, 4)], value_type="status")
_add("engine.cooling.fan1.duty", "Cooling fan 1 activation duty", [(135, 2)])
_add("engine.cooling.auxiliary_pump", "Auxiliary water pump", [(136, 3)], value_type="status")
_add("engine.cooling.fan_after_run", "Fan after run", [(136, 4)], value_type="status")
_add("engine.ac.refrigerant_pressure", "A/C refrigerant pressure", [(137, 3)], unit="bar")
_add("engine.ac.fan_request", "Fan request from A/C system", [(137, 4)], value_type="status")
_add("engine.thermostat.mean_air_mass", "Mean engine air mass (thermostat diagnostic)", [(138, 2)],
     note="Diagnostic aggregate; not interchangeable with instantaneous MAF.")
_add("engine.thermostat.median_speed", "Median vehicle speed (thermostat diagnostic)", [(138, 3)], unit="km/h")
_add("engine.thermostat.test_result", "Thermostat test result", [(138, 4), (139, 4)], value_type="status")
_add("engine.coolant_temperature.diagnostic", "Engine coolant temperature diagnostic", [(139, 1)], unit="C",
     note="Reference does not identify G62 or equivalence to instantaneous coolant temperature.")
_add("engine.thermostat.integral_air_mass.actual", "Integral mass air flow (actual)", [(139, 2)],
     note="Diagnostic integral; not interchangeable with instantaneous MAF.")
_add("engine.thermostat.integral_air_mass.specified", "Integral mass air flow (specified)", [(139, 3)])
_add("engine.fuel_quantity_valve.closing_angle", "Quantity valve closing angle", [(140, 1)], unit="deg")
_add("engine.fuel_quantity_valve.opening_angle", "Quantity valve opening angle", [(140, 2)], unit="deg")
_add("engine.fuel_quantity_valve.status", "Quantity control valve status", [(140, 4)], value_type="status")
_add("engine.fuel_high_pressure.adaptation", "High pressure system adaptation", [(141, 1)])
_add("engine.fuel_high_pressure.controller_portion", "High pressure controller portion", [(141, 2)])
_add("engine.fuel_high_pressure.compression_volume", "Total compression volume", [(141, 3)])
_add("engine.runner_flap.bank1.position.actual", "Runner flap bank 1 position (actual)", [(142, 1)])
_add("engine.runner_flap.bank1.position.specified", "Runner flap bank 1 position (specified)", [(142, 2)])
_add("engine.runner_flap.bank1.position.offset", "Runner flap bank 1 position offset", [(142, 3)])
_add("engine.runner_flap.bank1.adaptation", "Runner flap bank 1 adaptation", [(142, 4)], value_type="status")
_add("engine.runner_flap.position.actual", "Runner flap position (actual, bank unspecified)", [(143, 3)],
     note="Bank is not stated; not automatically aliased to the bank 1 field in group 142.")
_add("engine.runner_flap.operating_mode", "Runner flap operating mode (group 143)", [(143, 4)], value_type="status")
_add("engine.status.group200.counter", "Status counter (group 200)", [(200, 1)])
for _block in (2, 3, 4):
    _add(f"engine.status.group200.field{_block}", f"Status (group 200 field {_block})", [(200, _block)], value_type="status",
         note="Reference labels this field Status without naming the underlying subsystem or code meanings.")


TENTATIVE_FIELDS = [
    {"module": 1, "group": 11, "block": 5, "label": "Ambient Air?", "verified": False},
    {"module": 1, "group": 11, "block": 6, "label": "Mass Air Flow?", "verified": False},
    {"module": 1, "group": 11, "block": 7, "label": "vehicle speed?", "verified": False},
    {"module": 1, "group": 11, "block": 8, "label": "?", "verified": False,
     "excluded_reason": "No documented semantic identity; raw observation only."},
]


def coverage_ledger(catalog):
    """Audit every original first-four field and identify deliberate exclusions."""
    mapped = {}
    for entry in catalog.values():
        for provider in entry.get("providers", []):
            if (provider.get("kind") == "diag" and provider.get("module") == 1
                    and provider.get("verified")):
                mapped.setdefault((provider["group"], provider["block"]), set()).add(entry["id"])
    ledger = []
    for group, block, label in REFERENCE_ROWS:
        ids = sorted(mapped.get((group, block), ()))
        classification = "placeholder" if not label else ("supported" if ids else "unmapped")
        ledger.append({"module": 1, "group": group, "block": block, "label": label,
                       "classification": classification, "value_ids": ids})
    return {"reference": "Measuring Groups - Engine - 01.pdf", "field_count": len(ledger),
            "meaningful_count": sum(bool(row["label"]) for row in ledger),
            "supported_count": sum(row["classification"] == "supported" for row in ledger),
            "placeholder_count": sum(row["classification"] == "placeholder" for row in ledger),
            "unmapped_count": sum(row["classification"] == "unmapped" for row in ledger),
            "fields": ledger, "tentative_fields": [dict(field) for field in TENTATIVE_FIELDS]}


# Literal transcription of all 384 first-four rows is appended below. It is
# independent of the definitions so an omitted declaration fails the audit.
REFERENCE_ROWS = [
    (1, 1, 'Engine Speed (G28)'),
    (1, 2, 'Coolant Temperature (G62)'),
    (1, 3, 'Lambda Control Bank 1'),
    (1, 4, 'Basic Setting Requirements'),
    (2, 1, 'Engine Speed (G28)'),
    (2, 2, 'Engine Load'),
    (2, 3, 'Injection Timing'),
    (2, 4, 'Mass Air Flow Sensor (G70)'),
    (3, 1, 'Engine Speed (G28)'),
    (3, 2, 'Mass Air Flow Sensor (G70)'),
    (3, 3, 'Throttle Valve Angle'),
    (3, 4, 'Ignition Timing Angle'),
    (4, 1, 'Engine Speed (G28)'),
    (4, 2, 'Battery Voltage (Terminal 30)'),
    (4, 3, 'Coolant Temperature (G62)'),
    (4, 4, 'Intake Air Temperature (G42)'),
    (5, 1, 'Engine Speed (G28)'),
    (5, 2, 'Engine Load'),
    (5, 3, 'Vehicle Speed'),
    (5, 4, 'Load Status'),
    (6, 1, 'Engine Speed (G28)'),
    (6, 2, 'Engine Load'),
    (6, 3, 'Intake Air Temperature (G42)'),
    (6, 4, 'Altitude Correction Factor'),
    (7, 1, 'Engine Speed (G28)'),
    (7, 2, 'Engine Load'),
    (7, 3, 'Coolant Temperature (G62)'),
    (7, 4, 'Operating Mode'),
    (10, 1, 'Engine Speed (G28)'),
    (10, 2, 'Engine Load'),
    (10, 3, 'Throttle Valve Angle'),
    (10, 4, 'Ignition Timing Angle'),
    (11, 1, 'Engine Speed (G28) 5 Ambient Air?'),
    (11, 2, 'Coolant Temperature (G62) 6 Mass Air Flow?'),
    (11, 3, 'Intake Air Temperature (G42) 7 vehicle speed?'),
    (11, 4, 'Ignition Timing Angle 8 ?'),
    (13, 1, 'Engine Speed (G28)'),
    (13, 2, ''),
    (13, 3, ''),
    (13, 4, ''),
    (14, 1, 'Engine Speed (G28)'),
    (14, 2, 'Engine Load'),
    (14, 3, 'Misfire Counter'),
    (14, 4, 'Misfire Recognition'),
    (15, 1, 'Misfire Counter Cylinder 1'),
    (15, 2, 'Misfire Counter Cylinder 2'),
    (15, 3, 'Misfire Counter Cylinder 3'),
    (15, 4, 'Misfire Recognition'),
    (16, 1, 'Misfire Counter Cylinder 4'),
    (16, 2, ''),
    (16, 3, ''),
    (16, 4, 'Misfire Recognition'),
    (18, 1, 'Lower RPM Barrier'),
    (18, 2, 'Upper RPM Barrier'),
    (18, 3, 'Lower Load Barrier'),
    (18, 4, 'Upper Load Barrier'),
    (20, 1, 'Timing RetardationCylinder 1'),
    (20, 2, 'Timing RetardationCylinder 2'),
    (20, 3, 'Timing RetardationCylinder 3'),
    (20, 4, 'Timing RetardationCylinder 4'),
    (22, 1, 'Engine Speed (G28)'),
    (22, 2, 'Engine Load'),
    (22, 3, 'Timing RetardationCylinder 1'),
    (22, 4, 'Timing RetardationCylinder 2'),
    (23, 1, 'Engine Speed (G28)'),
    (23, 2, 'Engine Load'),
    (23, 3, 'Timing RetardationCylinder 3'),
    (23, 4, 'Timing RetardationCylinder 4'),
    (26, 1, 'Knock Sensor Voltage Cylinder 1'),
    (26, 2, 'Knock Sensor Voltage Cylinder 2'),
    (26, 3, 'Knock Sensor Voltage Cylinder 3'),
    (26, 4, 'Knock Sensor Voltage Cylinder 4'),
    (28, 1, 'Engine Speed (G28)'),
    (28, 2, 'Engine Load'),
    (28, 3, 'Coolant Temperature (G62)'),
    (28, 4, 'Knock Sensor Test Result'),
    (30, 1, 'Bank 1 Sensor 1'),
    (30, 2, 'Bank 1 Sensor 2'),
    (30, 3, ''),
    (30, 4, ''),
    (31, 1, 'Lambda Control Bank 1 (actual)'),
    (31, 2, 'Lambda Control Bank 1 (specified)'),
    (31, 3, ''),
    (31, 4, ''),
    (32, 1, 'Adaptation (Idle)Bank 1 Sensor 1'),
    (32, 2, 'Adaptation (Partial)Bank 1 Sensor 1'),
    (32, 3, ''),
    (32, 4, ''),
    (33, 1, 'Lambda Control Bank 1 Sensor 1'),
    (33, 2, 'Sensor Voltage Bank 1 Sensor 1'),
    (33, 3, ''),
    (33, 4, ''),
    (34, 1, 'Engine Speed (G28)'),
    (34, 2, 'Catalytic ConverterBank 1 Temp.'),
    (34, 3, 'Dynamic Factor Bank 1 Sensor 1'),
    (34, 4, 'Result Lambda Aging'),
    (36, 1, 'Sensor Voltage Bank 1 Sensor 2'),
    (36, 2, 'Result Lambda Availability'),
    (36, 3, ''),
    (36, 4, ''),
    (37, 1, 'Engine Load'),
    (37, 2, 'Sensor Voltage Bank 1 Sensor 2'),
    (37, 3, 'Delta Lambda Bank 1 Sensor 2'),
    (37, 4, 'Result Delta Lambda B1'),
    (41, 1, 'Resistance Bank 1 Sensor 1'),
    (41, 2, 'Heater Condition'),
    (41, 3, 'Resistance Bank 1 Sensor 2'),
    (41, 4, 'Heater Condition'),
    (43, 1, 'Engine Speed (G28)'),
    (43, 2, 'Catalytic ConverterBank 1 Temp.'),
    (43, 3, 'Lambda Voltage Bank 1 Sensor 1'),
    (43, 4, 'Lambda Sensor Aging Test B1S2'),
    (46, 1, 'Engine Speed (G28)'),
    (46, 2, 'Catalytic ConverterBank 1 Temp.'),
    (46, 3, 'Catalytic Conversion Bank 1'),
    (46, 4, 'Cat. Conversion Test Bank 1'),
    (48, 1, 'Operating Mode'),
    (48, 2, ''),
    (48, 3, ''),
    (48, 4, ''),
    (50, 1, 'Engine Speed (actual)'),
    (50, 2, 'Engine Speed (specified)'),
    (50, 3, 'A/C Readiness'),
    (50, 4, 'A/C Compressor'),
    (51, 1, 'Engine Speed (actual)'),
    (51, 2, 'Engine Speed (specified)'),
    (51, 3, 'Selected Gear'),
    (51, 4, 'Battery Voltage (Terminal 30)'),
    (52, 1, 'Engine Speed (actual)'),
    (52, 2, 'Engine Speed (specified)'),
    (52, 3, 'A/C Readiness'),
    (52, 4, 'Front/Rear Window Heater'),
    (53, 1, 'Engine Speed (actual)'),
    (53, 2, 'Engine Speed (specified)'),
    (53, 3, 'Battery Voltage (Terminal 30)'),
    (53, 4, 'Generator Load'),
    (54, 1, 'Engine Speed (G28)'),
    (54, 2, 'Load Status'),
    (54, 3, 'Accel. Pedal Pos.Sensor 1 (G79)'),
    (54, 4, 'Throttle Valve Angle'),
    (55, 1, 'Engine Speed (G28)'),
    (55, 2, 'Idle Regulator'),
    (55, 3, 'Idle Stabilization Self-Adaptation'),
    (55, 4, 'Operating Condition'),
    (56, 1, 'Engine Speed (actual)'),
    (56, 2, 'Engine Speed (specified)'),
    (56, 3, 'Idle Regulator'),
    (56, 4, 'Operating Condition'),
    (57, 1, 'Engine Speed (actual)'),
    (57, 2, 'Engine Speed (specified)'),
    (57, 3, 'A/C Compressor'),
    (57, 4, 'A/C CompressorLoad'),
    (60, 1, 'Throttle Valve Sensor 1 (G187)'),
    (60, 2, 'Throttle Valve Sensor 2 (G188)'),
    (60, 3, 'Throttle Valve Steps Counter'),
    (60, 4, 'Throttle Body Alignment Status'),
    (61, 1, 'Engine Speed (G28)'),
    (61, 2, 'Battery Voltage (Terminal 30)'),
    (61, 3, 'Throttle Valve Angle'),
    (61, 4, 'Operating Condition'),
    (62, 1, 'Throttle Valve Sensor 1 (G187)'),
    (62, 2, 'Throttle Valve Sensor 2 (G188)'),
    (62, 3, 'Accel. Pedal Pos.Sensor 1 (G79)'),
    (62, 4, 'Accel. Pedal Pos.Sensor 2 (G185)'),
    (63, 1, 'Accel. Pedal Pos.Sensor 1 (G79)'),
    (63, 2, 'Kick-Down Alignment Value'),
    (63, 3, 'Kick-Down Switch'),
    (63, 4, 'Kick-Down Alignment Status'),
    (64, 1, 'Lower AdaptationSensor 1 (G187)'),
    (64, 2, 'Lower AdaptationSensor 2 (G188)'),
    (64, 3, 'Emergency Air GapSensor 1 (G187)'),
    (64, 4, 'Emergency Air GapSensor 2 (G188)'),
    (66, 1, 'Vehicle Speed (current)'),
    (66, 2, 'Switch Positions I'),
    (66, 3, 'Vehicle Speed (specified)'),
    (66, 4, 'Switch Positions II'),
    (67, 1, 'Cruise Control Shut-Off Crit. (rev.)'),
    (67, 2, 'Switch Positions I'),
    (67, 3, 'Cruise Control Shut-Off Crit. (irre...'),
    (67, 4, ''),
    (68, 1, 'Engine Speed (G28)'),
    (68, 2, 'Engine Load'),
    (68, 3, 'Selected Gear'),
    (68, 4, 'Torque Converter/Clutch'),
    (70, 1, 'Evap. EmissionsSol. Valve (Open)'),
    (70, 2, 'Lambda Control'),
    (70, 3, 'Evap. EmissionsSol. Valve (Flow)'),
    (70, 4, 'EVAP Valve Test'),
    (71, 1, 'Reed Contact Condition'),
    (71, 2, 'Malfunction Message'),
    (71, 3, 'Test Status'),
    (71, 4, 'Leak Diagnostic Test Status'),
    (80, 1, 'Advanced Identification I'),
    (80, 2, ''),
    (80, 3, ''),
    (80, 4, ''),
    (81, 1, 'Vehicle Ident. Number (VIN)'),
    (81, 2, 'Immobilizer Ident. (IMMO-ID)'),
    (81, 3, ''),
    (81, 4, ''),
    (82, 1, 'Advanced Identification III'),
    (82, 2, ''),
    (82, 3, ''),
    (82, 4, ''),
    (85, 1, 'Vehicle Mileage'),
    (85, 2, 'IUMPR Record Counter'),
    (85, 3, 'General Denominator'),
    (85, 4, 'Ignition Cycle Counter'),
    (86, 1, 'Readiness Bits'),
    (86, 2, 'Cycle Flags I'),
    (86, 3, 'Cycle Flags II (Part 1)'),
    (86, 4, ''),
    (87, 1, 'Readiness Bits'),
    (87, 2, 'Error Flags I'),
    (87, 3, 'Error Flags II (Part 1)'),
    (87, 4, ''),
    (88, 1, 'Cycle Flags I'),
    (88, 2, 'Cycle Flags II'),
    (88, 3, 'Cycle Flags III'),
    (88, 4, ''),
    (89, 1, 'Distance Driven with MIL on'),
    (89, 2, 'Tank Condition'),
    (89, 3, ''),
    (89, 4, ''),
    (91, 1, 'Engine Speed (G28)'),
    (91, 2, 'Cam. AdjustmentIntake Bank 1'),
    (91, 3, 'Cam. AdjustmentIntake B1 (spec.)'),
    (91, 4, 'Cam. AdjustmentIntake B1 (act.)'),
    (93, 1, 'Engine Speed (G28)'),
    (93, 2, 'Engine Load'),
    (93, 3, 'Phase Position Bank 1 Intake'),
    (93, 4, ''),
    (94, 1, 'Engine Speed (G28)'),
    (94, 2, 'Cam. AdjustmentIntake B1 (act.)'),
    (94, 3, 'Cam. Adj. Test Bank 1 Intake'),
    (94, 4, ''),
    (99, 1, 'Engine Speed (G28)'),
    (99, 2, 'Coolant Temperature (G62)'),
    (99, 3, 'Lambda Control'),
    (99, 4, 'Lambda Control Status'),
    (100, 1, 'Readiness Bits'),
    (100, 2, 'Coolant Temperature (G62)'),
    (100, 3, 'Time since Engine Start'),
    (100, 4, 'OBD-Status'),
    (101, 1, 'Engine Speed (G28)'),
    (101, 2, 'Engine Load'),
    (101, 3, 'Injection Timing'),
    (101, 4, 'Mass Air Flow Sensor (G70)'),
    (102, 1, 'Engine Speed (G28)'),
    (102, 2, 'Coolant Temperature (G62)'),
    (102, 3, 'Intake Air Temperature (G42)'),
    (102, 4, 'Injection Timing'),
    (104, 1, 'Engine Start Temperature'),
    (104, 2, 'Temperature Adaptation Factor 1'),
    (104, 3, 'Temperature Adaptation Factor 2'),
    (104, 4, 'Temperature Adaptation Factor 3'),
    (106, 1, 'Fuel Rail Pressure (spec.)'),
    (106, 2, 'Fuel Rail Pressure (actual)'),
    (106, 3, 'Fuel Pump Duty Cycle'),
    (106, 4, 'Fuel Temperature(calculated)'),
    (107, 1, 'Engine Speed (G28)'),
    (107, 2, 'Lambda Control Bank 1'),
    (107, 3, ''),
    (107, 4, 'Result Lambda Control'),
    (110, 1, 'Engine Speed (G28)'),
    (110, 2, 'Coolant Temperature (G62)'),
    (110, 3, 'Injection Timing'),
    (110, 4, 'Throttle Valve Angle'),
    (111, 1, 'Adaptation RPM Range 1'),
    (111, 2, 'Adaptation RPM Range 2'),
    (111, 3, 'Adaptation RPM Range 3'),
    (111, 4, 'Adaptation RPM Range 4'),
    (112, 1, ''),
    (112, 2, 'Enrichment FactorSensor Bank 1'),
    (112, 3, 'Exhaust Temp. Projection'),
    (112, 4, ''),
    (113, 1, 'Engine Speed (G28)'),
    (113, 2, 'Engine Load'),
    (113, 3, 'Throttle Valve Angle'),
    (113, 4, 'Athmospheric Pressure'),
    (114, 1, 'Engine Load (specified)'),
    (114, 2, 'Engine Load (spec. corrected)'),
    (114, 3, 'Engine Load (actual Value)'),
    (114, 4, 'Boost Pressure Control (N75)'),
    (115, 1, 'Engine Speed (G28)'),
    (115, 2, 'Engine Load'),
    (115, 3, 'Boost Pressure (specified)'),
    (115, 4, 'Boost Pressure (actual)'),
    (116, 1, 'Engine Speed (G28)'),
    (116, 2, 'Correction FactorFuel'),
    (116, 3, 'Correction FactorCoolant Temp.'),
    (116, 4, 'Intake Air Temp.Correction Factor'),
    (117, 1, 'Engine Speed (G28)'),
    (117, 2, 'Accel. Pedal Pos.Sensor 1 (G79)'),
    (117, 3, 'Throttle Valve Sensor 1 (G187)'),
    (117, 4, 'Boost Pressure (specified)'),
    (118, 1, 'Engine Speed (G28)'),
    (118, 2, 'Intake Air Temperature (G42)'),
    (118, 3, 'Boost Pressure Control (N75)'),
    (118, 4, 'Boost Pressure (actual)'),
    (119, 1, 'Engine Speed (G28)'),
    (119, 2, 'Boost Pressure Control Adapt.'),
    (119, 3, 'Boost Pressure Control (N75)'),
    (119, 4, 'Boost Pressure (actual)'),
    (120, 1, 'Engine Speed (G28)'),
    (120, 2, 'Torque specifiedby ASR'),
    (120, 3, 'Engine Torque (actual)'),
    (120, 4, 'Traction Control Status'),
    (122, 1, 'Engine Speed (G28)'),
    (122, 2, 'Torque specifiedby ASR'),
    (122, 3, 'Engine Torque (actual)'),
    (122, 4, 'Transmission Status'),
    (125, 1, 'Transmission Electronics (J217)'),
    (125, 2, 'Brake Electronics(J104)'),
    (125, 3, 'Instrument Cluster(J285)'),
    (125, 4, 'Heating/Air Condition (J255)'),
    (126, 1, ''),
    (126, 2, ''),
    (126, 3, 'Airbag (J234)'),
    (126, 4, ''),
    (127, 1, ''),
    (127, 2, ''),
    (127, 3, 'Steering Wheel Electronics (J527)'),
    (127, 4, ''),
    (129, 1, ''),
    (129, 2, 'Instrument Cluster(J285)'),
    (129, 3, 'CAN-Gateway (J533)'),
    (129, 4, ''),
    (130, 1, 'Engine Outlet Temperature'),
    (130, 2, 'Radiator Outlet Temperature'),
    (130, 3, ''),
    (130, 4, ''),
    (131, 1, 'Coolant Temperature (G62)'),
    (131, 2, ''),
    (131, 3, 'Radiator Outlet Temperature'),
    (131, 4, ''),
    (132, 1, ''),
    (132, 2, ''),
    (132, 3, ''),
    (132, 4, 'Cooling Status'),
    (134, 1, 'Oil Temperature'),
    (134, 2, 'Ambient Temperature'),
    (134, 3, 'Intake Air Temperature (G42)'),
    (134, 4, 'Engine Outlet Temperature'),
    (135, 1, 'Radiator Outlet Temperature'),
    (135, 2, 'Fan 1 Activation Duty Cycle'),
    (135, 3, ''),
    (135, 4, ''),
    (136, 1, ''),
    (136, 2, ''),
    (136, 3, 'Auxiliary Water Pump'),
    (136, 4, 'Fan After Run'),
    (137, 1, 'A/C Readiness'),
    (137, 2, 'A/C Compressor'),
    (137, 3, 'A/C Refrigerant Pressure'),
    (137, 4, 'Fan Request from A/C-System'),
    (138, 1, 'Engine Start Temperature'),
    (138, 2, 'Mean Engine Air Mass'),
    (138, 3, 'Median Vehicle Speed'),
    (138, 4, 'Thermostat Test Result'),
    (139, 1, 'Engine Coolant Temperature Diag.'),
    (139, 2, 'Actual Integral Mass Air Flow'),
    (139, 3, 'Specified IntegralMass Air Flow'),
    (139, 4, 'Thermostat Test Result'),
    (140, 1, 'Quantity Valve closing Angle'),
    (140, 2, 'Quantity Valve opening Angle'),
    (140, 3, 'Fuel Rail Pressure (actual)'),
    (140, 4, 'Quantity Control Valve Status'),
    (141, 1, 'High Pressure System Adaptation'),
    (141, 2, 'Controller Portion'),
    (141, 3, 'Total CompressionVolume'),
    (141, 4, 'Fuel Rail Pressure (actual)'),
    (142, 1, 'Runner Flap B1 Position (act.)'),
    (142, 2, 'Runner Flap B1 Position (spec.)'),
    (142, 3, 'Runner Flap B1 Position Offset'),
    (142, 4, 'Runner Flap B1 Adaptation'),
    (143, 1, 'Engine Speed (G28)'),
    (143, 2, 'Engine Load'),
    (143, 3, 'Runner Flap Position (act.)'),
    (143, 4, 'Operating Mode'),
    (200, 1, 'Status Counter'),
    (200, 2, 'Status'),
    (200, 3, 'Status'),
    (200, 4, 'Status'),
]

