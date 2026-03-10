#!/usr/bin/env python3
import zmq
import time
import json
import os
import sys
from PIL import Image

def extract_deltas(prev_img: Image.Image, curr_img: Image.Image):
    w, h = curr_img.size
    
    updated_rows = []
    
    prev_pixels = prev_img.load() if prev_img else None
    curr_pixels = curr_img.load()
    
    for y in range(h):
        curr_row = bytearray()
        has_change = False
        
        for x_byte in range(w // 8):
            curr_byte = 0
            prev_byte = 0
            
            for bit in range(8):
                x = (x_byte * 8) + bit
                cv = 1 if curr_pixels[x, y] > 0 else 0
                pv = 1 if prev_pixels and prev_pixels[x, y] > 0 else 0
                
                if cv == 1:
                    curr_byte |= (1 << (7 - bit))
                if pv == 1:
                    prev_byte |= (1 << (7 - bit))
            
            if curr_byte != prev_byte:
                has_change = True
            
            curr_row.append(curr_byte)
            
        if has_change or prev_img is None:
            updated_rows.append({
                'y': y,
                'data': bytes(curr_row)
            })
            
    return updated_rows

def run_test():
    import argparse
    from PIL import ImageOps
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true', help='Connect to DIS Emulator (TCP 5557)')
    parser.add_argument('--file', type=str, default='polish_cow.gif', help='Path to the GIF file to play')
    parser.add_argument('--invert', action='store_true', help='Invert the colors of the GIF')
    parser.add_argument('--fps', type=float, default=5.0, help='Playback framerate (default: 5)')
    args = parser.parse_args()

    # Load config to get the IPC address, or default to standard location
    config_path = '/home/pi/config.json'
    if not os.path.exists(config_path) and os.path.exists('../../config.json'):
        config_path = '../../config.json'

    if args.mock:
        config_addr = "tcp://127.0.0.1:5557"
    else:
        try:
            with open(config_path) as f:
                config = json.load(f)
            
            # Check new structure first, then legacy
            zmq_cfg = config.get('interfaces', {}).get('zmq', {})
            if not zmq_cfg:
                zmq_cfg = config.get('zmq', {})
            
            config_addr = zmq_cfg.get('dis_draw', "tcp://127.0.0.1:5557")
        except Exception as e:
            # If we're not on a pi and it failed, fallback to mock implicitly
            config_addr = "tcp://127.0.0.1:5557"
            print(f"Assuming mock/emulator mode: {config_addr}")

    print(f"Connecting to {config_addr}...")
    context = zmq.Context()
    draw = context.socket(zmq.PUSH)
    draw.connect(config_addr)
    time.sleep(1)
    
    gif_path = args.file
    if not os.path.exists(gif_path):
        print(f"Error: {gif_path} not found.")
        return
        
    print(f"Loading and processing {gif_path}...")
    img = Image.open(gif_path)
    
    target_size = (64, 48)
    
    frames_dithered = []
    
    for f_idx in range(img.n_frames):
        img.seek(f_idx)
        frame = img.copy().convert("RGB")
        frame.thumbnail(target_size, Image.Resampling.LANCZOS)
        
        canvas = Image.new("RGB", target_size, (0, 0, 0))
        offset_x = (target_size[0] - frame.size[0]) // 2
        offset_y = (target_size[1] - frame.size[1]) // 2
        canvas.paste(frame, (offset_x, offset_y))
        
        if args.invert:
            canvas = ImageOps.invert(canvas)
        
        curr_dithered = canvas.convert('1')
        frames_dithered.append(curr_dithered)
        
    delta_frames = []
    for f_idx in range(len(frames_dithered)):
        prev_idx = f_idx - 1 if f_idx > 0 else len(frames_dithered) - 1
        rows = extract_deltas(frames_dithered[prev_idx], frames_dithered[f_idx])
        delta_frames.append(rows)

    # To initialize the physical screen before the loop, we need a payload connecting a blank black screen to Frame 0
    black_canvas = Image.new('1', target_size, 0)
    prime_rows = extract_deltas(black_canvas, frames_dithered[0])
        
    print(f"Computed {len(delta_frames)} delta frames. Starting playback on DIS...")

    draw.send_json({'command': 'set_region', 'region': 'central'})
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    print("Priming first frame layout...")
    for row in prime_rows:
        draw.send_json({
            'command': 'draw_raw_bitmap',
            'data_hex': row['data'].hex(),
            'w': 64, 'h': 1, 'x': 0, 'y': row['y'],
            'mode_flag': 0x02 # Draw Mode
        })
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    print("Playing optimized deltas (Ctrl+C to stop)...")
    try:
        while True:
            for f_idx, rows in enumerate(delta_frames):
                for row in rows:
                    draw.send_json({
                        'command': 'draw_raw_bitmap',
                        'data_hex': row['data'].hex(),
                        'w': 64, 
                        'h': 1, 
                        'x': 0, 
                        'y': row['y'],
                        'mode_flag': 0x02 # Draw Mode
                    })
                    
                draw.send_json({'command': 'commit'})
                time.sleep(1.0 / args.fps)
    except KeyboardInterrupt:
        pass
        
    print("\nClearing central screen...")
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})

if __name__ == "__main__":
    run_test()
