"""Bridge thread ownership and non-RGB cover processing regressions."""
import ast
import json
import logging
import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
import dis_image


def bridge_methods():
    tree = ast.parse((ROOT / 'dis_emulator/emulator_service.py').read_text(encoding='utf8'))
    bridge = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'EmulatorBridge')
    names = {'_publish', '_drain_publications', 'send_mock_can', 'send_mock_hudiy'}
    namespace = {'queue': queue, 'json': json, 'logger': logging.getLogger(__name__),
                 'zmq': SimpleNamespace(NOBLOCK=1, ZMQError=RuntimeError)}
    methods = [n for n in bridge.body if getattr(n, 'name', None) in names]
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'emulator_bridge', 'exec'), namespace)
    return type('Bridge', (), {name: namespace[name] for name in names})


class EmulatorPublicationTests(unittest.TestCase):
    def test_web_callbacks_only_enqueue_and_bridge_loop_owns_sends(self):
        bridge = bridge_methods()()
        bridge._publications = queue.SimpleQueue()
        bridge.pub_socket = Mock()
        bridge.hudiy_pub = Mock()
        bridge.status_pub = Mock()
        bridge.send_mock_can({'btn': 'up', 'state': 'pressed'})
        bridge.send_mock_hudiy({'topic': 'HUDIY_NAV', 'payload': {'has_route': False}})
        bridge._publish('status_pub', 'DIS_STATE PAUSED')
        for socket in (bridge.pub_socket, bridge.hudiy_pub, bridge.status_pub):
            self.assertEqual(socket.mock_calls, [])
        bridge._drain_publications()
        can_frames = bridge.pub_socket.send_multipart.call_args.args[0]
        self.assertEqual(can_frames[0], b'CAN_0x2C1')
        self.assertEqual(json.loads(can_frames[1])['data_hex'], '000020')
        nav_frames = bridge.hudiy_pub.send_multipart.call_args.args[0]
        self.assertEqual(nav_frames[0], b'HUDIY_NAV')
        self.assertEqual(json.loads(nav_frames[1]), {'has_route': False})
        bridge.status_pub.send_string.assert_called_once_with('DIS_STATE PAUSED', flags=1)


class CoverBlurTests(unittest.TestCase):
    def test_blurred_letterbox_accepts_common_source_modes(self):
        for mode in ('RGB', 'RGBA', 'L', 'P'):
            with self.subTest(mode=mode):
                source = Image.new('RGB', (100, 50), 'red').convert(mode)
                result = dis_image.process_image(source, bg_fill='blur', invert=True)
                self.assertEqual(result.mode, '1')
                self.assertEqual(result.size, (64, 48))
                self.assertEqual(source.mode, mode)


if __name__ == '__main__':
    unittest.main()
