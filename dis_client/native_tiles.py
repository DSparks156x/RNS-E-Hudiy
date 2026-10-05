"""Verified native completed tiles for the A3 white center (128x96).

Each <=105-byte message contains its ROI, opaque base and every individually
primed correction. Delta needs a known intact previous image; the service owns
that state. Output restores the full center and contains no commit39.
"""
from functools import lru_cache
from native_bitmap import decode_bitmap, _runs, validate_update_rect

FULL = [0x52, 5, 0, 0, 27, 64, 48]
PRIMER = [0x55, 4, 1, 0, 0, 0]


def run_count(mask):
    result = 0
    while mask:
        mask >>= (mask & -mask).bit_length() - 1
        count = (mask ^ (mask + 1)).bit_length() - 1
        result += (count + 14) // 15
        mask >>= count
    return result


class CompletedTileModel:
    def __init__(self, source, *, reset=False):
        self.grid = decode_bitmap(source)
        self.reset = reset
        self.h_masks = [sum(1 << x for x, p in enumerate(row) if bool(p & 2) ^ bool(p & 8)) for row in self.grid]
        self.v_masks = [sum(1 << y for y in range(48) if bool(self.grid[y][x] & 4) ^ bool(self.grid[y][x] & 8)) for x in range(64)]
        self.dot_prefix = [[0] * 65 for _ in range(49)]
        for y, row in enumerate(self.grid):
            for x, p in enumerate(row):
                dot = bool(p & 1) ^ bool(p & 2) ^ bool(p & 4) ^ bool(p & 8)
                a = self.dot_prefix
                a[y + 1][x + 1] = dot + a[y][x + 1] + a[y + 1][x] - a[y][x]
        # Bound caches to this analysis instance, not a global method cache
        # that would retain every decoded corpus image indefinitely.
        self.cost = lru_cache(maxsize=None)(self.cost)
        self.subdivide = lru_cache(maxsize=None)(self.subdivide)

    def cost(self, x, y, w, h):
        a = self.dot_prefix
        dots = a[y + h][x + w] - a[y][x + w] - a[y + h][x] + a[y][x]
        horizontal = sum(run_count((self.h_masks[row] >> x) & ((1 << w) - 1)) for row in range(y, y + h))
        vertical = sum(run_count((self.v_masks[col] >> y) & ((1 << h) - 1)) for col in range(x, x + w))
        strokes = dots + horizontal + vertical
        size = 12 + ((w + 7) // 8) * h + strokes * 12 + (7 if self.reset else 0)
        return dict(bytes=size, can=(size + 6) // 7, ack=1, strokes=strokes,
                    dots=dots, horizontal=horizontal, vertical=vertical,
                    fits=h <= 12 and size <= 105)

    def subdivide(self, x, y, w, h):
        cost = self.cost(x, y, w, h)
        if cost['fits']:
            return (1, cost['can'], cost['bytes']), ((x, y, w, h),)
        candidates = []
        if w > 1:
            left = w // 2
            candidates.append((self.subdivide(x, y, left, h), self.subdivide(x + left, y, w - left, h)))
        if h > 1:
            upper = h // 2
            candidates.append((self.subdivide(x, y, w, upper), self.subdivide(x, y + upper, w, h - upper)))
        if not candidates:
            raise AssertionError('A single-cell tile must fit')
        options = [(tuple(a + b for a, b in zip(first[0], second[0])), first[1] + second[1])
                   for first, second in candidates]
        return min(options, key=lambda item: item[0])

    def choose(self, rect=(0, 0, 64, 48)):
        """Bounded candidate grids with adaptive half-splits, not global optimum."""
        rx, ry, rw, rh = rect
        candidates = []
        for width in (8, 16, 32, 64):
            for height in (1, 2, 3, 4, 6, 8, 10, 11, 12):
                tiles = []
                for y in range(ry, ry + rh, height):
                    for x in range(rx, rx + rw, width):
                        tiles += self.subdivide(x, y, min(width, rx + rw - x), min(height, ry + rh - y))[1]
                costs = [self.cost(*tile) for tile in tiles]
                score = len(tiles), sum(c['can'] for c in costs), sum(c['bytes'] for c in costs)
                candidates.append((score, (width, height), tuple(tiles)))
        return min(candidates, key=lambda item: item[0])

    def packet(self, tile):
        x, y, w, h = tile
        if not self.cost(*tile)['fits']:
            raise ValueError('Completed tile does not fit105')
        stride = (w + 7) // 8
        data = bytearray(stride * h)
        v, horizontal, dots = [], [], []
        for local_y in range(h):
            for local_x in range(w):
                p = self.grid[y + local_y][x + local_x]
                tl, tr, bl, br = (bool(p & bit) for bit in (1, 2, 4, 8))
                if br:
                    data[local_y * stride + local_x // 8] |= 0x80 >> (local_x % 8)
                if bl ^ br:
                    v.append((local_x, local_y))
                if tr ^ br:
                    horizontal.append((local_x, local_y))
                if tl ^ tr ^ bl ^ br:
                    dots.append((local_x, local_y))
        packet = [0x52, 5, 0, x, y + 27, w, h, 0x55, len(data) + 3, 2, 0, 0, *data]
        commands = _runs(v, True) + _runs(horizontal, False)
        commands += [dict(x=px, y=py, length=1, orientation=0) for px, py in dots]
        for command in commands:
            packet += PRIMER + [0x63, 4, command['orientation'], command['x'], command['y'], command['length']]
        if self.reset:
            packet += FULL
        assert len(packet) == self.cost(*tile)['bytes'] <= 105
        return packet


class CompletedDeltaTileModel(CompletedTileModel):
    def __init__(self, previous, target, *, reset=True):
        if previous is None:
            raise ValueError('Unknown previous image requires a full opaque keyframe')
        self.previous = decode_bitmap(previous)
        super().__init__(target, reset=reset)
        a = self.changed_prefix = [[0] * 65 for _ in range(49)]
        for y in range(48):
            for x in range(64):
                changed = self.previous[y][x] != self.grid[y][x]
                a[y + 1][x + 1] = changed + a[y][x + 1] + a[y + 1][x] - a[y][x]

    def changed_in(self, x, y, w, h):
        a = self.changed_prefix
        return a[y + h][x + w] - a[y][x + w] - a[y + h][x] + a[y][x]

    def subdivide(self, x, y, w, h):
        if not self.changed_in(x, y, w, h):
            return (0, 0, 0), ()
        options = []
        cost = self.cost(x, y, w, h)
        if cost['fits']:
            options.append(((1, cost['can'], cost['bytes']), ((x, y, w, h),)))
        # Unlike the full-image model, even a fitting rectangle may split to
        # omit unchanged children at equal ACK count and lower byte/CAN cost.
        splits = []
        if w > 1:
            first = w // 2
            splits.append((self.subdivide(x, y, first, h), self.subdivide(x + first, y, w - first, h)))
        if h > 1:
            first = h // 2
            splits.append((self.subdivide(x, y, w, first), self.subdivide(x, y + first, w, h - first)))
        for left, right in splits:
            options.append((tuple(a + b for a, b in zip(left[0], right[0])), left[1] + right[1]))
        if not options:
            raise AssertionError('A changed single-cell tile must fit')
        return min(options, key=lambda item: item[0])



def compile_tile_payloads(source, *, previous=None, update_rect=None):
    """Opaque full snapshot, or bounded changed tiles with an explicit prior.

    No retained state lives in this compiler. It is safe to redraw a tile from
    any pixels within that ROI; unmodified ROIs in a delta depend on the prior.
    """
    update_rect = validate_update_rect(update_rect, 'tiles', delta=previous is not None)
    rect = tuple(v // 2 for v in update_rect) if update_rect is not None else (0, 0, 64, 48)
    model = (CompletedTileModel(source, reset=False) if previous is None
             else CompletedDeltaTileModel(previous, source, reset=False))
    _, _, tiles = model.choose(rect)
    packets = [model.packet(tile) for tile in tiles]
    if packets and len(packets[-1])+len(FULL) <= 105:
        packets[-1] += FULL
    else:
        packets.append(FULL[:])
    return packets
