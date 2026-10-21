"""Day/night mode in hudiy_client/dark_mode_api.py against a fake Hudiy API.

Hudiy starts seconds after this service and can restart under it (crash,
update, quit), and it has no dark-mode status event. The mode must reach
Hudiy whenever its API is up, without waiting for the next headlight change.
"""
import importlib.util
import json
import logging
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import zmq

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_COMMON = ROOT / 'references' / 'hudiy references' / 'hudiy-main' / 'examples' / 'api' / 'python' / 'common'


def load_dark_mode():
    # Same registration as test_hudiy_data_mapping: one Api_pb2 per process
    # (dropping or re-importing it under another name upsets the upb pool).
    if not hasattr(sys.modules.get('common'), 'Api_pb2'):
        for name in [n for n in sys.modules if n == 'common' or n.startswith('common.')]:
            del sys.modules[name]
        common = types.ModuleType('common')
        common.__path__ = [str(UPSTREAM_COMMON)]
        sys.modules['common'] = common
        importlib.import_module('common.Api_pb2')
        common.Api_pb2 = sys.modules['common.Api_pb2']
    sys.modules['Api_pb2'] = sys.modules['common.Api_pb2']
    spec = importlib.util.spec_from_file_location('dark_mode_api_under_test',
                                                  ROOT / 'hudiy_client' / 'dark_mode_api.py')
    module = importlib.util.module_from_spec(spec)
    with patch.object(logging, 'FileHandler', lambda *a, **k: logging.NullHandler()):
        spec.loader.exec_module(module)
    return module


DM = load_dark_mode()
API = sys.modules['Api_pb2']


class FakeHudiy:
    """Hudiy API stand-in: records (connection, message id, payload) frames."""

    def __init__(self, port=0):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(('127.0.0.1', port))
        self.listener.listen(4)
        self.port = self.listener.getsockname()[1]
        self.frames = []
        self.conns = []
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with self.lock:
                self.conns.append(conn)
                index = len(self.conns) - 1
            threading.Thread(target=self._read, args=(conn, index), daemon=True).start()

    def _read(self, conn, index):
        buf = b''
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while len(buf) >= 12:
                size, mid, _ = struct.unpack_from('<III', buf)
                if len(buf) < 12 + size:
                    break
                with self.lock:
                    self.frames.append((index, mid, buf[12:12 + size]))
                buf = buf[12 + size:]

    def modes(self):
        """[(connection, enabled)] for every SetDarkMode received."""
        with self.lock:
            frames = list(self.frames)
        out = []
        for index, mid, payload in frames:
            if mid == API.MESSAGE_SET_DARK_MODE:
                msg = API.SetDarkMode()
                msg.ParseFromString(payload)
                out.append((index, msg.enabled))
        return out

    def ids(self):
        with self.lock:
            return [mid for _, mid, _ in self.frames]

    def send_all(self, data):
        with self.lock:
            conns = list(self.conns)
        for conn in conns:
            conn.sendall(data)

    def stop(self):
        # close() alone leaves a blocked accept() listening on Linux.
        try:
            self.listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.listener.close()
        self.thread.join(1)
        with self.lock:
            conns, self.conns = list(self.conns), []
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()


def wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class HudiyLinkTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.port = free_port()
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.stop()

    def start_hudiy(self):
        server = FakeHudiy(self.port)
        self.servers.append(server)
        return server

    def make_link(self, desired=True, sync_aa=False):
        link = DM.HudiyLink(desired, sync_android_auto=sync_aa,
                            address=('127.0.0.1', self.port), clock=self.clock)
        self.addCleanup(link.close)
        return link

    def advance(self, link, seconds, step=0.25):
        end = self.clock.now + seconds
        while self.clock.now < end:
            self.clock.now = min(end, self.clock.now + step)
            link.tick()

    def test_starts_before_hudiy_and_sends_when_it_appears_without_a_new_frame(self):
        link = self.make_link(desired=True)
        self.advance(link, 3)  # Hudiy not up yet: refused, quietly retried
        self.assertFalse(link.connected)
        link.set_desired(False)  # the 0x635 frame arrives while Hudiy is down
        hudiy = self.start_hudiy()
        self.advance(link, 1)
        self.assertTrue(link.connected)
        self.assertTrue(wait_for(lambda: hudiy.modes()[:1] == [(0, False)]))
        self.assertEqual(hudiy.ids()[0], API.MESSAGE_HELLO_REQUEST)

    def test_reasserts_shortly_after_connect_then_stays_quiet(self):
        hudiy = self.start_hudiy()
        link = self.make_link(desired=True)
        link.tick()
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 1))
        self.advance(link, 6)  # +2 s and +5 s re-asserts
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 3))
        for _ in range(20):
            link.set_desired(True)  # same light status, frame after frame
        self.advance(link, 120, step=1)
        time.sleep(0.1)
        self.assertEqual(hudiy.modes(), [(0, True)] * 3)
        self.assertIsNone(link.seconds_until_due())  # nothing scheduled: no polling

    def test_mode_change_while_up_is_sent_once(self):
        hudiy = self.start_hudiy()
        link = self.make_link(desired=True)
        link.tick()
        self.advance(link, 6)
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 3))
        link.set_desired(False)
        link.set_desired(False)
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 4))
        time.sleep(0.1)
        self.assertEqual(hudiy.modes()[-1], (0, False))
        self.assertEqual(len(hudiy.modes()), 4)

    def test_hudiy_restart_gets_the_mode_again(self):
        hudiy = self.start_hudiy()
        link = self.make_link(desired=True)
        link.tick()
        self.assertTrue(wait_for(lambda: hudiy.modes() == [(0, True)]))
        link.set_desired(False)
        hudiy.stop()  # Hudiy crashes / is updated
        self.assertTrue(wait_for(lambda: (link.on_readable(), not link.connected)[1]))
        self.advance(link, 2)  # refused while it is down
        self.assertFalse(link.connected)
        hudiy = self.start_hudiy()
        self.advance(link, 1)
        self.assertTrue(link.connected)
        self.assertTrue(wait_for(lambda: hudiy.modes()[:1] == [(0, False)]))

    def test_byebye_counts_as_hudiy_gone(self):
        hudiy = self.start_hudiy()
        link = self.make_link()
        link.tick()
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 1))
        hudiy.send_all(struct.pack('<III', 0, API.MESSAGE_BYEBYE, 0))
        self.assertTrue(wait_for(lambda: (link.on_readable(), not link.connected)[1]))

    def test_ping_is_answered(self):
        hudiy = self.start_hudiy()
        link = self.make_link()
        link.tick()
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 1))
        hudiy.send_all(struct.pack('<III', 0, API.MESSAGE_PING, 0))
        self.assertTrue(wait_for(lambda: (link.on_readable(), API.MESSAGE_PONG in hudiy.ids())[1]))
        self.assertTrue(link.connected)

    def test_sync_android_auto_sends_the_projection_mode_too(self):
        hudiy = self.start_hudiy()
        link = self.make_link(desired=True, sync_aa=True)
        link.tick()
        self.assertTrue(wait_for(lambda: API.MESSAGE_SET_ANDROID_AUTO_DAY_NIGHT_MODE in hudiy.ids()))
        with hudiy.lock:
            payload = next(p for _, mid, p in hudiy.frames
                           if mid == API.MESSAGE_SET_ANDROID_AUTO_DAY_NIGHT_MODE)
        msg = API.SetAndroidAutoDayNightMode()
        msg.ParseFromString(payload)
        self.assertEqual(msg.mode, API.SetAndroidAutoDayNightMode.NIGHT)

    def test_no_android_auto_message_without_sync(self):
        hudiy = self.start_hudiy()
        link = self.make_link(desired=True, sync_aa=False)
        link.tick()
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 1))
        time.sleep(0.05)
        self.assertNotIn(API.MESSAGE_SET_ANDROID_AUTO_DAY_NIGHT_MODE, hudiy.ids())

    def test_failed_send_is_retried_against_the_next_connection(self):
        hudiy = self.start_hudiy()
        link = self.make_link(desired=True)
        link.tick()
        self.assertTrue(wait_for(lambda: hudiy.modes() == [(0, True)]))
        link.drop('test')  # e.g. a send error
        self.assertIsNone(link.sent)
        link.set_desired(True)  # same value as before: still owed to Hudiy
        self.advance(link, 1)
        self.assertTrue(wait_for(lambda: (1, True) in hudiy.modes()))

    def test_light_byte_decoding(self):
        self.assertTrue(DM.light_is_night('0064000000'))
        self.assertFalse(DM.light_is_night('0000000000'))


