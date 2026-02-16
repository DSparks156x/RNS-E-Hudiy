#!/usr/bin/env python3
import os
import sys
from PIL import Image

TARGET_W = 31
TARGET_H = 37
TARGET_W = 31
TARGET_H = 37
INPUT_DIR = os.path.join(os.path.dirname(__file__), 'pngs')
PROCESSED_DIR = os.path.join(os.path.dirname(__file__), 'processed')
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'new_icons_data.py')

def process_image(path):
    img = Image.open(path).convert('RGBA')
    # Resize attempting to keep aspect ratio? 
    # User said "resized into 31 wide x37 tall". We will force fit.
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    
    pixels = img.load()
    bit_data = []

    # Prepare debug/processed image (Black ink on Transparent)
    processed_img = Image.new('RGBA', (TARGET_W, TARGET_H), (0, 0, 0, 0))
    proc_pixels = processed_img.load()
    
    current_byte = 0
    bit_count = 0
    
    # Process Row by Row
    for y in range(TARGET_H):
        row_bits = []
        for x in range(TARGET_W):
            r, g, b, a = pixels[x, y]
            
            # Determine if pixel is ON (1) or OFF (0)
            # DIS: 1 = Ink (Foreground), 0 = Background
            # PNG: Black ink -> 1. Transparent/White -> 0.
            
            is_on = 0
            
            if a < 64:
                is_on = 0 # Transparent -> OFF
            else:
                # Calculate luminance (0=Black, 255=White)
                lum = (0.299 * r + 0.587 * g + 0.114 * b)
                
                if lum < 100:
                    is_on = 1 # Dark -> ON
                elif lum > 200:
                    is_on = 0 # Light -> OFF
                else:
                    # Gray / Anti-aliased edge -> Checkered Dither
                    # Checkerboard pattern
                    if (x + y) % 2 == 0:
                        is_on = 1
                    else:
                        is_on = 0
            
            if is_on:
                proc_pixels[x, y] = (0, 0, 0, 255) # Black
            
            row_bits.append(is_on)
        
        # Pack row into bytes (MSB first)
        # 31 bits -> 4 bytes (pad last byte)
        
        # We process the row_bits to bytes
        for i in range(0, len(row_bits), 8):
            byte_val = 0
            chunk = row_bits[i:i+8]
            for bit_idx, bit in enumerate(chunk):
                if bit:
                    byte_val |= (1 << (7 - bit_idx))
            bit_data.append(byte_val)

    # Save the processed image
    proc_filename = os.path.basename(path)
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)
    processed_img.save(os.path.join(PROCESSED_DIR, proc_filename))

    return bit_data

def main():
    if not os.path.exists(INPUT_DIR):
        print(f"Error: {INPUT_DIR} not found.")
        sys.exit(1)
        
    print("Processing icons...")
    
    files = sorted([f for f in os.listdir(INPUT_DIR) if f.lower().endswith('.png')])
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write("# Generated Icons\n\n")
        
        for fname in files:
            variable_name = os.path.splitext(fname)[0].upper().replace('IC_', '')
            path = os.path.join(INPUT_DIR, fname)
            try:
                data = process_image(path)
                
                f.write(f"{variable_name} = {{\n")
                f.write(f"    'w': {TARGET_W}, 'h': {TARGET_H},\n")
                f.write("    'data': [\n")
                
                # Format data
                hex_strs = [f"0x{b:02X}" for b in data]
                rows = [hex_strs[i:i+12] for i in range(0, len(hex_strs), 12)]
                
                for row in rows:
                    f.write("        " + ", ".join(row) + ",\n")
                
                f.write("    ]\n")
                f.write("}\n\n")
                print(f"Processed {fname} -> {variable_name}")
            except Exception as e:
                print(f"Failed to process {fname}: {e}")

        # Generate BITMAPS dictionary
        f.write("BITMAPS = {\n")
        
        # 1. Add all generated icons by their name
        for fname in files:
            variable_name = os.path.splitext(fname)[0].upper().replace('IC_', '')
            f.write(f"    '{variable_name}': {variable_name},\n")
            
        # 2. Add Compatibility Aliases (mapping old keys to new Google equivalents)
        f.write("    # Aliases for compatibility\n")
        f.write("    'RIGHT': TURN_RIGHT,\n")
        f.write("    'LEFT': TURN_LEFT,\n")
        f.write("    'SLIGHT_RIGHT': TURN_SLIGHT_RIGHT,\n")
        f.write("    'SLIGHT_LEFT': TURN_SLIGHT_LEFT,\n")
        f.write("    'SHARP_RIGHT': TURN_SHARP_RIGHT,\n")
        f.write("    'SHARP_LEFT': TURN_SHARP_LEFT,\n")
        f.write("    'UTURN': TURN_U_TURN_COUNTERCLOCKWISE,\n") # Standard
        
        # Fallbacks for missing RAMP icons
        # f.write("    'RAMP_RIGHT': TURN_SLIGHT_RIGHT,\n") 
        # f.write("    'RAMP_LEFT': TURN_SLIGHT_LEFT,\n")
        
        # Roundabout Mappings
        f.write("    'ROUNDABOUT_ENTER': ROUNDABOUT_COUNTERCLOCKWISE,\n")
        f.write("    'ROUNDABOUT_EXIT': ROUNDABOUT_EXIT_COUNTERCLOCKWISE,\n")
        f.write("    'ROUNDABOUT_FULL': ROUNDABOUT_COUNTERCLOCKWISE,\n")
        
        f.write("}\n")

    print(f"\nDone. Output written to {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
