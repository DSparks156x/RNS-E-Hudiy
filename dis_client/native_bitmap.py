"""Full128x96 native bitmap compiler for the verified white-cluster center.

Uses measured ambient XOR mode. Wire packing primes EVERY63 after run splitting
with the verified one-zero-byte55mode1 selector. Eight-zero-byte selectors remain
available; per-message priming is a failed comparison. Standard library only;
byte input needs no Pillow. Output has no commit or feedback.
"""
from collections import defaultdict

MODEL = 'primed_xor'
PHYSICAL_WIDTH, PHYSICAL_HEIGHT = 128, 96
CELL_WIDTH, CELL_HEIGHT = 64, 48
BITMAP_BYTES = 1536


def packed_bitmap(source):
    """Accept packed MSB-first rows, or an exact128x96 Pillow mode1 image.

    Images are deliberately not resized, thresholded or dithered implicitly.
    Callers choose those transformations before compiling.
    """
    if not isinstance(source, (bytes, bytearray, memoryview)):
        if getattr(source, 'mode', None) != '1' or getattr(source, 'size', None) != (128, 96):
            raise ValueError('Expected a128x96 mode1 image or packed1536-byte bitmap')
        source = source.tobytes()
    if len(source) != BITMAP_BYTES:
        raise ValueError('Expected exactly1536 packed bytes for128x96 pixels')
    return bytes(source)


def changed_native_rect(source, previous):
    """Smallest complete-cell physical rectangle containing changed pixels."""
    target, prior = packed_bitmap(source), packed_bitmap(previous)
    left, top, right, bottom = 128, 96, -1, -1
    for index, (before, after) in enumerate(zip(prior, target)):
        difference = before ^ after
        if not difference:
            continue
        y, byte_x = divmod(index, 16)
        first = byte_x * 8 + 8 - difference.bit_length()
        last = byte_x * 8 + 8 - (difference & -difference).bit_length()
        left, right = min(left, first), max(right, last)
        top, bottom = min(top, y), max(bottom, y)
    if right < 0:
        return None
    x, y = left & ~1, top & ~1
    return [x, y, (right | 1) + 1 - x, (bottom | 1) + 1 - y]


