"""Engine-first value definitions from the owner's measuring-block reference.

Diagnostic blocks are ONE-BASED. ``verified`` means documented in the supplied
reference/DBC, not independently measured on every ECU. Undocumented extra
fields and the vehicle-specific MO7 display boost signal require explicit opt-in.
This module has no transport dependencies and does not truncate raw responses.
"""

from copy import deepcopy
import math
import re


CATALOG = {}
_SOURCE_INDEX = {}


def _value(value_id, label, unit, locations=(), *, note=None):
    entry = {"id": value_id, "label": label, "unit": unit, "type": "number", "providers": []}
    if note:
        entry["note"] = note
    for group, block in locations:
        entry["providers"].append({
            "id": f"diag:01:{group}:{block}", "kind": "diag", "module": 1,
            "group": group, "block": block, "verified": True, "estimated": False,
            "stale_after_ms": 2000, "reference": "Measuring Groups - Engine - 01.pdf",
        })
    CATALOG[value_id] = entry
    return entry


def _can(value_id, can_id, signal, start, length, factor=1, offset=0,
         *, invalid_raw=(), invalid_bits=(), verified=True, estimated=False, note=None,
         valid_raw_max=None, frame_length=8):
    provider = {
        "id": f"ican:{can_id:03X}:{signal}", "kind": "ican", "can_id": can_id,
        "signal": signal, "start": start, "length": length, "factor": factor,
        "offset": offset, "invalid_raw": list(invalid_raw),
        "invalid_bits": list(invalid_bits), "verified": verified, "estimated": estimated,
        "frame_length": frame_length, "stale_after_ms": 1000,
        "reference": "PQ35_46_ICAN.dbc",
    }
    if note:
        provider["note"] = note
    if valid_raw_max is not None:
        provider["valid_raw_max"] = valid_raw_max
    CATALOG[value_id]["providers"].insert(0, provider)


_rpm_groups = (1, 2, 3, 4, 5, 6, 7, 10, 11, 13, 14, 22, 23, 28, 34, 43, 46,
               50, 51, 52, 53, 54, 55, 56, 57, 61, 68, 91, 93, 94, 99, 101, 102,
               107, 110, 113, 115, 116, 117, 118, 119, 120, 122, 143)
_value("engine.rpm", "Engine speed", "rpm", [(g, 1) for g in _rpm_groups])
_value("engine.coolant_temperature", "Coolant temperature (G62)", "C",
       [(1, 2), (4, 3), (7, 3), (11, 2), (28, 3), (99, 2), (100, 2), (102, 2), (110, 2), (131, 1)])
_value("engine.oil_temperature", "Oil temperature", "C", [(134, 1)])
_value("engine.intake_temperature", "Intake air temperature (G42)", "C",
       [(4, 4), (6, 3), (11, 3), (102, 3), (118, 2), (134, 3)])
_value("engine.maf", "Mass air flow (G70)", "g/s", [(2, 4), (3, 2), (101, 4)])
_value("engine.ignition_timing", "Ignition timing", "deg", [(3, 4), (10, 4), (11, 4)])
_value("engine.injection_time", "Injection duration", "ms", [(2, 3), (101, 3), (102, 4), (110, 3)],
       note="Reference calls this Injection Timing; accepted only when ECU returns a time unit.")
_load_groups = (2, 5, 6, 7, 10, 14, 22, 23, 28, 68, 93, 101, 113, 115, 143)
_value("engine.load.actual", "Engine load (actual)", "%", [(g, 2) for g in _load_groups] + [(37, 1), (114, 3)])
_value("engine.load.spec", "Engine load (specified)", "%", [(114, 1)])
_value("engine.load.corrected", "Engine load (specified corrected)", "%", [(114, 2)])
_value("engine.boost.actual_absolute", "Boost pressure (actual absolute)", "mbar", [(115, 4), (118, 4), (119, 4)])
_value("engine.boost.spec_absolute", "Boost pressure (specified absolute)", "mbar", [(115, 3), (117, 4)])
_value("engine.atmospheric_pressure", "Atmospheric pressure", "mbar", [(113, 4)])
_value("engine.n75_duty", "Boost control valve duty (N75)", "%", [(114, 4), (118, 3), (119, 3)])
for _c in range(1, 5):
    _value(f"engine.timing_retard.cylinder{_c}", f"Timing retard cylinder {_c}", "deg",
           [(20, _c), (22 if _c <= 2 else 23, 3 if _c % 2 else 4)])
