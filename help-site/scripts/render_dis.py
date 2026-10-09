"""Rebuild the help site's DIS demos from production apps and captured LCD masks.

From the repository root: python help-site/scripts/render_dis.py
Requires Pillow and NumPy. All inputs are synthetic; no hardware, sockets or log files
are opened. Native center images show 128x96 physical pixels enlarged 4x;
legacy center images show 64x48 logical pixels enlarged 8x. Top-only images
show the two eight-character lines. All enlargements use nearest neighbor.
Text painting mirrors dis_emulator/templates/index.html. The website preview
palette is pure black and white; native masks and dither patterns are preserved.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import sys
from types import ModuleType
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'help-site/public/media'
sys.path[:0] = [str(ROOT), str(ROOT / 'dis_client')]
from apps.nav import NavApp
from apps.media import MediaApp
from apps.coverart import CoverArtApp
from apps.phone import PhoneApp
from apps.readings import ReadingsApp
from apps.acceleration_test import AccelerationTestApp
from apps.car_info import CarInfoApp
from icons import encode_audscii
from vehicle_data.catalog import CATALOG
from vehicle_data.workspace import default_workspace

# Import the production text scroller without its optional transport dependency.
# No DISController constructor, worker or socket is used by this offline script.
with patch.dict(sys.modules, {'zmq': ModuleType('zmq')}):
    import dis_top_display_service as top_service
    from dis_top_display_service import DISController, TextScroller

SOURCE_FONT = ROOT / 'dis_emulator/static/native_font_data.js'
font_source = SOURCE_FONT.read_text(encoding='utf-8')
FONT, _ = json.JSONDecoder().raw_decode(font_source[re.search(r'const data\s*=\s*', font_source).end():])
LEGACY_FONT_SOURCE = ROOT / 'dis_emulator/static/font_data.js'
legacy_source = LEGACY_FONT_SOURCE.read_text(encoding='utf-8')
LEGACY_FONT, _ = json.JSONDecoder().raw_decode(
    legacy_source[re.search(r'const FONT_DATA_PROP\s*=\s*', legacy_source).end():])
BG, INK = (0, 0, 0), (255, 255, 255)
CONFIG = {'display': {'text_centering': True, 'road_side': 'right',
    'center_display': {'high_resolution': True, 'navigation': {
        'icon_style': 'bitmap', 'approach_bar_max_distance': 300}},
    'units': {'speed': 'metric'},
    'text_scrolling': {'speed_ms': 300, 'start_delay_ms': 1000,
                       'end_delay_ms': 500, 'continuous': False}}}


def rectangle(canvas, x, y, w, h, color):
    if w > 0 and h > 0:
        ImageDraw.Draw(canvas).rectangle((x, y, x + w - 1, y + h - 1), fill=color)


def draw_codes(canvas, codes, x, y, flags, command):
    name = 'graphics' if flags & 8 else 'proportional' if flags & 4 else 'fixed'
    glyphs = [FONT['fonts'][name]['glyphs'][code] for code in codes]
    for glyph in glyphs:
        if glyph['status'] not in ('verified', 'observed_blank') or glyph['advance_px'] is None:
            raise ValueError(f'Uncaptured glyph in demo: {name} {glyph["code"]:02x}')
    width = sum(glyph['advance_px'] for glyph in glyphs)
    cursor = max(0, (128 - width) // 2) if flags & 0x20 else x * 2
    fg, bg = (BG, INK) if flags & 0x80 else (INK, BG)
    if flags & 0x80 and 'highlight_width' in command:
        rectangle(canvas, x * 2, y * 2, command['highlight_width'] * 2,
                  command.get('highlight_height', 9) * 2, bg)
    for glyph in glyphs:
        advance = glyph['advance_px']
        rectangle(canvas, cursor, y * 2, advance, 18, bg)
        if glyph['mask_hex'] and glyph['size']:
            w, h = glyph['size']
            data = bytes.fromhex(glyph['mask_hex'])
            stride = (w + 7) // 8
            for py in range(h):
                for px in range(w):
                    if data[py * stride + px // 8] & (128 >> (px % 8)):
                        dx, dy = int(cursor + px), y * 2 + py
                        if 0 <= dx < 128 and 0 <= dy < 96:
                            canvas.putpixel((dx, dy), fg)
        cursor += advance


def render(view):
    canvas = Image.new('RGB', (128, 96), BG)
    if isinstance(view, dict):
        offsets = {'line1': 1, 'line2': 11, 'line3': 21, 'line4': 31, 'line5': 41}
        view = [dict(cmd='draw_text', text=text, flags=flags, x=0, y=offsets[key])
                for key, (text, flags) in view.items()]
    for command in view:
        cmd = command.get('cmd')
        if cmd == 'clear_area':
            rectangle(canvas, command['x'] * 2, command['y'] * 2,
                      command['w'] * 2, command['h'] * 2, BG)
        elif cmd in ('draw_text', 'draw_native_font'):
            codes = encode_audscii(command['text']) if cmd == 'draw_text' else command['glyphs']
            draw_codes(canvas, codes, command['x'], command['y'], command['flags'], command)
        elif cmd == 'native_bitmap':
            data = bytes.fromhex(command['data_hex'])
            assert len(data) == 1536
            x, y, w, h = command.get('update_rect', (0, 0, 128, 96))
            for py in range(y, y + h):
                for px in range(x, x + w):
                    canvas.putpixel((px, py), INK if data[py * 16 + px // 8] & (128 >> (px % 8)) else BG)
        elif cmd is not None:
            raise ValueError('Unsupported draw command: ' + cmd)
    return canvas.resize((512, 384), Image.Resampling.NEAREST)


def draw_legacy_codes(canvas, codes, y, *, fixed_width=False, ink=INK):
    """Mirror emulator drawText/drawAudscii in its 64px logical grid."""
    glyphs = [LEGACY_FONT[str(code)] for code in codes]
    width = sum(6 if fixed_width else glyph[0] for glyph in glyphs)
    cursor = max(0, (64 - width) // 2)
    for glyph in glyphs:
        advance = 6 if fixed_width else glyph[0]
        for row in range(7):
            for col in range(6 if fixed_width else advance):
                if glyph[row + 1] & (1 << (5 - col)):
                    if 0 <= cursor + col < 64 and y + row + 1 < canvas.height:
                        canvas.putpixel((cursor + col, y + row + 1), ink)
        cursor += advance


def render_legacy(view):
    canvas = Image.new('RGB', (64, 48), (0, 0, 0))
    offsets = {'line1': 1, 'line2': 11, 'line3': 21, 'line4': 31, 'line5': 41}
    for key, (text, flags) in view.items():
        assert flags == 0x26, 'Legacy demo expects centered proportional text'
        draw_legacy_codes(canvas, encode_audscii(text), offsets[key])
    return canvas.resize((512, 384), Image.Resampling.NEAREST)


def render_top(scrollers):
    # The top service sends eight fixed-width AUDSCII bytes per line. As in
    # draw_top_text in the emulator, those use the legacy 6x7 glyph table even
    # when the center display uses native pixel masks.
    canvas = Image.new('RGB', (64, 23), BG)
    for scroller, y in zip(scrollers, (3, 13)):
        draw_legacy_codes(canvas, scroller.snapshot(), y, fixed_width=True, ink=INK)
    return canvas.resize((512, 184), Image.Resampling.NEAREST)


assets = []


def save(name, frames, caption, sources, duration=500, inputs=None, display=None):
    frames[0].save(OUT / (name + '.png'))
    if len(frames) > 1:
        frames[0].save(OUT / (name + '.gif'), save_all=True, append_images=frames[1:],
                       duration=duration, loop=0, optimize=False, disposal=2)
    encoded_frames = 1
    if len(frames) > 1:
        with Image.open(OUT / (name + '.gif')) as saved:
            encoded_frames = saved.n_frames
    assets.append({'name': name, 'caption': caption, 'demo_inputs': inputs,
                   'rendered_size_px': list(frames[0].size), 'display': display or 'Native 128x96 center area enlarged 4x',
                   'source_frame_count': len(frames), 'encoded_frame_count': encoded_frames,
                   'source_frame_duration_ms': duration, 'source_files': sources})


class DemoWorkspace:
    def load(self):
        return copy.deepcopy(default_workspace())


class DemoLogger:
    recording = {'recording': False}
    error = None

    def tick(self):
        pass

    def command(self, *args, **kwargs):
        pass


def main():
    assets.clear()
    OUT.mkdir(parents=True, exist_ok=True)
    route = {'description': 'Turn left onto Main St', 'distance': '250 m',
             'maneuver_type': 4, 'maneuver_side': 1}
    nav = NavApp(copy.deepcopy(CONFIG))
    nav.update_hudiy(b'HUDIY_NAV', route)
    save('dis-navigation', [render(nav.get_view())],
         'Custom bitmap navigation: left turn, distance and native approach bar. Sample route, metric units.',
         ['dis_client/apps/nav.py', 'dis_client/enhanced_navigation.py', 'dis_client/nav_icons.py'], inputs=route)
    frames, input_frames = [], []
    for kind, side, street, distances in (
        (4, 1, 'Turn left onto Main St', (300, 250, 200, 150, 100, 60, 30, 10)),
        (14, 3, 'Continue onto Oak Ave', (800, 700, 600, 500)),
        (4, 2, 'Turn right onto Pine St', (300, 250, 200, 150, 100, 60, 30, 10))):
        for distance in distances:
            update = dict(description=street, distance=f'{distance} m',
                          maneuver_type=kind, maneuver_side=side)
            nav.update_hudiy(b'HUDIY_NAV', update)
            frames.append(render(nav.get_view()))
            input_frames.append(update)
    save('dis-navigation-approach', frames,
         'Sample route: approach a left turn, continue straight, then approach a right turn. The native bar appears within 300 m and fills as distance falls. This is a rendered sequence, not a road recording.',
         ['dis_client/apps/nav.py', 'dis_client/enhanced_navigation.py', 'dis_client/nav_icons.py'],
         duration=650, inputs=input_frames)
    stock_config = copy.deepcopy(CONFIG)
    stock_config['display']['center_display']['navigation']['icon_style'] = 'stock'
    stock = NavApp(stock_config)
    stock.update_hudiy(b'HUDIY_NAV', route)
    save('dis-navigation-stock', [render(stock.get_view())],
         'Stock glyph navigation: production placement of captured OEM icon and bar glyphs. Sample left turn at 250 m; this renderer does not draw the bitmap style distance field.',
         ['dis_client/apps/nav.py', 'dis_client/enhanced_navigation.py'], inputs=route)

    media_input = dict(title='Night Drive', artist='Demo Artist', album='After Hours', position='1:24', duration='4:08')
    media = MediaApp(copy.deepcopy(CONFIG))
    media.update_hudiy(b'HUDIY_MEDIA', media_input)
    save('dis-media', [render(media.get_view())],
         'Now playing: track, artist, album and playback time. All metadata is made-up demo content.',
         ['dis_client/apps/media.py'], inputs=media_input)
    media_input['title'] = 'Night Drive Along the Coast'
    media.update_hudiy(b'HUDIY_MEDIA', media_input)
    with patch('apps.base.time.monotonic') as now:
        frames = []
        for step in range(40):
            now.return_value = step * .35
            frames.append(render(media.get_view()))
    save('dis-media-scroll', frames,
         'Measured text scrolling keeps a long sample track title inside the display. Short fields remain centered.',
         ['dis_client/apps/media.py', 'dis_client/apps/base.py', 'dis_client/font_metrics.py'],
         duration=350, inputs=media_input)

    # Original geometric demo artwork, supplied through the same encoded
    # image payload as HUDIY cover art. No third-party album artwork is used.
    cover_source = Image.new('RGB', (256, 256), (18, 30, 43))
    artwork = ImageDraw.Draw(cover_source)
    artwork.ellipse((64, 36, 192, 164), fill=(245, 212, 130))
    for index in range(6):
        y = 134 + index * 19
        artwork.line((0, y + 35, 92, y - 12, 158, y + 6, 256, y - 28),
                     fill=(105 + index * 21, 150 + index * 13, 172 + index * 9), width=7)
    cover_source.save(OUT / 'demo-cover-source.png')
    encoded = io.BytesIO()
    cover_source.save(encoded, format='PNG')
    cover_config = copy.deepcopy(CONFIG)
    cover_config['display']['center_display']['coverart'] = {'native_preset': 'balanced'}
    cover = CoverArtApp(cover_config)
    cover.update_hudiy(b'HUDIY_COVERART', {'image_hex': encoded.getvalue().hex()})
    save('dis-cover-art', [render(cover.get_view())],
         'Original geometric demo artwork converted by the production cover-art pipeline. Native 128×96 resolution, balanced preset with ordered dithering.',
         ['dis_client/apps/coverart.py', 'dis_client/dis_image.py'],
         inputs={'artwork': 'demo-cover-source.png', 'native_preset': 'balanced'})

    phone_input = dict(state='INCOMING', caller_name='Alex', caller_id='555-0100', connection_state='CONNECTED')
    # PhoneApp may create a Linux uinput device during construction. For this
    # offline render, make its optional hardware dependency unavailable.
    with patch.dict(sys.modules, {'uinput': None}):
        phone = PhoneApp(copy.deepcopy(CONFIG))
    phone.update_hudiy(b'HUDIY_PHONE', phone_input)
    phone.set_control_mode(True)
    save('dis-phone', [render(phone.get_view())],
         'Sample incoming call with wheel control active. The wheel symbol indicates input ownership; Accept is selected.',
         ['dis_client/apps/phone.py', 'dis_client/icons.py'], inputs=phone_input)

    logger = DemoLogger()
    readings = ReadingsApp(copy.deepcopy(CONFIG), workspace=DemoWorkspace(), logger_client=logger, clock=lambda: 0)
    demo_values = (94, 1450, 89, 36, 27, 2400, 67, 54)
    samples = [dict(id=slot['value_id'], value=value, unit=CATALOG[slot['value_id']]['unit'],
                    status='ok', age_ms=0, max_age_ms=5000)
               for slot, value in zip(readings.page['slots'], demo_values)]
    readings.update_hudiy(b'HUDIY_VALUES', {'client_id': 'dis_display', 'values': samples})
    readings.set_control_mode(True)
    save('dis-readings', [render(readings.get_view())],
         'Default Daily readings page: oil temperature, absolute boost, coolant, MAF, intake temperature, RPM, transmission and AWD oil temperature. Synthetic values; support depends on the vehicle and providers.',
         ['dis_client/apps/readings.py', 'dis_client/readings_assets.py', 'vehicle_data/workspace.py', 'vehicle_data/catalog.py'], inputs=samples)
    frames = [render(readings.get_view())]
    logger.recording = {'recording': True}
    readings.handle_input('next')
    frames.append(render(readings.get_view()))
    readings.handle_input('next')
    frames.append(render(readings.get_view()))
    logger.recording = {'recording': False}
    readings.focus = 0
    frames.append(render(readings.get_view()))
    save('dis-readings-controls', frames,
         'Readings controls: page selection, recording with Stop focused, Mark focused, then idle. Logger state is simulated; the script starts no recording.',
         ['dis_client/apps/readings.py', 'dis_client/readings_assets.py'], duration=1400, inputs=samples)

    acceleration_config = copy.deepcopy(CONFIG)
    acceleration_config['display']['units']['speed'] = 'imperial'
    acceleration_config['display']['center_display']['acceleration_test'] = {
        'line_1': '0-60', 'line_2': '0-30', 'line_3': '40-70', 'line_4': 'speed',
        'auto_reset_on_stop': True, 'auto_reset_delay': .25, 'tolerance_display': True,
    }
    acceleration = AccelerationTestApp(acceleration_config)
    frames, speed_inputs = [], []
    # A synthetic 20Hz CAN_351 stream accelerating at 10mph/s. The app itself
    # detects launches, interpolates crossings, computes sample tolerance and
    # highlights each completed result. Times are not measured vehicle claims.
    with patch('apps.acceleration_test.time.time') as now:
        for step in range(181):
            seconds = step * .05
            speed_mph = min(75, max(0, seconds - .5) * 10)
            encoded_speed = round(speed_mph / .621371 * 200)
            payload = bytes((0, encoded_speed & 255, encoded_speed >> 8))
            now.return_value = 1000 + seconds
            acceleration.update_can('CAN_351', payload)
            speed_inputs.append({'time_s': round(seconds, 2), 'data_hex': payload.hex()})
            if step % 5 == 0:
                frames.append(render(acceleration.get_view()))
        final = render(acceleration.get_view())
    acceleration_sources = ['dis_client/apps/acceleration_test.py', 'dis_client/apps/base.py']
    acceleration_inputs = {'config': acceleration_config['display'], 'CAN_351': speed_inputs}
    save('dis-acceleration', [final],
         'Acceleration page after a simulated run: 0–60 mph, 0–30 mph, 40–70 mph and current speed. Times are synthetic; the header reports tolerance from CAN sample intervals.',
         acceleration_sources, inputs=acceleration_inputs)
    save('dis-acceleration-run', frames,
         'Acceleration page from Ready through Timing to Done. Completed rows briefly invert. Production timing logic receives a synthetic 20Hz speed stream; no vehicle run is shown.',
         acceleration_sources, duration=250, inputs=acceleration_inputs)

    legacy_config = copy.deepcopy(CONFIG)
    legacy_config['display']['center_display']['high_resolution'] = False
    legacy = CarInfoApp(legacy_config)
    legacy_samples = [dict(id=value_id, value=value, status='ok', age_ms=0, max_age_ms=5000)
                      for value_id, value in (
                          ('engine.boost.actual_absolute', 1450), ('engine.maf', 36),
                          ('engine.ignition_timing', 12.5), ('engine.oil_temperature', 94),
                          ('engine.coolant_temperature', 89))]
    legacy.update_hudiy(b'HUDIY_VALUES', {'client_id': 'dis_display', 'values': legacy_samples})
    save('dis-car-info-legacy', [render_legacy(legacy.get_view())],
         'Low-resolution red-cluster Car Info: absolute boost, MAF, ignition timing, oil and coolant. The production five-line view uses the emulator legacy glyph table, enlarged 8x. Synthetic readings.',
         ['dis_client/apps/car_info.py', 'dis_client/apps/base.py', 'dis_emulator/static/font_data.js',
          'dis_emulator/templates/index.html'], inputs=legacy_samples,
         display='Legacy 64x48 logical center area enlarged 8x')

    top_controller = DISController.__new__(DISController)
    top_controller._ctrl_l1 = top_controller._ctrl_l2 = True
    top_controller._l1_mode, top_controller._l2_mode = 'title', 'artist'
    top_controller._l1_alt_mode = 'source'
    top_input = dict(title='Night Drive', artist='Demo Artist', source_label='CarPlay')
    top_texts = top_controller._media_fields(top_input)[:2]
    with patch.object(top_service.time, 'monotonic') as now:
        now.return_value = 0
        scrollers = [TextScroller(width=8, speed_seconds=.3, start_delay=1,
                                  end_delay=.5, stagger=index * .35)
                     for index in range(2)]
        for scroller, text in zip(scrollers, top_texts):
            scroller.set_text(text)
        frames = []
        for step in range(32):
            now.return_value = step * .35
            for scroller in scrollers:
                scroller.tick()
            frames.append(render_top(scrollers))
    save('dis-top-media', frames,
         'Two-line top DIS with sample track and artist, each limited to eight fixed-width characters. The production scrollers advance independently, pause at the ends and restart. This image shows the top strip only.',
         ['dis_client/dis_top_display_service.py', 'dis_emulator/static/font_data.js',
          'dis_emulator/templates/index.html'], duration=350,
         inputs={'media': top_input, 'line_modes': ['title', 'artist'], 'scroller_width': 8,
                 'speed_ms': 300, 'start_delay_ms': 1000, 'end_delay_ms': 500, 'line_stagger_ms': 350},
         display='64x23 logical top strip enlarged 8x; no center area')
    source_paths = sorted({source for asset in assets for source in asset['source_files']} |
                          {'dis_emulator/static/native_font_data.js', 'dis_client/icons.py'})
    manifest = {'display': '128x96 physical-pixel center DIS area, enlarged 4x nearest neighbor',
                'preview_palette': {'background_rgb': BG, 'ink_rgb': INK},
                'production_config': CONFIG, 'data': 'Synthetic demonstration inputs; no road capture',
                'font_painting': 'Captured native glyph masks, opaque 18px cells, emulator coordinate rules',
                'assets': assets, 'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_paths}}
    (OUT / 'provenance.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Rendered {len(assets)} DIS examples to {OUT}')


if __name__ == '__main__':
    main()
