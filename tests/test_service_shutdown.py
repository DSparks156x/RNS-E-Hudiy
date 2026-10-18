"""SIGTERM must stop every service quickly, with or without CAN traffic.

systemd gives each unit TimeoutStopSec=5 and can_handler stops only after the
services bound to it, so a wait that ignores the stop flag costs seconds at
every ignition-off shutdown.
"""
import ast
import importlib.util
import logging
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

import zmq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    with patch.object(logging, 'FileHandler', lambda *a, **k: logging.NullHandler()):
        spec.loader.exec_module(module)
    return module


class CanHandlerShutdownTests(unittest.TestCase):
    def test_send_worker_leaves_a_quiet_socket_when_asked(self):
        gw = load('can_handler_shutdown', 'rns-e_can/can_handler.py')
        context = zmq.Context()
        self.addCleanup(context.term)
        pull = context.socket(zmq.PULL)
        pull.setsockopt(zmq.LINGER, 0)
        pull.bind('inproc://can-send-test')
        gw.ZMQ_PULL_SOCKET, gw.RUNNING = pull, True
        gw.start_send_worker()
        time.sleep(0.05)
        started = time.monotonic()
        gw.stop_send_worker()
        self.assertFalse(gw.SEND_THREAD.is_alive())
        self.assertLess(time.monotonic() - started, 0.5)
        pull.close()

    def test_pause_returns_early_once_stopping(self):
        gw = load('can_handler_pause', 'rns-e_can/can_handler.py')
        gw.RUNNING = True
        threading.Timer(0.1, setattr, (gw, 'RUNNING', False)).start()
        started = time.monotonic()
        self.assertFalse(gw.pause(10))
        self.assertLess(time.monotonic() - started, 0.5)


class HaldexShutdownTests(unittest.TestCase):
    def test_reply_wait_gives_up_when_stopping(self):
        hm = load('haldex_shutdown', 'rns-e_can/haldex_manager.py')
        manager = hm.HaldexManager.__new__(hm.HaldexManager)
        manager.running = True
        context = zmq.Context()
        self.addCleanup(context.term)
        sock = context.socket(zmq.PULL)
        sock.setsockopt(zmq.LINGER, 0)
        self.addCleanup(sock.close)
        threading.Timer(0.1, setattr, (manager, 'running', False)).start()
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            manager._recv_json(sock, 5000)
        self.assertLess(time.monotonic() - started, 0.5)


class TopDisplayShutdownTests(unittest.TestCase):
    def test_signal_handler_is_defined_once_and_wakes_run(self):
        # A second _shutdown used to override the one run() waited on.
        tree = ast.parse((ROOT / 'dis_client/dis_top_display_service.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DISController')
        handlers = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_shutdown']
        self.assertEqual(len(handlers), 1)
        sys.path.insert(0, str(ROOT / 'dis_client'))
        from dis_top_display_service import DISController
        top = DISController.__new__(DISController)
        top._stop_requested = False
        top._shutdown()
        self.assertTrue(top._stop_requested)


class HudiyClientShutdownTests(unittest.TestCase):
    def test_wake_reader_unblocks_a_thread_in_recv(self):
        # close() from another thread does not wake recv() on Linux.
        tree = ast.parse((ROOT / 'hudiy_client/hudiy_data.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'HudiyData')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_wake_reader')
        namespace = {'socket': socket}
        holder = ast.ClassDef(name='Holder', bases=[], keywords=[], body=[method], decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[holder], type_ignores=[])),
                     'hudiy_data.py', 'exec'), namespace)
        ours, peer = socket.socketpair()
        self.addCleanup(ours.close)
        self.addCleanup(peer.close)
        received = []
        reader = threading.Thread(target=lambda: received.append(ours.recv(16)), daemon=True)
        reader.start()
        time.sleep(0.05)
        namespace['Holder']._wake_reader(type('Client', (), {'_socket': ours})())
        reader.join(1.0)
        self.assertFalse(reader.is_alive())
        self.assertEqual(received, [b''])


if __name__ == '__main__':
    unittest.main()
