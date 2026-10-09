"""Raw stock navigation graphics, without Unicode/AUDSCII conversion.

52-window clusters use57 graphics-font text;7A-window clusters use69 symbol
records. These are cluster-owned glyphs, not bitmap pixel data. The catalog
keeps raw firmware maneuver/direction selectors; visual names are unresolved.
No CAN I/O, window negotiation, or packet flush is performed here.
"""
import hashlib
import json
from pathlib import Path

STOCK_OSM_SHA256 = '9edf419c023b97c3e1b435f8a47ac3c168f8e3146e084d6aa82b0425d91e5ba2'


def _integer(value, maximum, name):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('%s must be an integer in0..%d' % (name, maximum))
    return value


def _profile(capability):
    """Check actual09 negotiation; do not infer fonts from opaque tail bytes."""
    family = getattr(capability, 'command_family', None)
    fmt = getattr(capability, 'format_code', None)
    company = getattr(capability, 'company_code', None)
    if family == 0x52 and fmt == 0x20:
        return 'mono'
    if family == 0x7A and fmt == 0x10 and company == 0x03:
        return 'hicolor'
    raise ValueError('Native navigation renderer is not verified for this capability family')


def raw_graphics_record(capability, x, y, glyph_bytes, flags=0x0B):
    """Exact805624E6/805637A2 layout:57,len,flags,x,y,binary glyphs.

    The49-byte per-record budget is stock805546E4, not an inferred09 field.
    Caller owns window permission and transport packetization. Flags are raw;
    do not apply ordinary text normal/invert/font masks to these records.
    """
    if _profile(capability) != 'mono':
        raise ValueError('57 graphics font requires the negotiated52 family')
    x = _integer(x, 255, 'x'); y = _integer(y, 255, 'y')
    flags = _integer(flags, 255, 'flags')
    glyphs = bytes(_integer(v, 255, 'glyph') for v in glyph_bytes)
    if not 1 <= len(glyphs) <= 44:
        raise ValueError('Graphics record requires1..44 glyph bytes')
    return bytes((0x57, len(glyphs) + 3, flags, x, y)) + glyphs


def raw_symbol_records(capability, symbols):
    """Exact8055D8B8 layout:69,4*n,{x,y,symbolLow,symbolHigh}.

    Split only between four-byte symbol entries, at the stock128-byte record
    budget. Symbol IDs retain every16-bit value; no guessed bitmap encoding.
    """
    if _profile(capability) != 'hicolor':
        raise ValueError('69 symbols require the negotiated7A family')
    values = []
    for x, y, symbol in symbols:
        values.append(bytes((_integer(x, 255, 'x'), _integer(y, 255, 'y'),
                             _integer(symbol, 65535, 'symbol') & 255, symbol >> 8)))
    return tuple(bytes((0x69, len(part) * 4)) + b''.join(part)
                 for start in range(0, len(values), 31)
                 for part in (values[start:start + 31],))


def commit_record(capability):
    """Common stock39 transaction terminator8055B0AA for verified renderers.

    Does not acquire a window or flush queued transport data by itself.
    """
    _profile(capability)
    return b'\x39'


