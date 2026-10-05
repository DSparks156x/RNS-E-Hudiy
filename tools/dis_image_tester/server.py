import os
import sys
import base64
import io
import json
from typing import Optional, List, Dict, Any
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

app = FastAPI(title="DIS Image & GIF Processing Tester API")

# Enable CORS for React development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALBUM_COVERS_DIR = os.path.join(root_dir, "tools", "dis_image_tester", "albumcovers")
GIFS_DIR = os.path.join(root_dir, "tools", "dis_image_tester", "gifs")

os.makedirs(ALBUM_COVERS_DIR, exist_ok=True)
os.makedirs(GIFS_DIR, exist_ok=True)


class ProcessRequest(BaseModel):
    filename: str
    contrast: float = 1.4
    sharpen: float = 1.5
    dither: str = "fs"
    invert: bool = False
    no_enhance: bool = False
    bg_fill: str = "black"
    grayscale_mode: str = "smart"
    brightness: float = 1.0
    gamma: float = 2.2
    black_floor: int = 45
    boldness: float = 0.0
    diffusion: float = 0.85
    width: int = 64
    height: int = 48
    max_frames: Optional[int] = 300


class UploadRequest(BaseModel):
    filename: str
    data: str  # Base64 data URL


def resolve_file_path(filename: str) -> Optional[str]:
    """Find file in GIFS_DIR or ALBUM_COVERS_DIR."""
    # If specific folder indicated or direct match
    gif_path = os.path.join(GIFS_DIR, filename)
    if os.path.exists(gif_path):
        return gif_path

    img_path = os.path.join(ALBUM_COVERS_DIR, filename)
    if os.path.exists(img_path):
        return img_path

    return None


@app.get("/api/images")
async def list_images():
    images = []
    gifs = []

    if os.path.exists(ALBUM_COVERS_DIR):
        for f in os.listdir(ALBUM_COVERS_DIR):
            lower = f.lower()
            if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                images.append(f)
            elif lower.endswith(".gif"):
                gifs.append(f)

    if os.path.exists(GIFS_DIR):
        for f in os.listdir(GIFS_DIR):
            lower = f.lower()
            if lower.endswith(".gif") and f not in gifs:
                gifs.append(f)
            elif lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")) and f not in images:
                images.append(f)

    all_items = [{"filename": f, "type": "image"} for f in images] + [
        {"filename": f, "type": "gif"} for f in gifs
    ]

    return {
        "images": images,
        "gifs": gifs,
        "all": all_items,
    }


@app.get("/api/gifs")
async def list_gifs():
    gifs = []
    if os.path.exists(GIFS_DIR):
        gifs = [f for f in os.listdir(GIFS_DIR) if f.lower().endswith(".gif")]
    return {"gifs": gifs}


