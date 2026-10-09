"""Assemble the browser-captured DataView fixture frames into a looping demo."""
from pathlib import Path
from PIL import Image
import hashlib
import json

root = Path(__file__).resolve().parents[1]
frames = [Image.open(path).convert('RGB') for path in sorted((root / '.capture-frames').glob('*.jpg'))]
if not frames:
    raise SystemExit('Capture scripts/capture-dataview.html in a browser at 800x480 first.')
frames[0].save(root / 'public/media/dataview-engine.gif', save_all=True,
               append_images=frames[1:], duration=70, loop=0, optimize=False)
sources = ['hudiy_dataview/src/tabs/EngineTab.tsx', 'hudiy_dataview/src/tabs/TransmissionTab.tsx',
           'hudiy_dataview/src/components/Gauge.tsx', 'hudiy_dataview/src/store/DataStore.ts',
           'hudiy_dataview/static/css/style_v3.css']
manifest = {
    'capture': 'Actual production React components and CSS, captured in browser at 800x480',
    'data': 'Synthetic telemetry injected into production DataStore, no vehicle connection',
    'fixture': 'scripts/capture-dataview.jsx',
    'theme': 'Sample Hudiy Material You palette, injected as production CSS variables',
    'assets': ['dataview-engine.jpg', 'dataview-transmission.jpg', 'dataview-engine.gif'],
    'source_sha256': {path: hashlib.sha256((root.parent / path).read_bytes()).hexdigest() for path in sources},
}
(root / 'public/media/dataview-provenance.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(f'Assembled {len(frames)} frames with {len({f.tobytes() for f in frames})} distinct images.')
