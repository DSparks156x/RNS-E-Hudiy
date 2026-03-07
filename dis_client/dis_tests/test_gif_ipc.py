#!/usr/bin/env python3
import zmq
import time
import json
import os
import sys
from PIL import Image

def extract_deltas(prev_img: Image.Image, curr_img: Image.Image):
    w, h = curr_img.size
    
    set_rows = []
    erase_rows = []
    
    set_y_min = h; set_y_max = -1
    erase_y_min = h; erase_y_max = -1
    
    prev_pixels = prev_img.load() if prev_img else None
    curr_pixels = curr_img.load()
    
    for y in range(h):
        set_row = bytearray()
        erase_row = bytearray()
        row_has_set = False
        row_has_erase = False
        
        for x_byte in range(w // 8):
            set_byte = 0
            erase_byte = 0
            
            for bit in range(8):
                x = (x_byte * 8) + bit
                curr_val = 1 if curr_pixels[x, y] > 0 else 0
                prev_val = 1 if prev_pixels and prev_pixels[x, y] > 0 else 0
                
                if curr_val == 1 and prev_val == 0:
                    set_byte |= (1 << (7 - bit))
                    row_has_set = True
                elif curr_val == 0 and prev_val == 1:
                    erase_byte |= (1 << (7 - bit))
                    row_has_erase = True
                    
            set_row.append(set_byte)
            erase_row.append(erase_byte)
            
        set_rows.append(set_row)
        erase_rows.append(erase_row)
            
        if row_has_set:
            if y < set_y_min: set_y_min = y
            if y > set_y_max: set_y_max = y
            
        if row_has_erase:
            if y < erase_y_min: erase_y_min = y
            if y > erase_y_max: erase_y_max = y

    set_dict = None
    if set_y_min <= set_y_max:
        set_data = bytearray()
        for y in range(set_y_min, set_y_max + 1):
            set_data.extend(set_rows[y])
        set_h = (set_y_max - set_y_min) + 1
        set_dict = {
            'data': bytes(set_data),
            'y': set_y_min,
            'h': set_h
        }

    erase_dict = None
    if erase_y_min <= erase_y_max:
        erase_data = bytearray()
        for y in range(erase_y_min, erase_y_max + 1):
            erase_data.extend(erase_rows[y])
        erase_h = (erase_y_max - erase_y_min) + 1
        erase_dict = {
            'data': bytes(erase_data),
            'y': erase_y_min,
            'h': erase_h
        }
            
    return (set_dict, erase_dict)

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
        set_payload, erase_payload = extract_deltas(frames_dithered[prev_idx], frames_dithered[f_idx])
        delta_frames.append((set_payload, erase_payload))

    # To initialize the physical screen before the loop, we need a payload connecting a blank black screen to Frame 0
    black_canvas = Image.new('1', target_size, 0)
    prime_set, prime_erase = extract_deltas(black_canvas, frames_dithered[0])
        
    print(f"Computed {len(delta_frames)} delta frames. Starting playback on DIS...")

    draw.send_json({'command': 'set_region', 'region': 'central'})
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(1)

    print("Priming first frame layout...")
    if prime_erase:
        draw.send_json({
            'command': 'draw_raw_bitmap',
            'data_hex': prime_erase['data'].hex(),
            'w': 64, 'h': prime_erase['h'], 'x': 0, 'y': prime_erase['y'],
            'mode_flag': 0x00
        })
    if prime_set:
        draw.send_json({
            'command': 'draw_raw_bitmap',
            'data_hex': prime_set['data'].hex(),
            'w': 64, 'h': prime_set['h'], 'x': 0, 'y': prime_set['y'],
            'mode_flag': 0x03
        })
    draw.send_json({'command': 'commit'})
    time.sleep(0.5)

    print("Playing optimized deltas (Ctrl+C to stop)...")
    try:
        while True:
            for f_idx, (set_dict, erase_dict) in enumerate(delta_frames):
                if erase_dict:
                    draw.send_json({
                        'command': 'draw_raw_bitmap',
                        'data_hex': erase_dict['data'].hex(),
                        'w': 64, 
                        'h': erase_dict['h'], 
                        'x': 0, 
                        'y': erase_dict['y'],
                        'mode_flag': 0x00 # Erase Mode
                    })
                
                if set_dict:
                    draw.send_json({
                        'command': 'draw_raw_bitmap',
                        'data_hex': set_dict['data'].hex(),
                        'w': 64, 
                        'h': set_dict['h'], 
                        'x': 0, 
                        'y': set_dict['y'],
                        'mode_flag': 0x03 # Set Mode
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
