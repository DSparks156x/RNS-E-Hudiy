"""No compositor, installed profile or real display is touched by these tests."""
import array
from concurrent.futures import Future
import copy
import json
import math
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hudiy_manager.pi_wayland_color import ColorSettings, Output, WaylandSession, gamma_ramps
from hudiy_manager.video_control import (DEFAULT_SETTINGS, VideoController, VideoError,
                                        VideoUnavailable, validate_settings, wayland_socket)


class RampTests(unittest.TestCase):
    def ramps(self, size, settings=ColorSettings()):
        result = array.array('H')
        result.frombytes(gamma_ramps(size, settings))
        return [list(result[n*size:(n+1)*size]) for n in range(3)]

    def test_identity_exact_endpoints_and_native_uint16_planar_channels(self):
        self.assertEqual(self.ramps(5), [[0, 16384, 32768, 49151, 65535]] * 3)
        self.assertEqual(len(gamma_ramps(256)), 256 * 3 * 2)

    def test_gamma_brightens_midtones_and_gain_only_changes_its_channel(self):
        bright = self.ramps(5, ColorSettings(gamma=2))
        self.assertGreater(bright[0][2], 32768)
        gains = self.ramps(5, ColorSettings(gains=(.5, 1, 1.5)))
        self.assertEqual(gains[0][-1], 32768)
        self.assertEqual(gains[1][-1], 65535)
        self.assertEqual(gains[2][-1], 65535)
        self.assertGreater(gains[2][1], gains[1][1])

    def test_black_point_clips_low_input_and_contrast_clamps_high_and_low(self):
        adjusted = self.ramps(11, ColorSettings(black_point=.1, contrast=1.5))[0]
        self.assertEqual(adjusted[:3], [0, 0, 0])
        self.assertEqual(adjusted[-1], 65535)
        self.assertEqual(adjusted, sorted(adjusted))

    def test_rejects_bad_sizes_and_ui_settings(self):
        for size in (True, 0, 1, 65537, 2.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                gamma_ramps(size)
        for name, value in [('gamma', 0), ('contrast', 2), ('black_point', .11),
                            ('gain_r', True), ('gain_g', math.nan), ('gain_b', math.inf)]:
            with self.subTest(name=name, value=value), self.assertRaises(VideoError):
                validate_settings({**DEFAULT_SETTINGS, name: value})
        with self.assertRaises(VideoError):
            validate_settings({**DEFAULT_SETTINGS, 'unknown': 1})


class NativeAdapterTests(unittest.TestCase):
    def test_live_ramp_updates_reuse_native_control_and_pass_complete_planar_fd(self):
        captured = []
        created = []
        def marshal(proxy, opcode, arguments):
            descriptor = arguments[0].h
            os.lseek(descriptor, 0, os.SEEK_SET)
            captured.append(os.read(descriptor, 100000))
        def construct(*args):
            created.append(args)
            return 33
        api = SimpleNamespace(
            core={}, protocol=SimpleNamespace(manager='gamma-manager', control='gamma-control'),
            bind=lambda *args: 22, construct=construct,
            lib=SimpleNamespace(wl_proxy_marshal_array=marshal))
        session = WaylandSession(api)
        session.outputs = [Output(1, 4, 10, name='HDMI-A-1')]
        session.manager_global = (100, 1)
        session.listen = lambda *args: None
        session.roundtrip = lambda: setattr(session, 'gamma_size', 5)
        session.apply('HDMI-A-1', ColorSettings())
        session.update_settings(ColorSettings(gamma=1.4))
        self.assertEqual(len(created), 1)
        self.assertEqual(captured, [gamma_ramps(5), gamma_ramps(5, ColorSettings(gamma=1.4))])

    def test_stalled_roundtrip_has_deadline_and_destroys_callback(self):
        destroyed = []
        api = SimpleNamespace(core={'wl_callback': 'sync-callback'},
                              construct=lambda *args: 33, destroy=destroyed.append,
                              lib=SimpleNamespace(wl_display_get_fd=lambda *args: 42,
                                                  wl_display_dispatch_pending=lambda *args: 0,
                                                  wl_display_flush=lambda *args: 0))
        session = WaylandSession(api)
        session.display = 11
        session.listen = lambda *args: session.callbacks.append(('listener',))
        with patch('hudiy_manager.pi_wayland_color.time.monotonic', side_effect=[0, .001, .02]), \
                patch('hudiy_manager.pi_wayland_color.select.select', return_value=([], [], [])), \
                self.assertRaisesRegex(RuntimeError, 'did not answer'):
            session.roundtrip(timeout=.01)
        self.assertEqual(destroyed, [33])
        self.assertEqual(session.callbacks, [])


class FakeSession:
    def __init__(self, owner):
        self.owner = owner
        self.outputs = [Output(index + 1, 4, index + 20, name=name)
                        for index, name in enumerate(owner.names)]
        self.selected = None
        self.closed = False
        self.fail_pump = False
        self.owner.sessions.append(self)

    def record(self, name):
        self.owner.calls.append((name, threading.get_ident(), self))

    def discover(self):
        self.record('discover')
        if self.owner.unavailable:
            raise RuntimeError('desktop asleep')
        return dict(gamma_protocol=self.owner.protocol,
                    outputs=[output.info() for output in self.outputs])

    def apply(self, output, settings):
        self.record('apply')
        if self.owner.fail_apply:
            raise RuntimeError('gamma control failed: another client owns it')
        self.selected = next(item for item in self.outputs if item.identifier == output)
        self.owner.settings = settings

    def update_settings(self, settings):
        self.record('update')
        if self.owner.fail_apply:
            raise RuntimeError('gamma setting rejected')
        self.owner.settings = settings

    def pump(self, timeout):
        self.record('pump')
        if self.fail_pump:
            raise RuntimeError('compositor disconnected')
        if self.selected and self.selected.removed:
            raise RuntimeError('selected output was removed')

    def close(self):
        self.record('close')
        self.closed = True


class FakeDesktop:
    def __init__(self, names=('HDMI-A-1',)):
        self.names = names
        self.sessions = []
        self.calls = []
        self.protocol = True
        self.fail_apply = False
        self.unavailable = False
        self.settings = None

    def factory(self, display):
        assert display == '/fake/wayland-0'
        return FakeSession(self)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.desktop = FakeDesktop()
        self.controllers = []

    def tearDown(self):
        for controller in self.controllers:
            controller.close()
        self.temporary.cleanup()

    def controller(self, desktop=None):
        desktop = desktop or self.desktop
        controller = VideoController(home=self.home, session_factory=desktop.factory,
                                     environment=lambda: '/fake/wayland-0', retry_delays=(.03, .05))
        self.controllers.append(controller)
        return controller

    def wait_until(self, check):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.02)
        self.fail('condition did not become true')

    def test_discovery_never_acquires_control_and_closes_temporary_session(self):
        controller = self.controller()
        snapshot = controller.snapshot()
        self.assertTrue(snapshot['available'])
        self.assertFalse(snapshot['active'])
        self.assertEqual(snapshot['settings'], DEFAULT_SETTINGS)
        self.assertNotIn('apply', [call[0] for call in self.desktop.calls])
        self.assertTrue(self.desktop.sessions[0].closed)

    def test_multiple_outputs_need_explicit_selection_before_control_is_acquired(self):
        desktop = FakeDesktop(('HDMI-A-1', 'DP-1'))
        controller = self.controller(desktop)
        with self.assertRaises(VideoError):
            controller.apply(DEFAULT_SETTINGS)
        self.assertNotIn('apply', [call[0] for call in desktop.calls])
        self.assertTrue(desktop.sessions[-1].closed)
        result = controller.apply(DEFAULT_SETTINGS, 'DP-1')
        self.assertEqual(result['output'], 'DP-1')

    def test_live_update_reuses_control_all_native_calls_use_one_worker_thread(self):
        controller = self.controller()
        controller.apply(DEFAULT_SETTINGS)
        result = controller.apply({**DEFAULT_SETTINGS, 'gamma': 1.4})
        self.assertTrue(result['active'])
        self.assertEqual(result['settings']['gamma'], 1.4)
        self.assertEqual([call[0] for call in self.desktop.calls].count('apply'), 1)
        self.assertEqual([call[0] for call in self.desktop.calls].count('update'), 1)
        self.assertEqual(len({call[1] for call in self.desktop.calls}), 1)
        self.assertNotEqual(self.desktop.calls[0][1], threading.get_ident())
        self.assertFalse(controller.profile_path.exists())

    def test_switching_output_releases_previous_before_acquiring_next(self):
        desktop = FakeDesktop(('HDMI-A-1', 'DP-1'))
        controller = self.controller(desktop)
        controller.apply(DEFAULT_SETTINGS, 'HDMI-A-1')
        first = desktop.sessions[-1]
        controller.apply(DEFAULT_SETTINGS, 'DP-1')
        self.assertTrue(first.closed)
        self.assertIsNot(first, desktop.sessions[-1])

    def test_failed_apply_never_publishes_draft_as_applied(self):
        controller = self.controller()
        self.desktop.fail_apply = True
        with self.assertRaises(VideoUnavailable):
            controller.apply({**DEFAULT_SETTINGS, 'gamma': 1.9})
        snapshot = controller.snapshot()
        self.assertFalse(snapshot['active'])
        self.assertEqual(snapshot['settings'], DEFAULT_SETTINGS)
        self.assertTrue(self.desktop.sessions[0].closed)

    def test_save_is_separate_profile_not_project_config_and_reset_is_durable(self):
        controller = self.controller()
        result = controller.save_profile({**DEFAULT_SETTINGS, 'gain_b': .8})
        self.assertFalse(result['active'])
        self.assertNotIn('apply', [call[0] for call in self.desktop.calls])
        document = json.loads(controller.profile_path.read_text())
        self.assertEqual(document['settings']['gain_b'], .8)
        self.assertEqual(document['output'], 'HDMI-A-1')
        self.assertEqual(document['version'], 1)
        self.assertFalse((self.home / 'config.json').exists())
        controller.apply(document['settings'])
        active = self.desktop.sessions[-1]
        restored = controller.reset()
        self.assertTrue(active.closed)
        self.assertFalse(restored['active'])
        self.assertIsNone(restored['saved_profile'])
        self.assertFalse(controller.profile_path.exists())

    def test_saved_startup_profile_retries_until_desktop_is_available(self):
        first = self.controller()
        first.save_profile({**DEFAULT_SETTINGS, 'contrast': 1.1})
        first.close()
        desktop = FakeDesktop()
        desktop.unavailable = True
        controller = self.controller(desktop)
        self.wait_until(lambda: len(desktop.sessions) > 0)
        self.assertIsNone(desktop.settings)
        desktop.unavailable = False
        self.wait_until(lambda: desktop.settings is not None)
        self.assertEqual(controller.snapshot()['settings']['contrast'], 1.1)

    def test_revoked_control_is_closed_and_reacquired_after_backoff(self):
        controller = self.controller()
        controller.apply({**DEFAULT_SETTINGS, 'gamma': 1.2})
        active = self.desktop.sessions[-1]
        active.fail_pump = True
        self.wait_until(lambda: active.closed)
        self.wait_until(lambda: len(self.desktop.sessions) > 1 and self.desktop.sessions[-1].selected is not None)
        self.assertTrue(controller.snapshot()['active'])
        self.assertEqual(controller.snapshot()['settings']['gamma'], 1.2)

    def test_unsupported_protocol_does_not_acquire_control(self):
        self.desktop.protocol = False
        controller = self.controller()
        self.assertEqual(controller.snapshot()['status'], 'unsupported')
        with self.assertRaises(VideoUnavailable):
            controller.apply(DEFAULT_SETTINGS)
        self.assertNotIn('apply', [call[0] for call in self.desktop.calls])

    def test_close_releases_control_and_is_idempotent(self):
        controller = self.controller()
        controller.apply(DEFAULT_SETTINGS)
        session = self.desktop.sessions[-1]
        controller.close()
        controller.close()
        self.assertTrue(session.closed)
        self.assertFalse(controller._thread.is_alive())
        with self.assertRaises(VideoUnavailable):
            controller.snapshot()

    def test_invalid_profile_does_not_apply(self):
        path = self.home / '.hudiy' / 'share' / 'video-color.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'version': 1, 'output': 'HDMI-A-1',
                                    'settings': {**DEFAULT_SETTINGS, 'gamma': 900}}))
        controller = self.controller()
        self.assertFalse(controller.snapshot()['active'])
        self.assertIsNone(self.desktop.settings)
        self.assertIn('Saved video profile was not loaded', controller.snapshot()['error'])

    def test_output_removal_releases_control_and_reports_unavailable(self):
        controller = self.controller()
        controller.apply(DEFAULT_SETTINGS)
        active = self.desktop.sessions[-1]
        self.desktop.names = ()
        active.selected.removed = True
        self.wait_until(lambda: active.closed)
        state = controller.snapshot()
        self.assertFalse(state['active'])
        self.assertFalse(state['available'])
        self.assertEqual(state['outputs'], [])

    def test_invalid_new_output_does_not_release_existing_control(self):
        controller = self.controller()
        controller.apply(DEFAULT_SETTINGS)
        active = self.desktop.sessions[-1]
        with self.assertRaises(VideoError):
            controller.apply(DEFAULT_SETTINGS, 'missing-output')
        self.assertFalse(active.closed)
        self.assertTrue(controller.snapshot()['active'])

    def test_reset_releases_original_even_when_profile_cannot_be_removed(self):
        controller = self.controller()
        controller.save_profile(DEFAULT_SETTINGS)
        controller.apply(DEFAULT_SETTINGS)
        session = self.desktop.sessions[-1]
        with patch.object(controller, '_safe_profile_parent', side_effect=PermissionError('read-only storage')), \
                self.assertRaisesRegex(VideoUnavailable, 'may return after restart'):
            controller.reset()
        self.assertTrue(session.closed)
        self.assertFalse(controller.snapshot()['active'])
        self.assertTrue(controller.profile_path.exists())

    def test_full_queue_cannot_block_shutdown(self):
        controller = self.controller()
        entered, release = threading.Event(), threading.Event()
        original_factory = self.desktop.factory
        def blocking_factory(display):
            entered.set()
            release.wait(2)
            return original_factory(display)
        controller._factory = blocking_factory
        active = Future()
        controller._commands.put_nowait((active, 'snapshot', ()))
        self.assertTrue(entered.wait(1))
        queued = []
        for _ in range(32):
            future = Future()
            controller._commands.put_nowait((future, 'snapshot', ()))
            queued.append(future)
        controller._timeout = .05
        started = time.monotonic()
        controller.close()
        self.assertLess(time.monotonic() - started, .2)
        release.set()
        controller._thread.join(2)
        self.assertFalse(controller._thread.is_alive())
        self.assertTrue(all(future.done() for future in queued))


