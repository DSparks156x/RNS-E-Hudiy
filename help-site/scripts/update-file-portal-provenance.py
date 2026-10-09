"""Record the sources and screenshot hashes for the real file-portal fixture."""
import hashlib
import json
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
media = repo / "help-site/public/media"
sources = [
    "hudiy_dataview/src/FilePortal.tsx",
    "hudiy_dataview/src/tabs/FilesTab.tsx",
    "hudiy_dataview/src/filePortalModel.ts",
    "hudiy_dataview/src/portal.css",
    "help-site/scripts/capture-file-portal.jsx",
]
assets = {
    "file-portal-overview.jpg": "recordings",
    "file-portal-debug.jpg": "debug",
    "file-portal-upload.jpg": "upload",
}
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
manifest = {
    "data": "Synthetic filenames, sizes, dates and in-memory file APIs; actual production FilePortal and FilesTab components with a sample Hudiy color scheme. No vehicle connection or controller operation.",
    "viewport": [1280, 720],
    "capture": "scripts/CAPTURE-FILE-PORTAL.md",
    "sources": {name: digest(repo / name) for name in sources},
    "assets": {name: {"scene": scene, "sha256": digest(media / name)} for name, scene in assets.items()},
}
(media / "file-portal-provenance.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
