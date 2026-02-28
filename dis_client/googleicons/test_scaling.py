#!/usr/bin/env python3
"""
Compare different scaling methods for icon processing.
Rows = scaling method, each column = one icon.
"""
import os
import math
from PIL import Image, ImageDraw

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = 'pngs'

DITHER_MIDPOINT = 170  # keep consistent — isolate the scaling variable

def bayer_dither(img_gray, midpoint=170, contrast=3.0):
    """Bayer ordered 4x4 dither with bias toward midpoint."""
    BAYER_4x4 = [
        [ 0,  8,  2, 10],
        [12,  4, 14,  6],
        [ 3, 11,  1,  9],
        [15,  7, 13,  5],
    ]
    pixels = img_gray.load()
    out = Image.new('1', (TARGET_W, TARGET_H), 1)
    out_px = out.load()
    for y in range(TARGET_H):
        for x in range(TARGET_W):
            L = pixels[x, y]
            # Contrast stretch around midpoint so midpoint → 50% dither
            L_adj = max(0, min(255, int(128 + (L - midpoint) * contrast)))
            threshold = (BAYER_4x4[y % 4][x % 4] + 0.5) / 16 * 255
            out_px[x, y] = 0 if L_adj < threshold else 1  # 0=black, 1=white
    return out

def composite_and_gray(path):
    img = Image.open(path).convert('RGBA')
    white_bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
    white_bg.paste(img, mask=img.split()[3])
    return white_bg.convert('L')

def process_method(path, method):
    gray = composite_and_gray(path)
    W, H = gray.size

    if method == 'lanczos':
        resized = gray.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)

    elif method == 'bilinear':
        resized = gray.resize((TARGET_W, TARGET_H), Image.Resampling.BILINEAR)

    elif method == 'box':
        # Box = area averaging, no ringing
        resized = gray.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)

    elif method == 'twostep_lanczos':
        # Scale to 2x intermediate with LANCZOS, then BOX to final
        mid_w, mid_h = TARGET_W * 2, TARGET_H * 2
        resized = gray.resize((mid_w, mid_h), Image.Resampling.LANCZOS)
        resized = resized.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)

    elif method == 'twostep_box':
        # Two-pass BOX — extra averaging step
        mid_w, mid_h = TARGET_W * 3, TARGET_H * 3
        resized = gray.resize((mid_w, mid_h), Image.Resampling.BOX)
        resized = resized.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)

    elif method == 'alpha_lanczos':
        # Scale the ALPHA channel only (pure ink coverage, no color confusion)
        img = Image.open(path).convert('RGBA')
        alpha = img.split()[3]
        alpha_scaled = alpha.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
        # Invert: alpha 255 = ink = dark on gray scale
        resized = alpha_scaled.point(lambda a: 255 - a)

    elif method == 'alpha_box':
        img = Image.open(path).convert('RGBA')
        alpha = img.split()[3]
        alpha_scaled = alpha.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)
        resized = alpha_scaled.point(lambda a: 255 - a)

    return bayer_dither(resized, midpoint=DITHER_MIDPOINT)


METHODS = [
    ('lanczos',          'LANCZOS (current)'),
    ('bilinear',         'Bilinear'),
    ('box',              'Box (area avg)'),
    ('twostep_lanczos',  '2-pass: LANCZOS→BOX'),
    ('twostep_box',      '3x BOX→BOX'),
    ('alpha_lanczos',    'Alpha channel LANCZOS'),
    ('alpha_box',        'Alpha channel BOX'),
]

def build_grid():
    files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith('.png')])
    n = len(files)

    scale = 3
    padding = 3
    label_w = 120

    cell_w = TARGET_W + padding * 2
    cell_h = TARGET_H + padding * 2

    grid_w = label_w + n * cell_w
    grid_h = len(METHODS) * (cell_h + 10)

    grid = Image.new('RGB', (grid_w, grid_h), (200, 200, 200))

    for row_i, (method_key, method_label) in enumerate(METHODS):
        y_base = row_i * (cell_h + 10)
        for col_i, fname in enumerate(files):
            path = os.path.join(INPUT_DIR, fname)
            try:
                im = process_method(path, method_key)
                x = label_w + col_i * cell_w + padding
                y = y_base + 10 + padding
                grid.paste(im.convert('RGB'), (x, y))
            except Exception as e:
                print(f"Error {fname} {method_key}: {e}")

    # Scale up
    grid = grid.resize((grid_w * scale, grid_h * scale), Image.Resampling.NEAREST)

    draw = ImageDraw.Draw(grid)
    for row_i, (_, method_label) in enumerate(METHODS):
        y = row_i * (cell_h + 10) * scale + 12
        draw.text((4, y), method_label, fill=(255, 50, 50))

    grid.save('scaling_comparison.png')
    print("Saved scaling_comparison.png")

if __name__ == '__main__':
    build_grid()
