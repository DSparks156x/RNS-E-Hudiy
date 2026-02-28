import math
import os
from PIL import Image, ImageDraw

W, H = 1620, 1920
gray = (127, 127, 127, 255)
black = (0, 0, 0, 255)
R = 190  # Even thicker road

def bezier_point(t, p0, p1, p2):
    x = (1-t)**2 * p0[0] + 2*(1-t)*t * p1[0] + t**2 * p2[0]
    y = (1-t)**2 * p0[1] + 2*(1-t)*t * p1[1] + t**2 * p2[1]
    return (x, y)

def draw_thick_line_flat(draw, p0, p1, color, r=R):
    # draws a thick line with flat caps by filling a polygon
    # assumes vertical or horizontal for simplicity in this icon
    if p0[0] == p1[0]: # vertical
        x = p0[0]
        y_min = min(p0[1], p1[1])
        y_max = max(p0[1], p1[1])
        draw.polygon([(x-r, y_min), (x+r, y_min), (x+r, y_max), (x-r, y_max)], fill=color)
    else: # horizontal
        y = p0[1]
        x_min = min(p0[0], p1[0])
        x_max = max(p0[0], p1[0])
        draw.polygon([(x_min, y-r), (x_max, y-r), (x_max, y+r), (x_min, y+r)], fill=color)

def draw_thick_curve_flat(draw, p0, p1, p2, color, r=R):
    # For the curve, we still use the sweeping circles method, but we will
    # crop the very ends flat manually in the main function if needed,
    # or rely on the arrowhead covering the end.
    steps = 1000
    for t in range(steps+1):
        x, y = bezier_point(t/steps, p0, p1, p2)
        draw.ellipse([x-r, y-r, x+r, y+r], fill=color)

def draw_arrow(draw, tip, angle, color, size=850): 
    # Massive arrowhead like the "good" reference image
    a1 = angle + math.pi * 0.80
    a2 = angle - math.pi * 0.80
    pt1 = (int(tip[0] + size * math.cos(a1)), int(tip[1] + size * math.sin(a1)))
    pt2 = (int(tip[0] + size * math.cos(a2)), int(tip[1] + size * math.sin(a2)))
    
    # Flat back rather than deeply curved back, matching reference
    back_mid = (int(tip[0] + size*0.75 * math.cos(angle+math.pi)), int(tip[1] + size*0.75 * math.sin(angle+math.pi)))
    draw.polygon([tip, pt1, back_mid, pt2], fill=color)

def make_ramp(name, off, left):
    # We will draw on a large canvas and then crop it tightly
    cw, ch = 3000, 3000
    img = Image.new('RGBA', (cw, ch), (0,0,0,0)) 
    d = ImageDraw.Draw(img)
    
    # Draw large
    m_x = 1500
    
    if off:
        # Off ramp (diverge)
        # Gray road: straight vertical line with flat ends
        draw_thick_line_flat(d, (m_x, 2500), (m_x, 800), gray)
        
        sign = -1 if left else 1
        # Start the curve closer to the middle, diverging faster
        r_start = (m_x, 1800)
        r_ctrl  = (m_x, 1000)
        r_end   = (m_x + sign*800, 800)
        
        draw_thick_curve_flat(d, r_start, r_ctrl, r_end, black)
        # Flatten the start of the ramp curve
        draw_thick_line_flat(d, (m_x, 2000), (m_x, 1800), black)
        
        vx = r_end[0] - r_ctrl[0]
        vy = r_end[1] - r_ctrl[1]
        a = math.atan2(vy, vx)
        # Arrowhead much closer to the end of the line
        draw_arrow(d, (r_end[0] + math.cos(a)*50, r_end[1] + math.sin(a)*50), a, black)
        
    else:
        # On ramp (merge)
        draw_thick_line_flat(d, (m_x, 2500), (m_x, 800), gray)
        
        sign = -1 if left else 1
        r_start = (m_x + sign*800, 1800)
        r_ctrl  = (m_x + sign*100, 1000)
        r_end   = (m_x, 800)
        
        draw_thick_curve_flat(d, r_start, r_ctrl, r_end, black)
        # Flatten the start of the ramp curve
        draw_thick_line_flat(d, (r_start[0], 2000), (r_start[0], 1800), black)
        
        draw_arrow(d, (r_end[0], r_end[1]-30), -math.pi/2, black)
        
    # Crop to fit the shape perfectly, leaving a little padding
    bbox = img.getbbox()
    if bbox:
        img = img.crop((bbox[0]-100, bbox[1]-100, bbox[2]+100, bbox[3]+100))
        
    # Final center crop / pad to exact aspect ratio WxH (162x192) then scale down
    aspect_target = W/H
    aspect_current = img.width/img.height
    
    if aspect_current > aspect_target:
        # Too wide, pad height
        new_h = int(img.width / aspect_target)
        bg = Image.new('RGBA', (img.width, new_h), (0,0,0,0))
        bg.paste(img, (0, (new_h - img.height)//2))
        img = bg
    else:
        # Too tall, pad width
        new_w = int(img.height * aspect_target)
        bg = Image.new('RGBA', (new_w, img.height), (0,0,0,0))
        bg.paste(img, ((new_w - img.width)//2, 0))
        img = bg
        
    # Standardize size for the PNG input to potrace
    out = img.resize((162, 192), Image.Resampling.LANCZOS)
    
    out.save(os.path.join('pngs', name + '.png'))
    print('Generated:', name)

make_ramp('ic_ramp_off_left', off=True, left=True)
make_ramp('ic_ramp_off_right', off=True, left=False)
make_ramp('ic_ramp_on_left', off=False, left=True)
make_ramp('ic_ramp_on_right', off=False, left=False)
