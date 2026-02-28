import os
from PIL import Image

path = 'ic_straight.png'
path = os.path.join('pngs', path)

def show_ascii(img):
    pixels = img.load()
    w, h = img.size
    for y in range(h):
        row = ''
        for x in range(w):
            val = pixels[x, y]
            if type(val) is tuple:
                val = val[0] # assuming 1-bit or grayscale
            row += '#' if val == 0 else '.'
        print(row)

img = Image.open(path).convert('RGBA')
print("Original size:", img.size)

# Current method
resized = img.resize((31, 37), Image.Resampling.LANCZOS)
pixels = resized.load()
out_cur = Image.new('1', (31, 37), 1)
out_cur_px = out_cur.load()
for y in range(37):
    for x in range(31):
        r, g, b, a = pixels[x, y]
        if a >= 64:
            out_cur_px[x, y] = 0 # black
        else:
            out_cur_px[x, y] = 1 # white

print("\n--- CURRENT METHOD (LANCZOS, a>=64 threshold) ---")
show_ascii(out_cur)

