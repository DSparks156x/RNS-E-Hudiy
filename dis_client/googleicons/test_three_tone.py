#!/usr/bin/env python3
"""
3-step pipeline comparison:
  1. Pre-quantize at full res → exactly 3 values (0, 127, 255) based on RGB luminance
  2. Downsample to 31x37 (LANCZOS or BOX)
  3. Re-snap to 3 tones at target res

Rows vary the re-snap thresholds (the key tuning parameter).
Left half of grid: no pre-quantize reference | Right half: with pre-quantize

This isolates what the final 31x37 image looks like when forced to 3 exact tones.
"""
import os
from PIL import Image, ImageDraw

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = 'pngs'
SCALE_UP = 8

ICONS = [
    'ic_straight.png',
    'ic_turn_right.png',
    'ic_turn_left.png',
    'ic_turn_u_turn_clockwise.png',
    'ic_roundabout_counterclockwise.png',
    'ic_fork_right.png',
    'ic_turn_slight_right.png',
    'ic_merge.png',
]

BLACK_SNAP = 0
GRAY_SNAP  = 127
WHITE_SNAP = 255

# Pre-quantize params (fixed, reasonable values)
ALPHA_CUT  = 30   # pixels with alpha < this → background
LUM_SPLIT  = 80   # luminance < this → black, else → gray

# Rows: (low_thresh, high_thresh)
# After downscaling, snap: L < low → black, low <= L < high → gray, L >= high → white
SNAP_VARIANTS = [
    (None,  None,   'NO final snap (smooth ref)'),
    (  50,  200,    'snap: <50=blk  <200=gray'),
    (  64,  200,    'snap: <64=blk  <200=gray'),
    (  80,  200,    'snap: <80=blk  <200=gray'),
    (  64,  180,    'snap: <64=blk  <180=gray'),
    (  64,  160,    'snap: <64=blk  <160=gray'),
    (  80,  160,    'snap: <80=blk  <160=gray'),
    (  96,  160,    'snap: <96=blk  <160=gray'),
]

def prequantize_full(img_rgba):
    """Snap full-res RGBA to hard 3-tone grayscale: 0, 127, or 255 only."""
    pixels = img_rgba.load()
    w, h = img_rgba.size
    out = Image.new('L', (w, h), WHITE_SNAP)
    out_px = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a < ALPHA_CUT:
                out_px[x, y] = WHITE_SNAP
            else:
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                out_px[x, y] = BLACK_SNAP if lum < LUM_SPLIT else GRAY_SNAP
    return out

def resnap(img_gray, low, high):
    """Re-snap a grayscale image to exactly 3 tones."""
    pixels = img_gray.load()
    out = img_gray.copy()
    out_px = out.load()
    for y in range(TARGET_H):
        for x in range(TARGET_W):
            L = pixels[x, y]
            if L < low:
                out_px[x, y] = BLACK_SNAP
            elif L < high:
                out_px[x, y] = GRAY_SNAP
            else:
                out_px[x, y] = WHITE_SNAP
    return out

def get_scaled_prequant(path):
    img = Image.open(path).convert('RGBA')
    q = prequantize_full(img)
    return q.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)

def get_scaled_ref(path):
    img = Image.open(path).convert('RGBA')
    white = Image.new('RGBA', img.size, (255, 255, 255, 255))
    white.paste(img, mask=img.split()[3])
    gray = white.convert('L')
    return gray.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)


def paste_cell(grid, draw, scaled, x, y):
    zoomed = scaled.resize(
        (TARGET_W * SCALE_UP, TARGET_H * SCALE_UP),
        Image.Resampling.NEAREST)
    grid.paste(zoomed.convert('RGB'), (x, y))
    for px in range(0, TARGET_W * SCALE_UP, SCALE_UP):
        draw.line([(x+px, y), (x+px, y+TARGET_H*SCALE_UP)], fill=(180,180,255), width=1)
    for py in range(0, TARGET_H * SCALE_UP, SCALE_UP):
        draw.line([(x, y+py), (x+TARGET_W*SCALE_UP, y+py)], fill=(180,180,255), width=1)


def build_grid():
    label_w = 180
    padding = 2
    gap = 6  # gap between ref group and pre-quantized group

    cell_w = TARGET_W * SCALE_UP + padding * 2
    cell_h = TARGET_H * SCALE_UP + padding * 2
    row_label_h = 14

    n_icons = len(ICONS)
    n_rows = len(SNAP_VARIANTS)

    grid_w = label_w + n_icons * cell_w * 2 + gap
    grid_h = n_rows * (cell_h + row_label_h)

    grid = Image.new('RGB', (grid_w, grid_h), (210, 210, 210))
    draw = ImageDraw.Draw(grid)

    # Group headers
    draw.text((label_w + 2, 0), "WITHOUT pre-quantize", fill=(0, 80, 0))
    draw.text((label_w + n_icons * cell_w + gap + 2, 0), "WITH full-res pre-quantize (snap→0/127/255)", fill=(0, 0, 140))

    for row_i, (lo, hi, label) in enumerate(SNAP_VARIANTS):
        y_base = row_i * (cell_h + row_label_h)
        draw.text((4, y_base + row_label_h // 2), label, fill=(160, 0, 0))

        for col_i, fname in enumerate(ICONS):
            path = os.path.join(INPUT_DIR, fname)
            try:
                ref_scaled = get_scaled_ref(path)
                pre_scaled = get_scaled_prequant(path)

                if lo is not None:
                    ref_display = resnap(ref_scaled, lo, hi)
                    pre_display = resnap(pre_scaled, lo, hi)
                else:
                    ref_display = ref_scaled
                    pre_display = pre_scaled

                # Left: without pre-quantize
                x = label_w + col_i * cell_w + padding
                y = y_base + row_label_h + padding
                paste_cell(grid, draw, ref_display, x, y)

                # Right: with pre-quantize
                x2 = label_w + n_icons * cell_w + gap + col_i * cell_w + padding
                paste_cell(grid, draw, pre_display, x2, y)

            except Exception as e:
                print(f"Error {fname}: {e}")

    # Divider line between left/right groups
    div_x = label_w + n_icons * cell_w + gap // 2
    draw.line([(div_x, 0), (div_x, grid_h)], fill=(100, 100, 100), width=2)

    # Column labels
    for col_i, fname in enumerate(ICONS):
        short = fname.replace('ic_', '').replace('.png', '').replace('_', ' ')
        x_l = label_w + col_i * cell_w + padding
        x_r = label_w + n_icons * cell_w + gap + col_i * cell_w + padding
        draw.text((x_l, 2), short, fill=(0, 100, 0))
        draw.text((x_r, 2), short, fill=(0, 0, 120))

    grid.save('three_tone_comparison.png')
    print(f"Saved three_tone_comparison.png  ({grid_w}x{grid_h})")


if __name__ == '__main__':
    build_grid()
