"""Native monochrome navigation assets; runtime needs only the standard library.

Icons are 72x72 physical pixels in a 128x96 canvas, MSB first. Their origin (6,2)
leaves hardware distance text at x84+, street text at y78+, and bar at x122+ clear.
Generated from curated Maps SVG vectors at the approved default pixel phase.
Active routes are solid; half-opacity secondary routes use a fixed checker.
Source provenance and reviewed masks are retained in nav_icons_sources/.
The runtime only places pre-generated packed masks; it performs no image processing.
"""
from functools import lru_cache
from nav_icons_data import ICON_HEX

ICON_WIDTH = ICON_HEIGHT = 72
CANVAS_WIDTH, CANVAS_HEIGHT = 128, 96
ICON_X, ICON_Y = 6, 2
ICON_NAMES = tuple(ICON_HEX)


@lru_cache(maxsize=64)
def icon_bitmap(name):
    """Packed nine-byte rows; unknown keys deliberately show STRAIGHT."""
    key = str(name).upper()
    return bytes.fromhex(ICON_HEX.get(key, ICON_HEX['STRAIGHT']))


@lru_cache(maxsize=64)
def canvas_for_icon(name):
    """Fresh immutable complete native canvas, blank outside the icon region."""
    icon = icon_bitmap(name)
    canvas = bytearray(CANVAS_WIDTH * CANVAS_HEIGHT // 8)
    for y in range(ICON_HEIGHT):
        for x in range(ICON_WIDTH):
            if icon[y * 9 + x // 8] & (0x80 >> (x % 8)):
                px, py = ICON_X + x, ICON_Y + y
                canvas[py * 16 + px // 8] |= 0x80 >> (px % 8)
    return bytes(canvas)
