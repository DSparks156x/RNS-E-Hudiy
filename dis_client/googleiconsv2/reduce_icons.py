#!/usr/bin/env python3
"""
reduce_icons.py  (potrace pipeline v3)
----------------------------------------
Steps per icon:
  1. Center-crop source to 162x192 (matches 32x38 aspect ratio exactly).
  2. Classify each pixel -> black / gray / transparent by alpha + luminance.
  3. Build two binary masks (black layer, gray layer).
  4. Run potrace on each mask -> SVG path data.
  5. Transform potrace path coordinates to 32x38 output space.
       Potrace uses 10x pixel units with y-flip (bottom-to-top BMP origin):
         out_x = px  * TARGET_W / (CROP_W * 10)
         out_y = (CROP_H*10 - py) * TARGET_H / (CROP_H * 10)
  6. Render gray layer then black layer with aggdraw.
  7. Snap: every output pixel is exactly black / gray / transparent.

Outputs:
  googleiconsv2/reduced/         -- RGB PNGs at 32x38
"""

import os, re, math, struct, tempfile, subprocess
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw
import aggdraw

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR  = os.path.join(SCRIPT_DIR, 'pngs')
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'reduced')
POTRACE    = os.path.join(SCRIPT_DIR, 'potrace', 'potrace.exe')
SVG_DIR    = os.path.join(SCRIPT_DIR, 'svgs')

# Crop canvas (centered from 192x192 source, same aspect as 32x38)
CROP_W, CROP_H = 162, 192

TARGET_W, TARGET_H = 32, 38

# Pixel classification (applied to cropped RGBA)
ALPHA_MIN = 90     # pixels with alpha < this -> transparent
LUM_BLACK = 100     # luminance < this -> black (else gray)

# Post-render snap
SNAP_BLACK = 50
SNAP_TRANS = 230

SVG_NS = 'http://www.w3.org/2000/svg'

# ---------------------------------------------------------------------------
# Step 1: center-crop to CROP_W x CROP_H
# ---------------------------------------------------------------------------

def center_crop(img_rgba):
    """Crop 192x192 -> 162x192 from horizontal center."""
    w, h = img_rgba.size
    left = (w - CROP_W) // 2
    return img_rgba.crop((left, 0, left + CROP_W, CROP_H))

# ---------------------------------------------------------------------------
# Step 2: pixel classification
# ---------------------------------------------------------------------------

def make_masks(img_rgba):
    w, h = img_rgba.size
    px   = img_rgba.load()
    black_m = Image.new('L', (w, h), 0)
    gray_m  = Image.new('L', (w, h), 0)
    bp = black_m.load()
    gp = gray_m.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < ALPHA_MIN:
                continue
            lum = 0.299*r + 0.587*g + 0.114*b
            if lum < LUM_BLACK:
                bp[x, y] = 255
            else:
                gp[x, y] = 255
    return black_m, gray_m

# ---------------------------------------------------------------------------
# Step 3: mask -> BMP bytes (1-bit, for potrace)
# ---------------------------------------------------------------------------

