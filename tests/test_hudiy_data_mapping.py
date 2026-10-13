"""Hudiy API -> ZMQ mapping in hudiy_client/hudiy_data.py, with real Hudiy protobufs.

hudiy_client/api_files/common is not checked in (see its README), so the
module is loaded against the upstream copy in references/hudiy references/
(Api.proto, Api_pb2.py, Client.py). Using real proto2 messages matters: an
absent optional enum reads back as its first value (LEFT, ACTIVE, ...), which
is exactly what the HasField() guards in hudiy_data.py exist for.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'references' / 'hudiy references' / 'hudiy-main'
UPSTREAM_COMMON = UPSTREAM / 'examples' / 'api' / 'python' / 'common'
sys.path.insert(0, str(ROOT))

from flasher import traffic  # noqa: E402


def load_hudiy_data():
    common = types.ModuleType('common')
    common.__path__ = [str(UPSTREAM_COMMON)]
    # Left registered on purpose: dropping a generated *_pb2 module from
    # sys.modules lets GC free state the upb backend still uses (segfault on
    # the next message construction under protobuf 7). Replaces the empty
    # namespace package hudiy_client/api_files/common if a test imported it.
    if not hasattr(sys.modules.get('common'), 'Api_pb2'):
        for name in [n for n in sys.modules if n == 'common' or n.startswith('common.')]:
            del sys.modules[name]
        sys.modules['common'] = common
    saved_path = list(sys.path)
    sys.path.insert(0, str(ROOT / 'hudiy_client'))
    try:
        spec = importlib.util.spec_from_file_location(
            'hudiy_data_under_test', ROOT / 'hudiy_client' / 'hudiy_data.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        api = sys.modules['common.Api_pb2']
    finally:
        sys.path[:] = saved_path
    return module, api


HD, API = load_hudiy_data()


def proto_enum(name):
    """{number: NAME} for an enum in references/.../api/Api.proto (spec text)."""
    text = (UPSTREAM / 'api' / 'Api.proto').read_text(encoding='utf-8')
    body = re.search(r'enum\s+%s\s*\{([^}]*)\}' % name, text).group(1)
    return {int(v): k for k, v in re.findall(r'(\w+)\s*=\s*(\d+)\s*;', body)}


class Publisher:
    def __init__(self):
        self.items = []

    def publish(self, topic, data):
        self.items.append((topic, json.loads(json.dumps(data))))
        return True

    def last(self, topic):
        return [d for t, d in self.items if t == topic][-1]


class EnumMapTests(unittest.TestCase):
    def test_media_sources_match_api_proto(self):
        spec = proto_enum('MediaSource')
        self.assertEqual(set(HD.MEDIA_SOURCE_MAP), set(spec))
        self.assertEqual(HD.MEDIA_SOURCE_MAP[1], 'Android')
        self.assertEqual(spec[2], 'MEDIA_SOURCE_AUTOBOX')
        self.assertEqual(HD.MEDIA_SOURCE_MAP[2], 'CarPlay')
        self.assertEqual(spec[3], 'MEDIA_SOURCE_A2DP')
        self.assertEqual(HD.MEDIA_SOURCE_MAP[3], 'Bluetooth')

    def test_phone_states_match_api_proto(self):
        self.assertEqual(
            {k: v.rsplit('_', 1)[-1] for k, v in proto_enum('PhoneVoiceCallState').items()},
            {0: 'NONE', 1: 'INCOMING', 2: 'ALERTING', 3: 'ACTIVE'})
        self.assertEqual(HD.CALL_STATE_MAP, {0: 'IDLE', 1: 'INCOMING', 2: 'ALERTING', 3: 'ACTIVE'})
        self.assertEqual({k: v.rsplit('_', 1)[-1] for k, v in proto_enum('PhoneConnectionState').items()},
                         HD.CONN_STATE_MAP)

    def test_navigation_enums_match_api_proto(self):
        self.assertEqual(set(HD.MANEUVER_TYPE_MAP), set(proto_enum('NavigationManeuverType')))
        self.assertEqual({k: v.lower() for k, v in proto_enum('NavigationManeuverSide').items()},
                         {**{k: v for k, v in HD.MANEUVER_SIDE_MAP.items() if v}, 3: 'unspecified'})
        nav_sources = proto_enum('NavigationSource')
        self.assertEqual(nav_sources[1], 'NAVIGATION_SOURCE_ANDROID_AUTO')
        self.assertEqual(nav_sources[2], 'NAVIGATION_SOURCE_AUTOBOX')
        self.assertEqual(HD.PROJECTION_PROVIDER_MAP, {1: 'android_auto', 2: 'carplay'})


class HandlerTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {'HOME': tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.pub = Publisher()
        self.handler = HD.HudiyEventHandler(self.pub)
        self.addCleanup(self.handler.stop)
        self.client = Mock(_name='DATA')
        # Handlers also mirror state to /tmp/*.json for debugging; keep that private.
        real_open = open
        self.tmpdir = tmpdir = Path(tmp.name)
        mirrors = {'/tmp/now_playing.json', '/tmp/current_nav.json', '/tmp/current_call.json'}

        def private_open(path, *args, **kwargs):
            if path in mirrors:
                path = str(tmpdir / Path(path).name)
            return real_open(path, *args, **kwargs)
        patcher = patch('builtins.open', private_open)
        patcher.start()
        self.addCleanup(patcher.stop)


class PhoneTests(HandlerTestCase):
    def test_call_lifecycle(self):
        connected = API.PhoneConnectionStatus(state=1, name='Pixel')
        self.handler.on_phone_connection_status(self.client, connected)
        self.assertEqual(self.pub.last(b'HUDIY_PHONE')['connection_state'], 'CONNECTED')

        call = API.PhoneVoiceCallStatus(state=1, caller_id='+4930123', caller_name='Mum')
        self.handler.on_phone_voice_call_status(self.client, call)
        phone = self.pub.last(b'HUDIY_PHONE')
        self.assertEqual((phone['state'], phone['call_active'], phone['caller_name']),
                         ('INCOMING', True, 'Mum'))

        self.handler.on_phone_voice_call_status(
            self.client, API.PhoneVoiceCallStatus(state=0, caller_id='', caller_name=''))
        phone = self.pub.last(b'HUDIY_PHONE')
        self.assertEqual((phone['state'], phone['call_active'], phone['caller_name']),
                         ('IDLE', False, ''))

    def test_battery_uses_the_api_field_name_bettery_level(self):
        # Api.proto really spells it "bettery_level" (0..5).
        levels = API.PhoneLevelsStatus(bettery_level=4, signal_level=80)
        self.handler.on_phone_levels_status(self.client, levels)
        phone = self.pub.last(b'HUDIY_PHONE')
        self.assertEqual((phone['battery'], phone['signal']), (4, 80))

    def test_disconnect_clears_call_and_levels(self):
        self.handler.on_phone_connection_status(self.client, API.PhoneConnectionStatus(state=1, name='Pixel'))
        self.handler.on_phone_levels_status(self.client, API.PhoneLevelsStatus(bettery_level=5, signal_level=90))
        self.handler.on_phone_voice_call_status(
            self.client, API.PhoneVoiceCallStatus(state=3, caller_id='1', caller_name='A'))
        self.handler.on_phone_connection_status(self.client, API.PhoneConnectionStatus(state=2, name='Pixel'))
        phone = self.pub.last(b'HUDIY_PHONE')
        self.assertEqual({k: phone[k] for k in ('connection_state', 'state', 'call_active', 'name', 'battery')},
                         {'connection_state': 'DISCONNECTED', 'state': 'IDLE', 'call_active': False,
                          'name': '', 'battery': 0})

    def test_absent_connection_state_is_disconnected(self):
        message = API.PhoneConnectionStatus()
        message.name = 'Pixel'
        self.assertEqual(message.state, 1, 'proto2 default for an absent enum is CONNECTED')
        self.handler.on_phone_connection_status(self.client, message)
        self.assertEqual(self.pub.last(b'HUDIY_PHONE')['connection_state'], 'DISCONNECTED')


class NavigationTests(HandlerTestCase):
    def status(self, state, source=2):
        self.handler.on_navigation_status(self.client, API.NavigationStatus(source=source, state=state))
        return self.pub.last(b'HUDIY_NAV_STATUS')

    def details(self, **fields):
        fields.setdefault('description', 'Turn right onto Main St')
        fields.setdefault('icon', b'')
        self.handler.on_navigation_maneuver_details(self.client, API.NavigationManeuverDetails(**fields))
        return self.pub.last(b'HUDIY_NAV')

    def test_route_becomes_active_only_with_status_and_content(self):
        self.assertFalse(self.status(1)['active'])            # ACTIVE, no maneuver yet
        nav = self.details(maneuver_type=4, maneuver_side=2, maneuver_angle=90)
        self.assertEqual(nav['maneuver_text'], 'Turn right')
        self.handler.on_navigation_maneuver_distance(self.client, API.NavigationManeuverDistance(label='300 m'))
        self.assertTrue(self.pub.last(b'HUDIY_NAV_STATUS')['active'])
        self.assertEqual(self.pub.last(b'HUDIY_NAV')['distance'], '300 m')
        status = self.status(2)                                # INACTIVE
        self.assertFalse(status['active'])
        self.assertEqual(self.pub.last(b'HUDIY_NAV'), {'has_route': False})

    def test_absent_optional_fields_are_not_read_as_proto_defaults(self):
        self.status(1)
        nav = self.details(maneuver_type=4)        # no side, no angle
        self.assertEqual(nav['maneuver_side'], 3)  # unspecified, not LEFT
        self.assertEqual(nav['maneuver_text'], 'Turn')
        self.assertFalse(nav['maneuver_angle_present'])

    def test_absent_state_is_inactive(self):
        message = API.NavigationStatus(source=2)
        self.assertEqual(message.state, 1, 'proto2 default for an absent enum is ACTIVE')
        self.handler.on_navigation_status(self.client, message)
        self.assertFalse(self.pub.last(b'HUDIY_NAV_STATUS')['api_active'])

    def test_provider_switch_drops_previous_route(self):
        self.status(1, source=1)
        self.details(maneuver_type=4, maneuver_side=1)
        self.handler.on_navigation_maneuver_distance(self.client, API.NavigationManeuverDistance(label='1 km'))
        self.assertTrue(self.pub.last(b'HUDIY_NAV_STATUS')['active'])
        status = self.status(1, source=2)
        self.assertFalse(status['has_route'])
        self.assertEqual(status['source'], 2)


class MediaTests(HandlerTestCase):
    def test_source_and_play_state(self):
        self.handler.on_media_status(self.client, API.MediaStatus(position_label='0:42', is_playing=True, source=2))
        media = self.pub.last(b'HUDIY_MEDIA')
        self.assertEqual((media['source_label'], media['playing'], media['media_state']),
                         ('CarPlay', True, 'PLAYING'))
        self.handler.on_media_status(self.client, API.MediaStatus(position_label='', is_playing=True, source=0))
        media = self.pub.last(b'HUDIY_MEDIA')
        self.assertEqual((media['playing'], media['media_state']), (False, 'NONE'))

    def test_bluetooth_metadata_and_cover_art_published_once(self):
        self.handler.on_media_status(self.client, API.MediaStatus(position_label='0:01', is_playing=True, source=3))
        png = self.tmpdir / 'c.png'
        Image.new('RGB', (64, 64), (200, 30, 30)).save(png)
        art = png.read_bytes()
        meta = API.MediaMetadata(artist='Artist', title='Song', album='LP', duration_label='3:00', coverart=art)
        self.handler.on_media_metadata(self.client, meta)
        self.handler.on_media_metadata(self.client, meta)   # same track refresh
        media = self.pub.last(b'HUDIY_MEDIA')
        self.assertEqual((media['artist'], media['title'], media['source_label']), ('Artist', 'Song', 'Bluetooth'))
        covers = [d for t, d in self.pub.items if t == b'HUDIY_COVERART']
        self.assertEqual(len(covers), 1)
        self.assertTrue(covers[0]['bitmap_hex'])
        self.assertTrue(covers[0]['is_new_track'])

    def test_resubscribe_requests_the_four_status_streams(self):
        self.handler.on_hello_response(self.client, API.HelloResponse(
            app_version=API.Version(major=1, minor=0), api_version=API.Version(major=1, minor=3), result=1))
        (message_id, flags, payload), _ = self.client.send.call_args
        self.assertEqual(message_id, API.MESSAGE_SET_STATUS_SUBSCRIPTIONS)
        request = API.SetStatusSubscriptions.FromString(payload)
        S = API.SetStatusSubscriptions.Subscription
        self.assertEqual(list(request.subscriptions), [S.Value('PROJECTION'), S.Value('MEDIA'),
                                                       S.Value('NAVIGATION'), S.Value('PHONE')])


class FlashingModeActionTests(HandlerTestCase):
    def setUp(self):
        super().setUp()
        self.bridge = HD.TP2BridgeHandler('ipc:///nonexistent', haldex_cmd_addr='ipc:///nonexistent')
        self.bridge.client = self.client
        self.bridge.toast_channel_id = 7
        self.bridge.flashing_icon_id = 9

    def sent(self, message_id, cls):
        return [cls.FromString(c.args[2]) for c in self.client.send.call_args_list
                if c.args[0] == message_id]

    def test_toggle_turns_tx_inhibit_on_and_shows_it(self):
        self.bridge.on_dispatch_action(self.client, API.DispatchAction(action='toggle_flashing_mode'))
        self.assertTrue(traffic.flashing_mode_enabled())
        icons = self.sent(API.MESSAGE_CHANGE_STATUS_ICON_STATE, API.ChangeStatusIconState)
        self.assertEqual([(i.id, i.visible) for i in icons], [(9, True)])
        toasts = self.sent(API.MESSAGE_SHOW_TOAST, API.ShowToast)
        self.assertEqual(toasts[-1].message, 'Flashing Mode On')
        self.bridge.on_dispatch_action(self.client, API.DispatchAction(action='toggle_flashing_mode'))
        self.assertFalse(traffic.flashing_mode_enabled())

    def test_cannot_turn_off_with_incomplete_flash(self):
        traffic.set_flashing_mode(True)
        marker = Path(os.environ['HOME']) / '.hudiy' / 'haldex_recovery_required.json'
        marker.write_text('{}')
        self.bridge.on_dispatch_action(self.client, API.DispatchAction(action='toggle_flashing_mode'))
        self.assertTrue(traffic.flashing_mode_enabled())
        toasts = self.sent(API.MESSAGE_SHOW_TOAST, API.ShowToast)
        self.assertIn('incomplete flash', toasts[-1].message)

    def test_unreadable_state_shows_inhibit_icon(self):
        with patch.object(HD, 'flashing_mode_enabled', side_effect=OSError('EIO')):
            self.bridge.update_flashing_icon_state()
        icons = self.sent(API.MESSAGE_CHANGE_STATUS_ICON_STATE, API.ChangeStatusIconState)
        self.assertEqual([(i.id, i.visible) for i in icons], [(9, True)])


if __name__ == '__main__':
    unittest.main()