def decode_bitmap(source):
    """Physical cell patterns: TL1/TR2/BL4/BR8."""
    data = packed_bitmap(source)
    grid = []
    for y in range(48):
        row = []
        for x in range(64):
            pattern = 0
            for bit, dx, dy in ((1, 0, 0), (2, 1, 0), (4, 0, 1), (8, 1, 1)):
                px, py = 2 * x + dx, 2 * y + dy
                if data[py * 16 + px // 8] & (0x80 >> (px % 8)):
                    pattern |= bit
            row.append(pattern)
        grid.append(row)
    return grid


def _raw_bitmap(data, y=0, height=1, mode=1):
    return dict(command='draw_raw_bitmap', x=0, y=y, w=64, h=height,
                data_hex=bytes(data).hex(), mode_flag=mode, _native_bitmap_ephemeral=True)


def _prime():
    command = _raw_bitmap(bytes(8), y=47)
    command['_native_rop_prime'] = True
    return command


def _line(x, y, length, orientation):
    return dict(command='draw_line', x=x, y=y, length=length, orientation=orientation,
                vertical=orientation == 0x10, _native_bitmap_ephemeral=True)


def _runs(cells, vertical, limit=15):
    grouped = defaultdict(list)
    for x, y in cells:
        constant, along = (x, y) if vertical else (y, x)
        grouped[constant].append(along)
    commands = []
    for constant, values in sorted(grouped.items()):
        ordered = sorted(set(values))
        at = 0
        while at < len(ordered):
            first, end = ordered[at], at + 1
            while end < len(ordered) and ordered[end] == ordered[end - 1] + 1:
                end += 1
            count = end - at
            for offset in range(0, count, limit):
                x, y = (constant, first + offset) if vertical else (first + offset, constant)
                commands.append(_line(x, y, min(limit, count - offset), 0x10 if vertical else 0x20))
            at = end
    return commands


def validate_render_options(render_order='planes', band_rows=12):
    """Validate order only; band12 is the physically compared band profile."""
    if render_order not in ('planes', 'bands', 'tiles'):
        raise ValueError('Native render_order must be planes, bands or tiles')
    if isinstance(band_rows, bool) or not isinstance(band_rows, int) or not 1 <= band_rows <= 48:
        raise ValueError('Native band_rows must be an integer1..48')
    return render_order, band_rows


def validate_update_rect(update_rect=None, render_order='tiles', delta=False):
    """Optional cell-aligned physical rectangle for opaque tiles or planes."""
    if update_rect is None:
        return None
    if render_order not in ('tiles', 'planes') or delta:
        raise ValueError('Native update_rect requires tiles or planes without delta')
    if (not isinstance(update_rect, (tuple, list)) or len(update_rect) != 4
            or any(isinstance(v, bool) or not isinstance(v, int) for v in update_rect)):
        raise ValueError('Native update_rect requires four integer physical coordinates')
    x, y, w, h = update_rect
    if (any(v % 2 for v in update_rect) or not 0 <= x < 128 or not 0 <= y < 96
            or not 0 < w <= 128 - x or not 0 < h <= 96 - y):
        raise ValueError('Native update_rect must be cell-aligned and inside128x96')
    return list(update_rect)


def compile_native_records(source, *, rows_per_command=1, render_order='planes', band_rows=12):
    """Full-center low-level records; no commit, labels or clipping between planes."""
    if isinstance(rows_per_command, bool) or not isinstance(rows_per_command, int) or not 1 <= rows_per_command <= 12:
        raise ValueError('Native bitmap rows_per_command must be an integer1..12')
    validate_render_options(render_order, band_rows)
    if render_order == 'tiles':
        raise ValueError('Completed tiles require compile_native_payloads to preserve packet boundaries')
    if render_order == 'planes':
        commands = compile_native_bitmap(source)
    else:
        grid = decode_bitmap(source)
        commands = [command for first in range(0, 48, band_rows)
                    for command in _cell_commands(grid, first, min(48, first + band_rows))]
    records = [[0x52, 5, 0, 0, 27, 64, 48]]
    for command in commands:
        if command['command'] == 'draw_raw_bitmap':
            if command.get('_native_rop_prime'):
                continue  # The wire packer owns priming after every run split.
            data = bytes.fromhex(command['data_hex'])
            for first in range(0, command['h'], rows_per_command):
                raster = data[first * 8:min(first + rows_per_command, command['h']) * 8]
                records.append([0x55, len(raster) + 3, command['mode_flag'], 0,
                                command['y'] + first, *raster])
        else:
            records.append([0x63, 4, command['orientation'], command['x'],
                            command['y'], command['length']])
    return records


def _validate_record(record):
    if not record or any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255 for value in record):
        raise ValueError('Native records must contain whole byte values')
    if len(record) < 2 or record[1] + 2 != len(record):
        raise ValueError('Invalid native record length')
    if record[0] == 0x52:
        if record != [0x52, 5, 0, 0, 27, 64, 48]:
            raise ValueError('Only the full center native clip is supported')
    elif record[0] == 0x55:
        if record == [0x55, 4, 1, 0, 47, 0]:
            return  # Verified one-zero-byte selector; no pixels are selected.
        if len(record) < 13 or record[2] not in (1, 2) or record[3] != 0:
            raise ValueError('Only known full-width native bitmap records are supported')
        rows, remainder = divmod(len(record) - 5, 8)
        if remainder or not 0 <= record[4] <= 48 - rows:
            raise ValueError('Native raster exceeds the center window')
    elif record[0] == 0x63:
        if len(record) != 6 or record[2] not in (0, 0x10, 0x20):
            raise ValueError('Unsupported native stroke')
        _, _, orientation, x, y, length = record
        if not 0 <= x < 64 or not 0 <= y < 48 or not 1 <= length <= 15:
            raise ValueError('Native stroke exceeds bounds')
        if orientation == 0 and length != 1:
            raise ValueError('Native dot must have length1')
        if orientation == 0x10 and y + length > 48 or orientation == 0x20 and x + length > 64:
            raise ValueError('Native stroke exceeds the center window')
    else:
        raise ValueError('Unsupported native graphics opcode')


