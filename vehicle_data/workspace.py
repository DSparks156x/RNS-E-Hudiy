"""Persisted Data & Logs configuration shared by DataView and the DIS."""
import copy
import json
import math
import os
import re
import tempfile
import threading
from pathlib import Path

from .catalog import CATALOG

DEFAULT_VALUES = ['engine.oil_temperature', 'engine.boost.actual_absolute',
                  'engine.coolant_temperature', 'engine.maf', 'engine.intake_temperature',
                  'engine.rpm', 'transmission.fluid_temperature', 'awd.oil_temperature']
ENGINE_PULL_VALUES = ['engine.rpm', 'engine.boost.actual_absolute', 'engine.boost.spec_absolute',
                      'engine.maf', 'engine.ignition_timing', 'engine.oil_temperature',
                      'engine.coolant_temperature', 'engine.intake_temperature',
                      'engine.fuel_rail.actual', 'engine.fuel_rail.spec',
                      'engine.fuel_pump_duty', 'engine.injection_time']


def data_logs_directory(config):
    settings = config.get('data_logs', {})
    legacy = config.get('data_logger', {})
    return Path(os.path.expanduser(settings.get('directory',
                str(Path(os.path.expanduser(legacy.get('log_directory', '~/logs'))) / 'data-logs')))).resolve()


def default_workspace():
    values = [value for value in DEFAULT_VALUES if value in CATALOG]
    if len(values) < 8:
        values += [value for value in CATALOG if value not in values][:8-len(values)]
    slots = [{'value_id': value, 'icon': 'auto',
              'unit': 'bar' if value.startswith('engine.boost.') else None,
              'precision': 2 if value.startswith('engine.boost.') else 0,
              'font': 'fixed'} for value in values]
    pull = [value for value in ENGINE_PULL_VALUES if value in CATALOG]
    return {'version': 1, 'profiles': [{'id': 'daily', 'name': 'Daily', 'values': values},
                                      {'id': 'engine_pull', 'name': 'Engine pull', 'values': pull}],
            'dis_pages': [{'id': 'daily', 'name': 'Daily', 'profile_id': 'daily',
                           'slots': slots}],
            'settings': {}}


