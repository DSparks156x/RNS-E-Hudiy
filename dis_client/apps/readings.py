"""Configurable eight-value DIS page using native text for every changing field."""
import json
import math
import time
from collections import deque

from .base import BaseApp
try:
    from ..readings_assets import static_layer
except ImportError:
    from readings_assets import static_layer
from vehicle_data.catalog import CATALOG
from vehicle_data.workspace import WorkspaceStore, default_workspace
try:
    from ..icons import WHEEL_CONTROL_GLYPH
except ImportError:
    from icons import WHEEL_CONTROL_GLYPH


class LogControlClient:
    """Nonblocking logger RPC; unavailable services must not stall DIS rendering."""
    def __init__(self, config, clock=time.monotonic):
        self.address = config.get('interfaces', {}).get('zmq', {}).get(
            'data_logs_command', 'ipc:///run/rnse_control/data_logs_cmd.ipc')
        self.clock = clock
        self.socket = None
        self.pending = None
        self.queue = deque()
        self.last_status = -10
        self.recording = {'recording': False}
        self.error = None

    def command(self, cmd, **fields):
        if len(self.queue) < 4:
            self.queue.append({'cmd': cmd, **fields})

    def _reset(self):
        if self.socket is not None:
            self.socket.close(0)
        self.socket = None
        self.pending = None

    def tick(self):
        import zmq
        now = self.clock()
        try:
            if self.pending is not None:
                if self.socket.poll(0):
                    reply = self.socket.recv_json(flags=zmq.NOBLOCK)
                    self.pending = None
                    if not isinstance(reply, dict):
                        raise ValueError('Malformed logger response')
                    if isinstance(reply.get('recording'), dict):
                        self.recording = reply['recording']
                    self.error = reply.get('message') if reply.get('status') != 'ok' else None
                elif now - self.pending > 1.0:
                    self.error = 'Logger offline'
                    self._reset()
                else:
                    return
            if not self.queue and now - self.last_status < 1.0:
                return
            if self.socket is None:
                self.socket = zmq.Context.instance().socket(zmq.REQ)
                self.socket.setsockopt(zmq.LINGER, 0)
                self.socket.connect(self.address)
            message = self.queue.popleft() if self.queue else {'cmd': 'STATUS'}
            self.last_status = now
            self.socket.send_json(message, flags=zmq.NOBLOCK)
            self.pending = now
        except (zmq.ZMQError, ValueError, TypeError):
            self.error = 'Logger offline'
            self._reset()

    def close(self):
        self._reset()


def convert_unit(value, source, target):
    """Conversions preserve dimensions; unrelated/catalog-reported units stay raw."""
    aliases = {'°C': 'C', '°F': 'F', '°': 'deg', 'kph': 'km/h'}
    source, target = aliases.get(source, source), aliases.get(target, target)
    if target == source or not target:
        return value
    if source == 'C' and target == 'F':
        return value * 1.8 + 32
    if source == 'F' and target == 'C':
        return (value - 32) / 1.8
    scales = ({'mbar': .001, 'bar': 1, 'kPa': .01, 'psi': .0689475729},
              {'km/h': 1, 'mph': 1.609344}, {'km': 1, 'mi': 1.609344},
              {'A': 1, 'mA': .001}, {'s': 1, 'ms': .001, 'min': 60})
    for group in scales:
        if source in group and target in group:
            return value * group[source] / group[target]
    raise ValueError('Incompatible units')


