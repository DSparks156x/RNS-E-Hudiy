#!/usr/bin/env python3
"""
Show full-resolution icon quantization to 3 tones BEFORE any downsampling.

For each icon column:
  - Col 0: Original (composited on white, so alpha is visible)
  - Col 1+: Various 3-tone quantizations

Output is thumbnailed at 96px height using NEAREST so we can see the actual
quantized pixels, not resampled blends.
"""
import os
from PIL import Image, ImageDraw

INPUT_DIR = 'pngs'
THUMB_H = 192  # Show full original height
THUMB_W = 192

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

# Quantization variants:
# Each entry: (alpha_cut, lum_black_max, label)
# 'original' → show original composited on white
VARIANTS = [
    ('original', None, None, 'Original (on white)'),
    ('original_alpha', None, None, 'Original (alpha shown)'),
    # Snap by luminance with tight alpha cut
    ('snap', 20,  64,  'a≥20 L<64→blk'),
    ('snap', 20,  80,  'a≥20 L<80→blk'),
    ('snap', 20,  96,  'a≥20 L<96→blk'),
    ('snap', 64,  64,  'a≥64 L<64→blk'),
    ('snap', 64,  80,  'a≥64 L<80→blk'),
    ('snap', 64,  96,  'a≥64 L<96→blk'),
    ('snap', 128, 64,  'a≥128 L<64→blk'),
    ('snap', 128, 96,  'a≥128 L<96→blk'),
]

BLACK_RGB = (0, 0, 0, 255)
GRAY_RGB  = (127, 127, 127, 255)
WHITE_RGB = (255, 255, 255, 255)  # represent transparent as white for display

def quantize(img_rgba, alpha_cut, lum_black_max):
    """Return an RGBA image with pixels snapped to exactly black, gray, or white."""
    pixels = img_rgba.load()
    w, h = img_rgba.size
    out = Image.new('RGBA', (w, h), WHITE_RGB)
    out_px = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a < alpha_cut:
                out_px[x, y] = WHITE_RGB  # transparent → background
            else:
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                if lum <= lum_black_max:
                    out_px[x, y] = BLACK_RGB
                else:
                    out_px[x, y] = GRAY_RGB
    return out


def build_grid():
    padding = 4
    label_h = 12
    thumb_w = THUMB_W
    thumb_h = THUMB_H

    n_icons = len(ICONS)
    n_variants = len(VARIANTS)

    cell_w = thumb_w + padding * 2
    cell_h = thumb_h + padding * 2

    grid_w = n_variants * cell_w
    grid_h = n_icons * (cell_h + label_h)

    grid = Image.new('RGB', (grid_w, grid_h), (230, 230, 230))
    draw = ImageDraw.Draw(grid)

    for col_i, (mode, alpha_cut, lum_max, label) in enumerate(VARIANTS):
        x_base = col_i * cell_w

        # Column label at top (draw vertically using pixel coords)
        draw.text((x_base + padding, 2), label, fill=(180, 0, 0))

        for row_i, fname in enumerate(ICONS):
            path = os.path.join(INPUT_DIR, fname)
            y_base = row_i * (cell_h + label_h) + label_h

            x = x_base + padding
            y = y_base + padding

            try:
                img = Image.open(path).convert('RGBA')

                if mode == 'original':
                    # Composite on white
                    white = Image.new('RGBA', img.size, (255, 255, 255, 255))
                    white.paste(img, mask=img.split()[3])
                    display = white.convert('RGB')

                elif mode == 'original_alpha':
                    # Show with checkerboard for transparency
                    checker = Image.new('RGB', img.size, (200, 200, 200))
                    checker_px = checker.load()
                    for cy in range(img.size[1]):
                        for cx in range(img.size[0]):
                            if (cx // 16 + cy // 16) % 2 == 0:
                                checker_px[cx, cy] = (255, 255, 255)
                    checker.paste(img, mask=img.split()[3])
                    display = checker

                else:  # snap
                    q = quantize(img, alpha_cut, lum_max)
                    display = q.convert('RGB')

                # Resize to thumb using NEAREST to preserve quantized pixels
                display = display.resize((thumb_w, thumb_h), Image.Resampling.NEAREST)
                grid.paste(display, (x, y))

                # Draw border
                draw.rectangle([x-1, y-1, x+thumb_w, y+thumb_h], outline=(150, 150, 150))

            except Exception as e:
                draw.text((x, y), str(e)[:30], fill=(255, 0, 0))

        # Row labels (icon names on first column only)
    for row_i, fname in enumerate(ICONS):
        short = fname.replace('ic_', '').replace('.png', '').replace('_', ' ')
        y_base = row_i * (cell_h + label_h) + label_h
        draw.text((2, y_base + padding), short, fill=(0, 0, 150))

    grid.save('fullres_quantize.png')
    print(f"Saved fullres_quantize.png  ({grid_w}x{grid_h})")


if __name__ == '__main__':
    build_grid()