def mask_to_bmp(mask_L):
    """
    1-bit BMP from a binary L-mode image.
    BMP rows are stored bottom-to-top.
    Mask 255 = shape pixel -> BMP bit 0 (color 0 = black = potrace foreground).
    Mask 0   = background  -> BMP bit 1 (color 1 = white = potrace background).
    """
    w, h = mask_L.size
    px   = mask_L.load()
    row_stride = ((w + 31) // 32) * 4

    data = bytearray()
    for y in range(h - 1, -1, -1):         # BMP: bottom row first
        row = bytearray(row_stride)
        for x in range(w):
            if px[x, y] == 0:              # background -> white -> bit 1
                row[x // 8] |= (1 << (7 - x % 8))
            # shape (255) -> black -> bit 0 (already 0)
        data += row

    color_table = b'\x00\x00\x00\x00' + b'\xff\xff\xff\x00'
    hdr = 14 + 40 + len(color_table)
    bmp  = b'BM'
    bmp += struct.pack('<I', hdr + len(data))
    bmp += struct.pack('<HH', 0, 0)
    bmp += struct.pack('<I',  hdr)
    bmp += struct.pack('<I',  40)           # DIB header size
    bmp += struct.pack('<i',  w)
    bmp += struct.pack('<i',  h)            # positive = bottom-up stored
    bmp += struct.pack('<H',  1)            # color planes
    bmp += struct.pack('<H',  1)            # bpp
    bmp += struct.pack('<I',  0)            # no compression
    bmp += struct.pack('<I',  len(data))
    bmp += struct.pack('<ii', 2835, 2835)   # resolution (irrelevant)
    bmp += struct.pack('<II', 2, 0)         # size of color table
    bmp += color_table
    bmp += bytes(data)
    return bmp

# ---------------------------------------------------------------------------
# Step 4: run potrace, return path d-strings
# ---------------------------------------------------------------------------

def run_potrace(mask_L, tmp_dir, tag):
    """Run potrace on a binary mask. Returns (path_d_strings, raw_svg_text)."""
    if mask_L.getbbox() is None:
        return [], ''
    bmp_p = os.path.join(tmp_dir, f'{tag}.bmp')
    svg_p = os.path.join(tmp_dir, f'{tag}.svg')
    with open(bmp_p, 'wb') as f:
        f.write(mask_to_bmp(mask_L))
    r = subprocess.run(
        [POTRACE, '--svg', '--flat', '-o', svg_p, bmp_p],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(f'potrace failed: {r.stderr.strip()}')
    svg_str = open(svg_p, encoding='utf-8').read()
    root  = ET.fromstring(svg_str)
    paths = [e.get('d', '').strip()
             for e in root.iter(f'{{{SVG_NS}}}path') if e.get('d', '').strip()]
    return paths, svg_str


def save_merged_svg(name, black_svg, gray_svg, black_paths, gray_paths):
    """
    Combine potrace black + gray SVGs into one colored SVG.
    Potrace wraps paths in <g transform="translate(0,H) scale(0.1,-0.1)">
    which maps internal 10x units into the viewBox space.
    which maps its 10x internal units into the viewBox space.
    We preserve that transform and nest colored sub-groups inside it.
    """
    os.makedirs(SVG_DIR, exist_ok=True)

    src_svg = black_svg if black_svg else gray_svg
    if not src_svg:
        return

    root    = ET.fromstring(src_svg)
    width   = root.get('width',  '162pt')
    height  = root.get('height', '192pt')
    vb      = root.get('viewBox', '0 0 162 192')

    # Extract the potrace group transform (translate + negative-scale for y-flip)
    g_transform = ''
    for g in root.iter(f'{{{SVG_NS}}}g'):
        t = g.get('transform', '')
        if t:
            g_transform = t
            break

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg version="1.1" xmlns="http://www.w3.org/2000/svg"',
        f'     width="{width}" height="{height}" viewBox="{vb}">',
        f'  <g transform="{g_transform}">',
    ]

    if gray_paths:
        lines.append('    <g fill="#808080">')
        for d in gray_paths:
            lines.append(f'      <path d="{d}"/>')
        lines.append('    </g>')

    if black_paths:
        lines.append('    <g fill="#000000">')
        for d in black_paths:
            lines.append(f'      <path d="{d}"/>')
        lines.append('    </g>')

    lines += ['  </g>', '</svg>']

    nl = '\n'
    out_path = os.path.join(SVG_DIR, f'{name}.svg')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(nl.join(lines))
    return out_path


# ---------------------------------------------------------------------------
# Step 5: render SVG + snap
# ---------------------------------------------------------------------------

# Supersample factor: render at this many times the target resolution.
# Higher = more accurate point sampling. 16x gives sub-half-pixel precision.
SUPERSAMPLE = 16

def render_layer(svg_path, color_rgb):
    """
    Renders a single-color SVG at high resolution, hard-snaps it to the given color,
    and nearest-neighbor downsamples. Returns an RGBA image.
    """
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM

    if not svg_path or not os.path.exists(svg_path):
        return Image.new('RGBA', (TARGET_W, TARGET_H), (0,0,0,0))

    hi_w = TARGET_W * SUPERSAMPLE
    hi_h = TARGET_H * SUPERSAMPLE

    rlg = svg2rlg(svg_path)
    # The individual SVGs from potrace might not have the correct width/height/viewBox
    # because they don't have the merged wrapper. We must enforce the 162x192 viewBox.
    sx = hi_w / 162.0
    sy = hi_h / 192.0
    rlg.width     = hi_w
    rlg.height    = hi_h
    
    # Potrace group transform for individual layers
    # We must apply the potrace y-flip and the scale to high-res.
    # Note: potrace native scale is 0.1, y-flip is translate(0, 192) scale(1, -1)
    # rlg already parses the internal <g transform="..."> so we just scale the root.
    rlg.transform = (sx, 0, 0, sy, 0, 0)

    try:
        hi = renderPM.drawToPIL(rlg, dpi=72).convert('RGBA')
    except Exception as e:
        print(f"renderPM failed on {svg_path}: {e}")
        return Image.new('RGBA', (TARGET_W, TARGET_H), (0,0,0,0))

    # Create an RGBA image with a white background so we can reliably snap lum
    bg = Image.new('RGBA', hi.size, (255,255,255,255))
    bg.paste(hi, mask=hi)
    hi_rgb = bg.convert('RGB')

    # Hard snap: it's a single color, so anything darker than white is the shape
    # LUM_BLACK is the threshold where we consider it part of the shape
    SNAP_LUM = 200

    out_hi = Image.new('RGBA', hi_rgb.size, (0,0,0,0))
    sp, dp = hi_rgb.load(), out_hi.load()
    R, G, B = color_rgb
    for y in range(hi_h):
        for x in range(hi_w):
            r, g, b = sp[x, y]
            lum = 0.299*r + 0.587*g + 0.114*b
            if lum < SNAP_LUM:
                dp[x, y] = (R, G, B, 255)

    return out_hi.resize((TARGET_W, TARGET_H), Image.Resampling.NEAREST)

def process_image_dither(img):
    """
    Apply a checkerboard dither directly to the Image object.
    White pixels stay white (255,255,255).
    Gray pixels get checkerboarded (alternate Black/White).
    Black pixels stay black (0,0,0).
    Returns a newly processed Image in RGB format.
    """
    img = img.convert('RGB')
    new_img = Image.new('RGB', img.size)
    px_in = img.load()
    px_out = new_img.load()
    
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b = px_in[x, y]
            lum = (r + g + b) / 3
            
            # Default to black
            out_val = (0, 0, 0)
            
            if lum > 200: # White
                out_val = (255, 255, 255)
            elif lum > 50: # Gray
                # Checkerboard pattern: white if (x + y) is even, otherwise black
                if (x + y) % 2 == 0:
                    out_val = (255, 255, 255)
                    
            px_out[x, y] = out_val
            
    return new_img

def render_and_snap(b_svg, g_svg):
    """
    Zero-antialiasing render by rendering the black and gray layers SEPARATELY.
    This prevents antialiased black edges from passing through the gray luminance
    value and causing false gray pixels.
    """
    from PIL import ImageOps

    # Render gray layer
    gray_img = render_layer(g_svg, (127, 127, 127))
    
    # Render black layer
    black_img = render_layer(b_svg, (0, 0, 0))

    # Composite: gray as base, black on top, then onto a white background
    out = Image.new('RGBA', (TARGET_W, TARGET_H), (255, 255, 255, 255))
    out.paste(gray_img, mask=gray_img)
    out.paste(black_img, mask=black_img)

    # Convert to RGB and invert
    out_rgb = out.convert('RGB')
    inverted = ImageOps.invert(out_rgb)

    return process_image_dither(inverted)

# ---------------------------------------------------------------------------
# Per-icon pipeline
# ---------------------------------------------------------------------------

def process_icon(path, tmp_dir):
    basename = os.path.basename(path)
    tag = os.path.splitext(basename)[0]
    
    src     = Image.open(path).convert('RGBA')
    cropped = center_crop(src)
    black_m, gray_m = make_masks(cropped)
    
    b_svg_p = os.path.join(tmp_dir, tag + '_b.svg')
    g_svg_p = os.path.join(tmp_dir, tag + '_g.svg')
    
    bp, b_str = run_potrace(black_m, tmp_dir, tag + '_b')
    gp, g_str = run_potrace(gray_m,  tmp_dir, tag + '_g')
    
    # Process separated SVGs first
    rendered = render_and_snap(b_svg_p if bp else None, g_svg_p if gp else None)
    
    # Save combo for reference (optional now)
    save_merged_svg(tag, b_str, g_str, bp, gp)
        
    return rendered

# ---------------------------------------------------------------------------
# Preview grid
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(INPUT_DIR) if f.lower().endswith('.png'))
    if not files:
        print(f'No PNGs in {INPUT_DIR}'); return

    icons = []
    with tempfile.TemporaryDirectory() as tmp:
        for fname in files:
            # Skip generating the mirrored forms here, we handle in mirrorandconvert.py
            if fname.endswith('_right.png') or '_right_' in fname:
                try:
                    # check if the "left" counterpart exists.
                    is_right = False
                    if fname.endswith('_right.png'):
                        left_tag = fname[:-10] + '_left.png'
                        if os.path.exists(os.path.join(INPUT_DIR, left_tag)):
                            is_right = True
                    elif '_right_' in fname:
                        left_tag = fname.replace('_right_', '_left_')
                        if os.path.exists(os.path.join(INPUT_DIR, left_tag)):
                            is_right = True

                    if is_right:
                        continue # Let the mirror stage do this
                except:
                    pass

            try:
                rgb = process_icon(os.path.join(INPUT_DIR, fname), tmp)
                rgb.save(os.path.join(OUTPUT_DIR, fname))
                icons.append((os.path.splitext(fname)[0], rgb))
                print(f'  OK  {fname}')
            except Exception as e:
                import traceback
                print(f'  ERR {fname}: {e}')
                traceback.print_exc()

    if icons:
        print(f'\nSaved {len(icons)} base icons -> {OUTPUT_DIR}')

if __name__ == '__main__':
    main()
