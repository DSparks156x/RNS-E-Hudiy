#!/usr/bin/env python3
"""
Raw grayscale downscale comparison — NO dithering, NO thresholding.
Shows exactly what each scaling method produces before any binarization.
Rows = scaling method, Columns = selected icons, zoomed 8x so pixels are visible.
"""
import os
from PIL import Image, ImageDraw

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = 'pngs'
SCALE_UP = 8  # Zoom factor to make individual pixels visible

# Pick representative icons covering different shapes
ICONS = [
    'ic_straight.png',
    'ic_turn_right.png',
    'ic_turn_left.png',
    'ic_turn_sharp_right.png',
    'ic_turn_slight_right.png',
    'ic_turn_u_turn_clockwise.png',
    'ic_roundabout_counterclockwise.png',
    'ic_fork_right.png',
    'ic_merge.png',
]

def get_gray(path, method):
    """Return a raw grayscale image at target size, no dithering."""
    img = Image.open(path).convert('RGBA')

    if method in ('lanczos', 'bilinear', 'box', 'bicubic'):
        # Composite onto white first, then scale grayscale
        white = Image.new('RGBA', img.size, (255, 255, 255, 255))
        white.paste(img, mask=img.split()[3])
        gray = white.convert('L')
        filter_map = {
            'lanczos':  Image.Resampling.LANCZOS,
            'bilinear': Image.Resampling.BILINEAR,
            'box':      Image.Resampling.BOX,
            'bicubic':  Image.Resampling.BICUBIC,
        }
        return gray.resize((TARGET_W, TARGET_H), filter_map[method])

    elif method == 'lanczos_2x':
        # Two-step: LANCZOS to 2x, then BOX to target
        white = Image.new('RGBA', img.size, (255, 255, 255, 255))
        white.paste(img, mask=img.split()[3])
        gray = white.convert('L')
        mid = gray.resize((TARGET_W * 2, TARGET_H * 2), Image.Resampling.LANCZOS)
        return mid.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)

    elif method == 'lanczos_4x':
        # Two-step: LANCZOS to 4x, then BOX to target
        white = Image.new('RGBA', img.size, (255, 255, 255, 255))
        white.paste(img, mask=img.split()[3])
        gray = white.convert('L')
        mid = gray.resize((TARGET_W * 4, TARGET_H * 4), Image.Resampling.LANCZOS)
        return mid.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)

    elif method == 'alpha_lanczos':
        # Use only alpha channel as ink map (no RGB)
        alpha = img.split()[3]
        scaled = alpha.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
        return scaled.point(lambda a: 255 - a)  # invert: full alpha → dark

    elif method == 'alpha_box':
        alpha = img.split()[3]
        scaled = alpha.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)
        return scaled.point(lambda a: 255 - a)

    elif method == 'alpha_2x':
        alpha = img.split()[3]
        mid = alpha.resize((TARGET_W * 2, TARGET_H * 2), Image.Resampling.LANCZOS)
        scaled = mid.resize((TARGET_W, TARGET_H), Image.Resampling.BOX)
        return scaled.point(lambda a: 255 - a)


METHODS = [
    ('lanczos',      'LANCZOS (current)'),
    ('bilinear',     'Bilinear'),
    ('bicubic',      'Bicubic'),
    ('box',          'BOX (area avg)'),
    ('lanczos_2x',   'LANCZOS→2x→BOX'),
    ('lanczos_4x',   'LANCZOS→4x→BOX'),
    ('alpha_lanczos','Alpha LANCZOS'),
    ('alpha_box',    'Alpha BOX'),
    ('alpha_2x',     'Alpha LANCZOS→2x→BOX'),
]

def build_grid():
    label_w = 140
    padding = 2

    cell_w = TARGET_W * SCALE_UP + padding * 2
    cell_h = TARGET_H * SCALE_UP + padding * 2
    row_label_h = 14

    cols = len(ICONS)
    rows = len(METHODS)

    grid_w = label_w + cols * cell_w
    grid_h = rows * (cell_h + row_label_h)

    grid = Image.new('RGB', (grid_w, grid_h), (210, 210, 210))
    draw = ImageDraw.Draw(grid)

    for row_i, (method_key, method_label) in enumerate(METHODS):
        y_base = row_i * (cell_h + row_label_h)

        # Row label
        draw.text((4, y_base + row_label_h // 2), method_label, fill=(200, 0, 0))

        for col_i, fname in enumerate(ICONS):
            path = os.path.join(INPUT_DIR, fname)
            x = label_w + col_i * cell_w + padding
            y = y_base + row_label_h + padding

            try:
                gray = get_gray(path, method_key)
                # Scale up with NEAREST so individual pixels show clearly
                zoomed = gray.resize(
                    (TARGET_W * SCALE_UP, TARGET_H * SCALE_UP),
                    Image.Resampling.NEAREST
                )
                grid.paste(zoomed.convert('RGB'), (x, y))

                # Draw pixel grid overlay to help count pixels
                for px in range(0, TARGET_W * SCALE_UP, SCALE_UP):
                    draw.line([(x + px, y), (x + px, y + TARGET_H * SCALE_UP)],
                               fill=(180, 180, 255), width=1)
                for py in range(0, TARGET_H * SCALE_UP, SCALE_UP):
                    draw.line([(x, y + py), (x + TARGET_W * SCALE_UP, y + py)],
                               fill=(180, 180, 255), width=1)
            except Exception as e:
                draw.text((x, y), str(e)[:20], fill=(255, 0, 0))

    # Column labels (icon names, abbreviated)
    for col_i, fname in enumerate(ICONS):
        x = label_w + col_i * cell_w + padding
        short = fname.replace('ic_', '').replace('.png', '').replace('_', ' ')
        draw.text((x, 2), short, fill=(0, 0, 150))

    grid.save('raw_scaling_comparison.png')
    print(f"Saved raw_scaling_comparison.png  ({grid_w}x{grid_h})")


if __name__ == '__main__':
    build_grid()
