import os
import sys
import base64
import io
import json
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image

# Add parent directory and dis_client to path to import dis_image
script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
sys.path.insert(0, root_dir)

try:
    import dis_client.dis_image as dis_image
except ImportError:
    # Try alternate path if not found
    sys.path.insert(0, os.path.join(root_dir, "dis_client"))
    import dis_image

app = FastAPI(title="DIS Image Processing Tester API")

# Enable CORS for React development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALBUM_COVERS_DIR = os.path.join(root_dir, "tools", "dis_image_tester", "albumcovers")

class ProcessRequest(BaseModel):
    filename: str
    contrast: float = 1.4
    sharpen: float = 1.5
    dither: str = 'fs'
    invert: bool = False
    no_enhance: bool = False
    bg_fill: str = 'black'
    grayscale_mode: str = 'smart'
    brightness: float = 1.0
    gamma: float = 2.2
    black_floor: int = 45
    boldness: float = 0.0
    diffusion: float = 0.85

@app.get("/api/images")
async def list_images():
    if not os.path.exists(ALBUM_COVERS_DIR):
        return {"error": f"Directory not found: {ALBUM_COVERS_DIR}", "images": []}
    
    images = [f for f in os.listdir(ALBUM_COVERS_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    return {"images": images}

@app.post("/api/process")
async def process_image(req: ProcessRequest):
    img_path = os.path.join(ALBUM_COVERS_DIR, req.filename)
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="Image not found")
    
    try:
        with Image.open(img_path) as img:
            processed = dis_image.process_image(
                img,
                contrast=req.contrast,
                sharpen=req.sharpen,
                dither=req.dither,
                invert=req.invert,
                no_enhance=req.no_enhance,
                bg_fill=req.bg_fill,
                grayscale_mode=req.grayscale_mode,
                brightness=req.brightness,
                gamma=req.gamma,
                black_floor=req.black_floor,
                boldness=req.boldness,
                diffusion=req.diffusion
            )
            
            # Convert specifically to bitmap bytes just to verify it works (optional)
            # bitmap = dis_image.image_to_bitmap(processed)
            
            # Convert processed image to base64 for UI display
            # We want to show it scaled up so it's visible, but dis_image returns 64x48.
            # The UI can scale it with CSS (image-rendering: pixelated)
            buffered = io.BytesIO()
            # Convert to RGB for PNG save if it was 1-bit, though PNG handles 1-bit fine
            processed.convert("RGB").save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            # Also get the original image as base64 for comparison
            with open(img_path, "rb") as f:
                orig_str = base64.b64encode(f.read()).decode()

            # Generate config string for hudiy_data.py
            # Only include non-default values to keep it clean
            params = []
            if req.contrast != 1.4: params.append(f"contrast={req.contrast}")
            if req.sharpen != 1.5: params.append(f"sharpen={req.sharpen}")
            if req.dither != 'fs': params.append(f"dither='{req.dither}'")
            if req.invert: params.append(f"invert=True")
            if req.no_enhance: params.append(f"no_enhance=True")
            if req.bg_fill != 'black': params.append(f"bg_fill='{req.bg_fill}'")
            if req.grayscale_mode != 'smart': params.append(f"grayscale_mode='{req.grayscale_mode}'")
            if req.brightness != 1.0: params.append(f"brightness={req.brightness}")
            if req.gamma != 2.2: params.append(f"gamma={req.gamma}")
            if req.black_floor != 45: params.append(f"black_floor={req.black_floor}")
            if req.boldness != 0: params.append(f"boldness={req.boldness}")
            if req.diffusion != 0.85: params.append(f"diffusion={req.diffusion}")
            
            config_str = f"dis_image.process_image(img, {', '.join(params)})" if params else "dis_image.process_image(img)"
            
            # JSON format
            config_json = {k: v for k, v in req.dict().items() if k != 'filename'}

            return {
                "processed": f"data:image/png;base64,{img_str}",
                "original": f"data:image/png;base64,{orig_str}",
                "config_string": config_str,
                "config_json": config_json
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
