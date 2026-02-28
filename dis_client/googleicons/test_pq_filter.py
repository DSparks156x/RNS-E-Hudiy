#!/usr/bin/env python3
"""
Focused test: pre-quantize to 3 clean tones, then compare different downsample filters.
Shows raw grayscale result at 8x zoom — no dithering, no final snap.
This isolates whether the filter choice matters after pre-quantizing.

Methods compared:
  ref_lanczos   - reference: no pre-quantize, LANCZOS (current approach)
  pq+LANCZOS    - pre-quantize then LANCZOS
  pq+BOX        - pre-quantize then BOX (area average - no ringing)
  pq+BILINEAR   - pre-quantize then BILINEAR
  pq+BOX2       - pre-quantize then BOX via 2-step (4x intermediate)
  pq+NEAREST    - pre-quantize then NEAREST (most jagged but zero blur)
"""
import os
from PIL import Image, ImageDraw

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = 'pngs'
SCALE_UP  = 10   # big enough to really see pixels

ICONS = [
    'ic_straight.png',
    'ic_turn_right.png',
    'ic_turn_left.png',
    'ic_turn_sharp_right.png',
    'ic_turn_u_turn_clockwise.png',
    'ic_roundabout_counterclockwise.png',
    'ic_fork_right.png',
]

# Pre-quantize params
ALPHA_CUT     = 30
LUM_BLACK_MAX = 80
BLACK_L = 0
GRAY_L  = 127
WHITE_L = 255


def prequantize(img_rgba):
    """Snap full-res RGBA → exactly 3 grayscale values."""
    src = img_rgba.load()
    w, h = img_rgba.size
    out = Image.new('L', (w, h), WHITE_L)
    dst = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            if a < ALPHA_CUT:
                dst[x, y] = WHITE_L
            else:
                lum = 0.299*r + 0.587*g + 0.114*b
                dst[x, y] = BLACK_L if lum <= LUM_BLACK_MAX else GRAY_L
    return out

def composite_white(img_rgba):
    white = Image.new('RGBA', img_rgba.size, (255, 255, 255, 255))
    white.paste(img_rgba, mask=img_rgba.split()[3])
    return white.convert('L')


METHODS = [
    ('ref_lanczos',  'REF: no pre-q, LANCZOS'),
    ('pq_lanczos',   'pre-q + LANCZOS'),
    ('pq_box',       'pre-q + BOX'),
    ('pq_bilinear',  'pre-q + BILINEAR'),
    ('pq_box2step',  'pre-q + BOX (2-step via 4x)'),
    ('pq_nearest',   'pre-q + NEAREST'),
]

def scale(img_l, method):
    if method == 'ref_lanczos':
        return img_l.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    elif method == 'pq_lanczos':
        return img_l.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    elif method == 'pq_box':
        return img_l.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)
    elif method == 'pq_bilinear':
        return img_l.resize((TARGET_W, TARGET_H), Image.Resampling.BILINEAR)
    elif method == 'pq_box2step':
        mid = img_l.resize((TARGET_W*4, TARGET_H*4), Image.Resampling.BOX)
        return mid.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)
    elif method == 'pq_nearest':
        return img_l.resize((TARGET_W, TARGET_H), Image.Resampling.NEAREST)


def build_grid():
    padding  = 3
    label_w  = 170
    row_lh   = 14

    cell_w = TARGET_W * SCALE_UP + padding*2
    cell_h = TARGET_H * SCALE_UP + padding*2

    grid_w = label_w + len(ICONS) * cell_w
    grid_h = len(METHODS) * (cell_h + row_lh)

    grid = Image.new('RGB', (grid_w, grid_h), (215, 215, 215))
    draw = ImageDraw.Draw(grid)

    for row_i, (mkey, mlabel) in enumerate(METHODS):
        y_base = row_i * (cell_h + row_lh)
        draw.text((4, y_base + row_lh//2), mlabel, fill=(160, 0, 0))

        for col_i, fname in enumerate(ICONS):
            path = os.path.join(INPUT_DIR, fname)
            img  = Image.open(path).convert('RGBA')

            if mkey == 'ref_lanczos':
                src_l = composite_white(img)
            else:
                src_l = prequantize(img)

            small = scale(src_l, mkey)

            x = label_w + col_i * cell_w + padding
            y = y_base + row_lh + padding

            zoomed = small.resize(
                (TARGET_W * SCALE_UP, TARGET_H * SCALE_UP),
                Image.Resampling.NEAREST).convert('RGB')
            grid.paste(zoomed, (x, y))

            # pixel grid
            for px in range(0, TARGET_W*SCALE_UP, SCALE_UP):
                draw.line([(x+px, y), (x+px, y+TARGET_H*SCALE_UP)], fill=(200,200,255), width=1)
            for py in range(0, TARGET_H*SCALE_UP, SCALE_UP):
                draw.line([(x, y+py), (x+TARGET_W*SCALE_UP, y+py)], fill=(200,200,255), width=1)

    # Icon name labels
    for col_i, fname in enumerate(ICONS):
        x = label_w + col_i * cell_w + padding
        short = fname.replace('ic_','').replace('.png','').replace('_',' ')
        draw.text((x, 2), short[:14], fill=(0, 0, 150))

    out = 'pq_filter_comparison.png'
    grid.save(out)
    print(f"Saved {out}  ({grid_w}x{grid_h})")


if __name__ == '__main__':
    build_grid()
