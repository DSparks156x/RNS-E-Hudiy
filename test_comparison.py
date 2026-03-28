"""
DIS Image Pipeline Comparison — V1 vs V2

Generates side-by-side comparison grids for all album covers,
comparing the old pipeline settings against the new V2 defaults.
"""
import os
import sys
import io
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance, ImageFilter, ImageChops

# Add project root to sys.path
sys.path.append(os.path.abspath('dis_client'))
import dis_image

ALBUM_DIR = 'dis_emulator/teststuff/albumcovers'
OUTPUT_DIR = 'dis_tests/comparisons'
os.makedirs(OUTPUT_DIR, exist_ok=True)

UPSCALE = 8  # Blow up the 64x48 cells to look sharp in artifacts

# --- V1 Legacy Pipeline (inline, for A/B comparison) ---
def process_image_v1(img, target_size=(64, 48), contrast=1.2, sharpen=1.5, dither='fs',
                     invert=False, bg_fill='black', grayscale_mode='weighted',
                     brightness=1.0, gamma=2.2, black_floor=45, boldness=0):
    """V1 pipeline — preserved exactly as it was for comparison."""
    frame = img.copy().convert("RGB")
    frame.thumbnail(target_size, Image.Resampling.LANCZOS)
    
    if bg_fill == 'black':
        canvas = Image.new("RGB", target_size, (0, 0, 0))
    elif bg_fill == 'white':
        canvas = Image.new("RGB", target_size, (255, 255, 255))
    else:
        canvas = Image.new("RGB", target_size, (0, 0, 0))
        
    offset_x = (target_size[0] - frame.size[0]) // 2
    offset_y = (target_size[1] - frame.size[1]) // 2
    canvas.paste(frame, (offset_x, offset_y))
    
    if invert:
        canvas = ImageOps.invert(canvas)
    
    # Grayscale
    if grayscale_mode == 'max':
        r, g, b = canvas.split()
        gray = ImageChops.lighter(r, ImageChops.lighter(g, b))
    elif grayscale_mode == 'balanced':
        weighted = canvas.convert('L')
        r, g, b = canvas.split()
        max_lum = ImageChops.lighter(r, ImageChops.lighter(g, b))
        gray = Image.blend(weighted, max_lum, 0.5)
    else:
        gray = canvas.convert('L')
    
    gray = ImageOps.autocontrast(gray, cutoff=1)
    
    if gamma != 1.0:
        gamma_lut = [int(pow(i / 255.0, gamma) * 255.0) for i in range(256)]
        gray = gray.point(gamma_lut)
    
    if brightness != 1.0:
        gray = ImageEnhance.Brightness(gray).enhance(brightness)
    if contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(contrast)
    
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1, percent=int(sharpen * 100), threshold=3))
    
    if black_floor > 0:
        gray = gray.point(lambda p: 0 if p < black_floor else p)
    
    if dither == 'fs':
        return gray.convert('1', dither=Image.FLOYDSTEINBERG)
    elif dither == 'bayer':
        bayer_matrix = [
            [  0, 128,  32, 160],
            [192,  64, 224,  96],
            [ 48, 176,  16, 144],
            [240, 112, 208,  80]
        ]
        w, h = gray.size
        gray_data = list(gray.getdata())
        bayer_data = bytearray(w * h)
        for py in range(h):
            for px in range(w):
                val = gray_data[py * w + px]
                thresh = bayer_matrix[py % 4][px % 4]
                bayer_data[py * w + px] = 255 if val > thresh else 0
        bayer_img = Image.new('L', (w, h))
        bayer_img.putdata(bayer_data)
        return bayer_img.convert('1', dither=Image.Dither.NONE)
    
    return gray.convert('1', dither=Image.Dither.NONE)


# --- Experiment Definitions ---
EXPERIMENTS = [
    # V1 baseline
    {"name": "V1: FS",               "v1": True, "grayscale_mode": "weighted", "gamma": 2.2, "black_floor": 45, "dither": "fs"},
    
    # New baseline (smart+FS with V1 defaults)
    {"name": "New: baseline",        "v1": False, "grayscale_mode": "smart", "dither": "fs"},
    
    # Text improvement experiments
    {"name": "New: sharp=2.5",       "v1": False, "grayscale_mode": "smart", "dither": "fs", "sharpen": 2.5},
    {"name": "New: contrast=1.4",    "v1": False, "grayscale_mode": "smart", "dither": "fs", "contrast": 1.4},
    {"name": "New: s2.5+c1.4",       "v1": False, "grayscale_mode": "smart", "dither": "fs", "sharpen": 2.5, "contrast": 1.4},
]