@app.post("/api/upload")
async def upload_file(req: UploadRequest):
    try:
        header, b64data = req.data.split(",", 1) if "," in req.data else ("", req.data)
        file_bytes = base64.b64decode(b64data)
        safe_name = os.path.basename(req.filename)

        if safe_name.lower().endswith(".gif"):
            target_path = os.path.join(GIFS_DIR, safe_name)
            media_type = "gif"
        else:
            target_path = os.path.join(ALBUM_COVERS_DIR, safe_name)
            media_type = "image"

        with open(target_path, "wb") as f:
            f.write(file_bytes)

        return {"filename": safe_name, "type": media_type, "size": len(file_bytes)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")


@app.post("/api/process")
async def process_media(req: ProcessRequest):
    file_path = resolve_file_path(req.filename)
    if not file_path:
        raise HTTPException(status_code=404, detail=f"File not found: {req.filename}")

    is_gif = req.filename.lower().endswith(".gif")

    # Generate parameter list for config strings
    params = []
    if req.width != 64 or req.height != 48:
        params.append(f"target_size=({req.width}, {req.height})")
    if req.contrast != 1.4:
        params.append(f"contrast={req.contrast}")
    if req.sharpen != 1.5:
        params.append(f"sharpen={req.sharpen}")
    if req.dither != "fs":
        params.append(f"dither='{req.dither}'")
    if req.invert:
        params.append("invert=True")
    if req.no_enhance:
        params.append("no_enhance=True")
    if req.bg_fill != "black":
        params.append(f"bg_fill='{req.bg_fill}'")
    if req.grayscale_mode != "smart":
        params.append(f"grayscale_mode='{req.grayscale_mode}'")
    if req.brightness != 1.0:
        params.append(f"brightness={req.brightness}")
    if req.gamma != 2.2:
        params.append(f"gamma={req.gamma}")
    if req.black_floor != 45:
        params.append(f"black_floor={req.black_floor}")
    if req.boldness != 0:
        params.append(f"boldness={req.boldness}")
    if req.diffusion != 0.85:
        params.append(f"diffusion={req.diffusion}")

    data_dict = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    config_json = {
        k: v
        for k, v in data_dict.items()
        if k not in ("filename", "width", "height", "max_frames")
    }
    config_json["target_size"] = [req.width, req.height]

    # Non-default parameters for eggs.json
    egg_params = {
        k: v
        for k, v in data_dict.items()
        if k not in ("filename", "width", "height", "max_frames")
    }
    # Clean egg params to only include non-defaults for brevity
    egg_clean = {}
    default_vals = {
        "contrast": 1.4,
        "sharpen": 1.5,
        "dither": "fs",
        "invert": False,
        "no_enhance": False,
        "bg_fill": "black",
        "grayscale_mode": "smart",
        "brightness": 1.0,
        "gamma": 2.2,
        "black_floor": 45,
        "boldness": 0.0,
        "diffusion": 0.85,
    }
    for k, v in egg_params.items():
        if k in default_vals and v != default_vals[k]:
            egg_clean[k] = v

    try:
        if is_gif:
            with Image.open(file_path) as img:
                total_frames = getattr(img, "n_frames", 1)
                process_count = min(total_frames, req.max_frames or 300)

                processed_p_frames = []
                frame_png_b64s = []
                durations = []

                for f_idx in range(process_count):
                    img.seek(f_idx)
                    dur = img.info.get("duration", 100) or 100
                    durations.append(max(20, dur))

                    frame_img = img.convert("RGB")
                    processed_frame = dis_image.process_image(
                        frame_img,
                        target_size=(req.width, req.height),
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
                        diffusion=req.diffusion,
                    )
                    processed_p_frames.append(processed_frame.convert("P"))

                    # Individual frame PNG for inspection/scrubbing
                    buf = io.BytesIO()
                    processed_frame.save(buf, format="PNG")
                    frame_png_b64s.append(f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}")

                # Save animated GIF
                buffered_gif = io.BytesIO()
                if len(processed_p_frames) > 1:
                    processed_p_frames[0].save(
                        buffered_gif,
                        format="GIF",
                        save_all=True,
                        append_images=processed_p_frames[1:],
                        duration=durations,
                        loop=0,
                    )
                else:
                    processed_p_frames[0].save(buffered_gif, format="GIF")

                gif_b64 = base64.b64encode(buffered_gif.getvalue()).decode()

                # Get original GIF as base64
                with open(file_path, "rb") as f:
                    orig_b64 = base64.b64encode(f.read()).decode()

                avg_dur = sum(durations) / len(durations) if durations else 100
                fps = round(1000.0 / avg_dur, 1) if avg_dur > 0 else 10.0

                config_str = (
                    f"egg_app.load_gif('{req.filename}', loop_count=999, {', '.join(params)})"
                    if params
                    else f"egg_app.load_gif('{req.filename}', loop_count=999)"
                )

                egg_snippet = {
                    "regex": req.filename.replace(".gif", "").replace("_", " ").title(),
                    "gif": req.filename,
                    "loop": 999,
                    **egg_clean,
                }

                config_snippet = {
                    "display": {
                        "center_display": {"coverart": {"brief": True, "args": config_json}}
                    }
                }

                return {
                    "is_gif": True,
                    "frame_count": total_frames,
                    "processed_frames_count": process_count,
                    "fps": fps,
                    "durations": durations,
                    "processed": f"data:image/gif;base64,{gif_b64}",
                    "original": f"data:image/gif;base64,{orig_b64}",
                    "frames": frame_png_b64s,
                    "first_frame": frame_png_b64s[0] if frame_png_b64s else "",
                    "config_string": config_str,
                    "config_json": config_json,
                    "config_snippet": config_snippet,
                    "egg_snippet": egg_snippet,
                }
        else:
            with Image.open(file_path) as img:
                processed = dis_image.process_image(
                    img,
                    target_size=(req.width, req.height),
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
                    diffusion=req.diffusion,
                )

                buffered = io.BytesIO()
                processed.convert("RGB").save(buffered, format="PNG")
                img_str = base64.b64encode(buffered.getvalue()).decode()

                with open(file_path, "rb") as f:
                    orig_str = base64.b64encode(f.read()).decode()

                config_str = (
                    f"dis_image.process_image(img, {', '.join(params)})"
                    if params
                    else "dis_image.process_image(img)"
                )

                config_snippet = {
                    "display": {
                        "center_display": {"coverart": {"brief": True, "args": config_json}}
                    }
                }

                return {
                    "is_gif": False,
                    "frame_count": 1,
                    "fps": 0,
                    "processed": f"data:image/png;base64,{img_str}",
                    "original": f"data:image/png;base64,{orig_str}",
                    "frames": [f"data:image/png;base64,{img_str}"],
                    "first_frame": f"data:image/png;base64,{img_str}",
                    "config_string": config_str,
                    "config_json": config_json,
                    "config_snippet": config_snippet,
                    "egg_snippet": None,
                }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
