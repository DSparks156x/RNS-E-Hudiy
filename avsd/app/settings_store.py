"""The chain's settings. hud2.sh sources two files at chain start, plain NAME=value lines:
  ~/avsd/avsd.env                     saved
  $XDG_RUNTIME_DIR/avsd-trial.env     Apply. tmpfs, so a reboot drops it and a bad value can't outlive one

They're sourced as shell, so only known names and numbers inside the limits get written. Limits are DEPLOYMENT.md's safe ranges.
Other lines in avsd.env (comments, ENCEXTRA for an experiment) are yours and stay.
"""
import os
import re

MEGA = 1000000


def _range(name, label, low, high, step, default, unit='', scale=1, decimals=0, help_text=''):
    return {'id': name, 'label': label, 'kind': 'range', 'min': low, 'max': high, 'step': step, 'default': default,
            'unit': unit, 'scale': scale, 'decimals': decimals, 'help': help_text}


def _choice(name, label, options, default, help_text=''):
    return {'id': name, 'label': label, 'kind': 'choice', 'default': default, 'help': help_text,
            'options': [{'value': value, 'label': text} for value, text in options]}


FIELDS = [
    _range('GAIN', 'Audio gain', -30, -3, 1, -3, 'dB', help_text='Use -6 or lower with a tone or EQ boost.'),
    _range('CYC', 'Decode limit', 3000000, 4050000, 50000, 4050000, 'M', MEGA, 2, 'Safety limit. Lower it first if audio skips.'),
    _range('LINKCAP', 'Video rate', 3200000, 4500000, 100000, 4500000, 'MB/s', MEGA, 1, 'Higher risks stutter or audio gaps.'),
    _range('MAXVID', 'Largest video frame', 130, 161, 1, 161, 'sectors', help_text='161 is the RNS-E limit.'),
    _choice('KEYINT', 'Full refresh', [(0, 'When asked'), (240, '240 frames'), (480, '480 frames'), (960, '960 frames'), (1800, '1800 frames')], 0,
            'Short intervals soften the picture on each one.'),
    _choice('DITHER', 'Dither', [(0, 'Off'), (1, 'On')], 0, 'Dithers smooth areas. Costs decode time.'),
    _range('SRCDEAD', 'Noise floor', 0, 6, 1, 3, 'levels', help_text='Ignores changes this small. High holds stale colour.'),
    _range('SRCMEAN', 'Noise mean', 12, 64, 4, 48, help_text='Low gives more updates. High holds fades back.'),
    _range('FILLPEN', 'Fill penalty', 1, 4, 1, 2, help_text='Higher means fewer mosaics.'),
    _choice('ENCTHREADS', 'Encoder threads', [(2, '2'), (3, '3')], 2, '3 gains little and takes CPU from Hudiy.'),
    _range('RTPRIO', 'Real-time priority', 0, 5, 1, 5, help_text='0 is off, which risks video stutter.'),
]
BY_ID = {field['id']: field for field in FIELDS}
DEFAULTS = {field['id']: field['default'] for field in FIELDS}
LINE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$')
NUMBER = re.compile(r'^-?\d+(?:\.\d+)?(?:[eE]\d+)?$')


def field_allows(field, value):
    if type(value) is not int:
        return False
    if field['kind'] == 'choice':
        return value in [option['value'] for option in field['options']]
    return field['min'] <= value <= field['max'] and (value - field['min']) % field['step'] == 0


def validate(values):
    if not isinstance(values, dict) or set(values) != set(BY_ID):
        raise ValueError('Every setting must be sent.')
    for key, value in values.items():
        if not field_allows(BY_ID[key], value):
            raise ValueError('%s is out of range.' % BY_ID[key]['label'])
    return dict(values)


def parse_env(text, base=None):
    """Known settings with a usable value, on top of base. Anything else reads as if the line wasn't there."""
    values = dict(base or DEFAULTS)
    for line in text.splitlines():
        match = LINE.match(line)
        if not match or match.group(1) not in BY_ID or not NUMBER.match(match.group(2).strip()):
            continue
        number = float(match.group(2))
        if number == int(number) and field_allows(BY_ID[match.group(1)], int(number)):
            values[match.group(1)] = int(number)
    return values


def render_env(values, existing=''):
    """Changes known lines where they are and leaves the rest. A setting at its default needs no new line."""
    written = set()
    out = []
    for line in existing.splitlines():
        match = LINE.match(line)
        if match and match.group(1) in BY_ID:
            if match.group(1) not in written:
                out.append('%s=%d' % (match.group(1), values[match.group(1)]))
                written.add(match.group(1))
        else:
            out.append(line)
    for field in FIELDS:
        if field['id'] not in written and values[field['id']] != field['default']:
            out.append('%s=%d' % (field['id'], values[field['id']]))
    return '\n'.join(out) + '\n'


def without_settings(existing):
    """Deleting a line returns that setting to its default."""
    kept = [line for line in existing.splitlines() if not ((LINE.match(line) or [None, None])[1] in BY_ID)]
    return '\n'.join(kept) + '\n' if kept else ''


def _write_atomic(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    temporary = str(path) + '.tmp'
    with open(temporary, 'w') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ''


class SettingsStore:
    def __init__(self, paths, chain):
        self.paths, self.chain = paths, chain

    def saved(self):
        return parse_env(_read(self.paths.env))

    def values(self):
        """What the chain runs with after its next start."""
        return parse_env(_read(self.paths.trial), self.saved())

    def _clear_trial(self):
        try:
            self.paths.trial.unlink()
        except FileNotFoundError:
            pass

    def apply(self, values):
        """Until the next reboot."""
        values = validate(values)
        if values == self.saved():
            self._clear_trial()
        else:
            _write_atomic(self.paths.trial, ''.join('%s=%d\n' % (name, values[name]) for name in BY_ID))
        self.chain.restart()
        return self.snapshot()

    def save(self, values):
        """For good. The chain only restarts if this isn't what it's already running."""
        values = validate(values)
        running = self.values()
        _write_atomic(self.paths.env, render_env(values, _read(self.paths.env)))
        self._clear_trial()
        if values != running:
            self.chain.restart()
        return self.snapshot()

    def restore_defaults(self):
        existing = _read(self.paths.env)
        if existing:
            _write_atomic(self.paths.env, without_settings(existing))
        self._clear_trial()
        self.chain.restart()
        return self.snapshot()

    def snapshot(self):
        values, saved = self.values(), self.saved()
        return {
            'fields': FIELDS,
            'values': values,
            'saved': saved,
            'defaults': DEFAULTS,
            'temporary': values != saved,
            # ENCFLAGS replaces the encoder's flag block and silently ignores several of these.
            'encflags_override': any((LINE.match(line) or [None, None])[1] == 'ENCFLAGS' for line in _read(self.paths.env).splitlines()),
        }