@unittest.skipUnless(hasattr(socket, 'AF_UNIX') and hasattr(os, 'geteuid'), 'Needs Unix socket ownership')
class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temporary.name)
        os.chmod(self.runtime, 0o700)
        self.sockets = []

    def tearDown(self):
        for item in self.sockets:
            item.close()
        self.temporary.cleanup()

    def make_socket(self, name):
        item = socket.socket(socket.AF_UNIX)
        item.bind(str(self.runtime / name))
        self.sockets.append(item)
        return self.runtime / name

    def test_only_owned_socket_is_discovered_and_multiple_need_explicit_display(self):
        uid = os.geteuid()
        if uid == 0:
            self.skipTest('Test desktop user cannot be root')
        first = self.make_socket('wayland-0')
        environment = {'XDG_RUNTIME_DIR': str(self.runtime)}
        self.assertEqual(wayland_socket(environment, uid=uid, platform='linux'), str(first))
        self.make_socket('wayland-1')
        with self.assertRaises(VideoUnavailable):
            wayland_socket(environment, uid=uid, platform='linux')
        self.assertEqual(wayland_socket({**environment, 'WAYLAND_DISPLAY': 'wayland-0'}, uid=uid, platform='linux'), str(first))
        with self.assertRaises(VideoUnavailable):
            wayland_socket({**environment, 'WAYLAND_DISPLAY': '/tmp/foreign'}, uid=uid, platform='linux')