_value("engine.fuel_rail.actual", "Fuel rail pressure (actual)", "bar", [(106, 2), (140, 3), (141, 4)])
_value("engine.fuel_rail.spec", "Fuel rail pressure (specified)", "bar", [(106, 1)])
_value("engine.fuel_pump_duty", "Fuel pump duty", "%", [(106, 3)])
_throttle = [(3, 3), (10, 3), (54, 4), (61, 3), (110, 4), (113, 3)]
for _id, _unit, _suffix in (("engine.throttle_angle", "deg", "angle"), ("engine.throttle_position", "%", "position")):
    _entry = _value(_id, "Throttle valve " + _suffix, _unit, _throttle,
                    note="No conversion between angular degrees and percent opening is assumed.")
    for _provider in _entry["providers"]:
        _provider["id"] += ":" + _suffix
_value("engine.pedal_position", "Accelerator pedal position (G79)", "%", [(54, 3), (62, 3), (63, 1), (117, 2)])
_value("ambient.filtered_temperature", "Ambient temperature (filtered)", "C")
_value("ambient.unfiltered_temperature", "Ambient temperature (unfiltered)", "C")
_value("ambient.temperature", "Ambient temperature (engine diagnostic)", "C", [(134, 2)],
       note="Filtering equivalence to the two ICAN ambient values is not confirmed.")
_value("vehicle.speed", "Vehicle speed", "km/h", [(5, 3), (66, 1)])
_value("vehicle.battery_voltage", "Battery voltage (body controller)", "V")
_value("engine.terminal30_voltage", "Terminal 30 voltage (engine ECU)", "V", [(4, 2), (51, 4), (53, 3), (61, 2)])
_value("engine.generator_duty", "Generator duty (DFM)", "%", [(53, 4)],
       note="Generator load is distinct from engine load.")
_value("engine.outlet_temperature", "Engine outlet temperature", "C", [(130, 1), (134, 4)])
_value("engine.radiator_outlet_temperature", "Radiator outlet temperature", "C", [(130, 2), (131, 3), (135, 1)])

_can("engine.rpm", 0x35B, "GWM_Motordrehzahl", 8, 16, .25,
     invalid_raw=(65280,), invalid_bits=(0,), valid_raw_max=65024)
_can("engine.coolant_temperature", 0x35B, "GWM_KuehlmittelTemp", 24, 8, .75, -48,
     invalid_raw=(0, 255), invalid_bits=(1, 34))
_can("engine.oil_temperature", 0x555, "MO7_Oeltemperatur", 56, 8, 1, -60,
     invalid_raw=(0, 1, 255), invalid_bits=(4,))
_can("engine.generator_duty", 0x555, "MO7_DFM", 8, 8, .4, invalid_raw=(255,))
_can("engine.atmospheric_pressure", 0x555, "MO7_Hoeheninfo", 16, 8, 1013 / 128,
     invalid_raw=(255,), estimated=True,
     note="Approximation from altitude correction factor; DBC says factor 1 corresponds to 1013 mbar.")
_can("engine.boost.actual_absolute", 0x555, "MO7_Ladedruckneu", 32, 8, 20,
     invalid_raw=(255,), verified=False,
     note="Vehicle-specific cluster display signal; absolute pressure interpretation needs capture validation.")
_can("ambient.filtered_temperature", 0x527, "GWK_AussenTemp_gefiltert", 40, 8, .5, -50,
     invalid_raw=(0, 1, 255), invalid_bits=(2, 56))
_can("ambient.unfiltered_temperature", 0x527, "GWK_AussenTemp_ungefiltert", 48, 8, .5, -50,
     invalid_raw=(0, 1, 255), invalid_bits=(2, 56))
