"""Render extra Music & album art examples for the help site.

From the repository root: python help-site/scripts/render_media_showcase.py
Requires Pillow and NumPy. Covers are original synthetic artwork (no third-party
album art) sent through the production CoverArtApp at native 128x96. The
animation is the bundled GIF run through EasterEggApp.load_gif, the production
64x48 bitmap path. Outputs go to help-site/public/media with provenance in
media-showcase.json.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_dis as rd  # noqa: E402  (sets up sys.path for dis_client)
from apps.coverart import CoverArtApp  # noqa: E402
from apps.easteregg import EasterEggApp  # noqa: E402

ROOT, OUT = rd.ROOT, rd.OUT
FONT_PATH = ROOT / 'car_widget/EurostileExtBold.ttf'


def sunset():
    img = Image.new('RGB', (256, 256))
    draw = ImageDraw.Draw(img)
    for y in range(256):
        t = y / 255
        draw.line((0, y, 255, y), fill=(int(40 + 200 * t), int(30 + 90 * t), int(90 - 40 * t)))
    draw.ellipse((84, 48, 172, 136), fill=(255, 226, 150))
    for i, (base, color) in enumerate([(176, (70, 50, 80)), (204, (45, 32, 58)), (232, (22, 16, 30))]):
        points = [(0, 256)] + [(x, base - int(22 * abs(((x + i * 47) % 128) - 64) / 64)) for x in range(0, 257, 16)] + [(256, 256)]
        draw.polygon(points, fill=color)
    return img


def typographic():
    img = Image.new('RGB', (256, 256), (236, 230, 214))
    draw = ImageDraw.Draw(img)
    big = ImageFont.truetype(str(FONT_PATH), 58)
    small = ImageFont.truetype(str(FONT_PATH), 20)
    draw.rectangle((0, 0, 255, 70), fill=(20, 20, 20))
    draw.text((128, 36), 'NIGHT', font=big, fill=(236, 230, 214), anchor='mm')
    draw.text((128, 122), 'DRIVE', font=big, fill=(20, 20, 20), anchor='mm')
    draw.rectangle((24, 168, 232, 176), fill=(20, 20, 20))
    draw.text((128, 214), 'DEMO ARTIST', font=small, fill=(20, 20, 20), anchor='mm')
    return img


def record():
    img = Image.new('RGB', (256, 256), (180, 60, 50))
    draw = ImageDraw.Draw(img)
    for r in range(120, 30, -6):
        shade = 20 + (r % 12) * 2
        draw.ellipse((128 - r, 128 - r, 128 + r, 128 + r), fill=(shade, shade, shade))
    draw.ellipse((88, 88, 168, 168), fill=(240, 200, 70))
    draw.ellipse((122, 122, 134, 134), fill=(180, 60, 50))
    draw.arc((24, 24, 232, 232), 200, 250, fill=(150, 150, 150), width=4)
    return img


COVERS = [
    ('sunset', sunset, 'photo', 'Gradient sky and hills. Photo preset (error diffusion) keeps the tones.'),
    ('type', typographic, 'text', 'Type-only cover. Text preset (hard threshold) keeps edges crisp.'),
    ('record', record, 'balanced', 'Vinyl graphic. Balanced preset (ordered dither) stays stable between redraws.'),
]


def main():
    manifest = {'data': 'All artwork is original synthetic demo content; the animation is the bundled repository GIF.',
                'assets': []}
    for name, make, preset, caption in COVERS:
        source = make()
        source.save(OUT / f'demo-cover-{name}-source.png')
        encoded = io.BytesIO()
        source.save(encoded, format='PNG')
        config = copy.deepcopy(rd.CONFIG)
        config['display']['center_display']['coverart'] = {'native_preset': preset}
        app = CoverArtApp(config)
        app.update_hudiy(b'HUDIY_COVERART', {'image_hex': encoded.getvalue().hex()})
        rd.render(app.get_view()).save(OUT / f'dis-cover-{name}.png')
        manifest['assets'].append({'name': f'dis-cover-{name}', 'caption': caption, 'native_preset': preset,
                                   'source': f'demo-cover-{name}-source.png',
                                   'source_files': ['dis_client/apps/coverart.py', 'dis_client/dis_image.py']})

    # Production GIF path: 64x48 1-bit frames, shown 2x on the native 128x96 area.
    egg = json.loads((ROOT / 'dis_client/eggs.json').read_text())['matches'][0]
    params = {k: v for k, v in egg.items() if k not in ('regex', 'gif', 'loop')}
    app = EasterEggApp({})
    app.load_gif(egg['gif'], 999, **params)
    frames = []
    for frame in app.full_frames:
        cmd = frame[0]
        bitmap = Image.frombytes('1', (cmd['w'], cmd['h']), bytes.fromhex(cmd['data_hex']))
        frames.append(bitmap.convert('RGB').resize((512, 384), Image.Resampling.NEAREST))
    duration = round(1000 / app.fps)
    frames[0].save(OUT / 'dis-animation.png')
    frames[0].save(OUT / 'dis-animation.gif', save_all=True, append_images=frames[1:],
                   duration=duration, loop=0, optimize=False, disposal=2)
    gif_path = ROOT / 'dis_client/eggs' / egg['gif']
    manifest['assets'].append({'name': 'dis-animation', 'frames': len(frames), 'frame_ms': duration,
                               'logical_size': [64, 48], 'source_sha256': hashlib.sha256(gif_path.read_bytes()).hexdigest(),
                               'source_files': ['dis_client/apps/easteregg.py', 'dis_client/dis_image.py']})
    (OUT / 'media-showcase.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(f'Rendered {len(manifest["assets"])} media examples to {OUT}')


if __name__ == '__main__':
    main()
