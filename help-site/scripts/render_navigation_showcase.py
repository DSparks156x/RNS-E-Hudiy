"""Matched navigation renders from NavApp; synthetic route, no live transport.

Run from the repository root with Python, Pillow and NumPy installed.
The preferred stock renderer deliberately falls back where its semantic mapping
has no reviewed OEM object. The manifest records that decision for every frame.
"""
from __future__ import annotations

import copy
import hashlib
import json

from PIL import Image
from render_dis import CONFIG, OUT, ROOT, NavApp, render
from enhanced_navigation import approach_visible, native_selection

DURATION_MS = 1800
# Description is route data; label is documentation. Types and angles go through
# the same semantic mapping as incoming HUDIY_NAV, never raw RNSE object bytes.
EXAMPLES = [
    ('straight-far', 'Straight · 1.2 km', 14, 3, 'Continue onto Oak Ave', '1.2 km', None),
    ('left-far', 'Left turn · 500 m', 4, 1, 'Turn left onto Main St', '500 m', None),
    ('left-approach', 'Left turn · 250 m', 4, 1, 'Turn left onto Main St', '250 m', None),
    ('left-close', 'Left turn · 30 m', 4, 1, 'Turn left onto Main St', '30 m', None),
    ('right', 'Right turn · 100 m', 4, 2, 'Turn right onto Pine St', '100 m', None),
    ('slight-left', 'Slight left · 200 m', 3, 1, 'Keep left onto Cedar Rd', '200 m', None),
    ('slight-right', 'Slight right · 150 m', 3, 2, 'Keep right onto Elm Rd', '150 m', None),
    ('sharp-left', 'Sharp left · 100 m', 5, 1, 'Turn left onto Birch Rd', '100 m', None),
    ('sharp-right', 'Sharp right · 60 m', 5, 2, 'Turn right onto Ash Rd', '60 m', None),
    ('ramp-on-left', 'Ramp on left · 200 m', 7, 1, 'Highway ramp', '200 m', None),
    ('ramp-on-right', 'Ramp on right · 150 m', 7, 2, 'Highway ramp', '150 m', None),
    ('ramp-off-left', 'Ramp off left · 100 m', 8, 1, 'Left exit', '100 m', None),
    ('ramp-off-right', 'Ramp off right · 60 m', 8, 2, 'Right exit', '60 m', None),
    ('fork-left', 'Fork left · 250 m', 9, 1, 'Keep left onto West Rd', '250 m', None),
    ('fork-right', 'Fork right · 150 m', 9, 2, 'Keep right onto East Rd', '150 m', None),
    ('u-turn', 'U-turn · 60 m', 6, 1, 'U-turn', '60 m', None),
    ('roundabout-enter', 'Enter roundabout · 250 m', 11, 3, 'Roundabout', '250 m', None),
    ('roundabout-45', 'Roundabout · 45° exit · 200 m', 13, 2, 'First exit', '200 m', 45),
    ('roundabout-90', 'Roundabout · 90° exit · 150 m', 13, 2, 'East Rd', '150 m', 90),
    ('roundabout-135', 'Roundabout · 135° exit · 100 m', 13, 2, 'Oak Ave', '100 m', 135),
    ('roundabout-180', 'Roundabout · straight exit · 60 m', 13, 2, 'North Rd', '60 m', 180),
    ('roundabout-225', 'Roundabout · 225° exit · 100 m', 13, 2, 'West Rd', '100 m', 225),
    ('roundabout-270', 'Roundabout · 270° exit · 60 m', 13, 2, 'South Rd', '60 m', 270),
    ('roundabout-315', 'Roundabout · 315° exit · 30 m', 13, 2, 'Birch Rd', '30 m', 315),
    ('merge', 'Merge right · 200 m', 10, 2, 'Merge onto Highway', '200 m', None),
    ('destination', 'Destination on right · 10 m', 19, 2, 'Destination', '10 m', None),
]


def assert_monochrome(image):
    assert image.size == (512, 384)
    assert {color for _, color in image.getcolors(maxcolors=3) or []} == {(0, 0, 0), (255, 255, 255)}, 'DIS preview gained a color'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    renderers = {}
    for style in ('stock', 'bitmap'):
        config = copy.deepcopy(CONFIG)
        config['display']['center_display']['navigation'].update(
            icon_style=style, auto_switch_approach_threshold=500,
            auto_switch_return_threshold=1000)
        renderers[style] = NavApp(config)
    frames = {style: [] for style in renderers}
    samples = []
    for slug, label, kind, side, description, distance, angle in EXAMPLES:
        update = dict(description=description, distance=distance,
                      maneuver_type=kind, maneuver_side=side)
        if angle is not None:
            update.update(maneuver_angle=angle, maneuver_angle_present=True)
        sample = dict(id=slug, label=label, input=update, images={})
        for style, app in renderers.items():
            app.update_hudiy(b'HUDIY_NAV', update)
            image = render(app.get_view())
            assert_monochrome(image)
            filename = f'nav-showcase-{style}-{slug}.png'
            image.save(OUT / filename)
            sample['images'][style] = filename
            frames[style].append(image)
        sample['stock_fallback'] = native_selection(renderers['stock']) is None
        sample['bar_visible'] = approach_visible(renderers['bitmap'])
        sample['icon_key'] = renderers['bitmap']._get_icon_name()
        samples.append(sample)
    for style, images in frames.items():
        images[0].save(OUT / f'nav-showcase-{style}.png')
        images[0].save(OUT / f'nav-showcase-{style}.gif', save_all=True,
                       append_images=images[1:], duration=DURATION_MS,
                       loop=0, optimize=False, disposal=2)
        with Image.open(OUT / f'nav-showcase-{style}.gif') as gif:
            assert gif.n_frames == len(samples)
            for frame in range(gif.n_frames):
                gif.seek(frame)
                assert_monochrome(gif.convert('RGB'))
                assert gif.info['duration'] == DURATION_MS
    sources = ['dis_client/apps/nav.py', 'dis_client/enhanced_navigation.py',
               'dis_client/navigation_state.py', 'dis_client/nav_icons.py',
               'dis_client/nav_icons_data.py', 'dis_client/icons.py',
               'dis_client/stock_mono_frame.py', 'dis_client/stock_mono_catalog.json',
               'dis_client/apps/base.py', 'dis_client/font_metrics.py',
               'dis_client/display_resolution.py',
               'dis_emulator/static/native_font_data.js',
               'help-site/scripts/render_dis.py',
               'help-site/scripts/render_navigation_showcase.py']
    manifest = dict(data='Synthetic route inputs; production render commands, not road footage.',
                    display='128x96 physical center pixels, nearest-neighbor enlarged 4x',
                    preview_palette=dict(background_rgb=[0, 0, 0], ink_rgb=[255, 255, 255]),
                    duration_ms=DURATION_MS, samples=samples,
                    bar_limit_m=300, approach_threshold_m=500, return_threshold_m=1000,
                    road_side='right', units='metric',
                    source_sha256={path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                   for path in sources})
    (OUT / 'navigation-showcase.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'help-site/src/navigation-examples.json').write_text(json.dumps([
        {key: sample[key] for key in ('id', 'label', 'images', 'stock_fallback', 'bar_visible')}
        for sample in samples], indent=2) + '\n', encoding='utf-8')
    print(f'Rendered {len(samples)} matched stock/bitmap examples; checked every GIF frame is black/white.')


if __name__ == '__main__':
    main()
