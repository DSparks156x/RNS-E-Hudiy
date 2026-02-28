#!/usr/bin/env python3
"""
mirrorandconvert.py
-------------------
Reads RGB PNGs from `reduced/` produced by `reduce_icons.py`.
1. Mirrors left-facing and counterclockwise icons to create right-facing variants.
2. Formats all icons (original + mirrored) into 1-bit packed byte arrays.
   - White pixels are treated as 1 (active).
   - Black/Gray pixels are treated as 0 (inactive).
   - 31 width packed into 4 bytes per row.
3. Outputs a Python dictionary format into `newnewicons.py` payload file.
4. Generates a clean 8x preview grid `preview_all.png` showing all icons.
"""

import os, math
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR  = os.path.join(SCRIPT_DIR, 'reduced')
OUTPUT_PY  = os.path.join(SCRIPT_DIR, 'newnewicons.py')
PREVIEW    = os.path.join(SCRIPT_DIR, 'preview_all.png')

TARGET_W, TARGET_H = 32, 38
PACK_W = 32 # The effective width of the payload
PACK_H = 38 # The effective height of the payload

PREVIEW_SCALE = 8
PREVIEW_COLS  = 11
PREVIEW_PAD   = 4
LABEL_H       = 12

LUM_THRESHOLD = 50 # If pixel is > this luminance, it's considered "active" (White/Gray).
# Note: Since reduce_icons.py now produces inverted images, the background is near-black,
# shapes are white/gray.

# ---------------------------------------------------------------------------
# Mirroring Logic
# ---------------------------------------------------------------------------

def get_mirrored_name(tag):
    """
    Given a tag, compute its mirrored equivalent name.
    Left becomes right, clockwise becomes counterclockwise, and vice versa.
    If the name doesn't imply a directionality that benefits from mirroring, returns None.
    """
    new_tag = tag
    
    if '_left' in new_tag:
        new_tag = new_tag.replace('_left', '_right')
    elif '_right' in new_tag:
        new_tag = new_tag.replace('_right', '_left')
        
    if 'counterclockwise' in new_tag:
        new_tag = new_tag.replace('counterclockwise', 'clockwise')
    elif 'clockwise' in new_tag:
        new_tag = new_tag.replace('clockwise', 'counterclockwise')
        
    if new_tag != tag:
        return new_tag
        
    return None



# ---------------------------------------------------------------------------
# Byte Packing Logic
# ---------------------------------------------------------------------------

def pack_icon_to_bytes(img):
    """
    Pack a 32x38 image into a 31x37 1-bit byte array.
    This matches the `bitmap_tool.html` and `new_icons_data.py` format.
    Active pixels (White/Gray shapes) = 1.
    Background (Black) = 0.
    """
    # Force RGB
    img = img.convert('RGB')
    px = img.load()
    
    bytes_per_row = math.ceil(PACK_W / 8) # 4 bytes
    all_bytes = []
    
    for y in range(PACK_H):
        row_bits = ""
        for x in range(PACK_W):
            # Read pixel. Background is black, active is white.
            # Dithering is already applied to the Image before this step.
            r, g, b = px[x, y]
            lum = (r + g + b) / 3
            
            # Active if brighter than threshold
            is_active = (lum > 127) # since we either made it 0 or 255 in dither pass
            row_bits += "1" if is_active else "0"
            
        # Pad row to byte boundary
        while len(row_bits) < bytes_per_row * 8:
            row_bits += "0"
            
        # Convert row bits to hex bytes
        for j in range(0, len(row_bits), 8):
            byte_str = row_bits[j:j+8]
            byte_val = int(byte_str, 2)
            all_bytes.append(f"0x{byte_val:02X}")
            
    return all_bytes

def format_python_dict(name, byte_array):
    """Format the byte array as a Python dictionary string."""
    # Convert 'ic_turn_left' -> 'TURN_LEFT'
    var_name = name.replace('ic_', '').upper()
    
    lines = []
    lines.append(f"{var_name} = {{")
    lines.append(f"    'w': {PACK_W}, 'h': {PACK_H},")
    lines.append("    'data': [")
    
    # Group by 12 bytes per line for readability
    for i in range(0, len(byte_array), 12):
        chunk = byte_array[i:i+12]
        lines.append("        " + ", ".join(chunk) + ",")
        
    lines.append("    ]")
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Preview Generation
# ---------------------------------------------------------------------------

def build_preview_clean(icons):
    """Build a preview grid of all icons."""
    # icons is a list of (name, Image)
    # Sort alphabetically by name
    icons = sorted(icons, key=lambda x: x[0])
    
    cols = PREVIEW_COLS
    rows = math.ceil(len(icons) / cols)
    cw   = TARGET_W * PREVIEW_SCALE + PREVIEW_PAD * 2
    ch   = TARGET_H * PREVIEW_SCALE + PREVIEW_PAD * 2 + LABEL_H
    
    # White background for the grid itself
    img  = Image.new('RGB', (cols * cw, rows * ch), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    for i, (name, rgba) in enumerate(icons):
        col = i % cols; row = i // cols
        x0  = col * cw + PREVIEW_PAD
        y0  = row * ch + LABEL_H

        # Icons have black backgrounds. Let's just draw them directly.
        zoomed = rgba.convert('RGB').resize(
            (TARGET_W * PREVIEW_SCALE, TARGET_H * PREVIEW_SCALE),
            Image.Resampling.NEAREST)
            
        img.paste(zoomed, (x0, y0))
        
        # Draw label
        label = name.replace('ic_','').replace('_',' ')
        draw.text((x0, row * ch + 1), label, fill=(60, 60, 60))
        
    return img

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not os.path.exists(INPUT_DIR):
        print(f"Input directory not found: {INPUT_DIR}")
        return

    files = sorted(f for f in os.listdir(INPUT_DIR) if f.lower().endswith('.png'))
    if not files:
        print(f'No PNGs in {INPUT_DIR}'); return

    all_icons = [] # list of tuples: (name, img)
    base_names = set()

    # First pass: load all bases
    for fname in files:
        basename = os.path.splitext(fname)[0]
        path = os.path.join(INPUT_DIR, fname)
        img = Image.open(path).convert('RGB')
        
        all_icons.append((basename, img))
        base_names.add(basename)
        
    # Second pass: compute mirrors
    mirrors_to_add = []
    for name, img in all_icons:
        mirrored_name = get_mirrored_name(name)
        if mirrored_name and mirrored_name not in base_names:
            mirrored_img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            mirrors_to_add.append((mirrored_name, mirrored_img))
            base_names.add(mirrored_name)
            print(f"Generated mirror: {mirrored_name} (from {name})")
            
    all_icons.extend(mirrors_to_add)

    # Generate Python Payload File
    print(f"\nWriting payloads to {OUTPUT_PY}...")
    with open(OUTPUT_PY, 'w', encoding='utf-8') as f:
        f.write("# Generated Icons (Auto-created by mirrorandconvert.py)\n\n")
        
        # Sort alphabetically so the generated file is consistent
        all_icons.sort(key=lambda x: x[0])
        
        for name, img in all_icons:
            byte_array = pack_icon_to_bytes(img)
            dict_str = format_python_dict(name, byte_array)
            f.write(dict_str + "\n\n")

    # Generate Preview
    print(f"Generating preview at {PREVIEW}...")
    preview_img = build_preview_clean(all_icons)
    preview_img.save(PREVIEW)

    print(f"Done! Processed {len(all_icons)} distinct icons (including mirrors).")

if __name__ == '__main__':
    main()
