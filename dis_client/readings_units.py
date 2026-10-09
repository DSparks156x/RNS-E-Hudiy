"""Cached unit legends for the nine-pixel DIS unit column.

These masks are static labels only. Changing readings continue to use the native
DIS text commands. Every catalog unit has a deliberate case-sensitive legend.
"""
from functools import lru_cache


# Upper/lower case remain distinct. Lowercase m receives five columns wherever
# possible: its two arches must not collapse into the old n-shaped legend.
GLYPHS = {
    'A': ['010', '101', '111', '101', '101'],
    'B': ['110', '101', '110', '101', '110'],
    'C': ['111', '100', '100', '100', '111'],
    'D': ['110', '101', '101', '101', '110'],
    'E': ['111', '100', '110', '100', '111'],
    'F': ['111', '100', '110', '100', '100'],
    'G': ['111', '100', '101', '101', '111'],
    'H': ['101', '101', '111', '101', '101'],
    'I': ['111', '010', '010', '010', '111'],
    'J': ['001', '001', '001', '101', '111'],
    'K': ['101', '101', '110', '101', '101'],
    'L': ['100', '100', '100', '100', '111'],
    'M': ['101', '111', '111', '101', '101'],
    'N': ['101', '111', '111', '111', '101'],
    'O': ['111', '101', '101', '101', '111'],
    'P': ['110', '101', '110', '100', '100'],
    'Q': ['111', '101', '101', '111', '001'],
    'R': ['110', '101', '110', '101', '101'],
    'S': ['111', '100', '111', '001', '111'],
    'T': ['111', '010', '010', '010', '010'],
    'U': ['101', '101', '101', '101', '111'],
    'V': ['101', '101', '101', '101', '010'],
    'W': ['101', '101', '111', '111', '101'],
    'X': ['101', '101', '010', '101', '101'],
    'Y': ['101', '101', '010', '010', '010'],
    'Z': ['111', '001', '010', '100', '111'],
    'a': ['000', '011', '101', '111', '101'],
    'b': ['100', '100', '110', '101', '110'],
    'c': ['000', '000', '011', '100', '011'],
    'd': ['001', '001', '011', '101', '011'],
    'e': ['000', '011', '111', '100', '011'],
    'f': ['011', '010', '111', '010', '010'],
    'g': ['000', '011', '101', '011', '110'],
    'h': ['100', '100', '110', '101', '101'],
    'i': ['010', '000', '010', '010', '010'],
    'j': ['001', '000', '001', '101', '010'],
    'k': ['100', '101', '110', '101', '101'],
    'l': ['100', '100', '100', '100', '010'],
    'm': ['11010', '10101', '10101', '10101', '10101'],
    'n': ['000', '000', '110', '101', '101'],
    'o': ['000', '000', '111', '101', '111'],
    'p': ['000', '110', '101', '110', '100'],
    'q': ['000', '011', '101', '011', '001'],
    'r': ['000', '000', '110', '101', '100'],
    's': ['011', '100', '010', '001', '110'],
    't': ['010', '111', '010', '010', '011'],
    'u': ['000', '000', '101', '101', '111'],
    'v': ['000', '000', '101', '101', '010'],
    'w': ['00000', '10101', '10101', '10101', '01010'],
    'x': ['000', '000', '101', '010', '101'],
    'y': ['000', '101', '101', '011', '110'],
    'z': ['000', '111', '001', '010', '111'],
    '0': ['111', '101', '101', '101', '111'],
    '1': ['010', '110', '010', '010', '111'],
    '2': ['110', '001', '010', '100', '111'],
    '3': ['110', '001', '010', '001', '110'],
    '4': ['101', '101', '111', '001', '001'],
    '5': ['111', '100', '110', '001', '110'],
    '6': ['011', '100', '111', '101', '111'],
    '7': ['111', '001', '010', '010', '010'],
    '8': ['111', '101', '111', '101', '111'],
    '9': ['111', '101', '111', '001', '110'],
    '/': ['001', '001', '010', '100', '100'],
    '.': ['000', '000', '000', '000', '010'],
    ',': ['000', '000', '000', '010', '100'],
    ':': ['000', '010', '000', '010', '000'],
    '-': ['000', '000', '111', '000', '000'],
    '+': ['000', '010', '111', '010', '000'],
    '=': ['000', '111', '000', '111', '000'],
    ' ': ['0'] * 5,
    '°': ['11', '11', '00', '00', '00'],
    '²': ['110', '010', '110', '000', '000'],
}


def _text(text, gap=1):
    glyphs = [GLYPHS[char] for char in text]
    return [('0' * gap).join(glyph[row] for glyph in glyphs) for row in range(5)]


def _mask(*lines):
    result = []
    for line in lines:
        rows = _text(line) if isinstance(line, str) else line
        if result:
            result.append('0' * 9)
        result.extend(rows)
    width = max((len(row) for row in result), default=0)
    if width > 9 or len(result) > 11:
        raise ValueError('Unit legends must fit 9×11 physical pixels')
    return [row.ljust(width, '0') for row in result]


