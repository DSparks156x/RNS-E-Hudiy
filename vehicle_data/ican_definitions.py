"""Useful passive vehicle signals, separate from infotainment control packets.

Static definitions are grounded in PQ35_46_ICAN.dbc and the current custom
Haldex firmware contract. Importing this file needs neither a DBC parser nor
CAN hardware. DBC-documented does not guarantee that a particular vehicle
broadcasts the signal: absent/invalid frames remain unavailable in the broker.

Counters remain counters; selector position remains separate from actual gear;
sign/multiplex/unit qualifiers are explicit. Raw ACAN-only IDs, security bytes,
network-management packets and arbitrary protocol payloads are excluded.
"""


SIGNALS = []

# DBC GenMsgCycleTime, milliseconds. Trip frames are 1 Hz and climate2 is
# 1.25 Hz: a universal 1 s TTL would spuriously expire them between messages.
NOMINAL_CYCLE_MS = {
    0x2A1: 250, 0x2C3: 100, 0x351: 100, 0x359: 100, 0x35B: 100, 0x3C3: 100,
    0x3E1: 100, 0x3E3: 800, 0x470: 50, 0x527: 200, 0x529: 1000, 0x52B: 1000,
    0x545: 500, 0x555: 100, 0x571: 500, 0x575: 200, 0x58C: 100, 0x5B5: 200,
    0x5E1: 200, 0x621: 100, 0x629: 1000, 0x62B: 1000, 0x62D: 1000, 0x658: 100,
}


def _add(value_id, label, unit, can_id, signal, start, length, factor=1, offset=0,
         *, frame_length=8, type="number", invalid_raw=(), invalid_bits=(),
         verified=True, estimated=False, stale_after_ms=None, **extra):
    cycle = NOMINAL_CYCLE_MS.get(can_id)
    if stale_after_ms is None:
        stale_after_ms = max(1000, (cycle or 0) * 3)
    SIGNALS.append(dict(value_id=value_id, label=label, unit=unit, type=type,
        can_id=can_id, signal=signal, start=start, length=length, factor=factor,
        offset=offset, frame_length=frame_length, invalid_raw=list(invalid_raw),
        invalid_bits=list(invalid_bits), verified=verified, estimated=estimated,
        stale_after_ms=stale_after_ms, nominal_cycle_ms=cycle,
        reference="PQ35_46_ICAN.dbc", **extra))


def _flags(can_id, frame_length, rows, invalid_bits=()):
    for value_id, label, signal, bit in rows:
        _add(value_id, label, "", can_id, signal, bit, 1, frame_length=frame_length,
             type="status", invalid_bits=invalid_bits, choices={0: "No", 1: "Yes"})


# Engine gateway: the high-byte consumption channel is NOT litres remaining or
# an instantaneous flow rate; its exact counter depends on liquid/gas fuel.
_add("vehicle.speed", "Vehicle speed", "km/h", 0x359, "GWB_FzgGeschw", 9, 15, .01,
     invalid_raw=(32708, 32725, 32742, 32767), invalid_bits=(0,), valid_raw_max=32639)
_add("engine.cooling_fan_duty", "Engine cooling fan command", "%", 0x35B, "GWM_KLuefter", 40, 8, .4,
     invalid_raw=(255,), invalid_bits=(2,), valid_raw_max=250)
_add("engine.fuel_biodiesel_content", "Fuel RME content", "%", 0x35B, "GWM_RME_Gehalt", 5, 3, 12.5,
     invalid_raw=(7,), note="DBC says not currently supplied; meaningful only on supporting diesel ECUs.")
_add("engine.fuel_consumption_counter_high", "Fuel consumption counter (high byte)", "count", 0x35B,
     "GWM_KVerbrauch", 56, 7, 256, invalid_bits=(2,),
     note="High byte only, liquid-fuel counter or gas mass counter; no litres/hour conversion is implied.")
_add("engine.cruise_control_state", "Cruise control state", "", 0x35B, "GWM_GRA_Status", 54, 2,
     type="string", invalid_bits=(2,), choices={0: "Off or not installed", 1: "Active", 2: "Driver override", 3: "Not permitted or fault"})
_flags(0x35B, 8, [
    ("engine.brake_light_switch", "Engine brake light switch", "GWM_Bremslicht_Schalter", 32),
    ("engine.brake_test_switch", "Engine brake test switch", "GWM_Bremstest_Schalter", 33),
    ("engine.clutch_switch", "Clutch switch", "GWM_Kuppl_Schalter", 35),
], invalid_bits=(3,))
_flags(0x35B, 8, [
    ("engine.overheat_warning", "Engine overheat prewarning", "GWM_Heissl_Vorwarn", 36),
    ("engine.ac_cutoff_requested", "Engine requests AC cutoff", "GWM_Klimaabschaltung", 37),
    ("engine.mapped_cooling_available", "Mapped cooling installed and fault free", "GWM_Kennfeldkuehlung", 38),
    ("engine.ac_power_reduction_requested", "Engine requests AC power reduction", "GWM_Komp_Leist_red", 39),
    ("engine.starter_permitted", "Starter permitted", "GWM_Anl_Freigabe", 48),
    ("engine.starter_disengage_requested", "Starter disengagement requested", "GWM_Anl_Ausspuren", 49),
    ("engine.start_interlock", "Engine start interlock", "GWM_Interlock", 50),
    ("engine.preglow_active", "Preglow active", "GWM_Vorgluehen", 53),
    ("engine.fuel_counter_has_overflowed", "Fuel counter has overflowed", "GWM_Ueberl_KV", 63),
], invalid_bits=(2,))

_add("engine.rpm_change_20ms", "Engine speed change over 20 ms", "rpm", 0x555, "MO7_Gradient_Drehz", 24, 7,
     sign_bit=31, sign_negative_when=1, invalid_raw=(127,),
     note="Difference n(t)-n(t-20 ms); raw 127 is saturated, not an exact RPM/s value.")
