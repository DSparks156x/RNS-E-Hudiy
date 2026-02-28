#!/usr/bin/env python3
"""
Pre-quantize to 3 tones at full resolution, THEN downsample.
Shows raw grayscale output (no final dithering) at 8x zoom.

Strategy: working from the alpha channel since these are black icons on transparency.
  - alpha >= HI  → black (full ink)
  - LO <= alpha < HI → gray (half ink)
  - alpha < LO   → transparent (no ink)

Then downsample the 3-tone image with LANCZOS → get clean edges.
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
    'ic_turn_sharp_right.png',
    'ic_turn_slight_right.png',
    'ic_turn_u_turn_clockwise.png',
    'ic_roundabout_counterclockwise.png',
    'ic_fork_right.png',
]

# (black_threshold, gray_threshold, label)
# alpha >= black_thresh → black, alpha >= gray_thresh → gray, else transparent
VARIANTS = [
    # Reference: no pre-quantize (current approach)
    (None, None, 'NO pre-quantize (reference)'),
    # Tight black, generous gray
    (200, 80,  'black≥200 gray≥80'),
    (200, 60,  'black≥200 gray≥60'),
    (200, 40,  'black≥200 gray≥40'),
    # Less tight black
    (160, 80,  'black≥160 gray≥80'),
    (160, 60,  'black≥160 gray≥60'),
    (160, 40,  'black≥160 gray≥40'),
    # Very liberal — just black vs transparent (check if there's actually any gray)
    (128, 128, 'black≥128 (2-tone)'),
]

# Gray value used when rendering mid-tone (as a grayscale luminance)
GRAY_VALUE = 128  # 0=black, 255=white

def prequantize(img_rgba, black_thresh, gray_thresh):
    """Quantize RGBA to 3-tone RGBA at full resolution."""
    pixels = img_rgba.load()
    w, h = img_rgba.size
    out = Image.new('L', (w, h), 255)  # white background
    out_px = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a >= black_thresh:
                out_px[x, y] = 0          # black = full ink
            elif a >= gray_thresh:
                out_px[x, y] = GRAY_VALUE  # gray = half ink
            else:
                out_px[x, y] = 255        # white = transparent/background
    return out

def get_scaled(path, black_thresh, gray_thresh):
    img = Image.open(path).convert('RGBA')

    if black_thresh is None:
        # Reference: composite on white, LANCZOS directly
        white = Image.new('RGBA', img.size, (255, 255, 255, 255))
        white.paste(img, mask=img.split()[3])
        gray = white.convert('L')
    else:
        gray = prequantize(img, black_thresh, gray_thresh)

    return gray.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)


def build_grid():
    label_w = 170
    padding = 2

    cell_w = TARGET_W * SCALE_UP + padding * 2
    cell_h = TARGET_H * SCALE_UP + padding * 2
    row_label_h = 14

    cols = len(ICONS)
    rows = len(VARIANTS)

    grid_w = label_w + cols * cell_w
    grid_h = rows * (cell_h + row_label_h)

    grid = Image.new('RGB', (grid_w, grid_h), (210, 210, 210))
    draw = ImageDraw.Draw(grid)

    for row_i, (bt, gt, label) in enumerate(VARIANTS):
        y_base = row_i * (cell_h + row_label_h)
        draw.text((4, y_base + row_label_h // 2), label, fill=(180, 0, 0))

        for col_i, fname in enumerate(ICONS):
            path = os.path.join(INPUT_DIR, fname)
            x = label_w + col_i * cell_w + padding
            y = y_base + row_label_h + padding
            try:
                scaled = get_scaled(path, bt, gt)
                zoomed = scaled.resize(
                    (TARGET_W * SCALE_UP, TARGET_H * SCALE_UP),
                    Image.Resampling.NEAREST
                )
                grid.paste(zoomed.convert('RGB'), (x, y))
                # pixel grid overlay
                for px in range(0, TARGET_W * SCALE_UP, SCALE_UP):
                    draw.line([(x+px, y), (x+px, y+TARGET_H*SCALE_UP)], fill=(180,180,255), width=1)
                for py in range(0, TARGET_H * SCALE_UP, SCALE_UP):
                    draw.line([(x, y+py), (x+TARGET_W*SCALE_UP, y+py)], fill=(180,180,255), width=1)
            except Exception as e:
                draw.text((x, y), str(e)[:30], fill=(255, 0, 0))

    # Column labels
    for col_i, fname in enumerate(ICONS):
        x = label_w + col_i * cell_w + padding
        short = fname.replace('ic_', '').replace('.png', '').replace('_', ' ')
        draw.text((x, 2), short, fill=(0, 0, 140))

    grid.save('prequantize_comparison.png')
    print(f"Saved prequantize_comparison.png  ({grid_w}x{grid_h})")


if __name__ == '__main__':
    build_grid()
