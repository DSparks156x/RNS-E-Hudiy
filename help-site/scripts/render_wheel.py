"""Render wheel-control examples using actual DIS views, with no transport or I/O.

Run from the repo root: python help-site/scripts/render_wheel.py
The logger below only changes an in-memory demonstration state.
"""
import copy
import hashlib
import json
import sys
from unittest.mock import patch

from render_dis import BG, INK, CONFIG, OUT, ROOT, CATALOG, PhoneApp, ReadingsApp, default_workspace, render


class Workspace:
    def load(self):
        document = default_workspace()
        second = copy.deepcopy(document['dis_pages'][0])
        second.update(id='engine', name='Engine', profile_id='engine_pull')
        document['dis_pages'].append(second)
        return document


class Logger:
    def __init__(self):
        self.recording = {'recording': False}
        self.error = None
        self.commands = []

    def tick(self):
        pass

    def command(self, command, **fields):
        self.commands.append({'command': command, **fields})
        if command in ('START', 'STOP'):
            self.recording = {'recording': command == 'START'}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {'data': 'Synthetic samples and in-memory logger; no recording, vehicle or uinput',
                'preview_palette': {'background_rgb': BG, 'ink_rgb': INK}, 'assets': []}

    def snapshot(name, app, action, wheel_rect):
        view = app.get_view()
        render(view).save(OUT / (name + '.png'))
        manifest['assets'].append({'name': name, 'action': action, 'wheel_icon_rect_physical_px': wheel_rect,
                                   'view': view, 'size_px': [512, 384]})

    logger = Logger()
    readings = ReadingsApp(copy.deepcopy(CONFIG), workspace=Workspace(), logger_client=logger, clock=lambda: 0)
    samples = [dict(id=slot['value_id'], value=value, unit=CATALOG[slot['value_id']]['unit'],
                    status='ok', age_ms=0, max_age_ms=5000)
               for slot, value in zip(readings.page['slots'], (94, 1450, 89, 36, 27, 2400, 67, 54))]
    readings.update_hudiy(b'HUDIY_VALUES', {'client_id': 'dis_display', 'values': samples})
    snapshot('wheel-readings-normal', readings, 'Normal wheel ownership; no selection or ownership icon', None)
    readings.set_control_mode(True)
    snapshot('wheel-readings-page', readings, 'MODE double click gives DIS wheel ownership; page name selected', [116, 0, 12, 18])
    readings.handle_input('select')
    readings.handle_input('next')
    snapshot('wheel-readings-browse', readings, 'Click page name, rotate to Engine page', [116, 0, 12, 18])
    readings.handle_input('select')
    readings.handle_input('next')
    snapshot('wheel-readings-start', readings, 'Confirm page, rotate to Start', [116, 0, 12, 18])
    readings.handle_input('select')
    snapshot('wheel-readings-stop', readings, 'Click Start; in-memory logger acknowledges recording; Stop selected', [116, 0, 12, 18])
    readings.handle_input('next')
    snapshot('wheel-readings-mark', readings, 'Rotate to marker action while recording', [116, 0, 12, 18])

    with patch.dict(sys.modules, {'uinput': None}):
        phone = PhoneApp(copy.deepcopy(CONFIG))
    phone_input = dict(state='INCOMING', caller_name='Alex', caller_id='555-0100', connection_state='CONNECTED')
    phone.update_hudiy(b'HUDIY_PHONE', phone_input)
    snapshot('wheel-phone-normal', phone, 'Incoming call with normal wheel ownership', None)
    phone.set_control_mode(True)
    # The complete first line is centered, including the fixed ownership glyph.
    def phone_icon():
        text, flags = phone.get_view()['line1']
        width = phone.text_width(text, flags)
        return [max(0, (128 - width) // 2), 2, 12, 18]
    snapshot('wheel-phone-accept', phone, 'Wheel ownership active; Accept selected', phone_icon())
    phone.handle_input('next')
    snapshot('wheel-phone-reject', phone, 'Rotate down to select Reject', phone_icon())
    phone.update_hudiy(b'HUDIY_PHONE', {**phone_input, 'state': 'ACTIVE'})
    snapshot('wheel-phone-end', phone, 'Separate active-call example; End Call selected', phone_icon())

    sources = ['dis_client/apps/readings.py', 'dis_client/apps/phone.py', 'dis_client/icons.py',
               'dis_client/readings_assets.py', 'rns-e_can/wheel_controls.py',
               'dis_emulator/static/native_font_data.js', 'help-site/scripts/render_dis.py']
    manifest['source_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}
    (OUT / 'wheel-provenance.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Rendered {len(manifest["assets"])} wheel examples')


if __name__ == '__main__':
    main()
