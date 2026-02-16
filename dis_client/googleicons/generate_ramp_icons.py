#!/usr/bin/env python3
from PIL import Image, ImageDraw
import os
import sys

# Constants
ICON_W = 31
ICON_H = 37
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_DIR = os.path.join(BASE_DIR, 'processed')
OUTPUT_DIR = os.path.join(BASE_DIR, 'generated_ramps')

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def load_icon(name):
    path = os.path.join(PROCESSED_DIR, f"ic_{name}.png")
    if not os.path.exists(path):
        print(f"Error: {path} not found")
        return None
    return Image.open(path).convert("RGBA")

def create_blank():
    return Image.new("RGBA", (ICON_W, ICON_H), (0, 0, 0, 0))

def generate_ramps():
    # Load primitives
    straight = load_icon("straight")
    slight_right = load_icon("turn_slight_right")
    slight_left = load_icon("turn_slight_left")
    
    if not all([straight, slight_right, slight_left]):
        return

    # --- OFF RAMP RIGHT ---
    # Concept: Straight arrow on left + Slight Right arrow branching off
    # Resize slightly to fit?
    
    # 1. Main Path (Straight) - Shifted Left
    off_ramp_r = create_blank()
    # Mask straight to be thinner? Or just offset
    # Let's try offset straight to left by 4px
    s_left = Image.new("RGBA", (ICON_W, ICON_H), (0,0,0,0))
    s_left.paste(straight, (-6, 0)) 
    
    # 2. Exit Path (Slight Right) - Shifted Right
    # Maybe scale it down to 80%?
    sr_small = slight_right.resize((int(ICON_W*0.9), int(ICON_H*0.9)), Image.Resampling.NEAREST)
    sr_layer = Image.new("RGBA", (ICON_W, ICON_H), (0,0,0,0))
    # Paste centered/right
    sr_layer.paste(sr_small, (6, 2))
    
    # Composite: Straight is main, Exit is secondary.
    # Actually, usually Off Ramp shows both equal or main straight.
    # Let's paste Straight then Exit.
    off_ramp_r = Image.alpha_composite(off_ramp_r, s_left)
    off_ramp_r = Image.alpha_composite(off_ramp_r, sr_layer)
    
    # Add a separator line?
    draw = ImageDraw.Draw(off_ramp_r)
    # Draw vertical dashed line between them
    # x approx 15
    for y in range(8, 30, 4):
        draw.line([(14, y), (14, y+2)], fill=(255, 255, 255, 255), width=1)
        
    off_ramp_r.save(os.path.join(OUTPUT_DIR, "ramp_off_right.png"))
    print("Generated ramp_off_right.png")


    # --- OFF RAMP LEFT ---
    # Mirror of Right
    off_ramp_l = off_ramp_r.transpose(Image.FLIP_LEFT_RIGHT)
    off_ramp_l.save(os.path.join(OUTPUT_DIR, "ramp_off_left.png"))
    print("Generated ramp_off_left.png")


    # --- ON RAMP RIGHT ---
    # Concept: Main path (Straight) + Entry from Right
    
    on_ramp_r = create_blank()
    
    # 1. Main Path (Straight) - Shifted Left
    # Same as off ramp
    on_ramp_r = Image.alpha_composite(on_ramp_r, s_left)
    
    # 2. Entry Path (Slight Left? No, Slight Right but rotated or mirrored?)
    # On ramp from right implies merging LEFT into traffic.
    # So we need a arrow pointing Top-Left, coming from Bottom-Right.
    # That is `slight_left`. Positioned on the right.
    
    # Let's define "Entry" as the user's path.
    # If I am ON RAMPING, I am the one merging. 
    # Icon usually shows "Merge" symbol: Two arrows becoming one.
    # But `ic_merge.png` exists. Let's see if we should just use that.
    # User asked for ON RAMP.
    # If On Ramp = Merge, we can just alias it.
    # But often On Ramp is "Enter highway".
    # Let's generate a "Merge" style specific for On Ramp if standard merge isn't enough.
    # Let's stick to the "Two distinct paths" style.
    
    # On Ramp Right: I am on the right, merging into left.
    entr_layer = Image.new("RGBA", (ICON_W, ICON_H), (0,0,0,0))
    sl_small = slight_left.resize((int(ICON_W*0.9), int(ICON_H*0.9)), Image.Resampling.NEAREST)
    entr_layer.paste(sl_small, (8, 2)) # Shifted right, pointing left
    
    # This might look like colliding.
    # Let's try: Straight arrow (Left) + Curved arrow coming from right.
    
    # Alternative: Just use the `slight_left` icon but shifted?
    # Let's generate a "Lane Merge" icon.
    
    on_ramp_r = create_blank()
    on_ramp_r.paste(s_left, (0,0))
    on_ramp_r = Image.alpha_composite(on_ramp_r, entr_layer)
    
    # Separator line stops halfway?
    draw = ImageDraw.Draw(on_ramp_r)
    for y in range(18, 36, 4):
         draw.line([(14, y), (14, y+2)], fill=(255, 255, 255, 255), width=1)

    on_ramp_r.save(os.path.join(OUTPUT_DIR, "ramp_on_right.png"))
    print("Generated ramp_on_right.png")
    
    # --- ON RAMP LEFT ---
    on_ramp_l = on_ramp_r.transpose(Image.FLIP_LEFT_RIGHT)
    on_ramp_l.save(os.path.join(OUTPUT_DIR, "ramp_on_left.png"))
    print("Generated ramp_on_left.png")

if __name__ == "__main__":
    generate_ramps()