_add("engine.altitude_correction_factor.ratio", "Engine altitude correction factor (ICAN ratio)", "", 0x555,
     "MO7_Hoeheninfo", 16, 8, 1 / 128, invalid_raw=(255,), provider_suffix="factor",
     note="DBC factor 1 corresponds to atmospheric pressure 1013 mbar; this is not altitude in metres. "
          "Equivalence to the diagnostic group 6 correction representation is unconfirmed.")
_add("engine.generator_load_response_time", "Generator load response time", "s", 0x555,
     "MO7_GenLoadResp", 40, 2, 3)
_add("engine.generator_load_shed_stage", "Generator load shedding stage", "", 0x555,
     "MO7_Last_abwurf", 48, 2, type="string",
     choices={0: "No reduction", 1: "13.3 V", 2: "12.6 V", 3: "11.8 V emergency"})
_add("engine.glow_plug_duty", "Glow plug heating duty", "%", 0x555, "MO7_Stat_Gluehk", 52, 4, 8,
     invalid_raw=(15,))
_flags(0x555, 8, [
    ("engine.raised_idle_speed_reached", "Raised idle target reached for load management", "MO7_LL_Status", 0),
    ("engine.speed_limiter_present", "Speed limitation available", "MO7_V_Begrenz", 1),
    ("engine.speed_limiter_active", "Speed limitation active", "MO7_V_Begr_akt", 2),
    ("engine.fault_memory_present", "Engine fault memory indication", "MO7_FehlerSp", 3),
    ("engine.oil_temperature_invalid", "Oil temperature unavailable or faulty", "MO7_Fehler_Oel_Temp", 4),
    ("engine.additional_cooling_requested", "Additional cooling requested", "MO7_Zus_Kuehl", 45),
    ("engine.generator_enabled", "Generator enabled", "MO7_Ein_Generator", 50),
    ("engine.high_power_heaters_permitted", "High power heaters permitted", "MO7_Lastabwurf_Heiz", 51),
])
_add("engine.manifold_vacuum", "Manifold vacuum below ambient", "mbar", 0x58C,
     "M10_rel_Saugrohrdruck", 16, 6, 18, invalid_raw=(63,),
     note="Positive vacuum magnitude; zero means manifold pressure at or above ambient. Overpressure is not output.")
_add("engine.start_stop_state", "Start-stop coordinator state", "", 0x58C, "M10_Status_StSt", 8, 2,
     type="string", choices={0: "Unavailable this ignition cycle", 1: "No coordinator permission",
                             2: "All permissions present", 3: "At least one permission missing"})
_add("engine.recuperation_request", "Engine recuperation recommendation", "", 0x58C,
     "M10_Freigabe_Reku", 14, 2, type="string",
     choices={0: "Off", 1: "Raise voltage", 2: "Lower voltage", 3: "Recuperation active"})
_flags(0x58C, 8, [
    ("engine.start_stop_stopped", "Engine stopped by start-stop", "M10_MotorStopp", 10),
    ("engine.start_stop_restarting", "Engine restarting by start-stop", "M10_Wiederstart", 11),
    ("engine.overrun_fuel_cutoff", "Overrun fuel cutoff active", "M10_Schubabschaltung", 12),
    ("engine.manifold_vacuum_measured", "Vacuum determined entirely from measurements", "M10_Druck_err_gem", 13),
    ("vehicle.drive_ready", "Vehicle ready to drive", "M10_Fahrbereitschaft", 22),
    ("vehicle.hybrid_present", "Hybrid powertrain present", "M10_Hybrid", 23),
    ("vehicle.electric_motor_active", "Electric motor active", "M10_EM_aktiv", 24),
    ("vehicle.combustion_motor_active", "Combustion motor active", "M10_VM_aktiv", 25),
])

# Chassis: selector position is a selector/program state, never actual gear.
_add("transmission.selector_position", "Transmission selector position", "", 0x359,
     "GWB_Info_Waehlhebel", 60, 4, type="string", invalid_bits=(3,), invalid_raw=(15,),
     choices={0: "Between positions", 1: "1", 2: "2", 3: "3", 4: "4", 5: "D", 6: "N", 7: "R",
              8: "P / key release", 9: "Manual sport", 10: "Z1", 11: "Z2", 12: "S", 13: "L", 14: "Manual gate"},
     note="Automated manuals may use a driving-program interpretation.")
_add("vehicle.front_axle_path_pulses", "Average front axle path pulse counter", "count", 0x359,
     "GWB_Wegimpulse", 24, 11, invalid_bits=(1, 39),
     note="Rolling counter; uses surviving front sensor if one fails. Not distance without circumference/pulses-per-turn.")
_add("vehicle.path_pulses_per_revolution", "Path pulses per wheel revolution", "count", 0x359,
     "GWB_Impulszahl", 40, 6, invalid_bits=(1,))