class ReadingsApp(BaseApp):
    def __init__(self, config=None, *, workspace=None, logger_client=None, clock=time.monotonic):
        super().__init__(config)
        self.clock = clock
        self.workspace = workspace or WorkspaceStore(self.config)
        self.logger = logger_client or LogControlClient(self.config, clock)
        self.config_error = None
        try:
            self.document = self.workspace.load()
        except (OSError, ValueError, KeyError):
            self.document = default_workspace()
            self.config_error = 'Config error'
        self.page_id = self.document['dis_pages'][0]['id']
        self.focus = 0
        self.edit_page = False
        self.original_page = None
        self.control_mode = False
        self.values = {}
        self.last_config_check = -10

    @property
    def page(self):
        return next((p for p in self.document['dis_pages'] if p['id'] == self.page_id),
                    self.document['dis_pages'][0])

    @property
    def value_requests(self):
        requests = {}
        for slot in self.page['slots']:
            vid = slot.get('value_id')
            if not vid:
                continue
            spec = requests.setdefault(vid, {'id': vid})
            for permission in ('allow_estimated', 'allow_unverified'):
                if slot.get(permission) is True:
                    spec[permission] = True
        return [spec if len(spec) > 1 else spec['id'] for spec in requests.values()]

    def on_enter(self):
        super().on_enter()
        self.control_mode = False
        self.edit_page = False
        self.focus = 0
        self.last_config_check = -10

    def on_leave(self):
        super().on_leave()
        self.set_control_mode(False)

    def set_control_mode(self, active):
        if not active and self.edit_page and self.original_page:
            self.page_id = self.original_page
        self.control_mode = bool(active)
        if not active:
            self.edit_page = False
            self.focus = 0

    def tick(self):
        self.logger.tick()
        now = self.clock()
        if now - self.last_config_check >= 1.0:
            self.last_config_check = now
            try:
                document = self.workspace.load()
                if document != self.document:
                    self.document = document
                    if not any(p['id'] == self.page_id for p in document['dis_pages']):
                        self.page_id = document['dis_pages'][0]['id']
                    self.edit_page = False
                    self.focus = 0
                self.config_error = None
            except (OSError, ValueError, KeyError):
                self.config_error = 'Config error'

    def update_hudiy(self, topic, payload):
        if topic == b'HUDIY_VALUES' and payload.get('client_id') in (None, 'dis_display'):
            for sample in payload.get('values', []):
                if sample.get('id'):
                    self.values[sample['id']] = (sample, self.clock())

    @property
    def actions(self):
        return ['page', 'stop', 'mark'] if self.logger.recording.get('recording') else ['page', 'start']

    def handle_input(self, action):
        if not self.control_mode:
            return None
        if action in ('previous', 'next', 'scroll_up', 'scroll_down'):
            delta = -1 if action in ('previous', 'scroll_up') else 1
            if self.edit_page:
                pages = self.document['dis_pages']
                index = next(i for i, p in enumerate(pages) if p['id'] == self.page_id)
                self.page_id = pages[(index + delta) % len(pages)]['id']
            else:
                self.focus = (self.focus + delta) % len(self.actions)
        elif action in ('select', 'scroll_click'):
            if self.edit_page:
                self.edit_page = False
                self.original_page = None
                return True
            selected = self.actions[min(self.focus, len(self.actions) - 1)]
            if selected == 'page':
                self.original_page = self.page_id
                self.edit_page = True
            elif selected == 'start':
                self.logger.command('START', profile_id=self.page.get('profile_id'))
            elif selected == 'mark':
                self.logger.command('MARK', note='DIS ' + self.page['name'])
            elif selected == 'stop':
                self.logger.command('STOP')
        elif action == 'back':
            if self.edit_page:
                self.page_id = self.original_page
                self.edit_page = False
                self.original_page = None
            else:
                self.focus = 0
        return True

    def _reading(self, slot):
        vid = slot['value_id']
        sample, received = self.values.get(vid, ({}, self.clock()))
        source = sample.get('unit') or CATALOG.get(vid, {}).get('unit') or ''
        target = slot.get('unit') or source
        flags = 2 if slot.get('font') == 'fixed' else 6
        age, maximum = sample.get('age_ms'), sample.get('max_age_ms')
        stale = False
        if age is not None and maximum is not None:
            try:
                stale = (not math.isfinite(float(age)) or not math.isfinite(float(maximum))
                         or float(age) + (self.clock() - received) * 1000 > float(maximum))
            except (ValueError, TypeError):
                stale = True
        if sample.get('status') != 'ok' or stale or sample.get('value') is None:
            return '--', flags, target
        value = sample['value']
        if isinstance(value, bool):
            text = 'On' if value else 'Off'
        elif isinstance(value, (int, float)):
            try:
                value = convert_unit(float(value), source, target)
                if not math.isfinite(value):
                    raise ValueError('Nonfinite sample')
                precision = slot.get('precision', 0)
                text = f'{value:.{precision}f}'
                if self.text_width(text, flags) > 40:
                    flags = 6
                while self.text_width(text, flags) > 40 and precision > 0:
                    precision -= 1
                    text = f'{value:.{precision}f}'
            except (ValueError, TypeError, OverflowError):
                text = '--'
        else:
            text = str(value)
            flags = 6
        if self.text_width(text, flags) > 40:
            # Never clip a neighbor or truncate a number into a different value.
            text = '--'
        return text, flags, target

    def get_view(self):
        self.tick()
        readings = [self._reading(slot) for slot in self.page['slots']]
        recording = bool(self.logger.recording.get('recording'))
        self.focus = min(self.focus, len(self.actions) - 1)
        view = [{'type': 'readings:' + self.page_id, 'clear_on_update': False}]
        focused = self.actions[self.focus] if self.control_mode else None
        view.append({'group': 'static', 'cmd': 'native_bitmap', 'render_order': 'planes',
                     'data_hex': static_layer(self.page['slots'], [r[2] for r in readings],
                         None, False, False, False).hex()})
        control_bits = static_layer([], [], None, False, False, recording).hex()
        view.append({'group': 'record-indicator', 'cmd': 'native_bitmap', 'render_order': 'planes',
                     'update_rect': [70, 6, 2, 2], 'preserves_overlays': True, 'data_hex': control_bits})
        name = 'Cfg err' if self.config_error else self.page['name']
        if self.logger.error:
            name = 'Log off' if self.logger.error == 'Logger offline' else 'Log err'
        name = self.fit_text(name, 68, 6).rstrip()
        view.append({'group': 'page', 'cmd': 'draw_text', 'text': name,
                     'x': 0, 'y': 0, 'flags': 0x86 if focused == 'page' else 6,
                     'highlight_width': max(1, math.ceil(self.text_width(name, 6) / 2))})
        # Stable fields keep native focus changes bounded, with no bitmap text.
        toggle = 'stop' if recording else 'start'
        view.append({'group': 'log-toggle', 'cmd': 'draw_text', 'text': '□' if recording else '▶',
                     'x': 38, 'y': 0, 'flags': 0x82 if focused == toggle else 2,
                     # Captured ink is10px for AB,8px for69; omit font bearings.
                     'highlight_width': 5 if recording else 4, 'highlight_height': 7})
        view.append({'group': 'log-marker', 'cmd': 'draw_text', 'text': '⚑' if recording else '',
                     'x': 48, 'y': 0, 'flags': 0x82 if focused == 'mark' else 2,
                     'highlight_width': math.ceil(self.text_width('⚑', 2) / 2), 'highlight_height': 7})
        view.append({'group': 'control-mode', 'cmd': 'draw_text', 'text': WHEEL_CONTROL_GLYPH if self.control_mode else '',
                     'x': 58, 'y': 0, 'flags': 2,
                     'highlight_width': 6})
        for index, (text, flags, unit) in enumerate(readings):
            x = (index % 2) * 64 + 12 + ((40 - self.text_width(text, flags)) // 4) * 2
            view.append({'group': 'value:' + str(index), 'cmd': 'draw_text', 'text': text,
                         'x': x // 2, 'y': 12 + (index // 2) * 9, 'flags': flags})
        return view