def pack_native_records(records, *, budget=105, priming='each', selector_bytes=1):
    """Prime every stroke by default, with whole records and <=105-byte packets.

    Region52 is isolated; there are no57 or39 records in this snapshot body.
    Hardware established that retaining ROP between63 strokes is unreliable.
    Each emitted stroke must immediately follow a zero-mask55mode1 selector.
    priming='message' preserves the failed comparison. Both one- and eight-
    zero-byte selectors were individually confirmed on the native palette.
    """
    if priming not in ('each', 'message') or isinstance(selector_bytes, bool) or not isinstance(selector_bytes, int) or selector_bytes not in (1, 8):
        raise ValueError('Choose each/message priming and selector_bytes1 or8')
    minimum = max(13, 5 + selector_bytes + 6)
    if isinstance(budget, bool) or not isinstance(budget, int) or not minimum <= budget <= 105:
        raise ValueError('Native packet budget cannot fit a complete selector and stroke')
    packets, pending, mode = [], [], None
    primer = [0x55, selector_bytes + 3, 1, 0, 47, *([0] * selector_bytes)]
    for source in records:
        record = list(source)
        _validate_record(record)
        if len(record) > budget:
            raise ValueError('Never split a native graphics record')
        if record[0] == 0x52:
            if pending:
                packets.append(pending)
            packets.append(record)
            pending, mode = [], None
            continue
        needs_prime = record[0] == 0x63 and (priming == 'each' or mode != 1)
        required = len(record) + (len(primer) if needs_prime else 0)
        if pending and len(pending) + required > budget:
            packets.append(pending)
            pending, mode = [], None
        if record[0] == 0x63 and (priming == 'each' or mode != 1):
            pending += primer
            mode = 1
        pending += record
        if record[0] == 0x55:
            mode = record[2]
    if pending:
        packets.append(pending)
    return packets