_can("vehicle.speed", 0x527, "GWK_FzgGeschw", 9, 15, .01,
     invalid_raw=(32708, 32725, 32742, 32767), invalid_bits=(2,), valid_raw_max=32600)
_can("vehicle.speed", 0x351, "GW1_FzgGeschw", 9, 15, .01,
     invalid_raw=(32708, 32725, 32742, 32767), invalid_bits=(0,), valid_raw_max=32639)
_can("vehicle.battery_voltage", 0x571, "BS2_U_BATT", 0, 8, .05, 5, invalid_raw=(255,), frame_length=6)

# The owner's reference annotates fields 5-8 of group 11 as tentative. Keep
# candidates discoverable, but never promote them based only on matching units.
for _id, _block in (("ambient.temperature", 5), ("engine.maf", 6), ("vehicle.speed", 7)):
    CATALOG[_id]["providers"].append({
        "id": f"diag:01:11:{_block}", "kind": "diag", "module": 1,
        "group": 11, "block": _block, "verified": False, "estimated": False,
        "stale_after_ms": 2000, "note": "Tentative extra-field annotation in owner's reference.",
    })


def get_catalog():
    """Return a JSON-friendly independent catalog, safe for client editing."""
    return deepcopy(list(CATALOG.values()))


def get_catalog_coverage():
    """Describe reference coverage separately from counts of canonical values."""
    from collections import Counter
    from .engine_definitions import coverage_ledger
    from .ican_definitions import coverage_summary
    engine = coverage_ledger(CATALOG)
    return {
        'value_count': len(CATALOG),
        'provider_count': sum(len(entry['providers']) for entry in CATALOG.values()),
        'by_namespace': dict(sorted(Counter(key.split('.')[0] for key in CATALOG).items())),
        'by_type': dict(sorted(Counter(entry['type'] for entry in CATALOG.values()).items())),
        'engine_reference': {key: value for key, value in engine.items() if key != 'fields'},
        'ican_reference': coverage_summary(),
    }


def _entries(catalog):
    registry = CATALOG if catalog is None else catalog
    return registry.values() if isinstance(registry, dict) else registry


def _source_entries(catalog, kind, location):
    """Avoid scanning the entire expanded catalog on every incoming CAN frame."""
    if catalog is not None and catalog is not CATALOG:
        return _entries(catalog)
    if not _SOURCE_INDEX:
        for entry in CATALOG.values():
            groups = {}
            for provider in entry.get('providers', []):
                provider_kind = provider['kind']
                source = (provider['can_id'] if provider_kind == 'ican'
                          else (provider['module'], provider['group']))
                groups.setdefault((provider_kind, source), []).append(provider)
            for key, providers in groups.items():
                _SOURCE_INDEX.setdefault(key, []).append({**entry, 'providers': providers})
    return _SOURCE_INDEX.get((kind, location), ())


def _reading(value=None, reason=None):
    return {"value": value if reason is None else None, "valid": reason is None, "reason": reason}


def register_diagnostic_definitions(definitions):
    """Add documented fields while retaining existing canonical IDs and units."""
    _SOURCE_INDEX.clear()
    for definition in definitions:
        value_id = definition['id']
        entry = CATALOG.setdefault(value_id, {
            key: deepcopy(value) for key, value in definition.items()
            if key not in ('locations', 'module', 'verified', 'estimated', 'reference', 'provider_suffix')
        })
        entry.setdefault('type', 'number')
        entry.setdefault('providers', [])
        module = definition.get('module', 1)
        reference = definition.get('reference', 'Measuring Groups - Engine - 01.pdf')
        for group, block in definition['locations']:
            provider_id = f'diag:{module:02X}:{group}:{block}'
            if definition.get('provider_suffix'):
                provider_id += ':' + definition['provider_suffix']
            if any(p['id'] == provider_id for p in entry['providers']):
                continue
            entry['providers'].append({
                'id': provider_id, 'kind': 'diag', 'module': module, 'group': group, 'block': block,
                'verified': definition.get('verified', True), 'estimated': definition.get('estimated', False),
                'stale_after_ms': 2000, 'reference': reference,
            })


