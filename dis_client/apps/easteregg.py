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
        self.current_frame_idx = 0
        self.last_frame_time = 0
        self.fps = 10
        self.is_loaded = False
        
        # Sequencing for flow control
        self.last_sent_seq = 0
        self.last_acked_seq = 0
        self.loop_count = 999
        self.current_loop = 0
        self.finished = False

    def on_frame_sent(self, seq):
        self.last_sent_seq = seq

    def on_frame_acked(self, seq):
        if seq > self.last_acked_seq:
            self.last_acked_seq = seq

    def load_gif(self, filename, loop_count=999, **processing_params):
        """Pre-process GIF into dithered delta frames."""
        full_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'eggs', filename)
        if not os.path.exists(full_path):
            print(f"Egg GIF not found: {full_path}")
            return False
        
        self.gif_path = full_path
        self.frames = []
        self.current_frame_idx = 0
        self.is_loaded = False
        self.last_sent_seq = 0
        self.last_acked_seq = 0
        self.loop_count = loop_count
        self.current_loop = 0
        self.finished = False

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
            
            # Compute deltas
            for f_idx in range(len(raw_frames)):
                prev_idx = f_idx - 1 if f_idx > 0 else len(raw_frames) - 1
                # We use granular deltas for performance
                delta_blocks = dis_image.extract_deltas(raw_frames[prev_idx], raw_frames[f_idx], granular=True)
                
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

    def on_enter(self):
        super().on_enter()
        self.current_frame_idx = 0
        self.last_frame_time = time.time()
        self.last_sent_seq = 0
        self.last_acked_seq = 0
        self.current_loop = 0
        self.finished = False

    def get_view(self):
        if not self.is_loaded or not self.frames:
            return [{'type': 'easter_egg', 'cmd': 'clear', 'clear_on_update': True}]

        now = time.time()
        frame_time = 1.0 / self.fps
        
        # Only advance if: 
        # 1. Enough time has passed for the next frame
        # 2. THE PREVIOUS FRAME IS FULLY ACKNOWLEDGED by the service
        # Note: self.last_acked_seq >= self.last_sent_seq ensures the pipe is clear.
        if (now - self.last_frame_time >= frame_time) and (self.last_acked_seq >= self.last_sent_seq):
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
        
        cmds = self.frames[self.current_frame_idx][:] # Work on a copy
        if cmds:
            cmds[0]['type'] = 'easter_egg'
        
        # Wrap everything in a group so dis_display treats it as one update
        for cmd in cmds:
            cmd['group'] = f"frame_{self.current_frame_idx}"
        
        return cmds