def _compile_bounded_plane_payloads(source, rect, rows_per_command):
    """Verified opaque ROI base followed by individually primed V/H/dot planes.

    Each base chunk owns its clip and starts at raster row zero. This avoids
    relying on multi-row raster offsets in a retained larger clip. Corrections
    restore the ROI clip; the final record restores the full center window.
    """
    x, y, w, h = [value // 2 for value in rect]
    grid = decode_bitmap(source)
    stride = (w + 7) // 8
    base = bytearray(stride * h)
    vertical, horizontal, dots = [], [], []
    for py in range(h):
        for px in range(w):
            pattern = grid[y + py][x + px]
            tl, tr, bl, br = (bool(pattern & bit) for bit in (1, 2, 4, 8))
            if br:
                base[py * stride + px // 8] |= 0x80 >> (px % 8)
            if bl ^ br:
                vertical.append((px, py))
            if tr ^ br:
                horizontal.append((px, py))
            if tl ^ tr ^ bl ^ br:
                dots.append((px, py))
    records = []
    rows = min(rows_per_command, (105 - 5) // stride)
    for first in range(0, h, rows):
        height = min(rows, h - first)
        data = base[first * stride:(first + height) * stride]
        records.append([0x52, 5, 0, x, y + 27 + first, w, height])
        records.append([0x55, len(data) + 3, 2, 0, 0, *data])
    records.append([0x52, 5, 0, x, y + 27, w, h])
    strokes = _runs(vertical, True) + _runs(horizontal, False)
    strokes += [dict(orientation=0, x=px, y=py, length=1) for px, py in dots]
    for stroke in strokes:
        records.append([0x55, 4, 1, 0, 0, 0, 0x63, 4, stroke['orientation'],
                        stroke['x'], stroke['y'], stroke['length']])
    records.append([0x52, 5, 0, 0, 27, 64, 48])
    packets, pending = [], []
    for record in records:
        if pending and len(pending) + len(record) > 105:
            packets.append(pending)
            pending = []
        pending += record
    if pending:
        packets.append(pending)
    return packets


def compile_native_payloads(source, *, rows_per_command=1, budget=105, priming='each', selector_bytes=1,
                            render_order='planes', band_rows=12, update_rect=None):
    """Bounded native snapshot body, ready for existing guarded _send_graphics.

    Caller must append exactly one final commit and its matched frame result.
    The row setting is a maximum; reduce it when the byte budget is smaller.
    """
    if isinstance(rows_per_command, bool) or not isinstance(rows_per_command, int) or not 1 <= rows_per_command <= 12:
        raise ValueError('Native bitmap rows_per_command must be an integer1..12')
    if isinstance(budget, bool) or not isinstance(budget, int) or not 13 <= budget <= 105:
        raise ValueError('Native packet budget must be an integer13..105')
    validate_render_options(render_order, band_rows)
    update_rect = validate_update_rect(update_rect, render_order)
    if update_rect is not None and render_order == 'planes':
        if budget != 105 or priming != 'each' or selector_bytes != 1:
            raise ValueError('Bounded planes require the verified105-byte each/short profile')
        return _compile_bounded_plane_payloads(source, update_rect, rows_per_command)
    if render_order == 'tiles':
        if budget != 105 or priming != 'each' or selector_bytes != 1:
            raise ValueError('Completed tiles require the verified105-byte each/short profile')
        from native_tiles import compile_tile_payloads
        return compile_tile_payloads(source, update_rect=update_rect)
    rows = min(rows_per_command, (budget - 5) // 8)
    return pack_native_records(compile_native_records(source, rows_per_command=rows,
                               render_order=render_order, band_rows=band_rows), budget=budget,
                               priming=priming, selector_bytes=selector_bytes)


def compile_plane_delta_payloads(source, previous):
    """Toggle only changed pixels against a known, intact full snapshot.

    These payloads are not independently replayable. The service must discard
    its prior image after any uncertain write and recover with an opaque image.
    """
    target, prior = packed_bitmap(source), packed_bitmap(previous)
    rect = changed_native_rect(target, prior)
    if rect is None:
        return [[0x52, 5, 0, 0, 27, 64, 48]]
    difference = bytes(before ^ after for before, after in zip(prior, target))
    packets = compile_native_payloads(difference, rows_per_command=12,
                                      render_order='planes', update_rect=rect)
    for packet in packets:
        at = 0
        while at < len(packet):
            # Parse record boundaries; raster bytes may equal command opcodes.
            if packet[at] == 0x55 and packet[at + 2] == 2:
                packet[at + 2] = 1
            at += packet[at + 1] + 2
    return packets


def compile_native_bitmap(source, *, model=MODEL):
    """Return a fresh opaque base plus three explicitly XOR-primed planes.

    Base=BR, V=BL^BR, H=TR^BR, D=TL^TR^BL^BR. V/H runs are capped15;
    orientation00 dots use length1. The internal prime marker requires the
    service candidate to emit bare55 without clip/reset afterward. Every
    command is ephemeral: never replay individual strokes from a UI cache.
    """
    if model != MODEL:
        raise ValueError('Unsupported native model: ' + str(model))
    return _cell_commands(decode_bitmap(source), 0, 48)


def _cell_commands(grid, first, last):
    base_data, vertical, horizontal, dots = bytearray((last - first) * 8), [], [], []
    for y in range(first, last):
        row = grid[y]
        for x, pattern in enumerate(row):
            tl, tr, bl, br = (bool(pattern & bit) for bit in (1, 2, 4, 8))
            if br:
                base_data[(y - first) * 8 + x // 8] |= 0x80 >> (x % 8)
            if bl ^ br:
                vertical.append((x, y))
            if tr ^ br:
                horizontal.append((x, y))
            if tl ^ tr ^ bl ^ br:
                dots.append((x, y))
    base = _raw_bitmap(base_data, y=first, height=last - first, mode=2)
    base['_native_bitmap_snapshot'] = True
    commands = [base]
    for group in (_runs(vertical, True), _runs(horizontal, False),
                  [_line(x, y, 1, 0) for x, y in dots]):
        if group:
            commands.append(_prime())
            commands.extend(group)
    return commands
