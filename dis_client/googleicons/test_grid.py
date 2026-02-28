import os
import math
from PIL import Image

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = 'pngs'

def process(path, method='thresh', preserve_aspect=True, do_pad_crop=False):
    # Load image
    img = Image.open(path).convert('RGBA')
    
    if do_pad_crop:
        # crop transparent padded areas first
        alpha = img.split()[-1]
        bbox = alpha.getbbox()
        if bbox:
            img = img.crop(bbox)

    # white background
    white_bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
    white_bg.paste(img, (0, 0), img)
    img = white_bg.convert('L')
    
    w, h = img.size
    if preserve_aspect:
        scale = min(TARGET_W / w, TARGET_H / h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
    else:
        new_w, new_h = TARGET_W, TARGET_H
        
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    final_img = Image.new('L', (TARGET_W, TARGET_H), 255)
    offset_x = (TARGET_W - new_w) // 2
    offset_y = (TARGET_H - new_h) // 2
    final_img.paste(img, (offset_x, offset_y))
    
    if method == 'thresh':
        # Simple threshold
        return final_img.point(lambda p: 255 if p > 128 else 0, mode='1')
    elif method == 'dither':
        # Floyd-Steinberg
        return final_img.convert('1', dither=Image.Dither.FLOYDSTEINBERG)
    elif method == 'bayer':
        # simple ordered dither? PIL doesn't have it built-in easily for '1'.
        # Let's just return dither
        return final_img.convert('1', dither=Image.Dither.FLOYDSTEINBERG)

def build_grid():
    files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith('.png')])
    
    cols = 8
    rows = math.ceil(len(files) / cols)
    
    cell_w = TARGET_W + 10
    cell_h = TARGET_H + 10
    
    grid_img1 = Image.new('RGB', (cols * cell_w, rows * cell_h), (255, 255, 255))
    grid_img2 = Image.new('RGB', (cols * cell_w, rows * cell_h), (255, 255, 255))
    grid_img3 = Image.new('RGB', (cols * cell_w, rows * cell_h), (255, 255, 255))
    
    for i, f in enumerate(files):
        path = os.path.join(INPUT_DIR, f)
        
        # 1. As is in master (squashed, threshold)
        im1 = process(path, 'thresh', False, False)
        # 2. Aspect preserved, threshold
        im2 = process(path, 'thresh', True, False)
        # 3. Aspect preserved, cropped padding, threshold
        im3 = process(path, 'thresh', True, True)
        
        col = i % cols
        row = i // cols
        x = col * cell_w + 5
        y = row * cell_h + 5
        
        grid_img1.paste(im1.convert('RGB'), (x, y))
        grid_img2.paste(im2.convert('RGB'), (x, y))
        grid_img3.paste(im3.convert('RGB'), (x, y))
        
    grid_img1.save('grid_squashed_thresh.png')
    grid_img2.save('grid_aspect_thresh.png')
    grid_img3.save('grid_cropped_aspect_thresh.png')
    print("Grids saved!")

if __name__ == '__main__':
    build_grid()
