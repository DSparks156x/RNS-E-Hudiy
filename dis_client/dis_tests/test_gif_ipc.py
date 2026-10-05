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

class FrameRejected(RuntimeError):
    pass


class FrameSender:
    """One frame in flight; match the service's transfer/commit result by seq."""
    def __init__(self, draw, status, timeout=10.0, clock=time.monotonic):
        self.draw, self.status = draw, status
        self.timeout, self.clock = timeout, clock
        self.seq = time.time_ns()
        self.pending = False

    def submit(self, commands):
        if self.pending:
            raise RuntimeError('A frame is already awaiting its result')
        self.seq += 1
        self.pending = True
        start = self.clock()
        self.draw.send_json({'command': 'frame', 'seq': self.seq, 'commands': commands})
        deadline = start + self.timeout
        while self.clock() < deadline:
            remaining = max(1, int((deadline - self.clock()) * 1000))
            if not self.status.poll(remaining):
                continue
            parts = self.status.recv_string().split()
            if len(parts) != 2 or parts[0] not in ('DRAW_ACK', 'DRAW_NACK'):
                continue
            try:
                seq = int(parts[1])
            except ValueError:
                continue
            if seq != self.seq:
                continue
            if parts[0] == 'DRAW_NACK':
                raise FrameRejected(f'Frame {seq} failed or screen ownership was unavailable')
            self.pending = False
            return self.clock() - start
        # Leave pending set: an unknown outcome cannot start another delta.
        raise TimeoutError(f'No result for frame {self.seq}; playback stopped without queuing more frames')


def playback_indices(frame_count):
    # Frame 0 has already been primed. Its wraparound delta is used only
    # after the final frame, not immediately after priming.
    index = 1 % frame_count
    while True:
        yield index
        index = (index + 1) % frame_count


def bitmap_commands(blocks):
    return [{'command': 'draw_raw_bitmap', 'data_hex': b['data'].hex(),
             'w': len(b['data']) // b['h'] * 8, 'h': b['h'],
             'x': b['x'], 'y': b['y'], 'mode_flag': 2} for b in blocks]



def extract_frame_blocks(previous, current, strategy):
    """Full mode includes every pixel even when two images are identical."""
    if strategy == 'full':
        return [{'x': 0, 'y': 0, 'h': current.height,
                 'data': dis_image.image_to_bitmap(current)}]
    if strategy == 'adaptive':
        return dis_image.extract_deltas_optimized(previous, current)
    return dis_image.extract_deltas(previous, current, granular=strategy == 'granular')


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
    parser.add_argument('--delta-strategy', choices=['full', 'granular', 'rows', 'adaptive'])
    parser.add_argument('--delta', action='store_true', help='Use granular delta updates', default=True)
    parser.add_argument('--no-delta', dest='delta', action='store_false')
    parser.add_argument('--fps', type=int, default=10)
    parser.add_argument('--mock', action='store_true', help='Connect to DIS Emulator (TCP 5557)')
    parser.add_argument('--ack-timeout', type=float, default=10.0)
    parser.add_argument('--settle-ms', type=float, default=0.0, help='Extra delay after the transport/commit ACK; LCD completion is not measured')
    parser.add_argument('--frames', type=int, default=0, help='Stop after N animation updates (0 loops forever)')
    parser.add_argument('--stop-file', help='Stop cleanly between frames when this file exists')
    parser.add_argument('--draw-address')
    parser.add_argument('--status-address')
    parser.add_argument('--bg-fill', choices=['black', 'white', 'edge', 'blur'], default='black')
    args = parser.parse_args()
    if args.fps <= 0 or args.ack_timeout <= 0 or args.settle_ms < 0 or args.frames < 0:
        parser.error('fps/ack-timeout must be positive; settle-ms/frames must be nonnegative')
    zmq_cfg = {}

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
        
    strategy = args.delta_strategy or ('granular' if args.delta else 'rows')
    def extract(previous, current):
        return extract_frame_blocks(previous, current, strategy)
    delta_frames = []
    for f_idx in range(len(frames_dithered)):
        prev_idx = f_idx - 1 if f_idx > 0 else len(frames_dithered) - 1
        rows = extract(frames_dithered[prev_idx], frames_dithered[f_idx])
        delta_frames.append(rows)

    # To initialize the physical screen before the loop, we need a payload connecting a blank black screen to Frame 0
    black_canvas = Image.new('1', target_size, 0)
    prime_rows = extract(black_canvas, frames_dithered[0])
        
    print(f"Computed {len(delta_frames)} delta frames. Starting playback on DIS...")

    status_addr = args.status_address or (
        'tcp://127.0.0.1:5562' if args.mock else
        zmq_cfg.get('dis_status', 'ipc:///run/rnse_control/dis_status.ipc'))
    config_addr = args.draw_address or config_addr
    print(f'Connecting draw={config_addr}, status={status_addr}')
    context = zmq.Context()
    draw = context.socket(zmq.PUSH)
    draw.setsockopt(zmq.LINGER, 0)
    draw.setsockopt(zmq.SNDHWM, 1)
    draw.setsockopt(zmq.SNDTIMEO, int(args.ack_timeout * 1000))
    status = context.socket(zmq.SUB)
    status.setsockopt(zmq.LINGER, 0)
    for topic in ('DRAW_ACK ', 'DRAW_NACK ', 'DIS_STATE '):
        status.subscribe(topic)
    status.connect(status_addr)
    draw.connect(config_addr)
    sender = FrameSender(draw, status, args.ack_timeout)
    try:
        # Wait for a heartbeat to verify the subscription before the first
        # frame. This avoids losing its result during PUB/SUB startup.
        deadline = time.monotonic() + args.ack_timeout
        while time.monotonic() < deadline:
            if status.poll(100) and status.recv_string() == 'DIS_STATE READY':
                break
        else:
            raise TimeoutError('No READY status received; no graphics were submitted')
        prime = [{'command': 'resume'}, {'command': 'set_region', 'region': 'central'},
                 {'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48}]
        prime += bitmap_commands(prime_rows)
        sender.submit(prime)
        print('Frame 0 primed and transfer acknowledged. Playing one frame at a time.')
        completed = 0
        for f_idx in playback_indices(len(delta_frames)):
            started = time.monotonic()
            elapsed = sender.submit(bitmap_commands(delta_frames[f_idx]))
            completed += 1
            print(f'Frame {f_idx}: transfer + commit ACK {elapsed:.3f}s '
                  f'({len(delta_frames[f_idx])} bitmap blocks; {1 / max(elapsed, 1e-9):.2f} transfers/s)')
            # Additional display settling is explicit, never inferred from
            # a transport ACK. FPS is a cap and cannot queue frames ahead.
            time.sleep(max(args.settle_ms / 1000,
                           1 / args.fps - (time.monotonic() - started), 0))
            if args.stop_file and os.path.isfile(args.stop_file):
                break
            if args.frames and completed >= args.frames:
                break
    except KeyboardInterrupt:
        print('\nPlayback stopped.')
    except (TimeoutError, FrameRejected, zmq.ZMQError) as exc:
        print(f'Playback stopped: {exc}', file=sys.stderr)
        return 1
    finally:
        draw.close()
        status.close()
        context.term()
    return 0


if __name__ == "__main__":
    sys.exit(run_test())
