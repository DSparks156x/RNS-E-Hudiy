import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
from hudiy_manager.test_pattern import TestPatternWindow, PatternUnavailable, register_test_pattern
from hudiy_manager.config_store import ConfigError


class PatternTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        viewer = self.home / '.hudiy/share/web_viewer'
        viewer.parent.mkdir(parents=True)
        viewer.write_text('fixture')
        self.process = Mock()
        self.process.poll.return_value = None
        self.launcher = Mock(return_value=self.process)
        self.window = TestPatternWindow(self.home, launcher=self.launcher, desktop=lambda: '/run/user/1000/wayland-0', platform='linux')

    def test_fixed_native_surface_and_duplicate_open_reuse(self):
        self.assertTrue(self.window.open()['running'])
        self.window.open()
        self.launcher.assert_called_once()
        args, kwargs = self.launcher.call_args
        self.assertEqual(args[0][2].split('?')[0], 'http://127.0.0.1:5004/test-pattern')
        self.assertEqual(args[0][3:], ['--width', '800', '--height', '480', '--rendering_mode', '1'])
        self.assertEqual(kwargs['env']['WAYLAND_DISPLAY'], 'wayland-0')
        self.assertEqual(kwargs['env']['QT_QPA_PLATFORM'], 'wayland')

    def test_close_capability_only_closes_its_current_child(self):
        self.window.open()
        token = self.window._token
        with self.assertRaises(ConfigError):
            self.window.close('foreign')
        self.process.terminate.assert_not_called()
        self.window.close(token)
        self.process.terminate.assert_called_once()
        self.assertFalse(self.window.valid_session(token))
        self.assertFalse(self.window.status()['running'])

    def test_unavailable_platform_never_launches(self):
        self.window.platform = 'win32'
        with self.assertRaises(PatternUnavailable):
            self.window.open()
        self.launcher.assert_not_called()

    def test_native_close_needs_current_token_and_same_origin(self):
        app = Flask(__name__)
        register_test_pattern(app, SimpleNamespace(pin=lambda: 'private-pin'), self.window)
        client = app.test_client()
        self.assertEqual(client.post('/api/manage/test-pattern/open', headers={'X-Hudiy-Management':'1'}).status_code, 403)
        self.window.open()
        headers = {'X-Hudiy-Management':'1', 'X-Hudiy-Pattern-Session':self.window._token, 'Origin':'http://foreign.test'}
        self.assertEqual(client.post('/api/manage/test-pattern/close', headers=headers).status_code, 403)
        self.process.terminate.assert_not_called()
        headers['Origin'] = 'http://localhost'
        self.assertEqual(client.post('/api/manage/test-pattern/close', headers=headers).status_code, 200)
        self.process.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