class StockNavGlyphCatalog:
    """Packaged exact ROM placements, addressed by raw firmware selectors.

    Mono absolute lookup matches139 actual SH4 cases805636E4; hicolor lookup
    matches129 cases8055ED68. Relative placement selection and writing also
    have independent stock p-code parity. Whole maneuver-object parsing and
    screen-state transitions are not reconstructed by these small builders.
    """
    def __init__(self, path=None):
        path = Path(path) if path is not None else Path(__file__).with_name('native_nav_catalog.json')
        raw = path.read_bytes()
        digest = path.with_suffix('.sha256').read_text(encoding='ascii').split()[0]
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Native navigation catalog checksum mismatch')
        catalog = json.loads(raw)
        if catalog.get('schema') != 1 or catalog.get('stock_sha256') != STOCK_OSM_SHA256:
            raise ValueError('Native navigation catalog source/schema mismatch')
        self.catalog = catalog

    def selectors(self, capability):
        profile = _profile(capability)
        return tuple((t['type'], tuple(r['direction'] for r in t['single']),
                      tuple((p['direction_first'], tuple(r['direction'] for r in p['rows']))
                            for p in t['paired'])) for t in self.catalog['profiles'][profile])

    def _lookup(self, profile, maneuver_type, directions):
        kind = _integer(maneuver_type, 255, 'maneuver type')
        directions = tuple(_integer(v, 255, 'direction') for v in directions)
        if len(directions) not in (1, 2):
            raise ValueError('Stock maneuver selection requires one or two raw directions')
        entry = next((t for t in self.catalog['profiles'][profile] if t['type'] == kind), None)
        if entry is None:
            raise ValueError('No verified stock maneuver type')
        pair = None
        if len(directions) == 1:
            rows = entry['single']; key = directions[0]
        else:
            pair = next((p for p in entry['paired'] if p['direction_first'] == directions[0]), None)
            if pair is None:
                raise ValueError('No verified stock paired maneuver')
            rows = pair['rows']; key = directions[1]
        row = next((r for r in rows if r['direction'] == key), None)
        if row is None:
            raise ValueError('No verified stock direction row')
        return row, pair

    @staticmethod
    def _records(capability, units):
        if _profile(capability) == 'mono':
            return tuple(raw_graphics_record(capability, x, y, (glyph,))
                         for x, y, glyph in units)
        # Maneuver ROM units already contain low/high wire-order bytes.
        return raw_symbol_records(capability, ((x, y, lo | hi << 8)
                                              for x, y, lo, hi in units))

    def absolute_records(self, capability, maneuver_type, directions):
        """Select main stock placement by raw type/direction bytes.

        Lane supplements, clearing, distance bars, headers, and screen-state
        presentation remain separate. Missing selectors raise; no guessed
        visual fallback. Hicolor is a69 symbol record, mono is57 font text.
        """
        row, _ = self._lookup(_profile(capability), maneuver_type, directions)
        return self._records(capability, row['units'])

    def auxiliary_descriptor(self, capability, maneuver_type, directions, *,
                             clear=False, position=0):
        """Exact table+offset selection from four stock single/paired helpers.

        Returns (dx,dy,ROM pointer string). Position is a raw firmware selector,
        not degrees of rotation. A zero pointer is a stock no-output branch.
        Stock mono lane bookkeeping side effects are outside this builder.
        """
        if type(clear) is not bool:
            raise ValueError('clear must be bool')
        position = _integer(position, 2, 'position')
        profile = _profile(capability)
        row, pair = self._lookup(profile, maneuver_type, directions)
        offset = (0, 0); pointer = '00000000'
        if pair is None:
            if position == 2:
                raise ValueError('Single-direction placement accepts position0 or1')
            if clear:
                pointer = row['auxiliary_pointer']
            else:
                pointer = row['shifted_auxiliary_pointer']
                offset = row['offset_first' if position == 0 else 'offset_second']
        elif profile == 'mono':
            if not clear and position == 0:
                pointer = pair['shifted_auxiliary_pointer']; offset = pair['offset_first']
        elif clear:
            pointer = pair['auxiliary_pointer'] if position == 1 else row['auxiliary_pointer']
        else:
            pointer = pair['shifted_auxiliary_pointer']
            offset = (pair['offset_first'] if position == 0 else pair['offset_second']
                      if position == 1 else row['offset_first'])
        return offset[0], offset[1], pointer

    def auxiliary_records(self, capability, maneuver_type, directions, key, *,
                          clear=False, position=0):
        """Compose stock supplemental glyphs from raw key and placement.

        Coordinates wrap modulo256 exactly like the stock writers. No visual
        meaning for raw keys or maneuver kinds is inferred from their numbers.
        """
        key = _integer(key, 255, 'auxiliary key')
        dx, dy, pointer = self.auxiliary_descriptor(capability, maneuver_type,
                                                   directions, clear=clear, position=position)
        if pointer == '00000000':
            return ()
        rows = self.catalog['auxiliary'][_profile(capability)].get(pointer)
        if rows is None:
            raise ValueError('No verified stock auxiliary table')
        row = next((r for r in rows if r['key'] == key), None)
        if row is None:
            raise ValueError('No verified stock auxiliary key')
        units = [[(u[0]+dx) & 255, (u[1]+dy) & 255]+u[2:] for u in row['units']]
        return self._records(capability, units)

    def frame_records(self, capability, index):
        """Exact8055D102 hicolor frame/control record sequence, raw index0..15.

        Index0 is a7A window/control record, not a glyph. Other entries are83
        geometry records or69 symbols. Meanings/geometry units remain raw;
        callers must deliberately choose the record and own window state.
        """
        if _profile(capability) != 'hicolor':
            raise ValueError('Hicolor stock frames require negotiated7A family')
        index = _integer(index, 15, 'frame index')
        row = next(r for r in self.catalog['hicolor_frames'] if r['index'] == index)
        return tuple(bytes.fromhex(record) for record in row['records_hex'])
