import copy
import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rns-e_can'))
sys.path.insert(0, str(ROOT / 'dis_client'))
from wheel_controls import WheelControlRouter
from dis_client.apps.readings import LogControlClient, ReadingsApp, convert_unit
from vehicle_data.workspace import default_workspace


class WheelControlsTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.events, self.normal = [], []
        self.router = WheelControlRouter(lambda *event: self.events.append(event),
            self.normal.append, clock=lambda: self.now, auto_phone=True)
        self.router.context('app_car_info', True)

    def click(self, button='mode'):
        self.router.handle(button)
        self.router.handle('release')

    def double(self, button='mode'):
        self.click(button)
        self.now += .1
        self.click(button)

    def test_single_mode_delayed_double_consumes_both_clicks(self):
        self.click()
        self.assertEqual(self.normal, [])
        self.now += .4
        self.router.tick()
        self.assertEqual(self.normal, ['mode_short'])
        self.normal.clear()
        self.double()
        self.now += .4
        self.router.tick()
        self.assertEqual(self.normal, [])
        self.assertEqual(self.router.owner, 'dis')
        self.double()
        self.assertEqual(self.router.owner, 'normal')

    def test_held_frames_scroll_releases_and_click_double_back(self):
        self.double()
        self.events.clear()
        for _ in range(3):
            self.router.handle('scroll_down')
        self.assertEqual([e[0] for e in self.events], ['next'])
        self.router.handle('release')
        self.router.handle('scroll_down')
        self.assertEqual([e[0] for e in self.events], ['next', 'next'])
        self.router.handle('release')
        self.double('click')
        self.assertEqual(self.events[-1][0], 'back')
        self.click('click')
        self.now += .4
        self.router.tick()
        self.assertEqual(self.events[-1][0], 'select')

    def test_normal_wheel_click_remains_immediate_and_long_does_not_short(self):
        self.click('click')
        self.assertEqual(self.normal, ['scroll_click_short'])
        self.normal.clear()
        for _ in range(9):
            self.router.handle('mode')
        self.router.handle('release')
        self.now += .5
        self.router.tick()
        self.assertEqual(self.normal, ['mode_long'])

    def test_second_press_inside_window_can_release_after_deadline(self):
        self.click()
        self.now += .25
        self.router.handle('mode')
        self.now += .11
        self.router.tick()
        self.assertEqual(self.normal, [])
        self.now += .04
        self.router.handle('release')
        self.assertEqual(self.router.owner, 'dis')
        self.assertEqual(self.normal, [])
        # Wheel back uses the same gesture timing once DIS owns the wheel.
        self.click('click')
        self.now += .25
        self.router.handle('click')
        self.now += .15
        self.router.handle('release')
        self.assertEqual(self.events[-1][0], 'back')
        self.assertNotIn('select', [event[0] for event in self.events])

    def test_second_press_after_window_is_two_singles(self):
        self.click()
        self.now += .4
        self.click()
        self.now += .4
        self.router.tick()
        self.assertEqual(self.normal, ['mode_short', 'mode_short'])
        self.assertEqual(self.router.owner, 'normal')

    def test_holding_second_press_does_not_emit_first_short_or_toggle(self):
        self.click()
        self.now += .25
        for _ in range(5):
            self.router.handle('mode')
            self.now += .05
        self.router.handle('release')
        self.now += .4
        self.router.tick()
        self.assertEqual(self.normal, ['mode_long'])
        self.assertEqual(self.router.owner, 'normal')

    def test_page_change_or_timeout_drops_owner_and_pending_select(self):
        self.double()
        self.click('click')
        self.router.context('app_media', True)
        self.now += .5
        self.router.tick()
        self.assertEqual(self.router.owner, 'normal')
        self.assertNotIn('select', [e[0] for e in self.events])
        self.router.context('app_car_info', True)
        self.double()
        self.now += 4
        self.router.tick()
        self.assertEqual(self.router.owner, 'normal')
        self.router.handle('scroll_up')
        self.assertEqual(self.normal[-1], 'scroll_up')

    def test_same_app_reentry_is_a_new_context_and_cancels_pending_gesture(self):
        self.router.context('app_car_info', True, context_id=1)
        self.double()
        self.click('click')
        self.router.context('app_car_info', True, context_id=3)
        self.now += .5
        self.router.tick()
        self.assertEqual(self.router.owner, 'normal')
        self.assertNotIn('select', [e[0] for e in self.events])

    def test_phone_auto_uses_manual_override_until_call_end_and_app_exit(self):
        self.router.phone(True)
        self.router.context('app_phone', True)
        self.assertEqual(self.router.owner, 'dis')
        self.double()
        self.router.phone(True)
        self.router.context('app_phone', True)
        self.assertEqual(self.router.owner, 'normal')
        self.router.phone(False)
        self.router.phone(True)
        self.assertEqual(self.router.owner, 'dis')
        self.router.context('app_car_info', True)
        self.router.context('app_phone', True)
        self.assertEqual(self.router.owner, 'normal')
        self.double()
        self.assertEqual(self.router.owner, 'dis')

    def test_top_only_phone_shares_authority_and_center_phone_has_priority(self):
        self.router.context('app_media', True, controllable=False)
        self.router.phone(True)
        self.router.top_context(True)
        self.assertEqual(self.router.owner, 'dis')
        self.assertEqual(self.events[-1][2], 'app_phone_top')
        self.router.handle('scroll_down')
        self.assertEqual(self.events[-1], ('next', 'dis', 'app_phone_top'))
        self.router.handle('release')
        self.router.context('app_phone', True)
        self.assertEqual(self.events[-1], ('mode', 'dis', 'app_phone'))
        self.double()
        self.router.top_context(True)
        self.assertEqual(self.router.owner, 'normal')

    def test_manual_readings_ownership_beats_top_phone_and_stalk_exit_suppresses_auto(self):
        self.double()
        self.router.phone(True)
        self.router.top_context(True)
        self.assertEqual(self.router.target, 'center')
        self.router.context('app_media', True, controllable=False)
        self.router.top_context(True)
        self.assertEqual(self.router.owner, 'normal')
        self.router.phone(False)
        self.router.phone(True)
        self.assertEqual(self.router.target, 'top')
        self.assertEqual(self.router.owner, 'dis')
        self.router.context('app_media', True, controllable=False)
        self.now += 3.1
        self.router.tick()
        self.assertEqual(self.router.owner, 'normal')


class ReadingsTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.doc = default_workspace()
        self.commands = []
        self.logger = SimpleNamespace(recording={'recording': False}, error=None,
            tick=lambda: None, command=lambda cmd, **args: self.commands.append((cmd, args)))
        self.app = ReadingsApp(workspace=SimpleNamespace(load=lambda: copy.deepcopy(self.doc)),
            logger_client=self.logger, clock=lambda: self.now)
        self.app.on_enter()

    def publish(self, vid, value, **fields):
        self.app.update_hudiy(b'HUDIY_VALUES', {'client_id': 'dis_display',
            'values': [{'id': vid, 'value': value, 'status': 'ok', 'age_ms': 0,
                        'max_age_ms': 1000, **fields}]})

    def value_text(self, index=0):
        return next(i['text'] for i in self.app.get_view() if i.get('group') == 'value:' + str(index))

    def test_native_four_digit_centering_and_expiry_without_new_sample(self):
        vid = self.app.page['slots'][0]['value_id']
        self.publish(vid, 7200)
        self.assertEqual(self.value_text(), '7200')
        number = next(i for i in self.app.get_view() if i.get('group') == 'value:0')
        self.assertEqual(number['flags'], 6)
        self.assertGreaterEqual(number['x'] * 2, 12)
        self.assertLessEqual(number['x'] * 2 + self.app.text_width('7200', 6), 52)
        self.now += 1.1
        self.assertEqual(self.value_text(), '--')

    def test_dynamic_numbers_never_change_static_bitmap(self):
        vid = self.app.page['slots'][0]['value_id']
        self.publish(vid, 880)
        first = self.app.get_view()
        self.publish(vid, 7200)
        second = self.app.get_view()
        bitmaps = lambda view: [item for item in view if item.get('cmd') == 'native_bitmap']
        self.assertEqual(bitmaps(first), bitmaps(second))
        self.assertEqual(len([i for i in second if str(i.get('group', '')).startswith('value:')]), 8)
        self.assertTrue(all(i['cmd'] == 'draw_text' for i in second if str(i.get('group', '')).startswith('value:')))

    def test_configuration_error_recovers_without_stopping_the_dis(self):
        state = [ValueError('Corrupt JSON')]
        def load():
            if isinstance(state[0], Exception):
                raise state[0]
            return state[0]
        app = ReadingsApp(workspace=SimpleNamespace(load=load), logger_client=self.logger,
                          clock=lambda: self.now)
        self.assertTrue(app.value_requests)
        self.assertEqual(app.config_error, 'Config error')
        self.assertEqual(next(i['text'] for i in app.get_view() if i.get('group')=='page'), 'Cfg err')
        state[0] = default_workspace()
        self.now += 1.1
        app.get_view()
        self.assertIsNone(app.config_error)

    def test_restricted_provider_opt_ins_are_explicit_and_merge_duplicate_slots(self):
        slots = self.app.page['slots']
        slots[0].update(value_id='awd.estimated_torque', allow_estimated=True)
        slots[1].update(value_id='awd.estimated_torque', allow_unverified=True)
        requests = self.app.value_requests
        requested = [r for r in requests if isinstance(r, dict) and r['id']=='awd.estimated_torque']
        self.assertEqual(requested, [{'id':'awd.estimated_torque',
            'allow_estimated':True, 'allow_unverified':True}])
        self.assertEqual(len(requests), 7)
        slots[0].pop('allow_estimated')
        slots[1].pop('allow_unverified')
        self.assertIn('awd.estimated_torque', self.app.value_requests)

    def test_unit_conversion_zero_unavailable_and_wrong_client(self):
        slot = self.doc['dis_pages'][0]['slots'][0]
        slot.update(value_id='engine.oil_temperature', unit='°F')
        self.app.tick()
        self.publish(slot['value_id'], 100, unit='C')
        self.assertEqual(self.value_text(), '212')
        self.publish(slot['value_id'], 0, unit='C')
        self.assertEqual(self.value_text(), '32')
        self.publish(slot['value_id'], 10, status='unavailable')
        self.assertEqual(self.value_text(), '--')
        self.app.update_hudiy(b'HUDIY_VALUES', {'client_id':'other',
            'values':[{'id':slot['value_id'], 'value':99, 'status':'ok'}]})
        self.assertEqual(self.value_text(), '--')
        self.assertAlmostEqual(convert_unit(2000, 'mbar', 'bar'), 2)
        self.assertRaises(ValueError, convert_unit, 1, 'bar', '°F')

    def test_subpage_edit_commit_back_and_logger_share_selected_profile(self):
        alternate = copy.deepcopy(self.doc['dis_pages'][0])
        alternate.update(id='temps', name='Temps', profile_id='temperatures')
        self.doc['dis_pages'].append(alternate)
        self.app.tick()
        self.app.set_control_mode(True)
        self.app.handle_input('select')
        self.app.handle_input('next')
        self.assertEqual(self.app.page_id, 'temps')
        self.app.handle_input('back')
        self.assertEqual(self.app.page_id, 'daily')
        self.app.handle_input('select')
        self.app.handle_input('next')
        self.app.handle_input('select')
        self.assertTrue(self.app.control_mode)
        self.app.handle_input('next')
        self.app.handle_input('select')
        self.assertEqual(self.commands[-1], ('START', {'profile_id': 'temperatures'}))
        self.logger.recording['recording'] = True
        self.app.handle_input('select')
        self.assertEqual(self.commands[-1][0], 'STOP')
        self.app.handle_input('next')
        self.app.handle_input('select')
        self.assertEqual(self.commands[-1][0], 'MARK')
        self.app.set_control_mode(False)
        self.app.handle_input('select')
        self.assertEqual(self.commands[-1][0], 'MARK')

    def test_native_controls_and_bounded_focus_follow_recording_state(self):
        from icons import encode_audscii
        fields = lambda: {i['group']: i for i in self.app.get_view() if i.get('cmd') == 'draw_text'}
        idle = fields()
        self.assertEqual(encode_audscii(idle['log-toggle']['text']), b'\x69')
        self.assertEqual(idle['log-marker']['text'], '')
        self.assertEqual(idle['control-mode']['text'], '')
        self.assertFalse(any(i['flags'] & 0x80 for i in idle.values()))
        self.app.set_control_mode(True)
        controlled = fields()
        self.assertEqual(controlled['page']['flags'], 0x86)
        self.assertEqual(controlled['page']['highlight_width'],
                         self.app.text_width(controlled['page']['text'], 6) // 2)
        self.assertEqual(encode_audscii(controlled['control-mode']['text']), b'\x15')
        self.assertEqual(controlled['control-mode']['flags'], 2)
        for item in controlled.values():
            if item['flags'] & 0x80:
                self.assertLessEqual(item['highlight_width'] * 2,
                                     self.app.text_width(item['text'], item['flags']) + 1)
        self.app.handle_input('next')
        self.assertEqual(fields()['log-toggle']['flags'], 0x82)
        self.assertEqual(fields()['log-toggle']['highlight_width'], 4)
        self.assertEqual(fields()['log-toggle']['highlight_height'], 7)
        self.app.handle_input('next')
        self.assertEqual(self.app.focus, 0)  # No marker when idle.
        self.logger.recording['recording'] = True
        running = fields()
        self.assertEqual(encode_audscii(running['log-toggle']['text']), b'\xab')
        self.assertEqual(encode_audscii(running['log-marker']['text']), b'\xdf')
        self.app.handle_input('next')
        self.app.handle_input('select')
        self.assertEqual(self.commands[-1][0], 'STOP')
        self.assertEqual(fields()['log-toggle']['highlight_width'], 5)
        self.assertEqual(fields()['log-toggle']['highlight_height'], 7)
        self.app.handle_input('next')
        self.app.handle_input('select')
        self.assertEqual(self.commands[-1][0], 'MARK')
        self.assertEqual(fields()['log-marker']['flags'], 0x82)
        self.logger.recording['recording'] = False
        stopped = fields()
        self.assertEqual(self.app.focus, 1)
        self.assertEqual(stopped['log-marker']['text'], '')
        self.assertFalse(any(i.get('cmd') == 'draw_line' for i in self.app.get_view()))


class KeyboardRawFrameTests(unittest.TestCase):
    def test_old_config_double_mode_publishes_dis_control_and_input_without_rebinding(self):
        spec = importlib.util.spec_from_file_location('test_keyboard_old_config', ROOT / 'rns-e_can/can_keyboard_control.py')
        keyboard = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'uinput': SimpleNamespace()}):
            spec.loader.exec_module(keyboard)
        cfg = json.loads((ROOT / 'config.json').read_text())
        cfg['input_mappings']['mfsw'].pop('double_click_ms', None)
        for key in ('input_control_stream', 'dis_top_status', 'dis_display_status'):
            cfg['interfaces']['zmq'].pop(key, None)
        cfg['input_mappings']['mfsw']['phone_alt'] = {
            'short_press': {'mode': 'KEY_P'}, 'long_press': {'mode': 'KEY_O'}}
        keyboard.parse_key = lambda key: key
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(cfg))
            self.assertTrue(keyboard.load_and_initialize_config(path))
        self.assertEqual(keyboard.CONFIG['wheel_double_click_ms'], 350)
        self.assertEqual(keyboard.CONFIG['zmq_display_status'],
                         'ipc:///run/rnse_control/dis_display_status.ipc')
        self.assertEqual(keyboard.CONFIG['mfsw_map']['mode_short'], 'KEY_ENTER')
        self.assertEqual(keyboard.CONFIG['mfsw_map']['mode_long'], 'KEY_ESC')
        keyboard.WHEEL_CONTEXT_ID = 99
        events, pressed, now = [], [], [10.0]
        keyboard.INPUT_PUB = SimpleNamespace(send_multipart=lambda parts, **kw:
            events.append((parts[0], json.loads(parts[1]))))
        keyboard.press_key = pressed.append
        state = keyboard.ControlState()
        state.wheel.clock = lambda: now[0]
        state.wheel.context('app_car_info', True, context_id=99)
        events.clear()
        def frame(command):
            keyboard.handle_mfsw_message({'dlc':2, 'data_hex':f'00{command:02x}'}, state)
        frame(0x1c)
        frame(0)
        now[0] += .25
        frame(0x1c)
        now[0] += .15
        frame(0)
        self.assertEqual(state.wheel.owner, 'dis')
        self.assertEqual(events[-1][0], b'WHEEL_CONTROL')
        self.assertEqual(events[-1][1]['owner'], 'dis')
        for _ in range(3):
            frame(0x0c)
        frame(0)
        frame(0x08)
        frame(0)
        now[0] += .4
        state.wheel.tick()
        inputs = [payload for topic, payload in events if topic == b'DIS_INPUT']
        self.assertEqual([item['event'] for item in inputs], ['next', 'select'])
        self.assertTrue(all(item['app'] == 'app_car_info' and item['control_epoch'] == 99
                            for item in inputs))
        self.assertEqual(pressed, [])

    def test_volume_is_normal_in_dis_mode_and_release_repeat_deduplicates(self):
        spec = importlib.util.spec_from_file_location('test_keyboard_isolated', ROOT / 'rns-e_can/can_keyboard_control.py')
        keyboard = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'uinput': SimpleNamespace()}):
            spec.loader.exec_module(keyboard)
        commands = {'scroll_up':11, 'scroll_down':12, 'scroll_click':8, 'mode_press':28,
                    'ptt_press':27, 'volume_scroll_up':15, 'volume_scroll_down':16,
                    'volume_scroll_click':10}
        keys = {key: key for key in ['scroll_up', 'scroll_down', 'scroll_click_short',
            'mode_short', 'volume_scroll_up_short', 'volume_scroll_click_short', 'volume_scroll_click_long']}
        keyboard.CONFIG = {'mfsw_cmds': commands, 'mfsw_map': keys,
            'long_press_count':5, 'mfsw_release_cmds':[0]}
        pressed = []
        keyboard.press_key = pressed.append
        state = keyboard.ControlState()
        state.wheel.context('app_car_info', True)
        state.wheel.toggle()
        def frame(command):
            keyboard.handle_mfsw_message({'dlc':2, 'data_hex':f'00{command:02x}'}, state)
        frame(15)
        frame(15)
        frame(0)
        frame(15)
        frame(0)
        self.assertEqual(pressed, ['volume_scroll_up_short'] * 2)
        for _ in range(8):
            frame(10)
        frame(0)
        self.assertEqual(pressed[-1], 'volume_scroll_click_long')
        self.assertNotIn('volume_scroll_click_short', pressed)
        frame(12)
        frame(12)
        frame(0)
        self.assertNotIn('scroll_down', pressed)


