"""Default white navigation, exact stock bar and independent native/custom icons.

Stock translations change only verified57 anchors, retaining flags and glyph
bytes. This is UI placement of stock glyphs, not the complete OEM screen layout.
"""
from functools import lru_cache
import math
from stock_mono_frame import StockMonoFrameCompiler, records_from_stream
from display_resolution import high_resolution
from nav_icons import canvas_for_icon
from icons import BITMAPS

# Native types are renderer object bytes, not HUDIY maneuver enums.
STOCK_X_OFFSETS = {0x00: -3, 0x40: -3, 0xC0: -12}
STOCK_Y_OFFSET = -3  # Requested total six physical pixels up, where anchors permit.
_BASE_X_OFFSETS = {
    (13, 0): -3, (13, 32): -3, (13, 64): -3, (13, 96): -3,
    (13, 160): -6, (13, 192): -12, (13, 224): -6,
    (25, 64): -3, (25, 192): -6, (19, 64): -3, (19, 192): -6,
    (21, 0): -3, (21, 32): -3, (21, 64): -3, (21, 96): -3,
    (21, 128): -3, (21, 160): -6, (21, 192): -12, (21, 224): -6,
    (16, 64): -3, (15, 192): -6,
    (256, 0): -3,  # Named synthesized departure, never a raw firmware type.
}
_DEPARTURE_RECORDS = tuple(bytes.fromhex(r) for r in (
    '57040b15080b', '57040b1b080c', '57040b21080d',
    '57040b1b0f3a', '57040b1b1a41', '57040b1b2141'))


def icon_style(navigation):
    value = navigation.get('icon_style', 'stock' if navigation.get('renderer') == 'stock' else 'bitmap')
    if value == 'custom':
        return 'bitmap'
    if value not in ('stock', 'bitmap'):
        raise ValueError('navigation.icon_style must be stock or bitmap (custom is a legacy alias)')
    return value


def white_navigation_enabled(config, navigation):
    if (config.get('display') or {}).get('font_resolution') == 'legacy':
        return False
    explicit = navigation.get('icon_style') in ('stock', 'bitmap')
    return high_resolution(config) or explicit