_flags(0x359, 8, [
    ("vehicle.front_axle_pulse_counter_has_overflowed", "Front axle pulse counter has overflowed", "GWB_Wegimpuls_Status", 35),
    ("vehicle.front_axle_pulse_sensor_fault", "Front axle path pulse fault", "GWB_Wegimpulse_Fehler", 39),
], invalid_bits=(1,))
_flags(0x359, 8, [("vehicle.speed_from_abs", "Vehicle speed sourced from ABS", "GWB_FzgGeschw_Quelle", 8)], invalid_bits=(0,))
_flags(0x359, 8, [
    ("vehicle.brake_light_requested", "Parking assist requests brake light", "PLS_Bremsleuchte", 47),
], invalid_bits=(46,))
_flags(0x359, 8, [
    ("vehicle.trailer_stabilization_active", "Trailer stabilization active", "GWB_TSP_aktiv", 48),
    ("vehicle.emergency_braking_active", "Emergency braking active", "GWB_Notbremsung", 49),
], invalid_bits=(6,))
_flags(0x359, 8, [("vehicle.abs_active", "ABS intervention active", "GWB_ABS_Bremsung", 50)], invalid_bits=(2,))
_flags(0x359, 8, [
    ("vehicle.parking_brake_closed", "Electronic parking brake closed", "GWB_EPB_Status", 51),
    ("vehicle.parking_brake_brake_light", "Electronic parking brake brake light", "GWB_EPB_Bremslicht", 52),
], invalid_bits=(5,))
_flags(0x359, 8, [
    ("vehicle.rough_road_detected", "Rough road detected", "GWB_Schlechtweg", 53),
    ("vehicle.rough_road_sensor_fault", "Rough road sensor fault", "GWB_Schlechtweg_Fehler", 54),
    ("vehicle.substitute_speed_active", "Substitute speed active", "GWB_Geschw_Ersatz", 55),
    ("vehicle.esp_active", "ESP intervention active", "GWB_ESP_Eingriff", 58),
], invalid_bits=(2,))
_flags(0x359, 8, [
    ("transmission.shift_in_progress", "Gear shift in progress", "GWB_Schaltvorgang", 56),
], invalid_bits=(3,))
_flags(0x359, 8, [("transmission.shift_lock", "Selector shift lock", "GWB_Shift_Lock", 59)], invalid_bits=(4,))
_flags(0x351, 8, [("vehicle.reverse_light_gateway", "Gateway reverse light", "GW1_Rueckfahrlicht", 1)])
_add("vehicle.tyre_circumference", "Mean tyre circumference", "mm", 0x527, "GWK_Umfang_Reifen", 28, 12,
     invalid_bits=(0,), valid_when=[{"start": 4, "length": 1, "raw": 1}],
     note="Requires the received-circumference qualifier; not the gateway speed source flag.")
_flags(0x527, 8, [
    ("vehicle.speed_from_abs", "Vehicle speed sourced from ABS", "GWK_FzgGeschw_Quelle", 8),
], invalid_bits=(2,))
_flags(0x527, 8, [("ambient.temperature_sensor_fault", "Ambient temperature sensor fault", "GWK_AussenTemp_Fehler", 56)], invalid_bits=(2,))
_add("vehicle.steering_angle", "Steering wheel angle", "deg", 0x3C3, "LW1_Lenkradwinkel", 0, 15, .04375,
     sign_bit=15, sign_negative_when=1, valid_when=[{"start": 41, "length": 2, "raw": 0}],
     note="Magnitude plus separate sign bit. 0x7FFF is the end stop, not an invalid sentinel.")
_add("vehicle.steering_rate", "Steering wheel angular speed", "deg/s", 0x3C3, "LW1_Geschwindigkeit", 16, 15, .04375,
     sign_bit=31, sign_negative_when=1, valid_when=[{"start": 41, "length": 2, "raw": 0}])
_add("vehicle.steering_sensor_state", "Steering angle sensor state", "", 0x3C3, "LW1_Int_Status", 41, 2,
     type="string", choices={0: "OK", 1: "Not initialized", 2: "Intermittent fault", 3: "Permanent fault"})
_add("vehicle.yaw_rate", "Measured navigation yaw rate", "deg/s", 0x2A1, "NV1_Gierrate", 0, 14, .01,
     frame_length=7, invalid_raw=(16383,), invalid_bits=(14,), sign_bit=15, sign_negative_when=0,
     note="Navigation forwards measured yaw; sign bit 0 means negative, opposite steering's sign convention.")
_flags(0x2A1, 7, [("vehicle.yaw_sensor_fault", "Navigation yaw sensor fault", "NV1_Fehler_Gierrate", 14)])

for wheel, signal_suffix, pulse_start, qualifier, direction_start in (
        ("front_left", "VL", 16, 12, 60), ("front_right", "VR", 26, 13, 61),
        ("rear_left", "HL", 36, 14, 62), ("rear_right", "HR", 46, 15, 63)):
    _add(f"vehicle.wheel.{wheel}.path_pulses", f"{wheel.replace('_', ' ').title()} wheel pulse counter", "count",
         0x5B5, f"B10_Wegimp_{signal_suffix}", pulse_start, 10,
         invalid_raw=(1021, 1022, 1023), invalid_bits=(qualifier,), valid_raw_max=1000,
         note="Rolling pulse counter, not wheel speed. Counter increases during reverse travel too.")
    _add(f"vehicle.wheel.{wheel}.direction", f"{wheel.replace('_', ' ').title()} wheel direction", "",
         0x5B5, f"B10_Fahrtr_{signal_suffix}", direction_start, 1, type="string",
         invalid_bits=(direction_start - 4,), choices={0: "Forward", 1: "Reverse"})

# Battery/body/ignition. DBC messages have different DLCs: do not demand 8 bytes
# from the six-byte BSG2 or four-byte BSG3 frames.
_add("vehicle.battery_voltage", "Battery voltage (body controller)", "V", 0x571, "BS2_U_BATT", 0, 8, .05, 5,
     frame_length=6, invalid_raw=(255,))
_add("vehicle.starter_battery_voltage", "Starter battery voltage", "V", 0x571, "BS2_U_Start_BATT", 16, 8, .05, 5,
     frame_length=6, invalid_raw=(255,))
_flags(0x571, 6, [
    ("vehicle.electrical_load_management_active", "Electrical load management active", "BS2_Lastman_aktiv", 24),
    ("vehicle.consumer_shedding_requested", "Electrical consumer shedding requested", "BS2_Verbr_ab_aktiv", 25),
    ("vehicle.emergency_start_active", "Emergency start active", "BS2_Notstart", 26),
    ("vehicle.infotainment_shutdown_warning", "Infotainment shutdown warning", "BS2_Warn_Infotainment", 41),
    ("vehicle.second_battery_present", "Second battery installed", "BS2_VB_2_Battarie", 45),
])
_add("vehicle.battery_state_of_charge", "Battery state of charge (10% steps)", "%", 0x658,
     "BEM_Ladezustand", 24, 4, 10, invalid_raw=(14, 15), valid_raw_max=10)
