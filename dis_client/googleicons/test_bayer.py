#!/usr/bin/env python3
"""
Bayer ordered dithering comparison.
All methods use LANCZOS downsample + alpha-composite on white.
The only thing that varies is how the grayscale is converted to 1-bit.

old_checker  - original (x+y)%2 checkerboard (current)
thresh_170   - simple threshold t=170
bayer_std    - Bayer 4x4, neutral midpoint (~128)
bayer_t160   - Bayer 4x4, biased midpoint at ~160
bayer_t170   - Bayer 4x4, biased midpoint at ~170
bayer_t180   - Bayer 4x4, biased midpoint at ~180
bayer_8x8    - Bayer 8x8, midpoint 170 (finer pattern)
floyd        - Floyd-Steinberg (reference)
"""
import os
from PIL import Image, ImageDraw

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = 'pngs'
SCALE_UP  = 10

ICONS = [
    'ic_straight.png',
    'ic_turn_right.png',
    'ic_turn_left.png',
    'ic_turn_sharp_right.png',
    'ic_turn_u_turn_clockwise.png',
    'ic_roundabout_counterclockwise.png',
    'ic_fork_right.png',
    'ic_merge.png',
]

BAYER_4 = [
    [ 0,  8,  2, 10],
    [12,  4, 14,  6],
    [ 3, 11,  1,  9],
    [15,  7, 13,  5],
]
BAYER_8 = [
    [ 0, 32,  8, 40,  2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44,  4, 36, 14, 46,  6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [ 3, 35, 11, 43,  1, 33,  9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47,  7, 39, 13, 45,  5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
]

def get_gray(path):
    """LANCZOS downscale + alpha composite on white → grayscale 31x37."""
    img = Image.open(path).convert('RGBA')
    white = Image.new('RGBA', img.size, (255, 255, 255, 255))
    white.paste(img, mask=img.split()[3])
    gray = white.convert('L')
    return gray.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)

def apply_dither(gray, method):
    src = gray.load()
    out = Image.new('1', (TARGET_W, TARGET_H), 1)
    dst = out.load()

    if method == 'floyd':
        return gray.convert('1', dither=Image.Dither.FLOYDSTEINBERG)

    if method == 'thresh_170':
        return gray.point(lambda p: 0 if p < 170 else 255).convert('1')

    for y in range(TARGET_H):
        for x in range(TARGET_W):
            L = src[x, y]

            if method == 'old_checker':
                if L < 100:
                    on = True
                elif L > 200:
                    on = False
                else:
                    on = (x + y) % 2 == 0  # original buggy checkerboard

            elif method.startswith('bayer'):
                if 'bayer_8' in method:
                    mat = BAYER_8
                    size = 8
                    levels = 64
                else:
                    mat = BAYER_4
                    size = 4
                    levels = 16

                # Extract bias midpoint from method name (e.g. bayer_t170 → 170)
                if '_t' in method:
                    mid = int(method.split('_t')[1])
                else:
                    mid = 128

                # Remap L so that 'mid' maps to 128 (Bayer midpoint)
                # L_adj = 128 + (L - mid) with clamp
                L_adj = max(0, min(255, 128 + (L - mid)))
                threshold = int((mat[y % size][x % size] + 0.5) / levels * 255)
                on = L_adj < threshold

            dst[x, y] = 0 if on else 1  # 0=black in mode '1'

    return out


METHODS = [
    ('old_checker',  'OLD: checkerboard (current)'),
    ('thresh_170',   'Simple threshold t=170'),
    ('bayer_std',    'Bayer 4x4 midpoint=128'),
    ('bayer_t160',   'Bayer 4x4 midpoint=160'),
    ('bayer_t170',   'Bayer 4x4 midpoint=170'),
    ('bayer_t180',   'Bayer 4x4 midpoint=180'),
    ('bayer_8_t170', 'Bayer 8x8 midpoint=170'),
    ('floyd',        'Floyd-Steinberg (reference)'),
]

def build_grid():
    padding = 3
    label_w = 185
    row_lh  = 14

    cell_w = TARGET_W * SCALE_UP + padding*2
    cell_h = TARGET_H * SCALE_UP + padding*2

    grid_w = label_w + len(ICONS)*cell_w
    grid_h = len(METHODS)*(cell_h + row_lh)

    grid = Image.new('RGB', (grid_w, grid_h), (215, 215, 215))
    draw = ImageDraw.Draw(grid)

    # Pre-compute grayscale for each icon
    grays = {}
    for fname in ICONS:
        grays[fname] = get_gray(os.path.join(INPUT_DIR, fname))

    for row_i, (mkey, mlabel) in enumerate(METHODS):
        y_base = row_i*(cell_h + row_lh)
        draw.text((4, y_base + row_lh//2), mlabel, fill=(150, 0, 0))

        for col_i, fname in enumerate(ICONS):
            x = label_w + col_i*cell_w + padding
            y = y_base + row_lh + padding

            result = apply_dither(grays[fname], mkey)
            zoomed = result.convert('RGB').resize(
                (TARGET_W*SCALE_UP, TARGET_H*SCALE_UP),
                Image.Resampling.NEAREST)
            grid.paste(zoomed, (x, y))

            for px in range(0, TARGET_W*SCALE_UP, SCALE_UP):
                draw.line([(x+px, y), (x+px, y+TARGET_H*SCALE_UP)], fill=(200,200,255), width=1)
            for py in range(0, TARGET_H*SCALE_UP, SCALE_UP):
                draw.line([(x, y+py), (x+TARGET_W*SCALE_UP, y+py)], fill=(200,200,255), width=1)

    for col_i, fname in enumerate(ICONS):
        x = label_w + col_i*cell_w + padding
        draw.text((x, 2), fname.replace('ic_','').replace('.png','').replace('_',' ')[:12], fill=(0,0,150))

    grid.save('bayer_comparison.png')
    print(f"Saved bayer_comparison.png  ({grid_w}x{grid_h})")

if __name__ == '__main__':
    build_grid()