def register_ican_signals(signals):
    """Add declarative DBC signals, including enum and signed encodings."""
    _SOURCE_INDEX.clear()
    for signal in signals:
        value_id = signal['value_id']
        entry = CATALOG.setdefault(value_id, {
            'id': value_id, 'label': signal['label'], 'unit': signal['unit'],
            'type': signal.get('type', 'number'), 'providers': [],
        })
        if signal.get('note') and 'note' not in entry:
            entry['note'] = signal['note']
        provider_id = f"ican:{signal['can_id']:03X}:{signal['signal']}"
        if signal.get('provider_suffix'):
            provider_id += ':' + signal['provider_suffix']
        if any(p['id'] == provider_id for p in entry['providers']):
            continue
        provider = {key: deepcopy(value) for key, value in signal.items()
                    if key not in ('value_id', 'label', 'unit', 'type')}
        provider.update(id=provider_id, kind='ican')
        provider['unit'] = signal['unit']
        for key, default in (('verified', True), ('estimated', False), ('frame_length', 8),
                             ('stale_after_ms', 1000), ('reference', 'PQ35_46_ICAN.dbc')):
            provider.setdefault(key, default)
        entry['providers'].append(provider)


# Definitions live separately so the source coverage can be audited without
# changing the transport, planner or existing display IDs.
from .engine_definitions import DEFINITIONS as ENGINE_DEFINITIONS
register_diagnostic_definitions(ENGINE_DEFINITIONS)
from .consumer_definitions import DEFINITIONS as CONSUMER_DEFINITIONS
register_diagnostic_definitions(CONSUMER_DEFINITIONS)
from .ican_definitions import SIGNALS as ICAN_SIGNALS
register_ican_signals(ICAN_SIGNALS)


