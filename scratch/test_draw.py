import os
import math
from PIL import Image, ImageDraw

def _project_point(x, y, z=0.0):
    if x <= 0.1:
        return None
    local_horizon_y = 0
    cam_h = 1.0
    scale_x = 33.0
    scale_y = 70.0
    
    u = 32 - int((y * scale_x) / x)
    v = local_horizon_y + int(((cam_h - z) * scale_y) / x)
    return u, v

def draw_dashed_line(draw, pts, pattern=[2, 2]):
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

def get_mock_data(curvature):
    # Generates a plan, lane lines, and road edges based on a curvature factor
    c = curvature 
    x_idxs = [192.0 * ((i / 32.0) ** 2) for i in range(33)]
    
    plan = []
    for x in x_idxs:
        y = c * (x ** 2)
        plan.append([x, y, 0.0])
        
    # Generate left and right lane lines (1.6m left, 1.6m right of center path)
    lane_lines = [[], [], [], []]
    road_edges = [[], []]
    
    for x in x_idxs:
        y_c = c * (x ** 2)
        # Left Lane Line
        lane_lines[1].append(y_c + 1.6)
        # Right Lane Line
        lane_lines[2].append(y_c - 1.6)
        # Road Edges
        road_edges[0].append(y_c + 2.25)
        road_edges[1].append(y_c - 2.25)
        
    return plan, lane_lines, road_edges

def render_original(plan, lane_lines, road_edges):
    img = Image.new("1", (64, 36), 0)
    draw = ImageDraw.Draw(img)
    x_idxs = [192.0 * ((i / 32.0) ** 2) for i in range(33)]
    
    # 1. Draw Road Edges (dashed)
    pts_re_l = []
    pts_re_r = []
    for i in range(33):
        x_val = x_idxs[i]
        if x_val > 30.0: break
        y_c = plan[i][1]
        y_edge_l = road_edges[0][i]
        pt_l = _project_point(x_val, y_edge_l)
        if pt_l: pts_re_l.append(pt_l)
        
        y_edge_r = road_edges[1][i]
        pt_r = _project_point(x_val, y_edge_r)
        if pt_r: pts_re_r.append(pt_r)
    draw_dashed_line(draw, pts_re_l, pattern=[1, 2])
    draw_dashed_line(draw, pts_re_r, pattern=[1, 2])
    
    # 2. Draw Lane Lines (solid)
    pts_ll_l = []
    pts_ll_r = []
    for i in range(33):
        x_val = x_idxs[i]
        if x_val > 30.0: break
        y_lane_l = lane_lines[1][i]
        pt_l = _project_point(x_val, y_lane_l)
        if pt_l: pts_ll_l.append(pt_l)
        
        y_lane_r = lane_lines[2][i]
        pt_r = _project_point(x_val, y_lane_r)
        if pt_r: pts_ll_r.append(pt_r)
    if len(pts_ll_l) > 1: draw.line(pts_ll_l, fill=1, width=1)
    if len(pts_ll_r) > 1: draw.line(pts_ll_r, fill=1, width=1)
    
    # 3. Draw Planned Path (original solid polygon)
    pts_path_l = []
    pts_path_r = []
    for i in range(33):
        pt_orig = plan[i]
        x_val = pt_orig[0]
        if x_val > 28.0: break
        y_val = pt_orig[1]
        z_val = pt_orig[2]
        pt_l = _project_point(x_val, y_val + 0.3, z_val)
        pt_r = _project_point(x_val, y_val - 0.3, z_val)
        if pt_l: pts_path_l.append(pt_l)
        if pt_r: pts_path_r.append(pt_r)
    if len(pts_path_l) > 1 and len(pts_path_r) > 1:
        poly_pts = pts_path_l + list(reversed(pts_path_r))
        draw.polygon(poly_pts, fill=1)
        
    return img