_add("vehicle.battery_sensor_voltage", "Battery data module voltage", "V", 0x658,
     "BEM_UBDM", 40, 8, .05, 5, invalid_bits=(38,), valid_raw_max=254)
_add("vehicle.generator_target_voltage", "Generator target voltage", "V", 0x658,
     "BEM_UGenSoll", 48, 6, .1, 10.6, invalid_raw=(63,), invalid_bits=(38,))
_add("vehicle.generator_duty_lin", "Generator duty (LIN reported)", "%", 0x658,
     "BEM_DFM", 32, 5, 3.225, .025, invalid_bits=(38,),
     note="Separate from engine ECU generator duty; measured over generator LIN.")
_add("vehicle.battery_warning", "Battery management warning", "", 0x658, "BEM_Batteriediagnose", 28, 3,
     type="string", choices={0: "None", 1: "Start-stop not permitted", 2: "Battery disconnected", 3: "Weak battery"})
_add("vehicle.generator_warning", "Generator management warning", "", 0x658, "BEM_Generatordiagnose", 16, 2,
     type="string", choices={0: "None", 1: "Charging indicator", 2: "Generator fault"})
_add("vehicle.energy_shutdown_stage", "Energy management shutdown stage", "", 0x658, "BEM_02_Abschaltstufen", 0, 3,
     type="string", choices={0: "No restriction", 1: "Stage 1", 2: "Stage 2", 3: "Stage 3"})
_flags(0x658, 8, [
    ("vehicle.battery_disconnected", "Battery disconnected", "BEM_Batt_Ab", 39),
    ("vehicle.energy_lin_invalid", "Energy LIN signals invalid", "BEM_EMLIN_ungueltig", 38),
    ("vehicle.recuperation_permitted", "Recuperation permitted", "BEM_REK_aktiv", 37),
])
_add("vehicle.battery_resting_voltage", "Battery resting voltage", "V", 0x470,
     "BSK_Ruhespannung", 56, 5, .1, 10.5, invalid_raw=(0, 31),
     note="Quiescent/rest voltage, distinct from instantaneous battery voltage.")
_flags(0x575, 4, [
    ("vehicle.key_inserted", "Ignition key inserted (S contact)", "BS3_Klemme_S", 0),
    ("vehicle.ignition_on", "Ignition terminal 15 active", "BS3_Klemme_15", 1),
    ("vehicle.accessory_terminal_active", "Terminal X active", "BS3_Klemme_X", 2),
    ("vehicle.starter_terminal_active", "Starter terminal 50 active", "BS3_Klemme_50", 3),
    ("vehicle.park_terminal_active", "Park light terminal P active", "BS3_Klemme_P", 4),
    ("vehicle.charging_warning", "Battery charging warning", "BS3_Ladekontrollampe", 7),
    ("vehicle.hood_contact", "Hood contact active", "BS3_Haubenkontakt", 15),
    ("vehicle.starter_permitted_body", "Body controller starter permission", "BS3_Starterlaubnis", 31),
])
_flags(0x2C3, 1, [
    ("vehicle.key_inserted_requested", "Ignition switch S contact", "ZS1_ZAS_Kl_S", 0),
    ("vehicle.ignition_on_requested", "Ignition switch terminal 15 requested", "ZS1_ZAS_Kl_15", 1),
    ("vehicle.accessory_terminal_requested", "Ignition switch terminal X requested", "ZS1_ZAS_Kl_X", 2),
    ("vehicle.starter_terminal_requested", "Ignition switch terminal 50 requested", "ZS1_ZAS_Kl_50", 3),
])

# Fuel amount belongs to Kombi K1, not cooling-fan byte 5 in GWMotor.
_add("vehicle.fuel_remaining", "Fuel remaining (cluster estimate)", "L", 0x621, "KO1_Tankinhalt", 24, 7,
     frame_length=7, invalid_raw=(127,), estimated=True,
     note="Bottom 2 or 2.5 litres cannot be resolved; with ignition off the cluster sends the last ignition-on reading.")
_add("vehicle.parked_duration", "Parked duration", "s", 0x621, "KO1_Standzeit", 8, 15, 4,
     frame_length=7, invalid_bits=(23,),
     note="Starts at ignition off, saturates near 36 h; not engine running duration.")
_add("vehicle.ambient_light_level", "Cluster ambient light sensor level", "", 0x621, "KO1_Lichtsensor", 48, 8,
     frame_length=7, invalid_raw=(254, 255),
     note="DBC sensor level; no lux conversion documented.")