REFERENCE_MAIN_CONFIG = ROOT / 'references' / 'hudiy references' / 'hudiy-main' / 'config' / 'main_configuration.json'


class SavedThemeTests(unittest.TestCase):
    """Hudiy's first frames use main_configuration.json, before its API is up."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'main_configuration.json')
        self.original = REFERENCE_MAIN_CONFIG.read_text(encoding='utf-8')
        with open(self.path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.original)
        os.chmod(self.path, 0o640)

    def theme(self):
        with open(self.path, encoding='utf-8') as f:
            return json.load(f)['theme']['darkThemeEnabled']

    def test_flips_only_that_value(self):
        self.assertTrue(json.loads(self.original)['theme']['darkThemeEnabled'])
        self.assertTrue(DM.save_hudiy_theme(self.path, False))
        self.assertIs(self.theme(), False)
        with open(self.path, encoding='utf-8', newline='') as f:
            text = f.read()
        self.assertEqual(text.replace('"darkThemeEnabled" : false', '"darkThemeEnabled" : true'),
                         self.original)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)
        self.assertEqual(os.listdir(self.tmp.name), ['main_configuration.json'])

    def test_same_value_leaves_the_file_alone(self):
        before = os.stat(self.path).st_mtime_ns
        os.utime(self.path, ns=(before - 10**9, before - 10**9))
        self.assertTrue(DM.save_hudiy_theme(self.path, True))
        self.assertEqual(os.stat(self.path).st_mtime_ns, before - 10**9)

    def test_unexpected_files_are_not_touched(self):
        for text in ('{"theme": {}}', 'not json', '{"theme": {"darkThemeEnabled": true}, '
                                                    '"x": {"darkThemeEnabled": true}}'):
            with open(self.path, 'w', encoding='utf-8') as f:
                f.write(text)
            self.assertFalse(DM.save_hudiy_theme(self.path, False))
            with open(self.path, encoding='utf-8') as f:
                self.assertEqual(f.read(), text)
        self.assertFalse(DM.save_hudiy_theme(os.path.join(self.tmp.name, 'missing.json'), False))

    def test_saved_from_the_first_frame_before_hudiy_is_up(self):
        clock = Clock()
        link = DM.HudiyLink(True, address=('127.0.0.1', free_port()), clock=clock,
                            saved_theme_path=self.path)
        self.addCleanup(link.close)
        link.hold_until(clock.now + DM.FIRST_FRAME_WAIT)
        link.tick()
        self.assertIs(self.theme(), True)  # still waiting for 0x635: untouched
        link.set_desired(False)            # first frame: lights off
        link.release_hold()
        self.assertEqual(link.seconds_until_due(), 0.0)
        link.tick()
        self.assertFalse(link.connected)
        self.assertIs(self.theme(), False)
        link.set_desired(True)             # later change also lands in the file
        link.tick()
        self.assertIs(self.theme(), True)

    def test_initial_mode_saved_when_no_frame_arrives(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(self.original.replace('"darkThemeEnabled" : true', '"darkThemeEnabled" : false'))
        clock = Clock()
        link = DM.HudiyLink(True, address=('127.0.0.1', free_port()), clock=clock,
                            saved_theme_path=self.path)
        self.addCleanup(link.close)
        link.hold_until(clock.now + DM.FIRST_FRAME_WAIT)
        clock.now += DM.FIRST_FRAME_WAIT
        link.tick()
        self.assertIs(self.theme(), True)


class ServiceLoopTests(unittest.TestCase):
    """run() with a real ZMQ SUB socket and wall-clock timers."""

    def setUp(self):
        self.context = zmq.Context()
        self.pub = self.context.socket(zmq.PUB)
        self.pub.setsockopt(zmq.LINGER, 0)
        self.pub.bind('inproc://light-status')
        self.sub = DM.open_subscriber(self.context, 'inproc://light-status', 'CAN_635')
        self.port = free_port()
        self.servers = []
        DM.RUNNING = True

    def tearDown(self):
        DM.RUNNING = False
        if hasattr(self, 'thread'):
            self.thread.join(1)
        for server in self.servers:
            server.stop()
        self.sub.close()
        self.pub.close()
        self.context.term()

    def start_loop(self, desired=True):
        self.link = DM.HudiyLink(desired, address=('127.0.0.1', self.port))
        self.thread = threading.Thread(target=DM.run, args=(self.link, self.sub), daemon=True)
        self.thread.start()
        self.addCleanup(self.link.close)

    def publish(self, data_hex):
        self.pub.send_multipart([b'CAN_635', json.dumps({'data_hex': data_hex}).encode()])

    def test_frame_before_hudiy_then_hudiy_appears(self):
        self.start_loop(desired=True)
        time.sleep(0.05)
        for _ in range(5):
            self.publish('0000000000')  # day; Hudiy not up
            time.sleep(0.02)
        self.assertTrue(wait_for(lambda: self.link.desired is False))
        hudiy = FakeHudiy(self.port)
        self.servers.append(hudiy)
        # No further frames: the retry timer alone must get the mode across.
        self.assertTrue(wait_for(lambda: hudiy.modes()[:1] == [(0, False)], timeout=3))

    def periodic(self, data_hex, stop):
        # 0x635 is periodic: the same value keeps arriving.
        def loop():
            while not stop.is_set():
                self.publish(data_hex)
                time.sleep(0.02)
        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 1)
        self.addCleanup(stop.set)

    def test_steady_frames_resend_after_hudiy_restart_but_not_while_up(self):
        stop = threading.Event()
        with patch.object(DM, 'REASSERT_DELAYS', ()):
            hudiy = FakeHudiy(self.port)
            self.servers.append(hudiy)
            self.start_loop(desired=True)
            self.periodic('0000000000', stop)  # day, unchanged throughout
            self.assertTrue(wait_for(lambda: (0, False) in hudiy.modes(), timeout=3))
            time.sleep(0.5)
            first = hudiy.modes()
            self.assertEqual(first.count((0, False)), 1)  # steady frames: no resend
            hudiy.stop()
            hudiy = FakeHudiy(self.port)
            self.servers.append(hudiy)
            self.assertTrue(wait_for(lambda: hudiy.modes() == [(0, False)], timeout=3), hudiy.modes())
            time.sleep(0.5)
            self.assertEqual(hudiy.modes(), [(0, False)])

    def test_loop_answers_ping(self):
        hudiy = FakeHudiy(self.port)
        self.servers.append(hudiy)
        self.start_loop()
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 1, timeout=3))
        hudiy.send_all(struct.pack('<III', 0, API.MESSAGE_PING, 0))
        self.assertTrue(wait_for(lambda: API.MESSAGE_PONG in hudiy.ids()))

    def test_sigterm_exits_quickly_while_hudiy_is_down(self):
        self.start_loop()
        time.sleep(0.3)
        started = time.monotonic()
        DM.shutdown_handler(15, None)
        self.thread.join(1)
        self.assertFalse(self.thread.is_alive())
        self.assertLess(time.monotonic() - started, 0.4)

    def test_sigterm_exits_quickly_while_connected(self):
        hudiy = FakeHudiy(self.port)
        self.servers.append(hudiy)
        self.start_loop()
        self.assertTrue(wait_for(lambda: len(hudiy.modes()) == 1, timeout=3))
        started = time.monotonic()
        DM.shutdown_handler(15, None)
        self.thread.join(1)
        self.assertFalse(self.thread.is_alive())
        self.assertLess(time.monotonic() - started, 0.4)


if __name__ == '__main__':
    unittest.main()