def decode_ican(can_id, data, catalog=None):
    """Decode configured little-endian ICAN signals and their DBC validity bits.

Truncated frames invalidate every provider for that frame, including signals
whose bytes arrived, because validity bits may occur later in the payload.
Unknown IDs return no readings. No transport timestamps are manufactured here.
"""
    readings = {}
    for entry in _source_entries(catalog, 'ican', can_id):
        for provider in entry.get("providers", []):
            if provider.get("kind") != "ican" or provider.get("can_id") != can_id:
                continue
            pid = provider["id"]
            start, length = provider.get("start"), provider.get("length")
            if start is None or length is None:
                readings[pid] = _reading(reason="unsupported_signal")
                continue
            guards = provider.get('valid_when', [])
            guard_end = max((guard['start'] + guard.get('length', 1) for guard in guards), default=0)
            minimum = max(provider.get("frame_length", 0), (start + length + 7) // 8,
                          max(((bit + 8) // 8 for bit in provider.get("invalid_bits", [])), default=0),
                          (provider.get('sign_bit', -1) + 8) // 8, (guard_end + 7) // 8)
            if len(data) < minimum:
                readings[pid] = _reading(reason="short_frame")
                continue
            packed = int.from_bytes(data, "little")
            raw = (packed >> start) & ((1 << length) - 1)
            reason = None
            if raw in provider.get("invalid_raw", []):
                reason = "sentinel"
            elif any((packed >> bit) & 1 for bit in provider.get("invalid_bits", [])):
                reason = "invalid_flag"
            elif raw > provider.get("valid_raw_max", raw):
                reason = "out_of_range"
            elif any(((packed >> guard['start']) & ((1 << guard.get('length', 1)) - 1))
                     not in guard.get('raw_in', [guard.get('raw')]) for guard in guards):
                reason = 'qualifier_mismatch'
            signed_raw = raw
            if provider.get('signed') and raw & (1 << (length - 1)):
                signed_raw -= 1 << length
            value = signed_raw * provider.get("factor", 1) + provider.get("offset", 0)
            if 'sign_bit' in provider and ((packed >> provider['sign_bit']) & 1) == provider.get('sign_negative_when', 1):
                value = -value
            choices = provider.get('choices', {})
            if raw in choices or str(raw) in choices:
                value = choices[raw] if raw in choices else choices[str(raw)]
            readings[pid] = _reading(value, reason)
            if entry.get('unit_policy') == 'reported':
                readings[pid]['unit'] = provider.get('unit')
    return readings


_UNIT_ALIASES = {"°c": "C", "c": "C", "degc": "C", "rpm": "rpm", "/min": "rpm",
                 "°": "deg", "deg": "deg", "degrees": "deg", "v": "V", "bar": "bar",
                 "mbar": "mbar", "kpa": "kPa", "ms": "ms", "s": "s", "%": "%",
                 "g/s": "g/s", "kg/h": "kg/h", "km/h": "km/h"}
_UNIT_ALIASES.update({'a': 'A', 'ma': 'mA', 'nm': 'Nm', 'cnm': 'cNm', 'ohm': 'ohm',
                      'mm': 'mm', 'm': 'm', 'l': 'L', 'l/h': 'L/h', 'km': 'km',
                      'count': 'count', '°/s': 'deg/s', 'deg/s': 'deg/s'})
_CONVERSIONS = {("bar", "mbar"): 1000, ("mbar", "bar"): .001,
                ("kPa", "mbar"): 10, ("kPa", "bar"): .01,
                ("s", "ms"): 1000, ("kg/h", "g/s"): 1 / 3.6}
_CONVERSIONS.update({('A', 'mA'): 1000, ('mA', 'A'): .001, ('cNm', 'Nm'): .01,
                     ('Nm', 'cNm'): 100, ('m', 'mm'): 1000, ('mm', 'm'): .001})
_KNOWN_FORMULAS = set(range(1, 29)) | (set(range(30, 58)) - {32}) | set(range(59, 73)) | {81, 83, 94}


def diagnostic_readings(module, group, data, catalog=None):
    """Extract known providers from the COMPLETE TP2 decoded field list.

Validate numeric types, formula recognition, and dimensional units. Raw input
is left untouched: callers retain all fields, including undocumented fifth to
eighth fields, for inspection and later catalog extension.
"""
    readings = {}
    for entry in _source_entries(catalog, 'diag', (module, group)):
        for provider in entry.get("providers", []):
            if (provider.get("kind") != "diag" or provider.get("module") != module
                    or provider.get("group") != group):
                continue
            pid, index = provider["id"], provider["block"] - 1
            if index < 0 or index >= len(data):
                readings[pid] = _reading(reason="missing_field")
                continue
            field = data[index]
            if not isinstance(field, dict):
                readings[pid] = _reading(reason="invalid_field")
                continue
            unit = str(field.get("unit", "")).strip()
            formula = field.get("type")
            if unit.lower().startswith("type_") or (formula is not None and formula not in _KNOWN_FORMULAS):
                readings[pid] = _reading(reason="unknown_formula")
                continue
            value = field.get("value")
            kind = entry.get('type', 'number')
            numeric = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            textual = isinstance(value, str)
            accepted = (numeric if kind == 'number' else textual if kind == 'string' else
                        ((numeric and value >= 0 and float(value).is_integer()) or
                         (textual and re.fullmatch(r'[01Xx]{1,64}', value))) if kind == 'bitfield' else
                        (numeric or textual) if kind == 'status' else False)
            if not accepted:
                readings[pid] = _reading(reason="non_numeric" if kind == 'number' else 'type_mismatch')
                continue
            source_unit = _UNIT_ALIASES.get(unit.lower(), unit)
            target_unit = entry.get("unit")
            if target_unit is None and entry.get('unit_policy') == 'reported':
                readings[pid] = dict(_reading(value), unit=source_unit)
                continue
            if source_unit != target_unit:
                factor = _CONVERSIONS.get((source_unit, target_unit))
                if factor is None or not numeric:
                    readings[pid] = _reading(reason="unit_mismatch")
                    continue
                value *= factor
            readings[pid] = _reading(value)
    return readings