_flags(0x621, 7, [
    ("vehicle.refueling_detected", "Cluster detected refueling", "KO1_Tankstop", 0),
    ("vehicle.low_fuel_warning", "Low fuel warning lamp", "KO1_Tankwarnlampe", 1),
    ("vehicle.washer_fluid_warning", "Washer fluid warning", "KO1_WaschWasser", 2),
    ("vehicle.driver_door_open_cluster", "Driver door open (cluster)", "KO1_FT_geoeffnet", 4),
    ("vehicle.handbrake_applied", "Mechanical handbrake applied", "KO1_Handbremse", 5),
    ("vehicle.fuel_obd_threshold_warning", "Fuel below OBD threshold", "KO1_Tankwarnung", 31),
    ("vehicle.high_beam_cluster", "High beam active (cluster)", "KO1_Fernlicht", 37),
])
_flags(0x470, 8, [
    ("vehicle.turn_signal_left", "Left turn signal active", "BSK_Blk_links", 0),
    ("vehicle.turn_signal_right", "Right turn signal active", "BSK_Blk_rechts", 1),
    ("vehicle.trailer_turn_indicator", "Trailer turn indicator active", "BSK_Anhaenger", 2),
    ("vehicle.hazard_lights", "Hazard lights active", "BSK_Warnblinker", 3),
    ("vehicle.reverse_light", "Reverse light active", "BSK_Rueckfahrlicht", 5),
    ("vehicle.door.front_left.open", "Front left door open", "BSK_FT_geoeffnet", 8),
    ("vehicle.door.front_right.open", "Front right door open", "BSK_BT_geoeffnet", 9),
    ("vehicle.door.rear_left.open", "Rear left door open", "BSK_HL_geoeffnet", 10),
    ("vehicle.door.rear_right.open", "Rear right door open", "BSK_HR_geoeffnet", 11),
    ("vehicle.hood_open", "Hood open", "BSK_MH_geoeffnet", 12),
    ("vehicle.tailgate_main_latch", "Tailgate main latch engaged", "BSK_HD_Hauptraste", 13),
    ("vehicle.tailgate_pre_latch", "Tailgate preliminary latch engaged", "BSK_HD_Vorraste", 14),
    ("vehicle.undervoltage", "Body undervoltage indication", "BSK_Unterspannung", 15),
    ("vehicle.sidelights", "Sidelights active", "BSK_Standlicht", 40),
    ("vehicle.low_beam", "Low beam active", "BSK_Abblendlicht", 43),
    ("vehicle.front_fog_lights", "Front fog lights active", "BSK_Nebellicht", 44),
    ("vehicle.rear_window_heating", "Rear window heating active", "BSK_Heckscheibenhzg", 45),
    ("vehicle.fuel_flap_open", "Fuel flap open", "BSK_Tankklappe", 46),
    ("vehicle.rear_fog_light", "Rear fog light active", "BSK_Nebelschlusslicht", 61),
    ("vehicle.high_beam", "High beam active", "BSK_Fernlicht", 62),
    ("vehicle.daytime_running_lights", "Daytime running lights active", "BSK_Tagfahrlicht", 63),
])
_add("vehicle.display_brightness", "Instrument display brightness", "%", 0x470, "BSK_Display", 16, 7,
     invalid_bits=(23,), valid_raw_max=100)
_add("vehicle.terminal58_brightness", "Terminal 58t illumination brightness", "%", 0x470, "BSK_Klemme_58t", 24, 7,
     invalid_bits=(31,), valid_raw_max=100)

# Climate sensing/control status: useful cabin values, not BAP/UI protocol data.
_add("climate.ambient_temperature", "Climate-controller ambient temperature", "C", 0x3E1, "CL1_AussenTemp", 8, 8,
     .5, -50, invalid_raw=(255,), note="Kept distinct from filtered/unfiltered cluster ambient temperature.")
_add("climate.refrigerant_pressure", "AC refrigerant pressure", "bar", 0x3E1, "CL1_KaeltemittelDruck", 16, 8,
     .2, invalid_raw=(255,), invalid_bits=(7,))
_add("climate.compressor_torque", "AC compressor loss torque", "Nm", 0x3E1, "CL1_Last_Kompressor", 24, 8,
     .25, invalid_raw=(255,), invalid_bits=(6,))
_add("climate.blower_duty", "Cabin blower duty", "%", 0x3E1, "CL1_Geblaeselast", 32, 8, .4,
     invalid_raw=(255,), valid_raw_max=250)
_add("climate.cooling_fan_duty", "Climate cooling fan command", "%", 0x3E1, "CL1_Strg_Kluefter", 40, 8, .4,
     invalid_raw=(255,), valid_raw_max=250)
_add("climate.cabin_temperature", "Cabin temperature", "C", 0x3E3, "CL2_InnenTemp", 16, 8, .5, -50,
     invalid_raw=(255,))
_add("climate.solar_power_left", "Left solar radiation", "W/m2", 0x3E3, "CL2_Sonne_links", 0, 8, 4,
     invalid_raw=(255,))
_add("climate.solar_power_right", "Right solar radiation", "W/m2", 0x3E3, "CL2_Sonne_rechts", 8, 8, 4,
     invalid_raw=(255,))
_add("climate.coolant_temperature_requested", "Climate requested coolant temperature", "C", 0x3E3,
     "CL2_Vorgabe_KWTemp", 56, 8, .75, -48, invalid_raw=(255,))
_flags(0x3E1, 8, [
    ("climate.compressor_enabled", "AC compressor enabled", "CL1_Kompressor", 4),
    ("climate.ac_switch", "AC switch on", "CL1_AC_Schalter", 49),
    ("climate.residual_heat_enabled", "Residual heat enabled", "CL1_Restwaerme", 51),
    ("climate.fault_memory_present", "Climate fault memory indication", "CL1_KD_Fehler", 55),
])
_flags(0x5E1, 7, [
    ("climate.recirculation_active", "Recirculation active", "CL3_Umluft", 0),
    ("climate.defrost_active", "Defrost active", "CL3_Defrost", 4),
    ("climate.economy_active", "Climate economy mode active", "CL3_Econ", 6),
    ("climate.master_switch", "Climate master switch on", "CL3_Klima_Hauptschalter", 7),
    ("climate.auxiliary_heating_active", "Auxiliary heating active", "CL3_StandHzg", 23),
    ("climate.steering_wheel_heating_active", "Steering wheel heating active", "CL3_ein_Lenkrad_Hzg", 46),
])

_flags(0x545, 4, [
    ("parking.assist_fault", "Parking assistance disabled by fault", "PA3_Anlage_defekt", 1),
    ("parking.assist_manual_active", "Parking assistance manually activated", "PA3_Taster_aktiviert", 2),
    ("parking.assist_reverse_active", "Parking assistance activated by reverse", "PA3_Rueckwaertsgang_aktiv", 3),
    ("parking.assist_ready", "Parking assistance ready", "PA3_Bereit", 24),
])
for position, signal, start in (
        ("front_left", "VL", 0), ("front_right", "VR", 8), ("rear_left", "HL", 16), ("rear_right", "HR", 24),
        ("front_mid_left", "VML", 32), ("front_mid_right", "VMR", 40), ("rear_mid_left", "HML", 48), ("rear_mid_right", "HMR", 56)):
    _add(f"parking.distance.{position}", f"{position.replace('_', ' ').title()} parking distance", "cm",
         0x54B, f"PA5_{signal}_Abstand", start, 8, type="status", choices={255: "No obstacle"},
         note="0..254 cm; code 255 means no obstacle in detection range, not a 255 cm measurement or sensor fault.")

