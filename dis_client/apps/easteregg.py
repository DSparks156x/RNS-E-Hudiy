import os
import json
import time
from PIL import Image
from .base import BaseApp
import dis_image

class EasterEggApp(BaseApp):
    def __init__(self, config=None):
        super().__init__(config)
        self.gif_path = ""
        self.frames = []
        self.full_frames = []
        self._full_frame = True
        self._snapshot_pending = True
        self._view_generation = 0
        self.current_frame_idx = 0
        self.last_frame_time = 0
        self.fps = 10
        self.is_loaded = False
        
        # Sequencing for flow control
        self.last_sent_seq = 0
        self.last_acked_seq = 0
        self._pending_since = None
        try:
            self.ack_timeout_s = float((config or {}).get('display', {}).get('animation_ack_timeout_s', 10.0))
        except (TypeError, ValueError) as exc:
            raise ValueError('display.animation_ack_timeout_s must be finite and positive') from exc
        if not 0 < self.ack_timeout_s < float('inf'):
            raise ValueError('display.animation_ack_timeout_s must be finite and positive')
        self.loop_count = 999
        self.current_loop = 0
        self.finished = False

    def on_frame_sent(self, seq):
        self.last_sent_seq = seq
        self._pending_since = time.monotonic()
        self._snapshot_pending = False

    def on_frame_acked(self, seq):
        if seq == self.last_sent_seq:
            self.last_acked_seq = seq
            self._pending_since = None

    def on_frame_failed(self, seq):
        if seq != self.last_sent_seq:
            return
        self.on_display_reset()

    def on_display_reset(self):
        # A delta needs its preceding image. After a failed frame or ownership
        # interruption, restore a complete snapshot instead of replaying a delta.
        self.last_acked_seq = self.last_sent_seq
        self._pending_since = None
        self._full_frame = True
        self._snapshot_pending = True
        self._view_generation += 1
        self.last_frame_time = time.time()

    def load_gif(self, filename, loop_count=999, **processing_params):
        """Pre-process GIF into full snapshots, or an explicitly chosen delta strategy."""
        full_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'eggs', filename)
        if not os.path.exists(full_path):
            print(f"Egg GIF not found: {full_path}")
            return False
        
        self.gif_path = full_path
        self.frames = []
        self.full_frames = []
        self._full_frame = True
        self._snapshot_pending = True
        self._view_generation = 0
        self.current_frame_idx = 0
        self.is_loaded = False
        self.last_sent_seq = 0
        self.last_acked_seq = 0
        self._pending_since = None
        self.loop_count = loop_count
        self.current_loop = 0
        self.finished = False

        img = None
        try:
            img = Image.open(full_path)
            target_size = (64, 48)
            
            # Extract basic GIF info
            info = img.info
            duration = info.get('duration', 100) # ms
            if duration > 0:
                self.fps = 1000.0 / duration
            else:
                self.fps = 10
            
            # Limited to 15 FPS for stability
            self.fps = min(self.fps, 15)

            # Default parameters
            params = {
                'contrast': 1.4,
                'sharpen': 1.5,
                'dither': 'atkinson'
            }
            # Override with user provided params
            delta_strategy = processing_params.pop('delta_strategy', 'full')
            if delta_strategy not in ('full', 'rows', 'granular', 'adaptive'):
                raise ValueError(f'Unknown animation delta strategy: {delta_strategy}')
            params.update(processing_params)

            raw_frames = []
            for f_idx in range(img.n_frames):
                img.seek(f_idx)
                # Use standard processing parameters for best visual quality
                dithered = dis_image.process_image(
                    img, 
                    target_size=target_size, 
                    **params
                )
                raw_frames.append(dithered)
            
            self.full_frames = [[{
                'cmd': 'draw_raw_bitmap', 'data_hex': dis_image.image_to_bitmap(frame).hex(),
                'w': 64, 'h': 48, 'x': 0, 'y': 0, 'mode_flag': 2
            }] for frame in raw_frames]

            # Full snapshots avoid the command/window overhead of many small
            # dirty rectangles. Delta strategies remain explicit alternatives.
            if delta_strategy == 'full':
                self.frames = [[dict(command) for command in frame] for frame in self.full_frames]
                self.is_loaded = True
                return True

            for f_idx in range(len(raw_frames)):
                prev_idx = f_idx - 1 if f_idx > 0 else len(raw_frames) - 1
                # Use the explicitly selected delta strategy.
                if delta_strategy == 'adaptive':
                    delta_blocks = dis_image.extract_deltas_optimized(raw_frames[prev_idx], raw_frames[f_idx])
                else:
                    delta_blocks = dis_image.extract_deltas(raw_frames[prev_idx], raw_frames[f_idx], granular=delta_strategy != 'rows')
                
                # Convert blocks to draw commands
                frame_cmds = []
                for b in delta_blocks:
                    frame_cmds.append({
                        'cmd': 'draw_raw_bitmap',
                        'data_hex': b['data'].hex(),
                        'w': (len(b['data']) // b['h']) * 8,
                        'h': b['h'],
                        'x': b['x'],
                        'y': b['y'],
                        'mode_flag': 0x02
                    })
                self.frames.append(frame_cmds)
            
            self.is_loaded = True
            return True
        except Exception as e:
            print(f"Failed to load GIF {filename}: {e}")
            return False
        finally:
            if img is not None:
                img.close()

    def on_enter(self):
        super().on_enter()
        self.current_frame_idx = 0
        self._full_frame = True
        self._snapshot_pending = True
        self._view_generation += 1
        self.last_frame_time = time.time()
        self.last_sent_seq = 0
        self.last_acked_seq = 0
        self._pending_since = None
        self.current_loop = 0
        self.finished = False

    def get_view(self):
        if not self.is_loaded or not self.frames:
            return [{'type': 'easter_egg', 'cmd': 'clear', 'clear_on_update': True}]

        # PUB/SUB feedback can be lost while the service remains READY.
        # A bounded wait restores this same image as a full snapshot; it never
        # advances a delta whose predecessor has an unknown outcome. A new view
        # generation makes the renderer resend even when the image is unchanged.
        if (self._pending_since is not None
                and self.last_acked_seq != self.last_sent_seq
                and time.monotonic() - self._pending_since >= self.ack_timeout_s):
            self.on_display_reset()

        now = time.time()
        frame_time = 1.0 / self.fps
        
        # Only advance if: 
        # 1. Enough time has passed for the next frame
        # 2. THE PREVIOUS FRAME IS FULLY ACKNOWLEDGED by the service
        # Exact sequence equality also works when the UI sequence wraps.
        if not self._snapshot_pending and (now - self.last_frame_time >= frame_time) and (self.last_acked_seq == self.last_sent_seq):
            self._full_frame = False
            next_idx = self.current_frame_idx + 1
            if next_idx >= len(self.frames):
                self.current_loop += 1
                # 999 is Infinite
                if self.loop_count == 999 or self.current_loop < self.loop_count:
                    self.current_frame_idx = 0
                    self.last_frame_time = now
                else:
                    self.finished = True
            else:
                self.current_frame_idx = next_idx
                self.last_frame_time = now
        
        source = self.full_frames if self._full_frame else self.frames
        cmds = [dict(cmd) for cmd in source[self.current_frame_idx]]
        for cmd in cmds:
            cmd['group'] = f"frame_{self.current_frame_idx}_{self._view_generation}"
        # The renderer skips type descriptors. Keep it separate so the first
        # bitmap tile is rendered rather than being mistaken for a descriptor.
        return [{'type': 'easter_egg'}] + cmds
