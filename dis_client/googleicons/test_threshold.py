#!/usr/bin/env python3
"""
Compare threshold values for icon processing.
Generates a grid for each threshold value so you can pick the best one.
"""
import os
import math
from PIL import Image, ImageDraw, ImageFont

TARGET_W = 31
TARGET_H = 37
INPUT_DIR = 'pngs'

THRESHOLDS = [100, 128, 150, 160, 170, 190, 210, 230]

def process(path, threshold):
    img = Image.open(path).convert('RGBA')
    white_bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
    white_bg.paste(img, mask=img.split()[3])
    img_gray = white_bg.convert('L')
    img_gray = img_gray.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    # Simple threshold — no dithering
    img_1bit = img_gray.point(lambda p: 0 if p < threshold else 255, mode='L')
    return img_1bit

def build_comparison():
    files = sorted([f for f in os.listdir(INPUT_DIR) if f.endswith('.png')])
    n = len(files)

    padding = 3
    scale = 3
    label_h = 8  # space for threshold label at top of each column

    cols = n
    rows = len(THRESHOLDS)

    cell_w = (TARGET_W + padding * 2)
    cell_h = (TARGET_H + padding * 2)

    grid_w = cols * cell_w
    grid_h = rows * (cell_h + label_h)

    grid = Image.new('RGB', (grid_w, grid_h), (200, 200, 200))

    for row_i, thresh in enumerate(THRESHOLDS):
        for col_i, fname in enumerate(files):
            path = os.path.join(INPUT_DIR, fname)
            im = process(path, thresh)
            x = col_i * cell_w + padding
            y = row_i * (cell_h + label_h) + label_h + padding
            grid.paste(im.convert('RGB'), (x, y))

    # Scale up
    grid = grid.resize((grid_w * scale, grid_h * scale), Image.Resampling.NEAREST)

    # Add threshold labels on the left side (drawn after scaling)
    draw = ImageDraw.Draw(grid)
    for row_i, thresh in enumerate(THRESHOLDS):
        y = row_i * (cell_h + label_h) * scale + 2
        draw.text((2, y), f"t={thresh}", fill=(255, 0, 0))

    grid.save('threshold_comparison.png')
    print("Saved threshold_comparison.png")

if __name__ == '__main__':
    build_comparison()