# MFA values carry configurable display units. Each variant has a distinct
# value/provider ID and exclusive unit guards; no fixed L/100km or km assumption.
for suffix, prefix, can_id, dlc in (("instant", "MA1", 0x629, 7),
                                  ("short_term", "MA2", 0x62B, 8),
                                  ("long_term", "MA3", 0x62D, 8)):
    for unit_id, unit, flag in (("l_per_100km", "L/100km", 12), ("km_per_l", "km/L", 13), ("mpg", "mpg", 14)):
        _add(f"vehicle.fuel_consumption.{suffix}.{unit_id}", f"{suffix.replace('_', ' ').title()} fuel consumption ({unit})",
             unit, can_id, f"{prefix}_Verbrauch", 0, 12, .1, frame_length=dlc,
             invalid_raw=(4095,), estimated=True, provider_suffix=unit_id,
             valid_when=[{"start": bit, "length": 1, "raw": int(bit == flag)} for bit in (12, 13, 14)],
             note="Cluster display value; gallon convention is not specified by this ICAN field.")

for unit_id, unit, flag in (("km", "km", 30), ("miles", "mi", 31)):
    _add(f"vehicle.range_{unit_id}", f"Estimated remaining range ({unit})", unit, 0x629, "MA1_Reichweite", 16, 14,
         frame_length=7, invalid_raw=(16383,), estimated=True, provider_suffix=unit_id,
         valid_when=[{"start": 30, "length": 1, "raw": int(flag == 30)},
                     {"start": 31, "length": 1, "raw": int(flag == 31)}])
    _add(f"vehicle.odometer_{unit_id}", f"Odometer ({unit})", unit, 0x629, "MA1_Kilometerstand", 32, 22,
         frame_length=7, provider_suffix=unit_id,
         valid_when=[{"start": 54, "length": 1, "raw": int(flag == 30)},
                     {"start": 55, "length": 1, "raw": int(flag == 31)}])

for suffix, prefix, can_id in (("short_term", "MA2", 0x62B), ("long_term", "MA3", 0x62D)):
    _add(f"vehicle.trip.{suffix}.duration", f"{suffix.replace('_', ' ').title()} trip duration", "min", can_id,
         f"{prefix}_Zeit", 32, 14, invalid_raw=(16383,))
    for unit_id, unit, flag in (("km", "km", 30), ("miles", "mi", 31)):
        _add(f"vehicle.trip.{suffix}.distance_{unit_id}", f"{suffix.replace('_', ' ').title()} trip distance ({unit})",
             unit, can_id, f"{prefix}_Strecke", 16, 14, invalid_raw=(16383,), provider_suffix=unit_id,
             valid_when=[{"start": 30, "length": 1, "raw": int(flag == 30)},
                         {"start": 31, "length": 1, "raw": int(flag == 31)}])
    for unit_id, unit, flag in (("kmh", "km/h", 62), ("mph", "mph", 63)):
        _add(f"vehicle.trip.{suffix}.average_speed_{unit_id}", f"{suffix.replace('_', ' ').title()} average speed ({unit})",
             unit, can_id, f"{prefix}_Geschw", 48, 14, invalid_raw=(16383,), provider_suffix=unit_id,
             valid_when=[{"start": 62, "length": 1, "raw": int(flag == 62)},
                         {"start": 63, "length": 1, "raw": int(flag == 63)}])

for cycle, cycle_bit in (("current", 1), ("previous", 0)):
    cycle_guard = [{"start": 15, "length": 1, "raw": cycle_bit}]
    for unit_id, unit, flag in (("l_per_100km", "L/100km", 12), ("km_per_l", "km/L", 13), ("mpg", "mpg", 14)):
        _add(f"vehicle.fuel_consumption.{cycle}_tank.{unit_id}", f"{cycle.title()} tank-cycle fuel consumption ({unit})",
             unit, 0x529, "MA4_Verbr_TZ", 0, 12, .1, frame_length=6,
             invalid_raw=(4095,), estimated=True, provider_suffix=f"{cycle}_{unit_id}",
             valid_when=cycle_guard + [{"start": bit, "length": 1, "raw": int(bit == flag)} for bit in (12, 13, 14)])
    for unit_id, unit, flag in (("km", "km", 30), ("miles", "mi", 31)):
        _add(f"vehicle.trip.{cycle}_tank.distance_{unit_id}", f"{cycle.title()} tank-cycle distance ({unit})", unit,
             0x529, "MA4_Strecke_TZ", 16, 14, frame_length=6, invalid_raw=(16383,), provider_suffix=f"{cycle}_{unit_id}",
             valid_when=cycle_guard + [{"start": 30, "length": 1, "raw": int(flag == 30)},
                                       {"start": 31, "length": 1, "raw": int(flag == 31)}])
    for unit_id, unit, flag in (("kmh", "km/h", 46), ("mph", "mph", 47)):
        _add(f"vehicle.trip.{cycle}_tank.average_speed_{unit_id}", f"{cycle.title()} tank-cycle average speed ({unit})", unit,
             0x529, "MA4_Geschw", 32, 14, frame_length=6, invalid_raw=(16383,), provider_suffix=f"{cycle}_{unit_id}",
             valid_when=cycle_guard + [{"start": 46, "length": 1, "raw": int(flag == 46)},
                                       {"start": 47, "length": 1, "raw": int(flag == 47)}])
_add("vehicle.driving_duration_without_break", "Driving duration without break", "min", 0x52B, "MA5_Lenkzeit", 0, 14,
     frame_length=7, invalid_raw=(16383,), note="Reset after ignition is off for more than 10 minutes.")
_add("vehicle.driving_time_to_refuel", "Recommended driving time until refueling", "min", 0x52B, "MA5_Tankrestzeit", 16, 14,
     frame_length=7, invalid_raw=(16383,), estimated=True)


