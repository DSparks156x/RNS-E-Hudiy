# apps/openpilot.py
from .base import BaseApp
import time
import math
from PIL import Image, ImageDraw
import dis_image

class OpenpilotApp(BaseApp):
    def __init__(self, config=None):
        super().__init__(config)
        # Default State
        self.state = {
            'engaged': False,
            'steer_angle': 0.0,
            'steer_torque': 0.0,
            'model_confidence': 1.0,
            'speed': 0,
            'max_speed': 0,
            'lead_dist': 0.0,
            'lead_detected': False,
            'plan': None,
            'lane_lines': None,
            'road_edges': None
        }
        self.last_update_time = 0
        self.update_interval = 0.066 # ~15 FPS max refresh rate
        self.cached_view = []
        
        # Sequence tracking for flow control
        self.last_sent_seq = 0
        self.last_acked_seq = 0
        self.last_frame_sent_time = 0.0
        self.prev_road_img = None

    def update_hudiy(self, topic, data):
        if topic == b'HUDIY_OPENPILOT':
            self.state.update(data)

    def on_enter(self):
        super().on_enter()
        self.last_sent_seq = 0
        self.last_acked_seq = 0
        self.last_frame_sent_time = 0.0
        self.prev_road_img = None

    def on_frame_sent(self, seq):
        self.last_sent_seq = seq
        self.last_frame_sent_time = time.time()

    def on_frame_acked(self, seq):
        if seq > self.last_acked_seq:
            self.last_acked_seq = seq

    def _project_point(self, x, y, z=0.0):
        if x <= 0.1:
            return None
        # Road Area height is 36 (Y=0 to 35 local, mapped to Y=7 to 42 global)
        local_horizon_y = 0
        cam_h = 1.0
        scale_x = 33.0
        scale_y = 70.0
        
        u = 32 - int((y * scale_x) / x)
        v = local_horizon_y + int(((cam_h - z) * scale_y) / x)
        return u, v

    def _draw_dashed_line(self, draw, pts, pattern=[2, 2]):
        """Draws a dashed/dotted line through a list of points by toggling individual pixels.
        
        pattern = [dash_length, gap_length]
        """
        if len(pts) < 2:
            return
            
        dash_len, gap_len = pattern
        total_len = dash_len + gap_len
        
        pixel_index = 0
        for idx in range(len(pts) - 1):
            x0, y0 = pts[idx]
            x1, y1 = pts[idx + 1]
            
            dx = abs(x1 - x0)
            dy = abs(y1 - y0)
            sx = 1 if x0 < x1 else -1
            sy = 1 if y0 < y1 else -1
            err = dx - dy
            
            while True:
                # Draw pixel if inside the active phase of the step cycle
                phase = pixel_index % total_len
                if phase < dash_len:
                    draw.point((x0, y0), fill=1)
                pixel_index += 1
                
                if x0 == x1 and y0 == y1:
                    break
                e2 = 2 * err
                if e2 > -dy:
                    err -= dy
                    x0 += sx
                if e2 < dx:
                    err += dx
                    y0 += sy

    def get_view(self):
        now = time.time()
        # Flow control: Don't send a new frame until the previous one is fully acknowledged,
        # with a 1.0 second timeout to prevent getting stuck if an ACK is lost.
        if self.last_sent_seq > self.last_acked_seq and (now - self.last_frame_sent_time < 1.0) and self.cached_view:
            return self.cached_view

        # Rate Limit check
        if (now - self.last_update_time) < self.update_interval and self.cached_view:
            return self.cached_view

        engaged = self.state.get('engaged', False)
        steer_angle = self.state.get('steer_angle', 0.0)
        steer_torque = self.state.get('steer_torque', 0.0)
        model_confidence = self.state.get('model_confidence', 1.0)
        speed = self.state.get('speed', 0)
        max_speed = self.state.get('max_speed', 0)
        lead_dist = self.state.get('lead_dist', 0.0)
        lead_detected = self.state.get('lead_detected', False)

        plan = self.state.get('plan')
        lane_lines = self.state.get('lane_lines')
        road_edges = self.state.get('road_edges')
        lane_line_probs = self.state.get('lane_line_probs', [0.0, 1.0, 1.0, 0.0])
        road_edge_probs = self.state.get('road_edge_probs', [1.0, 1.0])

        # First element in list must define the page type for transition detection in display engine
        view_commands = [
            # Type identifier metadata (does not draw itself)
            {'type': 'openpilot_vis'}
        ]

        # ----------------------------------------------------
        # Group 1: Top Dashboard Info (Speed & Status & Conf)
        # ----------------------------------------------------
        status_text = "ENG" if engaged else "IDL"
        status_flag = self.FLAG_ITEM
        
        speed_str = f"{max_speed}" if (0 < max_speed < 255) else ""
        
        # Horizontal Confidence Progress Bar at X=52..62, Y=4
        bar_len = max(0, min(11, int(model_confidence * 11.0)))
        
        top_commands = [
            {'cmd': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 9, 'group': 'road_top'},
            # Status Text
            {'cmd': 'draw_text', 'text': status_text, 'x': 2, 'y': 1, 'flags': status_flag, 'group': 'road_top'},
            # Centered Speed Text
            {'cmd': 'draw_text', 'text': speed_str, 'y': 1, 'flags': self.FLAG_ITEM_CENTERED, 'group': 'road_top'},
            # Confidence Progress Bar (Baseline at Y=5)
            {'cmd': 'draw_line', 'x': 52, 'y': 5, 'length': 11, 'vertical': False, 'group': 'road_top'}
        ]
        if bar_len > 0:
            top_commands.append(
                {'cmd': 'draw_line', 'x': 52, 'y': 4, 'length': bar_len, 'vertical': False, 'group': 'road_top'}
            )

        # ----------------------------------------------------
        # Group 2: Road Visualization Area (Y=7 to 42) - 64x36 Bitmap
        # ----------------------------------------------------
        road_img = Image.new("1", (64, 36), 0)
        draw = ImageDraw.Draw(road_img)

        # Draw road edges, lane lines, and planned path
        # 1. Check if real model data is present
        if lane_lines is not None and road_edges is not None and plan is not None:
            # --- USE REAL MODEL OUTPUT ARRAYS ---
            x_idxs = [192.0 * ((i / 32.0) ** 2) for i in range(33)]
            
            # Draw Road Edges (dashed)
            # Left Edge (0)
            if len(road_edges) > 0 and len(road_edge_probs) > 0 and road_edge_probs[0] > 0.5:
                pts_re_l = []
                for i in range(33):
                    x_val = x_idxs[i]
                    if x_val > 30.0: break # don't render too far to avoid clutter
                    y_c = plan[i][1] if i < len(plan) else 0.0
                    y_edge_l = road_edges[0][i] if i < len(road_edges[0]) else (y_c + 2.25)
                    dy = y_edge_l - y_c
                    y_val = y_c + dy * (0.8 + 0.111 * x_val)
                    pt = self._project_point(x_val, y_val)
                    if pt: pts_re_l.append(pt)
                self._draw_dashed_line(draw, pts_re_l, pattern=[1, 2])

            # Right Edge (1)
            if len(road_edges) > 1 and len(road_edge_probs) > 1 and road_edge_probs[1] > 0.5:
                pts_re_r = []
                for i in range(33):
                    x_val = x_idxs[i]
                    if x_val > 30.0: break
                    y_c = plan[i][1] if i < len(plan) else 0.0
                    y_edge_r = road_edges[1][i] if i < len(road_edges[1]) else (y_c - 2.25)
                    dy = y_edge_r - y_c
                    y_val = y_c + dy * (0.8 + 0.111 * x_val)
                    pt = self._project_point(x_val, y_val)
                    if pt: pts_re_r.append(pt)
                self._draw_dashed_line(draw, pts_re_r, pattern=[1, 2])

            # Draw Lane Lines (solid)
            # Left Lane (1)
            if len(lane_lines) > 1 and len(lane_line_probs) > 1 and lane_line_probs[1] > 0.5:
                pts_ll_l = []
                for i in range(33):
                    x_val = x_idxs[i]
                    if x_val > 30.0: break
                    y_c = plan[i][1] if i < len(plan) else 0.0
                    y_lane_l = lane_lines[1][i] if i < len(lane_lines[1]) else (y_c + 1.6)
                    dy = y_lane_l - y_c
                    y_val = y_c + dy * (0.4375 + 0.0625 * x_val)
                    pt = self._project_point(x_val, y_val)
                    if pt: pts_ll_l.append(pt)
                if len(pts_ll_l) > 1:
                    draw.line(pts_ll_l, fill=1, width=1)

            # Right Lane (2)
            if len(lane_lines) > 2 and len(lane_line_probs) > 2 and lane_line_probs[2] > 0.5:
                pts_ll_r = []
                for i in range(33):
                    x_val = x_idxs[i]
                    if x_val > 30.0: break
                    y_c = plan[i][1] if i < len(plan) else 0.0
                    y_lane_r = lane_lines[2][i] if i < len(lane_lines[2]) else (y_c - 1.6)
                    dy = y_lane_r - y_c
                    y_val = y_c + dy * (0.4375 + 0.0625 * x_val)
                    pt = self._project_point(x_val, y_val)
                    if pt: pts_ll_r.append(pt)
                if len(pts_ll_r) > 1:
                    draw.line(pts_ll_r, fill=1, width=1)

            # Draw Adjacent Left Lane (0) - Aggressively dashed (single pixels / dots)
            if len(lane_lines) > 0 and len(lane_line_probs) > 0 and lane_line_probs[0] > 0.5:
                pts_ll_0 = []
                for i in range(33):
                    x_val = x_idxs[i]
                    if x_val > 30.0: break
                    y_c = plan[i][1] if i < len(plan) else 0.0
                    y_adj_l = lane_lines[0][i] if i < len(lane_lines[0]) else (y_c + 4.8)
                    dy = y_adj_l - y_c
                    y_val = y_c + dy * (0.2917 + 0.0417 * x_val)
                    pt = self._project_point(x_val, y_val)
                    if pt: pts_ll_0.append(pt)
                self._draw_dashed_line(draw, pts_ll_0, pattern=[6, 4])

            # Draw Adjacent Right Lane (3) - Aggressively dashed (single pixels / dots)
            if len(lane_lines) > 3 and len(lane_line_probs) > 3 and lane_line_probs[3] > 0.5:
                pts_ll_3 = []
                for i in range(33):
                    x_val = x_idxs[i]
                    if x_val > 30.0: break
                    y_c = plan[i][1] if i < len(plan) else 0.0
                    y_adj_r = lane_lines[3][i] if i < len(lane_lines[3]) else (y_c - 4.8)
                    dy = y_adj_r - y_c
                    y_val = y_c + dy * (0.2917 + 0.0417 * x_val)
                    pt = self._project_point(x_val, y_val)
                    if pt: pts_ll_3.append(pt)
                self._draw_dashed_line(draw, pts_ll_3, pattern=[6, 4])

            # Draw Planned Path
            if engaged:
                # Filled ribbon path
                pts_path_l = []
                pts_path_r = []
                for i in range(33):
                    pt_orig = plan[i] # [x, y, z]
                    x_val = pt_orig[0]
                    if x_val > 28.0: break
                    y_val = pt_orig[1]
                    z_val = pt_orig[2] if len(pt_orig) > 2 else 0.0
                    pt_l = self._project_point(x_val, y_val + 0.3, z_val)
                    pt_r = self._project_point(x_val, y_val - 0.3, z_val)
                    if pt_l: pts_path_l.append(pt_l)
                    if pt_r: pts_path_r.append(pt_r)
                if len(pts_path_l) > 1 and len(pts_path_r) > 1:
                    poly_pts = pts_path_l + list(reversed(pts_path_r))
                    draw.polygon(poly_pts, fill=1)

        else:
            # --- FALLBACK: CURVES DERIVED FROM STEER ANGLE ---
            c = -steer_angle * 0.0003
            lane_w = 3.2
            road_w = 4.5
            
            pts_re_left = []
            pts_re_right = []
            pts_ll_left = []
            pts_ll_right = []
            pts_path_left = []
            pts_path_right = []
            
            x_steps = [2.0, 3.0, 4.5, 6.0, 8.0, 10.0, 13.0, 17.0, 21.0, 25.0, 30.0]
            for x in x_steps:
                y_center = c * (x ** 2)
                
                edge_offset = 1.8 + 0.25 * x
                inner_offset = 0.7 + 0.10 * x
                
                pt_re_l = self._project_point(x, y_center + edge_offset)
                pt_re_r = self._project_point(x, y_center - edge_offset)
                if pt_re_l: pts_re_left.append(pt_re_l)
                if pt_re_r: pts_re_right.append(pt_re_r)
                
                pt_ll_l = self._project_point(x, y_center + inner_offset)
                pt_ll_r = self._project_point(x, y_center - inner_offset)
                if pt_ll_l: pts_ll_left.append(pt_ll_l)
                if pt_ll_r: pts_ll_right.append(pt_ll_r)
                
                if x <= 28.0:
                    pt_pat_l = self._project_point(x, y_center + 0.3)
                    pt_pat_r = self._project_point(x, y_center - 0.3)
                    if pt_pat_l: pts_path_left.append(pt_pat_l)
                    if pt_pat_r: pts_path_right.append(pt_pat_r)

            # Draw Fallback Road Edges (dashed)
            if len(road_edge_probs) > 0 and road_edge_probs[0] > 0.5:
                self._draw_dashed_line(draw, pts_re_left, pattern=[1, 2])
            if len(road_edge_probs) > 1 and road_edge_probs[1] > 0.5:
                self._draw_dashed_line(draw, pts_re_right, pattern=[1, 2])
                    
            # Draw Fallback Lane Lines (solid)
            if len(lane_line_probs) > 1 and lane_line_probs[1] > 0.5 and len(pts_ll_left) > 1:
                draw.line(pts_ll_left, fill=1, width=1)
            if len(lane_line_probs) > 2 and lane_line_probs[2] > 0.5 and len(pts_ll_right) > 1:
                draw.line(pts_ll_right, fill=1, width=1)

            # Draw Fallback Planned Path
            if engaged:
                if len(pts_path_left) > 1 and len(pts_path_right) > 1:
                    poly_pts = pts_path_left + list(reversed(pts_path_right))
                    draw.polygon(poly_pts, fill=1)

        # Draw Lead Vehicle Box(es)
        leads = self.state.get('leads')
        if leads is None:
            # Fallback to single lead
            leads = []
            if lead_detected and lead_dist > 2.0:
                leads.append({
                    'dist': lead_dist,
                    'lat_dist': self.state.get('lead_lat_dist')
                })

        for lead in leads:
            l_dist = lead.get('dist', 0.0)
            if l_dist <= 2.0:
                continue
            x_lead = min(45.0, l_dist)
            # Use real lateral distance if available, otherwise fall back to path lookup
            y_lead = lead.get('lat_dist')
            if y_lead is None:
                if lane_lines is not None and road_edges is not None and plan is not None:
                    x_idxs = [192.0 * ((i / 32.0) ** 2) for i in range(33)]
                    closest_idx = min(range(33), key=lambda idx: abs(x_idxs[idx] - x_lead))
                    y_lead = plan[closest_idx][1]
                else:
                    y_lead = -steer_angle * 0.0003 * (x_lead ** 2)

            pt_lead = self._project_point(x_lead, y_lead)
            if pt_lead:
                u, v = pt_lead
                scale_x = 33.0
                scale_y = 52.0
                w_pix = int((1.8 * scale_x) / x_lead)
                h_pix = int((1.4 * scale_y) / x_lead)
                
                if w_pix >= 3 and h_pix >= 3:
                    x1 = max(0, min(63, u - w_pix // 2))
                    x2 = max(0, min(63, u + w_pix // 2))
                    h_cab = int(h_pix * 0.4)
                    h_body = h_pix - h_cab
                    y1 = max(0, min(35, v - h_pix))
                    y_mid = max(0, min(35, v - h_body))
                    y2 = max(0, min(35, v))
                    
                    draw.rectangle([x1, y_mid, x2, y2], fill=0, outline=1)
                    
                    cabin_w = int(w_pix * 0.7)
                    cx1 = max(0, min(63, u - cabin_w // 2))
                    cx2 = max(0, min(63, u + cabin_w // 2))
                    draw.rectangle([cx1, y1, cx2, y_mid], fill=0, outline=1)
                    
                    draw.point((x1 + 1, y_mid + h_body // 2), fill=1)
                    draw.point((x2 - 1, y_mid + h_body // 2), fill=1)

        if not hasattr(self, 'prev_road_img'):
            self.prev_road_img = None
        blocks = dis_image.extract_deltas(self.prev_road_img, road_img, granular=True)
        self.prev_road_img = road_img.copy()

        # Add granular delta drawing commands
        for block in blocks:
            w_pix = (len(block['data']) // block['h']) * 8
            view_commands.append({
                'cmd': 'draw_raw_bitmap',
                'data_hex': block['data'].hex(),
                'w': w_pix,
                'h': block['h'],
                'x': block['x'],
                'y': 7 + block['y'],
                'mode_flag': 0x02
            })
        
        # Append top commands
        view_commands.extend(top_commands)

        # ----------------------------------------------------
        # Group 3: Actuator Steer Torque Bar (Y=44 to 48)
        # ----------------------------------------------------
        tx = 32 + int(steer_torque * 16.0)
        tx = max(16, min(48, tx))

        # Prepend clear_area for torque region (Y=44 to 49)
        view_commands.extend([
            {'cmd': 'clear_area', 'x': 16, 'y': 44, 'w': 33, 'h': 6, 'group': 'torque'},
            # Torque Bar Baseline
            {'cmd': 'draw_line', 'x': 16, 'y': 46, 'length': 33, 'vertical': False, 'group': 'torque'},
            # Center Tick
            {'cmd': 'draw_line', 'x': 32, 'y': 45, 'length': 3, 'vertical': True, 'group': 'torque'},
            # Command Notch
            {'cmd': 'draw_line', 'x': tx, 'y': 44, 'length': 5, 'vertical': True, 'group': 'torque'}
        ])

        self.cached_view = view_commands
        self.last_update_time = now
        return self.cached_view