@lru_cache(maxsize=64)
def normal_icon_canvas(name):
    """Exact existing32x38 artwork doubled pixel-for-pixel into white canvas."""
    bitmap = BITMAPS.get(str(name).upper(), BITMAPS['STRAIGHT'])
    if (bitmap['w'], bitmap['h']) != (32, 38) or len(bitmap['data']) != 152:
        raise ValueError('Normal navigation asset dimensions changed')
    canvas = bytearray(1536)
    for y in range(38):
        for x in range(32):
            if bitmap['data'][y * 4 + x // 8] & (128 >> (x % 8)):
                for py in (2 + y * 2, 3 + y * 2):
                    for px in (8 + x * 2, 9 + x * 2):
                        canvas[py * 16 + px // 8] |= 128 >> (px % 8)
    return bytes(canvas)


def native_selection(app):
    if type(app.maneuver_type) is not int or type(app.maneuver_side) is not int:
        return None
    kind, side = app.maneuver_type, app.maneuver_side
    if kind == 1:
        return (256, 0)
    if kind in (2, 14):
        return (13, 0)
    if kind in (3, 4, 5, 7) and side in (1, 2):
        directions = {3: (32, 224), 4: (64, 192), 5: (96, 160), 7: (64, 192)}
        return (13, directions[kind][side - 1])
    if kind == 8 and side in (1, 2):
        return (16, 64) if side == 1 else (15, 192)
    if kind in (11, 12):
        # User-selected generic ring, not an inferred exit angle/circulation.
        return (21, 0)
    if kind == 9 and side in (1, 2):
        return (19, 64 if side == 1 else 192)
    if kind == 6:
        if side in (1, 2):
            return (25, 64 if side == 1 else 192)
        if side == 3 and app.road_side in ('right', 'left'):
            return (25, 64 if app.road_side == 'right' else 192)
    if kind == 13 and app.maneuver_angle_present is True and app.road_side in ('right', 'left'):
        angle = app.maneuver_angle
        if (isinstance(angle, (int, float)) and not isinstance(angle, bool)
                and 0 <= angle <= 0xFFFFFFFF and math.isfinite(angle)):
            q = int(math.floor(((angle % 360) + 22.5) / 45)) % 8
            return (21, ((128 + q * 32) if app.road_side == 'right' else (128 - q * 32)) % 256)
    return None


def native_direction(app):
    """Compatibility helper for the three original ordinary directions."""
    selected = native_selection(app)
    return selected[1] if selected and selected[0] == 13 and selected[1] in STOCK_X_OFFSETS else None


@lru_cache(maxsize=1)
def native_bar_levels():
    levels = StockMonoFrameCompiler().data['bar']
    if len(levels) != 21:
        raise ValueError('Native bar requires the proved21 levels')
    result = []
    for level in levels:
        records = records_from_stream(bytes.fromhex(level))
        if (len(records) != 5 or any(r[0] != 0x57 or r[2] != 0x0A
                or r[3] != 57 or r[4] != y or len(r) != 6
                for r, y in zip(records, (3, 10, 17, 24, 31)))):
            raise ValueError('Native bar differs from reviewed table')
        result.append(tuple((r[3], r[4], r[5]) for r in records))
    return tuple(result)


@lru_cache(maxsize=22, typed=True)
def _positioned_native_details(kind, direction):
    """Exact catalog glyphs; derive bounded placement without applying52 clips.

    Canonical mapping offsets fit ink. Tighten x for the complete12px cell;
    clamp requested upward shift only when a source anchor would underflow.
    Background height/opacity remain bench concerns; overlays draw last.
    """
    if type(kind) is not int or type(direction) is not int or (kind, direction) not in _BASE_X_OFFSETS:
        raise ValueError('Native object is outside reviewed semantic mapping')
    if (kind, direction) == (256, 0):
        raw = _DEPARTURE_RECORDS
    else:
        source = bytes((0, 2, 1, kind, direction, 0)).hex()
        native = StockMonoFrameCompiler().data['icons']['render'][source]['stream']
        records = records_from_stream(bytes.fromhex(native))
        if records[0] != bytes.fromhex('520502001b3628') or not records[1:]:
            raise ValueError('Native icon framing changed')
        raw = records[1:]
    if any(r[0] != 0x57 or r[2] != 0x0B or len(r) != 6 for r in raw):
        raise ValueError('Native icon records changed')
    dx = min(_BASE_X_OFFSETS[(kind, direction)], 33 - max(r[3] for r in raw))
    dy = max(STOCK_Y_OFFSET, -min(r[4] for r in raw))
    output = []
    for r in raw:
        x, y = r[3] + dx, r[4] + dy
        if not 0 <= x <= 33 or not 0 <= y < 39:
            raise ValueError('Translated complete native cell outside icon field')
        output.append(bytes((r[0], r[1], r[2], x, y)) + r[5:])
    return tuple(output), dx, dy


def positioned_native_records(kind, direction):
    return _positioned_native_details(kind, direction)[0]


def positioned_stock_records(direction):
    if type(direction) is not int or direction not in STOCK_X_OFFSETS:
        raise ValueError('Only ordinary native straight/left/right in compatibility API')
    return positioned_native_records(13, direction)


def approach_level(app):
    if app.meters < 0:
        return 0
    height = app._get_progress_height()
    raw = max(0, min(255, (height * 255 + 24) // 48))
    return (raw * 100 // 255) // 5


def approach_visible(app):
    navigation = (((app.config.get('display') or {}).get('center_display') or {}).get('navigation') or {})
    limit = navigation.get('approach_bar_max_distance', 300)
    if (isinstance(limit, bool) or not isinstance(limit, (int, float))
            or not math.isfinite(limit) or limit <= 0):
        limit = 300
    return 0 <= app.meters <= limit


def distance_parts(app, width=32):
    if app.meters < 0:
        return ('?', '') if app.distance_label else ('', '')
    imperial = app.get_effective_unit('speed', 'imperial') == 'imperial'
    if imperial:
        value, unit, fractional = (app.meters * 3.28084, 'ft', False) if app.meters < 160.9 else (app.meters / 1609.344, 'mi', True)
    else:
        value, unit, fractional = (app.meters, 'm', False) if app.meters < 1000 else (app.meters / 1000, 'km', True)
    return app._fit_distance_value(value, fractional, width), unit


def road_name(app):
    street = app.description
    for prefix in ('Turn left onto ', 'Turn right onto ', 'Turn left into ', 'Turn right into ',
                   'Keep left onto ', 'Keep right onto ', 'Head onto ', 'Continue onto ',
                   'Take the ', ' toward ', ' towards '):
        if prefix.lower() in street.lower():
            return street.lower().split(prefix.lower(), 1)[-1]
    return street


def global_white_view(app, navigation):
    preferred = icon_style(navigation)
    if not white_navigation_enabled(app.config, navigation):
        return None
    selection = native_selection(app) if preferred == 'stock' else None
    stock = selection is not None
    icon_key = app._get_icon_name()
    level = approach_level(app)
    visible = approach_visible(app)
    # Ordered native field IDs retain every constituent. A changed object
    # flushes its previous composition; approach changes remain partial.
    if stock:
        records, dx, dy = _positioned_native_details(*selection)
        kind = 'nav_white_stock_%02x_%02x_x%d_y%d' % (*selection, dx, dy)
    else:
        kind = 'nav_white_%s_bitmap_%s' % ('stock_fallback' if preferred == 'stock' else 'direct',
                                          'high' if high_resolution(app.config) else 'normal')
    view = [dict(type=kind, clear_on_update=True, text_profile='native')]
    if stock:
        view.append(dict(group='icon', cmd='clear_area', x=0, y=0, w=39, h=39))
        for index, record in enumerate(records):
            view.append(dict(group='icon', cmd='draw_native_font', flags=record[2],
                             x=record[3], y=record[4], glyphs=list(record[5:]),
                             field_id='nav_icon_%02x_%02x_%02d' % (*selection, index)))
        dependency = ('stock', *selection, dx, dy)
    else:
        order = navigation.get('native_render_order', 'planes')
        if order not in ('planes', 'tiles'):
            order = 'planes'
        delay = navigation.get('native_message_delay_ms', 5)
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 0 <= delay <= 100:
            delay = 5
        canvas = canvas_for_icon(icon_key) if high_resolution(app.config) else normal_icon_canvas(icon_key)
        view.append(dict(group='icon', cmd='native_bitmap', update_rect=[6, 0, 72, 78],
                         preserves_overlays=True, data_hex=canvas.hex(),
                         render_order=order, post_message_delay_s=delay / 1000))
        dependency = None
    # Each native cell has its own dirty signature. Cold/full snapshots draw
    # all five; progress updates replace only changed glyphs, without a strip
    # clear or a sweep of unchanged cells. Opaque replacement needs bench proof.
    cells = native_bar_levels()[level] if visible else ()
    for x, y, glyph in cells:
        view.append(dict(group='bar_%d' % y, cmd='draw_native_font', flags=0x0A, x=x, y=y, glyphs=[glyph],
                         field_id='nav_bar_%d' % y))
    if not visible:
        # Retire the five exact desired cells as well as their pixels. This
        # group changes only on crossing the approach boundary; no full clear.
        view.append(dict(group='bar_visibility', cmd='clear_area', x=57, y=3, w=6, h=36,
                         retire_native_field_ids=['nav_bar_%d' % y for y in (3, 10, 17, 24, 31)]))
    if preferred == 'bitmap':
        value, unit = distance_parts(app)
        for y, text in ((8, value), (17, unit)):
            width = app.text_width(text, 6)
            if width > 32:
                raise ValueError('Complete numeric/unit field exceeds32px')
            x = 40 + (32 - width) // 4
            view += [dict(group='dist', cmd='clear_area', x=40, y=y, w=16, h=9),
                     dict(group='dist', cmd='draw_text', text=text, x=x, y=y, flags=6)]
    street = road_name(app)
    width = 124
    scrolling = not app.text_fits(street, width, flags=6)
    text = app._scroll_text(street, 'nav_white_street', max_width_px=width, font_flags=6, align='left')
    x = 1 if scrolling else 1 + max(0, (width - app.text_width(text, 6)) // 4)
    # Only the bottom y31 cell's possible background can reach street y39.
    # Duplicate native levels and upper-cell updates do not resend the road.
    stamp = (dependency, visible, cells[-1][2] if visible else None)
    view += [dict(group='street', cmd='clear_area', x=0, y=39, w=64, h=9, dependency=stamp),
             dict(group='street', cmd='draw_text', text=text, x=x, y=39, flags=6, dependency=stamp)]
    if not stock:
        # The bounded bitmap touches only the icon field. Show the fast bar
        # and text first, keeping street repair after native bar cells.
        icon_items = [item for item in view[1:] if item.get('group') == 'icon']
        view = view[:1] + [item for item in view[1:] if item.get('group') != 'icon'] + icon_items
    return view
