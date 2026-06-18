#!/usr/bin/env python3
"""
DIS Image Processing Pipeline V2
Converts album art to 64×48 1-bit images for the DIS cluster display.

Pipeline order:
  RGB → thumbnail to 2× target → bg_fill → smart grayscale → CLAHE →
  gamma → brightness/contrast → edge sharpen → downscale to target →
  adaptive black floor → dither (Atkinson default)
"""
import time
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageChops, ImageMorph
import numpy as np

# Try to import OpenCV for CLAHE - fall back to global autocontrast if unavailable
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ---------------------------------------------------------------------------
#  Delta extraction (unchanged from V1)
# ---------------------------------------------------------------------------

def extract_deltas(prev_img: Image.Image, curr_img: Image.Image, granular: bool = False):
    """Return a list of update segments for pixels that changed between frames.
    
    Ported from test_gif_ipc.py.
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


# ---------------------------------------------------------------------------
#  V2 Helper Functions
# ---------------------------------------------------------------------------

def smart_grayscale(rgb_img):
    """
    Saturation-aware grayscale conversion.
    
    Standard Rec.709 luminance as base, plus a small boost from the
    max-channel delta. This catches colored text/logos (red Foo Fighters text)
    without the extreme blowout of pure max-channel mode.
    """
    r, g, b = rgb_img.split()
    weighted = rgb_img.convert('L')
    
    max_ch = ImageChops.lighter(r, ImageChops.lighter(g, b))
    delta = ImageChops.subtract(max_ch, weighted)
    # Add 25% of the saturation-driven brightness delta
    boost = delta.point(lambda p: int(p * 0.25))
    
    return ImageChops.add(weighted, boost)


def apply_clahe(gray_img, clip_limit=2.5, grid_size=8):
    """
    Contrast-adaptive CLAHE.
    
    Measures the image's existing contrast. High-contrast images (neon on
    black, bright text on dark) already have a wide histogram spread and
    don't need aggressive local equalization — CLAHE would just boost noise
    in their dark regions. Low-contrast images (gray spheres on gray background)
    benefit from full CLAHE.
    
    Uses larger grid_size (8) to avoid tile-boundary artifacts around text.
    
    Falls back to global autocontrast if OpenCV is not available.
    """
    if HAS_CV2:
        arr = np.array(gray_img, dtype=np.uint8)
        
        # Measure existing contrast: how much of the 0-255 range is used?
        p_low, p_high = np.percentile(arr, [5, 95])
        contrast_range = p_high - p_low  # 0 = flat, 255 = full range
        
        if contrast_range > 180:
            # Already high contrast (neon on black, text on dark).
            # Light CLAHE just for subtle local detail, avoid boosting dark noise.
            effective_clip = max(clip_limit * 0.3, 1.0)
        elif contrast_range > 120:
            # Medium contrast — moderate CLAHE
            effective_clip = clip_limit * 0.6
        else:
            # Low contrast — full CLAHE to rescue detail
            effective_clip = clip_limit
        
        clahe = cv2.createCLAHE(clipLimit=effective_clip, tileGridSize=(grid_size, grid_size))
        result = clahe.apply(arr)
        return Image.fromarray(result)
    else:
        # Fallback: global autocontrast
        return ImageOps.autocontrast(gray_img, cutoff=1)


def compute_adaptive_floor(gray_img, base_floor=30, dark_threshold=0.45):
    """
    Content-adaptive black floor.
    
    Analyzes the grayscale histogram to determine how 'dark' the image is,
    then sets a floor that silences dither noise on true-black backgrounds
    while preserving dim-but-meaningful detail (thin lines, subtle textures).
    
    Key insight: a high dark-pixel fraction alone isn't enough — we must also
    check if there's significant content in the shadow-detail band (20-80).
    Images like Foo Fighters have 89% "dark" pixels, but 43% of those are
    dim strings/shapes in the 10-40 range that must be preserved.
    
    Returns the computed floor value (0-255).
    """
    hist = gray_img.histogram()
    total = sum(hist)
    if total == 0:
        return base_floor
    
    # Fraction of pixels in the deep shadow range (0-79)
    dark_pixels = sum(hist[:80]) / total
    
    # Fraction with meaningful shadow detail (20-80 range)
    # These are dim-but-real features: thin lines, subtle textures
    shadow_detail = sum(hist[20:80]) / total
    
    if dark_pixels > dark_threshold:
        if shadow_detail > 0.10:
            # Dark image BUT has significant dim content (Foo Fighters strings).
            # Keep floor low — only kill the very darkest noise (0-15 range).
            return min(base_floor // 2, 15)
        else:
            # Truly dark background with minimal shadow content (Daft Punk).
            # Safe to floor aggressively.
            extra = int((dark_pixels - dark_threshold) * 80)
            return min(base_floor + extra, 80)
    else:
        # Bright image: gentle floor
        return max(base_floor // 2, 8)


def edge_sharpen(gray_img, strength=1.5):
    """
    Edge-preserving sharpening.
    
    Two-pass: gentle Gaussian blur to suppress high-freq noise,
    then unsharp mask on the cleaned result. Uses Gaussian instead of
    median because median filters destroy thin lines (1-2px features
    get majority-voted out), while Gaussian merely softens them.
    """
    # 1. Gentle Gaussian to suppress noise (preserves thin lines unlike median)
    smooth = gray_img.filter(ImageFilter.GaussianBlur(radius=0.7))
    # 2. Blend: keep 80% original (edges + thin lines), 20% smoothed
    blended = Image.blend(gray_img, smooth, 0.2)
    # 3. Sharpen the cleaned image
    sharpened = blended.filter(
        ImageFilter.UnsharpMask(radius=1.0, percent=int(strength * 100), threshold=3)
    )
    return sharpened


def morphological_bold(gray_img, boldness=0):
    """
    Morphological boldness — dilates bright regions while preserving structure.
    
    Supports fractional boldness:
    - 0.5 = 1st dilation pass at 50% blend.
    - 1.0 = 1st dilation pass at 100% blend.
    - 1.2 = 1st pass full, 2nd pass at 20% blend.
    """
    if boldness <= 0:
        return gray_img
        
    import math
    iterations = int(math.ceil(boldness))
    # blend reflects the fractional part of the current iteration tier
    # e.g. 1.2 boldness -> iteration 2, blend = 0.2
    blend = boldness % 1.0
    if blend == 0 and boldness > 0:
        blend = 1.0

    if not HAS_CV2:
        # Fallback: simple MaxFilter approach
        dilated = gray_img
        for i in range(iterations):
            prev = dilated
            dilated = dilated.filter(ImageFilter.MaxFilter(size=3))
            if i == iterations - 1: # Last iteration, apply blend
                dilated = Image.blend(prev, dilated, blend)
        return dilated
    
    arr = np.array(gray_img, dtype=np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    
    curr = arr.copy()
    for i in range(iterations):
        prev = curr.copy()
        curr = cv2.dilate(curr, kernel, iterations=1)
        if i == iterations - 1: # Last iteration, apply blend
            curr = cv2.addWeighted(prev, 1.0 - blend, curr, blend, 0)
    
    return Image.fromarray(curr)


def atkinson_dither(gray_img, diffusion=0.85):
    """
    Atkinson-pattern dithering with tunable error diffusion.
    
    Uses the classic Atkinson 6-neighbor diffusion pattern but with a
    configurable total error amount:
      - 0.75 = classic Atkinson (25% error discarded, very clean blacks)
      - 0.85 = default sweet spot (more mid-tone detail than Atkinson,
               cleaner blacks than Floyd-Steinberg)
      - 1.0  = full diffusion (FS-like gradation, noisier blacks)
    
    The per-neighbor weight is diffusion/6, so at 0.85 each neighbor
    gets ~14.2% of the error (vs 12.5% classic, 25% FS).
    
    At 64×48 (3,072 pixels), this is effectively instant.
    """
    w, h = gray_img.size
    # Work with a float buffer for precision during error diffusion
    pixels = np.array(gray_img, dtype=np.float32)
    
    # Per-neighbor error weight: total diffusion split across 6 neighbors
    weight = diffusion / 6.0
    
    for y in range(h):
        for x in range(w):
            old_val = pixels[y, x]
            new_val = 255.0 if old_val > 127.0 else 0.0
            pixels[y, x] = new_val
            
            err = (old_val - new_val) * weight
            
            # Atkinson diffusion pattern:
            #         *  1  1
            #      1  1  1
            #         1
            if x + 1 < w:
                pixels[y, x + 1] += err
            if x + 2 < w:
                pixels[y, x + 2] += err
            if y + 1 < h:
                if x - 1 >= 0:
                    pixels[y + 1, x - 1] += err
                pixels[y + 1, x] += err
                if x + 1 < w:
                    pixels[y + 1, x + 1] += err
            if y + 2 < h:
                pixels[y + 2, x] += err
    
    # Clamp and convert back
    result = np.clip(pixels, 0, 255).astype(np.uint8)
    out = Image.fromarray(result, mode='L')
    return out.convert('1', dither=Image.Dither.NONE)


# ---------------------------------------------------------------------------
#  Main Processing Pipeline
# ---------------------------------------------------------------------------

def process_image(
    img: Image.Image,
    target_size=(64, 48),
    contrast=1.4,
    sharpen=1.5,
    dither='fs',
    invert=False,
    no_enhance=False,
    bg_fill='black',
    grayscale_mode='smart',
    brightness=1.0,
    gamma=2.2,
    black_floor=45,
    boldness=0.0,
    diffusion=0.85
) -> Image.Image:
    """
    Process a PIL Image for DIS display. Returns a dithered 1-bit PIL Image.
    
    Simple, proven pipeline:
      RGB → resize to target → bg_fill → grayscale → autocontrast →
      gamma → brightness/contrast → sharpen → black floor → dither
    
    Uses smart_grayscale by default for better color-to-mono conversion
    on colorful images. Otherwise follows the V1 direct-to-target approach
    that retains the most detail at 64×48.
    
    Parameters:
        img:            Source PIL Image (any mode)
        target_size:    Final output size (w, h). Default (64, 48).
        contrast:       Contrast multiplier. Default 1.2.
        sharpen:        Sharpening strength. Default 1.5.
        dither:         'fs' (default), 'atkinson', or 'none'.
        invert:         Invert colors before processing.
        no_enhance:     Skip all enhancement, just resize + convert.
        bg_fill:        Letterbox fill: 'black', 'white', 'edge', 'blur'.
        grayscale_mode: 'smart' (default), 'weighted', 'max', 'balanced'.
        brightness:     Brightness multiplier. Default 1.0.
        gamma:          Gamma correction exponent. Default 2.2.
        black_floor:    Integer 0-255. Default 45. Pixels below this → black.
        boldness:       0.0 = off, float = morphological dilation "thickness".
        diffusion:      Error diffusion for Atkinson dither (0.75-1.0). Default 0.85.
    """
    if isinstance(target_size, list):
        target_size = tuple(target_size)
    frame = img.copy().convert("RGB")
    frame.thumbnail(target_size, Image.Resampling.LANCZOS)
    
    # --- Background fill / letterboxing ---
    if bg_fill == 'edge':
        canvas = Image.new("RGB", target_size, (0, 0, 0))
        offset_x = (target_size[0] - frame.size[0]) // 2
        offset_y = (target_size[1] - frame.size[1]) // 2
        canvas.paste(frame, (offset_x, offset_y))
        
        if offset_x > 0:
            left_edge = frame.crop((0, 0, min(3, frame.size[0]), frame.size[1]))
            left_avg = left_edge.resize((1, frame.size[1]), Image.Resampling.LANCZOS)
            left_smear = left_avg.resize((offset_x, frame.size[1]), Image.Resampling.NEAREST)
            canvas.paste(left_smear, (0, offset_y))
            
        right_start = offset_x + frame.size[0]
        right_gap = target_size[0] - right_start
        if right_gap > 0:
            right_edge = frame.crop((max(0, frame.size[0]-3), 0, frame.size[0], frame.size[1]))
            right_avg = right_edge.resize((1, frame.size[1]), Image.Resampling.LANCZOS)
            right_smear = right_avg.resize((right_gap, frame.size[1]), Image.Resampling.NEAREST)
            canvas.paste(right_smear, (right_start, offset_y))
    elif bg_fill == 'blur':
        canvas = img.resize(target_size, Image.Resampling.LANCZOS)
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=3))
    elif bg_fill == 'black':
        canvas = Image.new("RGB", target_size, (0, 0, 0))
    else:
        canvas = Image.new("RGB", target_size, (255, 255, 255))
    
    offset_x = (target_size[0] - frame.size[0]) // 2
    offset_y = (target_size[1] - frame.size[1]) // 2
    canvas.paste(frame, (offset_x, offset_y))
    
    if invert:
        canvas = ImageOps.invert(canvas)
    
    if no_enhance:
        return canvas.convert('1')
    
    # --- Grayscale conversion ---
    if grayscale_mode == 'smart':
        gray = smart_grayscale(canvas)
    elif grayscale_mode == 'max':
        r, g, b = canvas.split()
        gray = ImageChops.lighter(r, ImageChops.lighter(g, b))
    elif grayscale_mode == 'balanced':
        weighted = canvas.convert('L')
        r, g, b = canvas.split()
        max_lum = ImageChops.lighter(r, ImageChops.lighter(g, b))
        gray = Image.blend(weighted, max_lum, 0.5)
    else:  # 'weighted' — standard Rec.709
        gray = canvas.convert('L')
    
    # --- Autocontrast (stretch histogram to full range) ---
    gray = ImageOps.autocontrast(gray, cutoff=1)
    
    # --- Gamma correction ---
    if gamma != 1.0:
        gamma_lut = [int(pow(i / 255.0, gamma) * 255.0) for i in range(256)]
        gray = gray.point(gamma_lut)
    
    # --- Brightness / contrast ---
    if brightness != 1.0:
        gray = ImageEnhance.Brightness(gray).enhance(brightness)
    if contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(contrast)
    
    # --- Sharpen ---
    if sharpen > 0:
        gray = gray.filter(
            ImageFilter.UnsharpMask(radius=1, percent=int(sharpen * 100), threshold=3)
        )
    
    # --- Morphological boldness ---
    if boldness > 0:
        gray = morphological_bold(gray, boldness=boldness)
    
    # --- Black floor (clamp near-black to black) ---
    if black_floor and int(black_floor) > 0:
        gray = gray.point(lambda p: 0 if p < int(black_floor) else p)
    
    # --- Dithering ---
    if dither == 'atkinson':
        return atkinson_dither(gray, diffusion=diffusion)
    elif dither == 'none':
        return gray.convert('1', dither=Image.Dither.NONE)
    
    # Default: PIL's native Floyd-Steinberg
    return gray.convert('1', dither=Image.FLOYDSTEINBERG)


# ---------------------------------------------------------------------------
#  Bitmap conversion (unchanged)
# ---------------------------------------------------------------------------

def image_to_bitmap(img: Image.Image) -> bytes:
    """Convert a 1-bit PIL image to packed bitmap bytes for DIS."""
    if img.mode != '1':
        img = img.convert('1')
    
    w, h = img.size
    pixels = img.load()
    bitmap_bytes = []
    
    for y in range(h):
        for x_byte in range(w // 8):
            byte_val = 0
            for bit in range(8):
                x = (x_byte * 8) + bit
                if x < w:
                    if pixels[x, y] > 0:
                        byte_val |= (1 << (7 - bit))
            bitmap_bytes.append(byte_val)
            
    return bytes(bitmap_bytes)