# Firmware 7316 custom telemetry on ICAN (HALDEX_LOGGING_SPEC.md sections 0-2).
# No ACAN-only production IDs are subscribed. Raw internal quantities retain
# count units where conversion into acceleration/throttle/slip is unconfirmed.
def _haldex(value_id, label, unit, can_id, signal, start, length=16, factor=1, *, page=None, **extra):
    guard = ([{"start": 0, "length": 8, "raw": 0xD0 + page}] if page is not None else [])
    note = "Custom firmware 7316 telemetry; absent on unmodified ECUs."
    if extra.get("note_override"):
        note += " " + extra.pop("note_override")
    _add(value_id, label, unit, can_id, signal, start, length, factor,
         valid_when=guard, note=note, **extra)
    SIGNALS[-1]["reference"] = "HALDEX_LOGGING_SPEC.md"


_haldex("awd.model_yaw_rate", "AWD model yaw rate", "deg/s", 0x679, "YAW_MODEL", 0, factor=1 / 17.87, signed=True)
_haldex("awd.model_yaw_raw", "AWD model yaw raw counts", "count", 0x679, "YAW_MODEL", 0,
        signed=True, provider_suffix="raw")
_haldex("awd.proactive_reference_raw", "AWD proactive reference C06", "count", 0x679, "C06", 16)
_haldex("awd.pre_reference_generation_raw", "AWD pre-reference generation C22", "count", 0x679, "C22", 32)
_haldex("awd.commanded_torque", "AWD commanded torque B08", "Nm", 0x679, "B08", 48, factor=.0625)
_haldex("awd.torque_ceiling", "AWD torque ceiling A72", "Nm", 0x6DA, "A72", 16, factor=.0625, page=0)
_haldex("awd.final_reference_torque", "AWD final reference torque A74", "Nm", 0x6DA, "A74", 32, factor=.0625, page=0)
_haldex("awd.slip_control_torque", "AWD slip control torque A7C", "Nm", 0x6DA, "A7C", 48, factor=.0625, page=0)
_haldex("awd.demanded_acceleration_raw", "AWD demanded acceleration C9E", "count", 0x6DA, "C9E", 16, signed=True, page=1)
_haldex("awd.actual_acceleration_raw", "AWD actual acceleration C9C", "count", 0x6DA, "C9C", 32, signed=True, page=1)
_haldex("awd.measured_yaw_rate", "AWD measured yaw rate", "deg/s", 0x6DA, "MEASURED_YAW", 48,
        factor=1 / 17.87, signed=True, page=1)
_haldex("awd.measured_yaw_raw", "AWD measured yaw raw counts", "count", 0x6DA, "MEASURED_YAW", 48,
        signed=True, page=1, provider_suffix="raw")
_haldex("awd.lateral_feedforward_raw", "AWD lateral feed-forward B26", "count", 0x6DA, "B26", 16, signed=True, page=2)
_haldex("awd.curvature_raw", "AWD curvature BC4", "count", 0x6DA, "BC4", 32, page=2)
_haldex("awd.computed_axle_slip_raw", "AWD computed axle slip BB6", "count", 0x6DA, "BB6", 48, signed=True, page=2)
for wheel, page, start in (("front_left", 3, 16), ("front_right", 3, 32), ("rear_left", 3, 48), ("rear_right", 4, 16)):
    _haldex(f"vehicle.wheel.{wheel}.speed", f"{wheel.replace('_', ' ').title()} wheel speed", "km/h",
            0x6DA, f"WHEEL_{wheel.upper()}", start, factor=.005, page=page)
_haldex("awd.lateral_acceleration_raw", "AWD measured lateral acceleration", "count", 0x6DA, "LATERAL_ACCEL", 32, signed=True, page=4)
_haldex("awd.throttle_raw", "AWD throttle input byte", "count", 0x6DA, "THROTTLE", 48, 8, page=4)
_haldex("awd.brake_light_raw", "AWD brake light input byte", "count", 0x6DA, "BLS", 56, 8, page=4)
_haldex("awd.hold_timer", "AWD hold timer A7E", "count", 0x6DA, "A7E", 16, page=5)
_haldex("awd.high_gear_factor_raw", "AWD high-gear factor C12", "count", 0x6DA, "C12", 32, page=5)
_haldex("awd.target_gear", "AWD target gear input", "", 0x6DA, "TARGET_GEAR", 48, 8, page=5,
        note_override="Low byte of gear word; target/input gear, not proof of the physically engaged gear.")
_haldex("awd.target_gear_word_raw", "AWD target gear input word", "count", 0x6DA, "TARGET_GEAR", 48, 16,
        page=5, provider_suffix="raw")
_haldex("awd.slip_energy_raw", "AWD slip energy C3A", "count", 0x6DA, "C3A", 16, page=6)
_haldex("awd.energy_ceiling_raw", "AWD energy ceiling C26", "count", 0x6DA, "C26", 32, page=6)
_haldex("awd.fault_derate_ceiling_raw", "AWD fault/derate ceiling AFE", "count", 0x6DA, "AFE", 48, page=6)
for value_id, label, signal, start, length, type, choices in (
        ("awd.active_mode", "AWD applied mode", "MODE", 8, 2, "string", {0: "Stock", 1: "Performance", 2: "Competition", 3: "Unknown"}),
        ("awd.selector_state", "AWD selector B1CC", "B1CC", 10, 3, "bitfield", {}),
        ("awd.force_zero_active", "AWD force zero torque A78", "A78", 13, 1, "status", {0: "No", 1: "Yes"}),
        ("awd.token_valid", "AWD token accepted", "TOKEN_OK", 14, 1, "status", {0: "No", 1: "Yes"}),
        ("awd.abs_braking", "AWD ABS braking state", "ABS", 15, 1, "status", {0: "No", 1: "Yes"})):
    _haldex(value_id, label, "", 0x6DA, signal, start, length, type=type, choices=choices)
    SIGNALS[-1]["valid_when"] = [{"start": 0, "length": 8, "raw_in": list(range(0xD0, 0xD7))}]


