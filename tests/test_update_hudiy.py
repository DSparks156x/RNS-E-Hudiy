"""Exercise update actions and the wrapper with no device or real downloads."""
import ast
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'hudiy_client/update_hudiy.sh'
BASH = (str(Path('C:/Program Files/Git/bin/bash.exe')) if os.name == 'nt'
        and Path('C:/Program Files/Git/bin/bash.exe').exists() else shutil.which('bash'))


class Request:
    def SerializeToString(self):
        return vars(self).copy()


def handler_methods():
    tree = ast.parse((ROOT / 'hudiy_client/hudiy_data.py').read_text(encoding='utf-8'))
    handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TP2BridgeHandler')
    methods = [n for n in handler.body if isinstance(n, ast.FunctionDef)
               and n.name in ('on_hello_response', 'on_dispatch_action')]
    api = SimpleNamespace(**{name: Request for name in (
        'RegisterActionRequest', 'DispatchAction', 'RegisterToastChannelRequest',
        'RegisterNotificationChannelRequest')}, MESSAGE_REGISTER_ACTION_REQUEST=1,
        MESSAGE_DISPATCH_ACTION=2, MESSAGE_REGISTER_TOAST_CHANNEL_REQUEST=3,
        MESSAGE_REGISTER_NOTIFICATION_CHANNEL_REQUEST=4)
    namespace = dict(hudiy_api=api, os=os, __file__=str(ROOT / 'hudiy_client/hudiy_data.py'),
                     logger=logging.getLogger(__name__))
    exec(compile(ast.Module(body=methods, type_ignores=[]), 'hudiy_data.py', 'exec'), namespace)
    return namespace


class HudiyUpdateActionTests(unittest.TestCase):
    def test_registers_update_hudiy_on_connection(self):
        namespace = handler_methods()
        client = Mock()
        namespace['on_hello_response'](Mock(timer=None), client, SimpleNamespace(
            api_version=SimpleNamespace(major=1, minor=0)))
        actions = [call.args[2]['action'] for call in client.send.call_args_list if call.args[0] == 1]
        self.assertIn('update_hudiy', actions)
        self.assertIn('update_rnse', actions)
        self.assertIn('restore_configs', actions)

    def test_quits_before_fullscreen_launch_and_routes_each_maintenance_action(self):
        namespace = handler_methods()
        for action, filename in [('update_hudiy', 'update_hudiy.sh'),
                                 ('update_rnse', 'update_rnse.sh'), ('restore_configs', 'restore_configs.sh')]:
            with self.subTest(action=action), patch('subprocess.Popen') as launch, patch.dict(
                    os.environ, {'XDG_RUNTIME_DIR': '/run/user/1234', 'WAYLAND_DISPLAY': 'wayland-test'}):
                events = []
                client = Mock()
                client.send.side_effect = lambda *args: events.append(('quit', args))
                launch.side_effect = lambda *args, **kwargs: events.append(('launch', args))
                namespace['on_dispatch_action'](Mock(), client, SimpleNamespace(action=action))
                self.assertEqual([e[0] for e in events], ['quit', 'launch'])
                self.assertEqual(events[0][1][2]['action'], 'quit_hudiy')
                command = launch.call_args.args[0]
                self.assertEqual(command[:2], ['foot', '--fullscreen'])
                self.assertEqual(command[-2:], ['bash', str(ROOT / 'hudiy_client' / filename)])
                self.assertEqual(launch.call_args.kwargs['env']['WAYLAND_DISPLAY'], 'wayland-test')

    def test_https_probe_has_timeout_and_handles_offline_failure(self):
        probe = SCRIPT.read_text().split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        with patch('urllib.request.urlopen') as request:
            exec(probe, {})
            request.assert_called_once_with('https://hudiy.eu/', timeout=10)
        with patch('urllib.request.urlopen', side_effect=OSError('offline')):
            with self.assertRaises(SystemExit) as error:
                exec(probe, {})
            self.assertEqual(error.exception.code, 1)


@unittest.skipUnless(BASH, 'Bash is required for wrapper fixture tests')
class HudiyUpdateScriptTests(unittest.TestCase):
    def run_wrapper(self, status=0, present=True):
        with tempfile.TemporaryDirectory(dir=ROOT / 'scratch') as directory:
            root = Path(directory)
            home, bin_dir = root / 'home with spaces', root / 'bin'
            share = home / '.hudiy/share'
            share.mkdir(parents=True)
            bin_dir.mkdir()
            files = {
                bin_dir / 'sleep': '#!/bin/bash\necho "sleep:$*" >> "$TEST_LOG"\n',
                bin_dir / 'python3': '#!/bin/bash\ncat >/dev/null\necho probe >> "$TEST_LOG"\n'
                    'if [ ! -f "$TEST_LOG.online" ]; then touch "$TEST_LOG.online"; exit 1; fi\n',
            }
            if present:
                files[share / 'updater'] = ('#!/bin/bash\n'
                    'echo "updater:$PWD:args=$#" >> "$TEST_LOG"\n'
                    'read -r answer\necho "input:$answer" >> "$TEST_LOG"\n'
                    f'exit {status}\n')
            for path, content in files.items():
                path.write_text(content, encoding='utf-8', newline='\n')
                path.chmod(0o755)
            log = root / 'events.log'
            # Let Bash convert fixture paths, including Windows drive letters.
            result = subprocess.run([BASH, '-c',
                'export HOME="$(cd "$1" && pwd)"; export PATH="$(cd "$2" && pwd):$PATH"; '
                'export TEST_LOG="$3"; bash "$4"', 'test', str(home), str(bin_dir), str(log), str(SCRIPT)],
                input='native prompt answer\n', text=True, capture_output=True, timeout=10)
            return result, log.read_text().splitlines()

    def test_waits_retries_and_runs_native_updater_with_terminal_input(self):
        result, events = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events[:4], ['sleep:3', 'probe', 'sleep:5', 'probe'])
        self.assertTrue(events[4].endswith('/home with spaces/.hudiy/share:args=0'), events)
        self.assertEqual(events[5], 'input:native prompt answer')
        self.assertIn('Hudiy updater finished.', result.stdout)

    def test_reports_native_failure_and_missing_updater_without_reboot(self):
        result, events = self.run_wrapper(status=7)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn('failed (exit status 7)', result.stdout)
        result, events = self.run_wrapper(present=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(events, ['sleep:3'])
        self.assertIn('missing or not executable', result.stdout)


if __name__ == '__main__':
    unittest.main()
