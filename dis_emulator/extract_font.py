import sys
from PIL import Image
import json

img = Image.open('c:/Users/raccoon/Documents/carstuff/RNS-E-Hudiy/references/dis display references/ProportionalFont.png').convert('RGB')

font_data = {}

for char_code in range(256):
    row = char_code // 16
    col = char_code % 16

    # 16px border, 25px width, 7px padding
    start_x = 16 + col * (25 + 7)
    # 16px border, 29px height, 3px padding
    start_y = 16 + row * (29 + 3)

    # 1. Find the exact width and starting offset of the character ink
    first_red_x = -1
    found_gray_x = -1
    
    for x in range(25):
        for y in range(29):
            p = img.getpixel((start_x + x, start_y + y))
            if p[1] > 100 and p[0] == p[1]: # Gray pixel
                if found_gray_x == -1 or x < found_gray_x:
                    found_gray_x = x
            elif p[0] > 100: # Red pixel
                if first_red_x == -1 or x < first_red_x:
                    first_red_x = x
            
    # Default to standard width 6 if no grey pixels exist
    phys_width = 6
    start_col = 0
    
    if found_gray_x != -1:
        if first_red_x == -1: 
            # It's a space character, no red ink
            # Its width is exactly the column index of the grey pixels.
            phys_width = int(found_gray_x / 4)
            start_col = 0
        else:
            # We have ink. The grey bar marks the rightmost padding edge.
            # The red ink marks the leftmost starting edge.
            # Convert these physical pixels directly into 6x7 column indexes (0 to 5)
            # Since the grid is 4px wide blocks:
            start_col = int(first_red_x / 4)
            end_col = int(found_gray_x / 4)
            
            # The width is the number of 4px columns it consumes, NOT inclusive.
            # E.g., if ink starts at 0, and grey is at 5, width is 5 (0,1,2,3,4).
            phys_width = (end_col - start_col)
            
    pixels = []
    
    # 2. Extract the actual character rows starting from the cropped left edge!
    for y in range(7):
        row_bits = 0
        # We only need to sample up to phys_width columns
        for col_idx in range(phys_width):
            # The true coordinate is the start_col offset + the loop index
            actual_col = start_col + col_idx
            
            sample_x = start_x + (actual_col * 4) + 1
            sample_y = start_y + (y * 4) + 2
            
            p = img.getpixel((sample_x, sample_y))
            if p[0] > 100 and p[1] < 100:  # Check Red channel strictly (ignore gray)
                # Pack the bits from Left-to-Right into the MSB of a 6-bit integer
                # e.g., if width is 4, bit 5, 4, 3, 2 are filled.
                row_bits |= (1 << (5 - col_idx))
        pixels.append(row_bits)
        
    # [width, row0, row1, row2, row3, row4, row5, row6]
    font_data[char_code] = [phys_width] + pixels

# Output as JS
js = f"const FONT_DATA = {json.dumps(font_data)};\n"
with open('c:/Users/raccoon/Documents/carstuff/RNS-E-Hudiy/dis_emulator/static/font_data.js', 'w') as f:
    f.write(js)
    
print("Extracted proportional font data to static/font_data.js")
