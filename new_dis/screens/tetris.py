from typing import List, Dict, Any
import time
import random

from .base import ScreenBase

class TetrisScreen(ScreenBase):
    def __init__(self):
        super().__init__()
        self.needs_full_screen = True
        
        # Grid: 10 columns, 20 rows
        self.cols = 10
        self.rows = 20
        self.grid = [[0 for _ in range(self.cols)] for _ in range(self.rows)]
        
        self.score = 0
        self.game_over = False
        
        # Current Piece
        self.cx = 4
        self.cy = 0
        self.cshape = []
        
        self.last_drop_time = time.time()
        self.drop_interval = 1.0 # seconds
        self._spawn_piece()

    def _spawn_piece(self):
        shapes = [
            [[1,1,1,1]], # I
            [[1,1],[1,1]], # O
            [[1,1,1],[0,1,0]], # T
            [[1,1,1],[1,0,0]], # L
            [[1,1,1],[0,0,1]], # J
            [[1,1,0],[0,1,1]], # S
            [[0,1,1],[1,1,0]]  # Z
        ]
        self.cshape = random.choice(shapes)
        self.cx = self.cols // 2 - len(self.cshape[0]) // 2
        self.cy = 0
        
        if self._check_collision(self.cx, self.cy, self.cshape):
            self.game_over = True

    def _check_collision(self, dx, dy, shape) -> bool:
        for ry, row in enumerate(shape):
            for rx, cell in enumerate(row):
                if cell:
                    nx = dx + rx
                    ny = dy + ry
                    if nx < 0 or nx >= self.cols or ny >= self.rows:
                        return True
                    if ny >= 0 and self.grid[ny][nx] != 0:
                        return True
        return False

    def _merge_piece(self):
        for ry, row in enumerate(self.cshape):
            for rx, cell in enumerate(row):
                if cell:
                    self.grid[self.cy + ry][self.cx + rx] = 1
        self._clear_lines()
        self._spawn_piece()

    def _clear_lines(self):
        lines_to_clear = [i for i, row in enumerate(self.grid) if all(row)]
        for i in lines_to_clear:
            del self.grid[i]
            self.grid.insert(0, [0 for _ in range(self.cols)])
            self.score += 100
        if lines_to_clear:
            self.drop_interval = max(0.2, self.drop_interval - 0.05)

    def handle_button_press(self, button_name: str, event_type: str):
        if self.game_over:
            if button_name == 'up' and event_type == 'tap':
                # Reset
                self.grid = [[0 for _ in range(self.cols)] for _ in range(self.rows)]
                self.score = 0
                self.game_over = False
                self._spawn_piece()
            return

        if event_type == 'tap':
            if button_name == 'left':
                if not self._check_collision(self.cx - 1, self.cy, self.cshape):
                    self.cx -= 1
            elif button_name == 'right':
                if not self._check_collision(self.cx + 1, self.cy, self.cshape):
                    self.cx += 1
            elif button_name == 'up':
                # Rotate
                rot = list(zip(*self.cshape[::-1]))
                rot = [list(r) for r in rot]
                if not self._check_collision(self.cx, self.cy, rot):
                    self.cshape = rot
            elif button_name == 'down':
                # Hard drop
                while not self._check_collision(self.cx, self.cy + 1, self.cshape):
                    self.cy += 1
                self._merge_piece()
                self.last_drop_time = time.time()

    def render(self) -> List[Dict[str, Any]]:
        elements = []
        
        # Draw Score
        elements.append(self.create_text(f"SCORE:{self.score}", 0, 0))

        if self.game_over:
            elements.append(self.create_text("GAME OVER", 8, 40, flags=0x86))
            elements.append(self.create_text("Tap UP", 16, 50))
            return elements

        now = time.time()
        if now - self.last_drop_time > self.drop_interval:
            if not self._check_collision(self.cx, self.cy + 1, self.cshape):
                self.cy += 1
            else:
                self._merge_piece()
            self.last_drop_time = now

        # Render Grid (Playfield starts at y=10, 4x4 px blocks)
        # DIS is 64x88. Playfield = 10 cols x 20 rows. 
        # A text character " " with inverted flag is 6x9 pixels (normally). 
        # Using " " flag=0x86 produces a Red block of 6x9.
        # So 10 cols * 6 = 60 pixels wide. 
        # 20 rows * 9 = 180 pixels high -> TOO TALL for 88 pixels!
        
        # We must use "small" blocks or lines.
        # Alternatively, draw text characters like "[]" which takes 2 chars (12x9). Wait, 10 cols = 120 pixels wide.
        # Let's use `draw_line` to draw 4px squares, or `draw_bitmap` for tiny 4x4 squares.
        # Actually, let's use tiny bitmap blocks!
        # Assuming we add a 'tetris_block' bitmap to icons.py (4x4 pixels):
        
        # Since I don't have the bitmap yet, I'll use draw_line of length 4 for horizontal bars as blocks? 
        # Or just use the string "#" which is 6x9, but we can only fit 9 rows. (88/9 = 9.7 rows).
        # Let's adjust grid to 10 wide, 10 high for DIS constraints if using text!
        # Actually, draw_bitmap of predefined 4x4 block is much better.
        BLOCK_SIZE = 4
        X_OFFSET = 12 # center 10*4=40 inside 64 (12 offset)
        Y_OFFSET = 10 # below score

        # Draw static grid
        for r in range(min(self.rows, 19)):
            for c in range(self.cols):
                if self.grid[min(r, len(self.grid)-1)][c]:
                    # Using a tiny horizontal line of length 4 as a basic block approximation
                    # until the user imports a real Tetris bitmap block 
                    # 3 lines of 4 length tightly packed
                    px = X_OFFSET + (c * BLOCK_SIZE)
                    py = Y_OFFSET + (r * BLOCK_SIZE)
                    elements.append(self.create_line(px, py, length=3, vertical=False))
                    elements.append(self.create_line(px, py+1, length=3, vertical=False))
                    elements.append(self.create_line(px, py+2, length=3, vertical=False))

        # Draw current piece
        for ry, row in enumerate(self.cshape):
            for rx, cell in enumerate(row):
                if cell:
                    c = self.cx + rx
                    r = self.cy + ry
                    px = X_OFFSET + (c * BLOCK_SIZE)
                    py = Y_OFFSET + (r * BLOCK_SIZE)
                    elements.append(self.create_line(px, py, length=3, vertical=False))
                    elements.append(self.create_line(px, py+1, length=3, vertical=False))
                    elements.append(self.create_line(px, py+2, length=3, vertical=False))

        return elements