class PortableEnvironmentTests(unittest.TestCase):
    def test_unsupported_os_root_and_missing_directory_fail_without_native_load(self):
        for kwargs in [dict(platform='win32'), dict(platform='linux', uid=0),
                       dict(platform='linux', uid=500, environ={'XDG_RUNTIME_DIR': '/no/such/runtime'})]:
            with self.assertRaises(VideoUnavailable):
                wayland_socket(**kwargs)

    def test_socket_selection_checks_owner_type_and_rejects_escape_or_ambiguity(self):
        runtime = Path(tempfile.gettempdir()).absolute()
        first, second = runtime / 'wayland-0', runtime / 'wayland-1'
        entries = {runtime: SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1000),
                   first: SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=1000)}
        def metadata(path):
            if path not in entries:
                raise FileNotFoundError(str(path))
            return entries[path]
        environment = {'XDG_RUNTIME_DIR': str(runtime)}
        with patch.object(Path, 'lstat', metadata), patch.object(Path, 'iterdir', lambda *_: list(entries)[1:]):
            self.assertEqual(wayland_socket(environment, uid=1000, platform='linux'), str(first))
            entries[second] = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=1000)
            with self.assertRaises(VideoUnavailable):
                wayland_socket(environment, uid=1000, platform='linux')
            self.assertEqual(wayland_socket({**environment, 'WAYLAND_DISPLAY': 'wayland-0'}, uid=1000, platform='linux'), str(first))
            entries[first].st_uid = 1001
            with self.assertRaises(VideoUnavailable):
                wayland_socket({**environment, 'WAYLAND_DISPLAY': 'wayland-0'}, uid=1000, platform='linux')
            with self.assertRaises(VideoUnavailable):
                wayland_socket({**environment, 'WAYLAND_DISPLAY': '../foreign'}, uid=1000, platform='linux')


if __name__ == '__main__':
    unittest.main()
