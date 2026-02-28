#!/usr/bin/env python3
"""
RGB-based 3-tone pre-quantize: classify each pixel as black (#000), gray (#7F7F7F),
or transparent BEFORE downsampling, using RGB luminance (not alpha).

Icons use exactly two ink colors:
  #000000 = primary black
  #7F7F7F = secondary gray

Varies the luminance boundary between "black" and "gray" and the alpha cutoff
for "transparent/background".
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

BLACK_L  = 0       # Snapped luminance for black pixels
GRAY_L   = 127     # Snapped luminance for gray pixels
WHITE_L  = 255     # Snapped luminance for transparent/background

# Rows: (alpha_cutoff, lum_boundary, label)
# alpha < alpha_cutoff → transparent (background)
# luminance(RGB) < lum_boundary → black, else → gray
VARIANTS = [
    (None, None, 'NO pre-quantize (reference)'),
    # alpha cutoff=30 (only very transparent → background)
    ( 30,  64, 'a≥30, lum<64=blk'),
    ( 30,  96, 'a≥30, lum<96=blk'),
    ( 30, 112, 'a≥30, lum<112=blk'),
    # alpha cutoff=64 (more aggressive bg removal)
    ( 64,  64, 'a≥64, lum<64=blk'),
    ( 64,  96, 'a≥64, lum<96=blk'),
    ( 64, 112, 'a≥64, lum<112=blk'),
    # alpha cutoff=128
    (128,  64, 'a≥128, lum<64=blk'),
    (128,  96, 'a≥128, lum<96=blk'),
    (128, 112, 'a≥128, lum<112=blk'),
]

def prequantize(img_rgba, alpha_cut, lum_boundary):
    """Snap each pixel to one of 3 exact tones, working from RGB color."""
    pixels = img_rgba.load()
    w, h = img_rgba.size
    out = Image.new('L', (w, h), WHITE_L)
    out_px = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a < alpha_cut:
                out_px[x, y] = WHITE_L  # transparent → background
            else:
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                if lum < lum_boundary:
                    out_px[x, y] = BLACK_L   # dark → black ink
                else:
                    out_px[x, y] = GRAY_L    # light ink → gray
    return out

def get_scaled(path, alpha_cut, lum_boundary):
    img = Image.open(path).convert('RGBA')
    if alpha_cut is None:
        # Reference: composite on white, LANCZOS
        white = Image.new('RGBA', img.size, (255, 255, 255, 255))
        white.paste(img, mask=img.split()[3])
        gray_img = white.convert('L')
    else:
        gray_img = prequantize(img, alpha_cut, lum_boundary)
    return gray_img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)


def build_grid():
    label_w = 175
    padding = 2
    cell_w = TARGET_W * SCALE_UP + padding * 2
    cell_h = TARGET_H * SCALE_UP + padding * 2
    row_label_h = 14

    grid_w = label_w + len(ICONS) * cell_w
    grid_h = len(VARIANTS) * (cell_h + row_label_h)

    grid = Image.new('RGB', (grid_w, grid_h), (210, 210, 210))
    draw = ImageDraw.Draw(grid)

    for row_i, (ac, lb, label) in enumerate(VARIANTS):
        y_base = row_i * (cell_h + row_label_h)
        draw.text((4, y_base + row_label_h // 2), label, fill=(180, 0, 0))

        for col_i, fname in enumerate(ICONS):
            path = os.path.join(INPUT_DIR, fname)
            x = label_w + col_i * cell_w + padding
            y = y_base + row_label_h + padding
            try:
                scaled = get_scaled(path, ac, lb)
                zoomed = scaled.resize(
                    (TARGET_W * SCALE_UP, TARGET_H * SCALE_UP),
                    Image.Resampling.NEAREST)
                grid.paste(zoomed.convert('RGB'), (x, y))
                for px in range(0, TARGET_W * SCALE_UP, SCALE_UP):
                    draw.line([(x+px, y), (x+px, y+TARGET_H*SCALE_UP)], fill=(180,180,255), width=1)
                for py in range(0, TARGET_H * SCALE_UP, SCALE_UP):
                    draw.line([(x, y+py), (x+TARGET_W*SCALE_UP, y+py)], fill=(180,180,255), width=1)
            except Exception as e:
                draw.text((x, y), str(e)[:30], fill=(255, 0, 0))

    for col_i, fname in enumerate(ICONS):
        x = label_w + col_i * cell_w + padding
        short = fname.replace('ic_', '').replace('.png', '').replace('_', ' ')
        draw.text((x, 2), short, fill=(0, 0, 140))

    grid.save('rgb_quantize_comparison.png')
    print(f"Saved rgb_quantize_comparison.png  ({grid_w}x{grid_h})")


if __name__ == '__main__':
    build_grid()