def validate_workspace(document):
    if not isinstance(document, dict):
        raise ValueError('Configuration must be an object')
    result = {'version': 1, 'profiles': [], 'dis_pages': [], 'settings': {}}
    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
            raise ValueError('IDs must contain 1–64 letters, digits, underscores or hyphens')
        return value
    def name(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise ValueError('A name must contain 1–64 characters')
        return value.strip()
    seen = set()
    profiles = document.get('profiles', [])
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 64:
        raise ValueError('Configure 1–64 recording profiles')
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError('Each profile must be an object')
        pid = identifier(profile.get('id'))
        if pid in seen:
            raise ValueError('Duplicate profile ID')
        seen.add(pid)
        values = profile.get('values', [])
        if not isinstance(values, list) or not 1 <= len(values) <= len(CATALOG):
            raise ValueError('Each profile needs at least one value')
        normalized, ids = [], set()
        for value in values:
            spec = {'id': value} if isinstance(value, str) else dict(value) if isinstance(value, dict) else {}
            vid = spec.get('id')
            if not isinstance(vid, str) or vid not in CATALOG or vid in ids:
                raise ValueError('Unknown or duplicate value: ' + str(vid))
            ids.add(vid)
            allowed = {'id', 'source', 'rate_hz', 'period_ms', 'allow_estimated', 'allow_unverified'}
            if set(spec) - allowed:
                raise ValueError('Unknown value request setting')
            source = spec.get('source', 'auto')
            if source not in ('auto', 'diag', 'ican') and source not in [p['id'] for p in CATALOG[vid]['providers']]:
                raise ValueError('Unknown value source')
            if 'rate_hz' in spec and 'period_ms' in spec:
                raise ValueError('Choose rate_hz or period_ms')
            for key in ('rate_hz', 'period_ms'):
                if key in spec and (isinstance(spec[key], bool) or not isinstance(spec[key], (int, float)) or
                                    not math.isfinite(spec[key]) or spec[key] <= 0):
                    raise ValueError('Value rates and periods must be positive and finite')
            period = spec.get('period_ms')
            if 'rate_hz' in spec:
                period = 1000 / spec['rate_hz']
            if period is not None and not 1 <= period <= 86400000:
                raise ValueError('Requested period must be between 1 ms and one day')
            for key in ('allow_estimated', 'allow_unverified'):
                if key in spec and not isinstance(spec[key], bool):
                    raise ValueError(key + ' must be boolean')
            normalized.append(value if isinstance(value, str) else spec)
        clean = {'id': pid, 'name': name(profile.get('name')), 'values': normalized}
        for key in ('allow_estimated', 'allow_unverified'):
            if key in profile:
                if not isinstance(profile[key], bool):
                    raise ValueError(key + ' must be boolean')
                clean[key] = profile[key]
        result['profiles'].append(clean)
    pages = document.get('dis_pages', [])
    if not isinstance(pages, list) or not 1 <= len(pages) <= 32:
        raise ValueError('Configure 1–32 DIS pages')
    seen_pages = set()
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError('Each DIS page must be an object')
        pid = identifier(page.get('id'))
        profile_id = page.get('profile_id', page.get('log_profile_id'))
        if pid in seen_pages or not isinstance(profile_id, str) or profile_id not in seen:
            raise ValueError('Duplicate DIS page or unknown linked profile')
        seen_pages.add(pid)
        slots = page.get('slots', [])
        if not isinstance(slots, list) or len(slots) != 8:
            raise ValueError('DIS pages require exactly eight slots')
        normalized = []
        for slot in slots:
            if not isinstance(slot, dict):
                raise ValueError('Each DIS slot must be an object')
            vid = slot.get('value_id')
            if not isinstance(vid, str) or vid not in CATALOG:
                raise ValueError('Unknown DIS value: ' + str(vid))
            precision = slot.get('precision', slot.get('decimals', 0))
            if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 3:
                raise ValueError('Precision must be 0–3')
            font = slot.get('font', 'fixed')
            if font not in ('fixed', 'proportional'):
                raise ValueError('Unknown native font')
            icon = slot.get('icon', 'auto')
            if not isinstance(icon, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', icon):
                raise ValueError('Invalid icon name')
            unit = slot.get('unit')
            if unit is not None and (not isinstance(unit, str) or len(unit) > 12):
                raise ValueError('Invalid unit')
            clean_slot = {'value_id': vid, 'icon': icon, 'unit': unit,
                          'precision': precision, 'font': font}
            for key in ('allow_estimated', 'allow_unverified'):
                if key in slot:
                    if not isinstance(slot[key], bool):
                        raise ValueError(key + ' must be boolean')
                    clean_slot[key] = slot[key]
            normalized.append(clean_slot)
        result['dis_pages'].append({'id': pid, 'name': name(page.get('name')),
                                    'profile_id': profile_id, 'slots': normalized})
    settings = document.get('settings', {})
    if not isinstance(settings, dict):
        raise ValueError('Settings must be an object')
    for key in ('review_after_stop',):
        value = settings.get(key, True)
        if not isinstance(value, bool):
            raise ValueError(key + ' must be boolean')
        result['settings'][key] = value
    return result


class WorkspaceStore:
    def __init__(self, config=None):
        config = config or {}
        self.path = Path(os.path.expanduser(config.get('data_logs', {}).get(
            'workspace_path', str(data_logs_directory(config) / 'workspace.json')))).resolve()
        self.lock = threading.RLock()

    def load(self):
        with self.lock:
            if not self.path.exists():
                return default_workspace()
            with self.path.open(encoding='utf-8') as handle:
                return validate_workspace(json.load(handle))

    def save(self, document):
        clean = validate_workspace(document)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.workspace-', dir=str(self.path.parent))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                    json.dump(clean, handle, ensure_ascii=False, indent=2, allow_nan=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return copy.deepcopy(clean)
