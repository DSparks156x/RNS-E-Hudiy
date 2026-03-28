#!/usr/bin/env python3
import zmq
import time
import json
import os
import sys
from PIL import Image

import dis_image

def run_test():
    import argparse
    from PIL import ImageOps, ImageEnhance, ImageFilter
    parser = argparse.ArgumentParser()
    # ... (args stay the same) ...
    args = parser.parse_args()

    # ... (config_addr logic stays the same) ...

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
        curr_dithered = dis_image.process_image(
            img, 
            target_size=target_size, 
            contrast=args.contrast, 
            sharpen=args.sharpen, 
            dither=args.dither, 
            invert=args.invert, 
            no_enhance=args.no_enhance
        )
        frames_dithered.append(curr_dithered)
        
    delta_frames = []
    for f_idx in range(len(frames_dithered)):
        prev_idx = f_idx - 1 if f_idx > 0 else len(frames_dithered) - 1
        rows = dis_image.extract_deltas(frames_dithered[prev_idx], frames_dithered[f_idx], granular=args.delta)
        delta_frames.append(rows)

    # To initialize the physical screen before the loop, we need a payload connecting a blank black screen to Frame 0
    black_canvas = Image.new('1', target_size, 0)
    prime_rows = dis_image.extract_deltas(black_canvas, frames_dithered[0], granular=args.delta)
        
    print(f"Computed {len(delta_frames)} delta frames. Starting playback on DIS...")

    draw.send_json({'command': 'set_region', 'region': 'central'})
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    print("Priming first frame layout...")
    for block in prime_rows:
        draw.send_json({
            'command': 'draw_raw_bitmap',
            'data_hex': block['data'].hex(),
            'w': (len(block['data']) // block['h']) * 8, 'h': block['h'], 'x': block['x'], 'y': block['y'],
            'mode_flag': 0x02 # Draw Mode
        })
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    print("Playing optimized deltas (Ctrl+C to stop)...")
    try:
        while True:
            for f_idx, blocks in enumerate(delta_frames):
                frame_start_time = time.time()
                for block in blocks:
                    draw.send_json({
                        'command': 'draw_raw_bitmap',
                        'data_hex': block['data'].hex(),
                        'w': (len(block['data']) // block['h']) * 8,
                        'h': block['h'],
                        'x': block['x'],
                        'y': block['y'],
                        'mode_flag': 0x02 # Draw Mode
                    })
                    
                draw.send_json({'command': 'commit'})
                
                elapsed = time.time() - frame_start_time
                print(f"Frame {f_idx} pushed to ZMQ in {elapsed:.3f}s (rows: {len(rows)})")
                
                # Deduct the time spent sending from the desired frame time
                frame_time = 1.0 / args.fps
                sleep_time = max(0, frame_time - elapsed)
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        pass
        
    print("\nClearing central screen...")
    draw.send_json({'command': 'clear'})
    draw.send_json({'command': 'commit'})

if __name__ == "__main__":
    run_test()
