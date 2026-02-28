#!/usr/bin/env python3
import os
import sys
import math
from PIL import Image

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = os.path.join(os.path.dirname(__file__), 'pngs')
PROCESSED_DIR = os.path.join(os.path.dirname(__file__), 'processed')
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'new_icons_data.py')
GRID_FILE = os.path.join(os.path.dirname(__file__), 'icons_preview.png')

def process_image(path):
    img = Image.open(path).convert('RGBA')

    # Composite the icon onto a white background.
    # This correctly handles anti-aliased/semi-transparent edge pixels
    # by blending them toward white, producing consistent gray values
    # rather than hard transparent/opaque steps.
    white_bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
    white_bg.paste(img, mask=img.split()[3])  # use alpha as mask
    img_gray = white_bg.convert('L')

    # Resize with LANCZOS for best downscale quality
    img_gray = img_gray.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)

    # Apply Floyd-Steinberg dithering for the 1-bit conversion.
    # This produces consistent, symmetric results on symmetric shapes
    # unlike the old (x+y)%2 checkerboard which was position-dependent.
    img_1bit = img_gray.convert('1', dither=Image.Dither.FLOYDSTEINBERG)

    # Pack bits into bytes (row by row, MSB first)
    bit_data = []
    pixels = img_1bit.load()
    for y in range(TARGET_H):
        row_bits = []
        for x in range(TARGET_W):
            # In '1' mode: 0 = black (ink/ON), 255 = white (background/OFF)
            is_on = 1 if pixels[x, y] == 0 else 0
            row_bits.append(is_on)

        # Pack 31 bits -> 4 bytes per row
        for i in range(0, len(row_bits), 8):
            byte_val = 0
            chunk = row_bits[i:i + 8]
            for bit_idx, bit in enumerate(chunk):
                if bit:
                    byte_val |= (1 << (7 - bit_idx))
            bit_data.append(byte_val)

    # Save processed preview image (black on transparent)
    processed_img = Image.new('RGBA', (TARGET_W, TARGET_H), (0, 0, 0, 0))
    proc_pixels = processed_img.load()
    src_pixels = img_1bit.load()
    for y in range(TARGET_H):
        for x in range(TARGET_W):
            if src_pixels[x, y] == 0:  # black pixel = ink
                proc_pixels[x, y] = (0, 0, 0, 255)

    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)
    processed_img.save(os.path.join(PROCESSED_DIR, os.path.basename(path)))

    return bit_data, img_1bit


def generate_preview_grid(processed_icons):
    """Render all icons onto a white grid PNG for easy visual review."""
    n = len(processed_icons)
    if n == 0:
        return

    padding = 4
    label_h = 0  # no text labels to keep it simple and small
    cols = 10
    rows = math.ceil(n / cols)

    cell_w = TARGET_W + padding * 2
    cell_h = TARGET_H + padding * 2

    grid_w = cols * cell_w
    grid_h = rows * cell_h

    # White background
    grid = Image.new('RGB', (grid_w, grid_h), (255, 255, 255))

    for i, (name, img_1bit) in enumerate(processed_icons):
        col = i % cols
        row = i // cols
        x = col * cell_w + padding
        y = row * cell_h + padding

        # Paste the 1-bit image (convert to RGB so it pastes cleanly)
        cell_rgb = img_1bit.convert('RGB')
        grid.paste(cell_rgb, (x, y))

    # Scale up 3x so pixels are visible when reviewing
    grid = grid.resize((grid_w * 3, grid_h * 3), Image.Resampling.NEAREST)
    grid.save(GRID_FILE)
    print(f"Preview grid saved to {GRID_FILE}")


def main():
    if not os.path.exists(INPUT_DIR):
        print(f"Error: {INPUT_DIR} not found.")
        sys.exit(1)

    print("Processing icons...")

    files = sorted([f for f in os.listdir(INPUT_DIR) if f.lower().endswith('.png')])

    processed_icons = []

    with open(OUTPUT_FILE, 'w') as f:
        f.write("# Generated Icons\n\n")

        for fname in files:
            variable_name = os.path.splitext(fname)[0].upper().replace('IC_', '')
            path = os.path.join(INPUT_DIR, fname)
            try:
                data, img_1bit = process_image(path)
                processed_icons.append((variable_name, img_1bit))

                f.write(f"{variable_name} = {{\n")
                f.write(f"    'w': {TARGET_W}, 'h': {TARGET_H},\n")
                f.write("    'data': [\n")

                hex_strs = [f"0x{b:02X}" for b in data]
                rows = [hex_strs[i:i + 12] for i in range(0, len(hex_strs), 12)]
                for row in rows:
                    f.write("        " + ", ".join(row) + ",\n")

                f.write("    ]\n")
                f.write("}\n\n")
                print(f"Processed {fname} -> {variable_name}")
            except Exception as e:
                print(f"Failed to process {fname}: {e}")

        # Generate BITMAPS dictionary
        f.write("BITMAPS = {\n")

        for fname in files:
            variable_name = os.path.splitext(fname)[0].upper().replace('IC_', '')
            f.write(f"    '{variable_name}': {variable_name},\n")

        # Compatibility Aliases
        f.write("    # Aliases for compatibility\n")
        f.write("    'RIGHT': TURN_RIGHT,\n")
        f.write("    'LEFT': TURN_LEFT,\n")
        f.write("    'SLIGHT_RIGHT': TURN_SLIGHT_RIGHT,\n")
        f.write("    'SLIGHT_LEFT': TURN_SLIGHT_LEFT,\n")
        f.write("    'SHARP_RIGHT': TURN_SHARP_RIGHT,\n")
        f.write("    'SHARP_LEFT': TURN_SHARP_LEFT,\n")
        f.write("    'UTURN': TURN_U_TURN_COUNTERCLOCKWISE,\n")

        # Roundabout Mappings
        f.write("    'ROUNDABOUT_ENTER': ROUNDABOUT_COUNTERCLOCKWISE,\n")
        f.write("    'ROUNDABOUT_EXIT': ROUNDABOUT_EXIT_COUNTERCLOCKWISE,\n")
        f.write("    'ROUNDABOUT_FULL': ROUNDABOUT_COUNTERCLOCKWISE,\n")

        f.write("}\n")

    generate_preview_grid(processed_icons)
    print(f"\nDone. Output written to {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