# Accepted legacy artwork is intentionally byte-for-byte unchanged.
UNITS = {
    '°C': ['1100111', '1100100', '0000100', '0000100', '0000111'],
    'bar': ['100000000', '100010010', '110101011', '101111010', '110101010'],
    'g/s': ['111001011', '101001100', '011010010', '001010001', '110000110'],
    '°': ['11', '11', '00', '00', '00'],
    '%': ['11001', '11010', '00100', '01011', '10011'],
    'rpm': ['110110101', '101101111', '101101111', '110110101',
            '101100101', '101100101', '101100101'],
    'ms': _mask('ms'),
    'Nm': _mask([a+b for a, b in zip(['1001', '1101', '1101', '1011', '1001'], GLYPHS['m'])]),
    'mA': _mask('mA'),
    'mm': _mask(['110111010', '101010101', '101010101', '101010101', '101010101']),
    'cm': _mask('cm'),
    'km': _mask('km'),
    'mi': _mask('mi'),
    's': _mask(['01111', '10000', '01110', '00001', '11110']),
    'min': _mask('mi', 'n'),
    'mbar': _mask('m', ['100000000', '100010010', '110101011', '101111010', '110101010']),
    'kPa': _mask(_text('kPa', gap=0)),
    'Pa': _mask('Pa'),
    'hPa': _mask(_text('hPa', gap=0)),
    'psi': _mask(_text('psi', gap=0)),
    'km/h': _mask('km', '/h'),
    'mph': _mask('m', 'ph'),
    'mpg': _mask('m', 'pg'),
    'km/L': _mask('km', '/L'),
    'L/h': _mask('L', '/h'),
    'L/min': _mask(['1000001', '1000010', '1110100'],
                   ['110100100', '101010000', '101010100'],
                   ['110', '101', '101']),
    'deg/s': _mask('°', '/s'),
    'W/m2': _mask('W/', _text('m²')),
    'm/s': _mask('m', '/s'),
    'm/s2': _mask('m/', _text('s²', gap=1)),
    'kg/h': _mask('kg', '/h'),
    'kg/s': _mask('kg', '/s'),
    'Hz': _mask('Hz'),
    'kHz': _mask('k', 'Hz'),
    'V': _mask(['10001', '10001', '10001', '10001', '01010', '01010', '00100']),
    'A': _mask(['01110', '10001', '10001', '11111', '10001', '10001', '10001']),
    'L': _mask(['10000', '10000', '10000', '10000', '10000', '10000', '11111']),
    'm': _mask('m'),
    'h': _mask(['10000', '10000', '10110', '11001', '10001']),
    'W': _mask(['10001', '10001', '10101', '10101', '10101', '10101', '01010']),
    'kW': _mask('kW'),
    '°F': _mask('°F'),
    'Ω': _mask(['01110', '10001', '10001', '01010', '11011']),
    # L / 100 km retains all symbols, using three three-pixel lines.
    'L/100km': _mask(['1000001', '1000010', '1110100'],
                      ['010111111', '110101101', '010111111'],
                      ['100011010', '110010101', '101010101']),
    # Dimensionless numbers and event/counter states need no unit legend.
    'count': [],
    '': [],
}
UNITS['C'] = UNITS['°C']
UNITS['deg'] = UNITS['°']
UNITS['RPM'] = UNITS['rpm']
UNITS['ohm'] = UNITS['Ω']
UNITS['°/s'] = UNITS['deg/s']
UNITS['W/m²'] = UNITS['W/m2']
UNITS['m/s²'] = UNITS['m/s2']
UNITS['°c'] = UNITS['°C']
UNITS['°f'] = UNITS['°F']


@lru_cache(maxsize=128)
def unit_rows(unit):
    """Return bounded static rows; do not uppercase unknown reported units.

    Unknown legends wrap at glyph boundaries into at most two 3×5 lines. This
    limited fallback supports up to six narrow characters (spaces retained),
    with a final ellipsis pixel when a longer label cannot fit. Known catalog
    units never use this fallback or lose characters.
    """
    if unit is None or unit == 'None':
        return []
    unit = str(unit)
    if unit in UNITS:
        return UNITS[unit]
    narrow = dict(GLYPHS)
    narrow['m'] = ['000', '111', '111', '101', '101']
    narrow['w'] = ['000', '101', '111', '111', '101']
    # A boxed missing-glyph mark is reserved for unrecognised Unicode only.
    missing = ['111', '101', '101', '101', '111']
    lines, current, width = [], [], 0
    omitted = False
    for char in unit:
        glyph = narrow.get(char, missing)
        next_width = len(glyph[0]) + (1 if current and width+1+len(glyph[0]) <= 9 else 0)
        if current and width+next_width > 9:
            lines.append(current)
            current, width = [], 0
            if len(lines) == 2:
                omitted = True
                break
        # Three compact glyphs use all nine pixels; two use a separating column.
        current.append(glyph)
        width = sum(len(item[0]) for item in current)
    if current and len(lines) < 2:
        lines.append(current)
    rows = []
    for line in lines:
        if rows:
            rows.append('0' * 9)
        gap = 1 if sum(len(glyph[0]) for glyph in line) + len(line)-1 <= 9 else 0
        rows.extend(('0' * gap).join(glyph[row] for glyph in line).ljust(9, '0') for row in range(5))
    if omitted and rows:
        rows[-1] = rows[-1][:8] + '1'
    return rows
