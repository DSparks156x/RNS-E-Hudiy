#!/usr/bin/env python3
"""
Mode (majority-vote) downsampler.
For each output pixel, counts black/gray/white votes from the source region.
Zero blending — output is always exactly one of 3 tones.

Shows comparison grid varying the pre-quantize thresholds (alpha_cut, lum_black_max).
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

BLACK = 0
GRAY  = 127
WHITE = 255

# Categories used internally
CAT_BLACK = 0
CAT_GRAY  = 1
CAT_WHITE = 2


def prequantize_cats(img_rgba, alpha_cut, lum_black_max):
    """Return a categorical image (0=black, 1=gray, 2=white) at full res."""
    src = img_rgba.load()
    w, h = img_rgba.size
    out = Image.new('L', (w, h), CAT_WHITE)
    dst = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            if a < alpha_cut:
                dst[x, y] = CAT_WHITE
            else:
                lum = 0.299*r + 0.587*g + 0.114*b
                dst[x, y] = CAT_BLACK if lum <= lum_black_max else CAT_GRAY
    return out


def mode_downsample(cat_img):
    """Majority-vote downsample. No blending — picks most common category."""
    sw, sh = cat_img.size
    src = cat_img.load()
    out = Image.new('L', (TARGET_W, TARGET_H), WHITE)
    dst = out.load()

    for oy in range(TARGET_H):
        y0 = int(oy * sh / TARGET_H)
        y1 = max(y0 + 1, int((oy + 1) * sh / TARGET_H))
        for ox in range(TARGET_W):
            x0 = int(ox * sw / TARGET_W)
            x1 = max(x0 + 1, int((ox + 1) * sw / TARGET_W))

            votes = [0, 0, 0]  # black, gray, white
            for y in range(y0, y1):
                for x in range(x0, x1):
                    votes[src[x, y]] += 1

            # Majority: ties broken black > gray > white
            best_cat = max(range(3), key=lambda k: votes[k])
            dst[ox, oy] = [BLACK, GRAY, WHITE][best_cat]

    return out


# Variants: (alpha_cut, lum_black_max)
VARIANTS = [
    ( 20,  64, 'a≥20  L<64=blk'),
    ( 20,  80, 'a≥20  L<80=blk'),
    ( 20,  96, 'a≥20  L<96=blk'),
    ( 64,  64, 'a≥64  L<64=blk'),
    ( 64,  80, 'a≥64  L<80=blk'),
    ( 64,  96, 'a≥64  L<96=blk'),
    (128,  64, 'a≥128 L<64=blk'),
    (128,  96, 'a≥128 L<96=blk'),
]


def zoom_cell(img_gray):
    return img_gray.resize(
        (TARGET_W * SCALE_UP, TARGET_H * SCALE_UP),
        Image.Resampling.NEAREST).convert('RGB')

def draw_pixel_grid(draw, x, y):
    for px in range(0, TARGET_W*SCALE_UP, SCALE_UP):
        draw.line([(x+px, y), (x+px, y+TARGET_H*SCALE_UP)], fill=(200,200,255), width=1)
    for py in range(0, TARGET_H*SCALE_UP, SCALE_UP):
        draw.line([(x, y+py), (x+TARGET_W*SCALE_UP, y+py)], fill=(200,200,255), width=1)


def build_grid():
    padding  = 3
    label_w  = 150
    row_lh   = 14

    cell_w = TARGET_W * SCALE_UP + padding*2
    cell_h = TARGET_H * SCALE_UP + padding*2

    grid_w = label_w + len(ICONS) * cell_w
    grid_h = len(VARIANTS) * (cell_h + row_lh)

    grid = Image.new('RGB', (grid_w, grid_h), (215, 215, 215))
    draw = ImageDraw.Draw(grid)

    for row_i, (ac, lb, label) in enumerate(VARIANTS):
        y_base = row_i * (cell_h + row_lh)
        draw.text((4, y_base + row_lh//2), label, fill=(160, 0, 0))

        for col_i, fname in enumerate(ICONS):
            path = os.path.join(INPUT_DIR, fname)
            img  = Image.open(path).convert('RGBA')

            cats  = prequantize_cats(img, ac, lb)
            small = mode_downsample(cats)

            x = label_w + col_i * cell_w + padding
            y = y_base + row_lh + padding

            grid.paste(zoom_cell(small), (x, y))
            draw_pixel_grid(draw, x, y)

    for col_i, fname in enumerate(ICONS):
        x = label_w + col_i*cell_w + padding
        short = fname.replace('ic_','').replace('.png','').replace('_',' ')
        draw.text((x, 2), short[:14], fill=(0,0,150))

    out = 'mode_downsample.png'
    grid.save(out)
    print(f"Saved {out}  ({grid_w}x{grid_h})")


if __name__ == '__main__':
    build_grid()
