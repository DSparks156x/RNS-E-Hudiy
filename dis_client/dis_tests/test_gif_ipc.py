#!/usr/bin/env python3
import zmq
import time
import json
import os
import sys
from PIL import Image

# Add parent directory to sys.path to allow importing dis_image
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dis_image

def run_test():
    import argparse
    from PIL import ImageOps, ImageEnhance, ImageFilter
    parser = argparse.ArgumentParser()
    parser.add_argument('file', help='Path to GIF file')
    parser.add_argument('--contrast', type=float, default=1.4)
    parser.add_argument('--brightness', type=float, default=1.0)
    parser.add_argument('--gamma', type=float, default=2.2)
    parser.add_argument('--black-floor', type=int, default=45)
    parser.add_argument('--sharpen', type=float, default=1.5)
    parser.add_argument('--boldness', type=int, default=0)
    parser.add_argument('--dither', choices=['fs', 'atkinson', 'none'], default='fs')
    parser.add_argument('--diffusion', type=float, default=0.85)
    parser.add_argument('--invert', action='store_true')
    parser.add_argument('--no-enhance', action='store_true')
    parser.add_argument('--grayscale-mode', choices=['smart', 'weighted', 'max', 'balanced'], default='smart')
    parser.add_argument('--delta', action='store_true', help='Use granular delta updates', default=True)
    parser.add_argument('--no-delta', dest='delta', action='store_false')
    parser.add_argument('--fps', type=int, default=10)
    parser.add_argument('--mock', action='store_true', help='Connect to DIS Emulator (TCP 5557)')
    parser.add_argument('--bg-fill', choices=['black', 'white', 'edge', 'blur'], default='black')
    args = parser.parse_args()

    # Load config to get the IPC address, or default to standard location
    config_path = '/home/pi/config.json'
    # Fallback to local config if present (e.g., ran from project root)
    if not os.path.exists(config_path) and os.path.exists('./config.json'):
        config_path = './config.json'

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
        curr_dithered = dis_image.process_image(
            img, 
            target_size=target_size, 
            contrast=args.contrast, 
            brightness=args.brightness,
            gamma=args.gamma,
            black_floor=args.black_floor,
            sharpen=args.sharpen, 
            boldness=args.boldness,
            dither=args.dither, 
            diffusion=args.diffusion,
            invert=args.invert, 
            no_enhance=args.no_enhance,
            bg_fill=args.bg_fill,
            grayscale_mode=args.grayscale_mode
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