def process_experiment(orig, exp):
    """Run an image through either V1 or V2 pipeline based on experiment config."""
    params = {k: v for k, v in exp.items() if k not in ('name', 'v1')}
    is_v1 = exp.get('v1', False)
    
    if is_v1:
        return process_image_v1(orig, **params)
    else:
        return dis_image.process_image(orig, **params)


def generate_comparison_grid(image_path):
    orig = Image.open(image_path).convert('RGB')
    filename = os.path.basename(image_path)
    
    cell_w = 64 * UPSCALE
    cell_h = 48 * UPSCALE
    padding = 40
    cols = 2
    rows = (len(EXPERIMENTS) + cols - 1) // cols
    
    grid_w = cols * (cell_w + padding) + padding
    grid_h = rows * (cell_h + padding + 60) + padding + 100
    
    canvas = Image.new('RGB', (grid_w, grid_h), (20, 20, 20))
    draw = ImageDraw.Draw(canvas)
    
    # Title
    draw.text((padding, 20), f"V1 vs V2 Comparison: {filename}", fill=(255, 255, 255))
    
    for i, exp in enumerate(EXPERIMENTS):
        col = i % cols
        row = i // cols
        
        x = padding + col * (cell_w + padding)
        y = 100 + row * (cell_h + padding + 60)
        
        processed = process_experiment(orig, exp)
        upscaled = processed.resize((cell_w, cell_h), Image.Resampling.NEAREST)
        rgb_processed = upscaled.convert('RGB')
        canvas.paste(rgb_processed, (x, y))
        
        # Label with color coding: red for V1, green for V2
        is_v1 = exp.get('v1', False)
        label_color = (255, 120, 120) if is_v1 else (120, 255, 120)
        draw.text((x, y + cell_h + 10), exp['name'], fill=label_color)
        
    output_path = os.path.join(OUTPUT_DIR, f"compare_{os.path.splitext(filename)[0]}.png")
    canvas.save(output_path)
    print(f"Saved comparison grid for {filename} to {output_path}")
    return output_path


def generate_master_grid():
    image_files = sorted([f for f in os.listdir(ALBUM_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    if not image_files:
        return
        
    cell_w = 64 * UPSCALE
    cell_h = 48 * UPSCALE
    padding = 60
    
    cols = len(EXPERIMENTS)
    rows = len(image_files)
    
    grid_w = cols * (cell_w + padding) + padding + 200  # extra for album names
    grid_h = rows * (cell_h + padding) + padding + 120  # extra for title/headers
    
    canvas = Image.new('RGB', (grid_w, grid_h), (15, 15, 15))
    draw = ImageDraw.Draw(canvas)
    
    # Title
    draw.text((padding, 20), "V1 vs V2 MASTER COMPARISON (Contact Sheet)", fill=(255, 255, 255))
    
    # Headers (Experiments) with color coding
    for j, exp in enumerate(EXPERIMENTS):
        header_x = padding + 200 + j * (cell_w + padding)
        is_v1 = exp.get('v1', False)
        header_color = (255, 120, 120) if is_v1 else (120, 255, 120)
        draw.text((header_x, 60), exp['name'], fill=header_color)
        
    for i, f in enumerate(image_files):
        img_path = os.path.join(ALBUM_DIR, f)
        orig = Image.open(img_path).convert('RGB')
        
        row_y = 120 + i * (cell_h + padding)
        
        # Row Label (Album Name)
        draw.text((padding, row_y + (cell_h // 2)), f[:22], fill=(200, 200, 200))
        
        for j, exp in enumerate(EXPERIMENTS):
            col_x = padding + 200 + j * (cell_w + padding)
            
            processed = process_experiment(orig, exp)
            upscaled = processed.resize((cell_w, cell_h), Image.Resampling.NEAREST)
            canvas.paste(upscaled.convert('RGB'), (col_x, row_y))
            
    output_path = os.path.join(OUTPUT_DIR, "MASTER_COMPARISON.png")
    canvas.save(output_path)
    print(f"Saved MASTER comparison grid to {output_path}")


if __name__ == "__main__":
    if not os.path.exists(ALBUM_DIR):
        print(f"Error: Album directory {ALBUM_DIR} not found.")
        sys.exit(1)
        
    for f in sorted(os.listdir(ALBUM_DIR)):
        if f.lower().endswith(('.png', '.jpg', '.jpeg')):
            path = os.path.join(ALBUM_DIR, f)
            generate_comparison_grid(path)
            
    generate_master_grid()