CONSUMER_FIELD_MAP = {
    "vehicle_speed_kmh": "vehicle.speed", "gateway_vehicle_speed_kmh": "vehicle.speed",
    "vehicle_speed_from_abs": "vehicle.speed_from_abs",
    "front_axle_path_pulses": "vehicle.front_axle_path_pulses",
    "path_pulse_status": "vehicle.front_axle_pulse_counter_has_overflowed",
    "path_pulse_error": "vehicle.front_axle_pulse_sensor_fault",
    "path_pulses_per_revolution": "vehicle.path_pulses_per_revolution",
    "brake_light_switch": "vehicle.brake_light_requested",  # Legacy logger label was a command bit.
    "abs_active": "vehicle.abs_active", "esp_active": "vehicle.esp_active",
    "selector_position": "transmission.selector_position",
    "steer_angle_deg": "vehicle.steering_angle", "steer_rate_deg_s": "vehicle.steering_rate",
    "engine_rpm": "engine.rpm", "engine_coolant_c": "engine.coolant_temperature",
    "engine_brake_switch": "engine.brake_light_switch",
    "measured_yaw_rate_deg_s": "vehicle.yaw_rate", "ambient_temp_c": "ambient.filtered_temperature",
    "boost_pressure_mbar": "engine.boost.actual_absolute", "engine_oil_temp_c": "engine.oil_temperature",
    "model_yaw_raw": "awd.model_yaw_raw", "model_yaw_deg_s": "awd.model_yaw_rate",
    "c06_proactive_ref": "awd.proactive_reference_raw", "c22_pre_refgen": "awd.pre_reference_generation_raw",
    "b08_torque_nm": "awd.commanded_torque", "haldex_mode": "awd.active_mode",
    "haldex_mode_name": "awd.active_mode", "haldex_selector_b1cc": "awd.selector_state",
    "haldex_force_zero_a78": "awd.force_zero_active", "haldex_token_ok": "awd.token_valid",
    "haldex_abs_braking": "awd.abs_braking", "a72_ceiling_nm": "awd.torque_ceiling",
    "a74_ref_torque_nm": "awd.final_reference_torque", "a7c_slip_torque_nm": "awd.slip_control_torque",
    "c9e_demanded_accel_raw": "awd.demanded_acceleration_raw", "c9c_actual_accel_raw": "awd.actual_acceleration_raw",
    "haldex_measured_yaw_raw": "awd.measured_yaw_raw", "haldex_measured_yaw_deg_s": "awd.measured_yaw_rate",
    "b26_lateral_feedforward_raw": "awd.lateral_feedforward_raw", "bc4_curvature_raw": "awd.curvature_raw",
    "bb6_computed_axle_slip_raw": "awd.computed_axle_slip_raw", "wheel_vl_kmh": "vehicle.wheel.front_left.speed",
    "wheel_vr_kmh": "vehicle.wheel.front_right.speed", "wheel_hl_kmh": "vehicle.wheel.rear_left.speed",
    "wheel_hr_kmh": "vehicle.wheel.rear_right.speed", "lat_accel_measured_raw": "awd.lateral_acceleration_raw",
    "haldex_throttle_raw": "awd.throttle_raw", "haldex_bls_raw": "awd.brake_light_raw",
    "hold_a7e_timer": "awd.hold_timer", "c12_high_gear_factor_raw": "awd.high_gear_factor_raw",
    "target_gear_word_raw": "awd.target_gear_word_raw", "target_gear": "awd.target_gear",
    "c3a_slip_energy_raw": "awd.slip_energy_raw", "c26_energy_ceiling_raw": "awd.energy_ceiling_raw",
    "afe_fault_ceiling_raw": "awd.fault_derate_ceiling_raw",
}

COVERAGE_NOTES = {
    "covered": ["Engine state, cooling and counters", "ABS/ESP/EPB, selector state and wheel counters",
                "Steering and measured yaw", "Battery, energy management, ignition, doors and lights",
                "Fuel estimate, range, odometer and trip display units", "Cabin/climate measurements and parking distances",
                "Current custom Haldex firmware telemetry pages on ICAN"],
    "excluded": ["Infotainment transport/BAP/CDEF payloads, security bytes, network management and message checksums",
                 "Raw ACAN-only IDs (0x4A0, 0x0C2, 0x1A0, 0x280, 0x288, 0x4A8, 0x428)",
                 "Haldex transmitted mode commands: requested mode is distinct from ECU-applied telemetry mode",
                 "Unspecified climate target-temperature encodings and GPS compound coordinate encodings",
                 "ICAN engine torque, actual transmission gear and pedal percent: absent from the reviewed DBC",
                 "Logger page IDs, nominal schedule rates, raw-frame blobs and inverse validity helper columns are metadata, not independent vehicle values"],
    "limitations": ["DBC documentation does not establish vehicle broadcast availability",
                    "Cluster boost interpretation remains unverified in the original catalog",
                    "Fuel/range/consumption are estimates and require allow_estimated",
                    "Raw Haldex throttle, acceleration and slip quantities retain counts until scaling is confirmed",
                    "Four-byte steering and two-byte yaw inputs accepted by the old logger omit DBC validity fields; full documented DLC is required"],
}


def coverage_summary():
    frames = {}
    for signal in SIGNALS:
        frame = frames.setdefault(f"0x{signal['can_id']:03X}", {"frame_length": signal["frame_length"],
            "nominal_cycle_ms": signal.get("nominal_cycle_ms"), "signal_definitions": 0})
        frame["signal_definitions"] += 1
    return {"signal_definitions": len(SIGNALS), "value_ids": len({signal["value_id"] for signal in SIGNALS}),
            "frames": dict(sorted(frames.items())), "consumer_fields_mapped": len(CONSUMER_FIELD_MAP), **COVERAGE_NOTES}