def render_chevron(plan, lane_lines, road_edges):
    img = Image.new("1", (64, 36), 0)
    draw = ImageDraw.Draw(img)
    x_idxs = [192.0 * ((i / 32.0) ** 2) for i in range(33)]
    
    # 1. Draw Road Edges (dashed)
    pts_re_l = []
    pts_re_r = []
    for i in range(33):
        x_val = x_idxs[i]
        if x_val > 30.0: break
        y_c = plan[i][1]
        y_edge_l = road_edges[0][i]
        pt_l = _project_point(x_val, y_edge_l)
        if pt_l: pts_re_l.append(pt_l)
        
        y_edge_r = road_edges[1][i]
        pt_r = _project_point(x_val, y_edge_r)
        if pt_r: pts_re_r.append(pt_r)
    draw_dashed_line(draw, pts_re_l, pattern=[1, 2])
    draw_dashed_line(draw, pts_re_r, pattern=[1, 2])
    
    # 2. Draw Lane Lines (solid)
    pts_ll_l = []
    pts_ll_r = []
    for i in range(33):
        x_val = x_idxs[i]
        if x_val > 30.0: break
        y_lane_l = lane_lines[1][i]
        pt_l = _project_point(x_val, y_lane_l)
        if pt_l: pts_ll_l.append(pt_l)
        
        y_lane_r = lane_lines[2][i]
        pt_r = _project_point(x_val, y_lane_r)
        if pt_r: pts_ll_r.append(pt_r)
    if len(pts_ll_l) > 1: draw.line(pts_ll_l, fill=1, width=1)
    if len(pts_ll_r) > 1: draw.line(pts_ll_r, fill=1, width=1)
    
    # 3. Draw Planned Path (chevron arrows)
    chevron_indices = [4, 7, 10]
    
    for i in chevron_indices:
        if i >= len(plan):
            break
        pt_orig = plan[i]
        x_val = pt_orig[0]
        y_val = pt_orig[1]
        z_val = pt_orig[2]
        pt_tip = _project_point(x_val, y_val, z_val)
        if not pt_tip:
            continue
        u_tip, v_tip = pt_tip
        
        if i - 1 >= 0:
            pt_base_orig = plan[i-1]
            xb_val = pt_base_orig[0]
            yb_val = pt_base_orig[1]
            zb_val = pt_base_orig[2]
            
            pt_base = _project_point(xb_val, yb_val, zb_val)
            if not pt_base:
                continue
            u_base, v_base = pt_base
            
            # Width offset: 0.4 meters
            pt_l = _project_point(xb_val, yb_val + 0.4, zb_val)
            pt_r = _project_point(xb_val, yb_val - 0.4, zb_val)
            
            if pt_l and pt_r:
                u_l, v_l = pt_l
                u_r, v_r = pt_r
                
                # Enforce minimum pixel width
                if abs(u_l - u_base) < 1:
                    u_l = u_base - 1
                if abs(u_r - u_base) < 1:
                    u_r = u_base + 1
                    
                draw.line([(u_l, v_base), (u_tip, v_tip), (u_r, v_base)], fill=1, width=1)
                
    return img

def render_centerline(plan, lane_lines, road_edges):
    img = Image.new("1", (64, 36), 0)
    draw = ImageDraw.Draw(img)
    x_idxs = [192.0 * ((i / 32.0) ** 2) for i in range(33)]
    
    # 1. Draw Road Edges (dashed)
    pts_re_l = []
    pts_re_r = []
    for i in range(33):
        x_val = x_idxs[i]
        if x_val > 30.0: break
        y_c = plan[i][1]
        y_edge_l = road_edges[0][i]
        pt_l = _project_point(x_val, y_edge_l)
        if pt_l: pts_re_l.append(pt_l)
        
        y_edge_r = road_edges[1][i]
        pt_r = _project_point(x_val, y_edge_r)
        if pt_r: pts_re_r.append(pt_r)
    draw_dashed_line(draw, pts_re_l, pattern=[1, 2])
    draw_dashed_line(draw, pts_re_r, pattern=[1, 2])
    
    # 2. Draw Lane Lines (solid)
    pts_ll_l = []
    pts_ll_r = []
    for i in range(33):
        x_val = x_idxs[i]
        if x_val > 30.0: break
        y_lane_l = lane_lines[1][i]
        pt_l = _project_point(x_val, y_lane_l)
        if pt_l: pts_ll_l.append(pt_l)
        
        y_lane_r = lane_lines[2][i]
        pt_r = _project_point(x_val, y_lane_r)
        if pt_r: pts_ll_r.append(pt_r)
    if len(pts_ll_l) > 1: draw.line(pts_ll_l, fill=1, width=1)
    if len(pts_ll_r) > 1: draw.line(pts_ll_r, fill=1, width=1)
    
    # 3. Draw Planned Centerline (dashed)
    pts_path = []
    for i in range(33):
        pt_orig = plan[i]
        x_val = pt_orig[0]
        if x_val > 28.0: break
        y_val = pt_orig[1]
        z_val = pt_orig[2]
        pt = _project_point(x_val, y_val, z_val)
        if pt: pts_path.append(pt)
    draw_dashed_line(draw, pts_path, pattern=[2, 3])
        
    return img

if __name__ == "__main__":
    os.makedirs("scratch", exist_ok=True)
    
    # Straight road
    plan_st, lanes_st, edges_st = get_mock_data(0.0)
    img_orig_st = render_original(plan_st, lanes_st, edges_st)
    img_chev_st = render_chevron(plan_st, lanes_st, edges_st)
    img_cline_st = render_centerline(plan_st, lanes_st, edges_st)
    
    img_orig_st.resize((384, 216), Image.NEAREST).save("scratch/path_original_straight.png")
    img_chev_st.resize((384, 216), Image.NEAREST).save("scratch/path_chevron_straight.png")
    img_cline_st.resize((384, 216), Image.NEAREST).save("scratch/path_centerline_straight.png")
    
    # Curved road
    plan_cv, lanes_cv, edges_cv = get_mock_data(-0.002)
    img_orig_cv = render_original(plan_cv, lanes_cv, edges_cv)
    img_chev_cv = render_chevron(plan_cv, lanes_cv, edges_cv)
    img_cline_cv = render_centerline(plan_cv, lanes_cv, edges_cv)
    
    img_orig_cv.resize((384, 216), Image.NEAREST).save("scratch/path_original_curved.png")
    img_chev_cv.resize((384, 216), Image.NEAREST).save("scratch/path_chevron_curved.png")
    img_cline_cv.resize((384, 216), Image.NEAREST).save("scratch/path_centerline_curved.png")
    
    print("Generated comparison images in scratch/")
