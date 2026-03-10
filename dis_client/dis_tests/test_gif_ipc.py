#!/usr/bin/env python3
import zmq
import time
import json
import os
import sys
from PIL import Image

def extract_deltas(prev_img: Image.Image, curr_img: Image.Image, granular: bool = False):
    """Return a list of update segments for pixels that changed between frames.

    Without granular: one segment per changed row (full row width, x=0).
    With granular: one trimmed segment per changed row — leading/trailing
    unchanged bytes are skipped, but the row is never split into multiple
    commands.  Each draw_raw_bitmap carries ~90 bytes of JSON overhead while
    a full row is only 8 bytes (64px); skipping a 1-byte internal gap saves
    2 bytes of payload but costs an extra ~90-byte command, so splitting
    always loses.  Trimming the leading/trailing edges is the only case where
    skipping bytes beats the overhead.
    Minimum granularity is 8 pixels (one packed byte) in both modes.
    """
    w, h = curr_img.size

    updates = []

    prev_pixels = prev_img.load() if prev_img else None
    curr_pixels = curr_img.load()

    blocks = []
    current_block = None

    for y in range(h):
        row_bytes = []
        changed = []

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

            row_bytes.append(curr_byte)
            changed.append(curr_byte != prev_byte or prev_img is None)

        if not any(changed):
            if current_block:
                blocks.append(current_block)
                current_block = None
            continue

        if not granular:
            row_x = 0
            row_data = bytes(row_bytes)
        else:
            first = next(i for i, c in enumerate(changed) if c)
            last  = len(changed) - 1 - next(i for i, c in enumerate(reversed(changed)) if c)
            row_x = first * 8
            row_data = bytes(row_bytes[first:last + 1])
            
        if current_block and current_block['x'] == row_x and len(current_block['data']) // current_block['h'] == len(row_data):
            current_block['data'] += row_data
            current_block['h'] += 1
        else:
            if current_block:
                blocks.append(current_block)
            current_block = {
                'y': y,
                'x': row_x,
                'h': 1,
                'data': row_data
            }
            
    if current_block:
        blocks.append(current_block)

    return blocks

def run_test():
    import argparse
    from PIL import ImageOps, ImageEnhance, ImageFilter
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true', help='Connect to DIS Emulator (TCP 5557)')
    parser.add_argument('--file', type=str, default='polish_cow.gif', help='Path to the GIF file to play')
    parser.add_argument('--invert', action='store_true', help='Invert the colors of the GIF')
    parser.add_argument('--fps', type=float, default=5.0, help='Playback framerate (default: 5)')
    parser.add_argument('--contrast', type=float, default=1.8, help='Contrast multiplier before dithering (default: 1.8)')
    parser.add_argument('--sharpen', type=float, default=1.5, help='Sharpness multiplier before dithering (default: 1.5)')
    parser.add_argument('--dither', type=str, choices=['fs', 'none', 'bayer'], default='fs', help='Dithering algorithm (fs=Floyd-Steinberg, none=Threshold, bayer=Ordered)')
    parser.add_argument('--no-enhance', action='store_true', help='Skip all enhancements, raw dither only')
    parser.add_argument('--delta', action='store_true', help='Send sub-row byte-span segments instead of whole rows (min 8px granularity)')
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
        
        # White letterbox: matches typical GIF/white backgrounds so empty borders
        # dither cleanly to solid white rather than a noisy 50% grey pattern.
        canvas = Image.new("RGB", target_size, (255, 255, 255))
        offset_x = (target_size[0] - frame.size[0]) // 2
        offset_y = (target_size[1] - frame.size[1]) // 2
        canvas.paste(frame, (offset_x, offset_y))
        
        if args.invert:
            canvas = ImageOps.invert(canvas)
        
        if args.no_enhance:
            curr_dithered = canvas.convert('1')
        else:
            # Convert to grayscale for a controlled enhancement pipeline
            gray = canvas.convert('L')
            
            # 1. Autocontrast: stretch histogram so darkest pixel → 0, brightest → 255.
            #    cutoff=1 clips the top/bottom 1% of pixels to handle blown-out whites
            #    or near-black shadows that would otherwise anchor the stretch badly.
            gray = ImageOps.autocontrast(gray, cutoff=1)
            
            # 2. Contrast boost: push midtones toward black/white so the ditherer
            #    produces crisper areas rather than uniform 50% noise.
            gray = ImageEnhance.Contrast(gray).enhance(args.contrast)
            
            # 3. Unsharp mask: compensate for LANCZOS softness at tiny resolution.
            #    Radius 1 = tight (sub-pixel scale for 64px images), percent controls
            #    strength, threshold 3 avoids sharpening noise in flat areas.
            gray = gray.filter(ImageFilter.UnsharpMask(radius=1, percent=int(args.sharpen * 100), threshold=3))
            
            if args.dither == 'fs':
                curr_dithered = gray.convert('1', dither=Image.FLOYDSTEINBERG)
            elif args.dither == 'none':
                curr_dithered = gray.convert('1', dither=Image.Dither.NONE)
            elif args.dither == 'bayer':
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
                curr_dithered = bayer_img.convert('1', dither=Image.Dither.NONE)
        
        frames_dithered.append(curr_dithered)
        
    delta_frames = []
    for f_idx in range(len(frames_dithered)):
        prev_idx = f_idx - 1 if f_idx > 0 else len(frames_dithered) - 1
        rows = extract_deltas(frames_dithered[prev_idx], frames_dithered[f_idx], granular=args.delta)
        delta_frames.append(rows)

    # To initialize the physical screen before the loop, we need a payload connecting a blank black screen to Frame 0
    black_canvas = Image.new('1', target_size, 0)
    prime_rows = extract_deltas(black_canvas, frames_dithered[0], granular=args.delta)
        
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
