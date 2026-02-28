#!/usr/bin/env python3
"""
Side-by-side comparison:
  A) 3-tone quantize at full res  →  downsample to 31x37
  B) Downsample to 31x37  →  3-tone snap

Both shown at 8x zoom with pixel grid. Multiple rows vary the quantize/snap thresholds.
"""
import os
from PIL import Image, ImageDraw

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = 'pngs'
SCALE_UP  = 8

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

# (alpha_cut, lum_black_max, label)
# These are applied BOTH as the pre-quantize (method A) and the re-snap (method B)
VARIANTS = [
    (20,   64, 'a≥20  L<64=blk'),
    (20,   80, 'a≥20  L<80=blk'),
    (20,   96, 'a≥20  L<96=blk'),
    (64,   64, 'a≥64  L<64=blk'),
    (64,   80, 'a≥64  L<80=blk'),
    (64,   96, 'a≥64  L<96=blk'),
    (128,  80, 'a≥128 L<80=blk'),
    (128,  96, 'a≥128 L<96=blk'),
]

BLACK_L = 0
GRAY_L  = 127
WHITE_L = 255


# ── helpers ──────────────────────────────────────────────────────────────────

def load_rgba(path):
    return Image.open(path).convert('RGBA')

def composite_white_gray(img_rgba):
    white = Image.new('RGBA', img_rgba.size, (255, 255, 255, 255))
    white.paste(img_rgba, mask=img_rgba.split()[3])
    return white.convert('L')

def prequantize(img_rgba, alpha_cut, lum_black_max):
    """Full-res RGBA → grayscale snapped to exactly 0 / 127 / 255."""
    w, h = img_rgba.size
    src = img_rgba.load()
    out = Image.new('L', (w, h), WHITE_L)
    dst = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            if a < alpha_cut:
                dst[x, y] = WHITE_L
            else:
                lum = 0.299*r + 0.587*g + 0.114*b
                dst[x, y] = BLACK_L if lum <= lum_black_max else GRAY_L
    return out

def resnap(img_gray, alpha_cut, lum_black_max):
    """Target-res grayscale → snapped to exactly 0 / 127 / 255.
    Reuses the same thresholds for apples-to-apples comparison."""
    w, h = img_gray.size
    src = img_gray.load()
    out = img_gray.copy()
    dst = out.load()
    # alpha_cut translates: pixels near white (L ≥ 255-alpha_cut) → background
    white_thresh = 255 - alpha_cut
    for y in range(h):
        for x in range(w):
            L = src[x, y]
            if L > white_thresh:
                dst[x, y] = WHITE_L
            elif L <= lum_black_max:
                dst[x, y] = BLACK_L
            else:
                dst[x, y] = GRAY_L
    return out

def method_A(img_rgba, alpha_cut, lum_black_max):
    """3-tone quantize first, then LANCZOS downsample."""
    q = prequantize(img_rgba, alpha_cut, lum_black_max)
    return q.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)

def method_B(img_rgba, alpha_cut, lum_black_max):
    """LANCZOS downsample first, then 3-tone snap."""
    gray = composite_white_gray(img_rgba)
    small = gray.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    return resnap(small, alpha_cut, lum_black_max)

def zoom(img_gray):
    return img_gray.resize(
        (TARGET_W * SCALE_UP, TARGET_H * SCALE_UP),
        Image.Resampling.NEAREST).convert('RGB')

def draw_grid_lines(draw, x, y):
    for px in range(0, TARGET_W * SCALE_UP, SCALE_UP):
        draw.line([(x+px, y), (x+px, y+TARGET_H*SCALE_UP)], fill=(180,180,255), width=1)
    for py in range(0, TARGET_H * SCALE_UP, SCALE_UP):
        draw.line([(x, y+py), (x+TARGET_W*SCALE_UP, y+py)], fill=(180,180,255), width=1)


# ── layout ───────────────────────────────────────────────────────────────────

def build_grid():
    padding  = 3
    gap      = 20   # gap between method A and B groups
    label_w  = 130
    row_lh   = 14

    cell_w = TARGET_W * SCALE_UP + padding*2
    cell_h = TARGET_H * SCALE_UP + padding*2

    n_icons    = len(ICONS)
    n_variants = len(VARIANTS)

    # Width: label | A columns | gap | B columns
    grid_w = label_w + n_icons*cell_w + gap + n_icons*cell_w
    grid_h = n_variants * (cell_h + row_lh) + row_lh  # +extra top row for group headers

    grid = Image.new('RGB', (grid_w, grid_h), (210, 210, 210))
    draw = ImageDraw.Draw(grid)

    header_y = 2
    a_x0 = label_w
    b_x0 = label_w + n_icons*cell_w + gap
    draw.text((a_x0 + 2, header_y), "A: 3-TONE FIRST  →  downsample", fill=(0, 120, 0))
    draw.text((b_x0 + 2, header_y), "B: DOWNSAMPLE FIRST  →  3-tone snap", fill=(0, 0, 160))

    # Divider
    div_x = label_w + n_icons*cell_w + gap//2
    draw.line([(div_x, 0), (div_x, grid_h)], fill=(100,100,100), width=2)

    for row_i, (ac, lb, label) in enumerate(VARIANTS):
        y_base = row_lh + row_i * (cell_h + row_lh)
        draw.text((4, y_base + row_lh//2), label, fill=(160, 0, 0))

        for col_i, fname in enumerate(ICONS):
            path = os.path.join(INPUT_DIR, fname)
            img  = load_rgba(path)
            y    = y_base + row_lh + padding

            try:
                # Method A
                xa = a_x0 + col_i*cell_w + padding
                a  = method_A(img, ac, lb)
                grid.paste(zoom(a), (xa, y))
                draw_grid_lines(draw, xa, y)

                # Method B
                xb = b_x0 + col_i*cell_w + padding
                b  = method_B(img, ac, lb)
                grid.paste(zoom(b), (xb, y))
                draw_grid_lines(draw, xb, y)

            except Exception as e:
                draw.text((a_x0 + col_i*cell_w + padding, y), str(e)[:25], fill=(255,0,0))

    # Icon name labels across the top for each group
    for col_i, fname in enumerate(ICONS):
        short = fname.replace('ic_','').replace('.png','').replace('_',' ')
        draw.text((a_x0 + col_i*cell_w + padding, row_lh + 2), short[:12], fill=(0,100,0))
        draw.text((b_x0 + col_i*cell_w + padding, row_lh + 2), short[:12], fill=(0,0,120))

    out = 'ab_comparison.png'
    grid.save(out)
    print(f"Saved {out}  ({grid_w}x{grid_h})")


if __name__ == '__main__':
    build_grid()