class LoggerControlTests(unittest.TestCase):
    def test_start_response_and_offline_timeout_are_nonblocking(self):
        import zmq
        import uuid
        address = 'inproc://dis-logger-' + uuid.uuid4().hex
        server = zmq.Context.instance().socket(zmq.REP)
        server.bind(address)
        now = [0.0]
        client = LogControlClient({'interfaces':{'zmq':{'data_logs_command':address}}}, lambda:now[0])
        try:
            client.command('START', profile_id='daily')
            client.tick()
            self.assertTrue(server.poll(100))
            self.assertEqual(server.recv_json(), {'cmd':'START', 'profile_id':'daily'})
            server.send_json({'status':'ok', 'recording':{'recording':True, 'profile_id':'daily'}})
            client.tick()
            self.assertTrue(client.recording['recording'])
            now[0] += 1.1
            client.tick()
            self.assertTrue(server.poll(100))
            self.assertEqual(server.recv_json(), {'cmd':'STATUS'})
            now[0] += 1.1
            client.tick()
            self.assertEqual(client.error, 'Logger offline')
            self.assertTrue(client.recording['recording'])
        finally:
            client.close()
            server.close(0)


class TopPhoneRoutingTests(unittest.TestCase):
    def test_only_matching_target_epoch_can_act_and_mode_indicator_clears(self):
        import time
        tree = ast.parse((ROOT / 'dis_client/dis_top_display_service.py').read_text(encoding='utf8'))
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                        and node.name == '_handle_wheel_control')
        namespace = {'time': time}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'topdisplay', 'exec'), namespace)
        actions, modes = [], []
        top = SimpleNamespace(_top_control_epoch=4, _top_ready=True, _phone_control_mode=False,
            _phone_controls=SimpleNamespace(set_control_mode=modes.append, handle_input=actions.append, action_idx=1),
            _last_phone_data={}, _phone_fields=lambda data: ('caller', 'state'), _resolve=lambda: None)
        handle = lambda topic, data: namespace['_handle_wheel_control'](top, topic, data)
        handle(b'WHEEL_CONTROL', {'app':'app_phone_top', 'owner':'dis', 'control_epoch':4})
        self.assertTrue(top._phone_control_mode)
        for app, epoch in [('app_phone',4), ('app_phone_top',3), ('app_phone_top',4)]:
            handle(b'DIS_INPUT', {'app':app, 'owner':'dis', 'control_epoch':epoch, 'event':'select'})
        self.assertEqual(actions, ['select'])
        handle(b'WHEEL_CONTROL', {'app':'app_phone', 'owner':'dis', 'control_epoch':4})
        self.assertFalse(top._phone_control_mode)
        self.assertEqual(modes, [True, False])


if __name__ == '__main__':
    unittest.main()
