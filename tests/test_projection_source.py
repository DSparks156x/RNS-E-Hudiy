"""Inferred provider labels must never pretend to be connection events."""
import ast
import json
import logging
import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from hudiy_client.projection_source import ProjectionSource
from dis_client.navigation_state import has_route_content, is_no_route


class ProjectionSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = ProjectionSource()

    def test_startup_has_no_provider_and_explicitly_unknown_connection(self):
        self.assertEqual(self.source.snapshot()['source'], 0)
        self.assertFalse(self.source.snapshot()['connection_known'])
        self.assertEqual(self.source.snapshot()['evidence'], 'api_disconnected')
        self.source.set_api_connected(True)
        self.assertEqual(self.source.snapshot()['evidence'], 'no_provider')

    def test_exact_command_mapping_and_reported_provider_evidence(self):
        self.source.set_api_connected(True)
        for reported, expected in ((1, 2), (2, 1)):
            self.source.report('media', reported)
            state = self.source.snapshot()
            self.assertEqual(state['source'], expected)
            self.assertEqual(state['evidence'], 'reported_provider')
            self.assertFalse(state['connection_known'])

    def test_other_audio_clears_only_media_and_preserves_navigation_hint(self):
        self.source.set_api_connected(True)
        self.source.report('navigation', 2)
        self.source.report('media', 1)
        self.assertEqual(self.source.snapshot()['source'], 2)
        self.source.report('media', 3)
        self.assertEqual(self.source.snapshot()['source'], 1)
        self.source.report('navigation', 0)
        self.assertEqual(self.source.snapshot()['source'], 0)

    def test_latest_conflicting_provider_report_wins_and_snapshots_are_copies(self):
        self.source.set_api_connected(True)
        self.source.report('media', 1)
        old = self.source.snapshot()
        self.source.report('navigation', 2)
        self.assertEqual(self.source.snapshot()['source'], 1)
        self.assertEqual(old['source'], 2)
        self.source.report('media', 1)
        self.assertEqual(self.source.snapshot()['source'], 2)

    def test_api_loss_and_new_session_clear_all_old_hints(self):
        self.source.set_api_connected(True)
        self.source.report('media', 2)
        self.source.report('navigation', 2)
        self.source.set_api_connected(False)
        self.assertEqual(self.source.snapshot()['source'], 0)
        self.assertEqual(self.source.snapshot()['evidence'], 'api_disconnected')
        self.source.set_api_connected(True)
        self.assertEqual(self.source.snapshot()['source'], 0)
        self.assertEqual(self.source.snapshot()['evidence'], 'no_provider')


def load_handler():
    path = Path(__file__).resolve().parents[1] / 'hudiy_client/hudiy_data.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'MANEUVER_TYPE_MAP', 'MANEUVER_SIDE_MAP', 'CALL_STATE_MAP',
             'CONN_STATE_MAP', 'MEDIA_SOURCE_MAP', 'PROJECTION_PROVIDER_MAP'}
    nodes = [node for node in tree.body if
             (isinstance(node, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id in names
                 for target in node.targets)) or
             (isinstance(node, ast.ClassDef) and node.name == 'HudiyEventHandler')]
    namespace = dict(ClientEventHandler=object, logger=logging.getLogger(__name__),
                     time=time, os=os, json=json, threading=threading,
                     has_route_content=has_route_content, is_no_route=is_no_route,
                     open=Mock(side_effect=OSError('No disk caches in test')))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['HudiyEventHandler']


class ProjectionCallbackTests(unittest.TestCase):
    def setUp(self):
        self.publisher = Mock()
        self.handler = load_handler()(self.publisher)
        self.handler.set_projection_api_connected(True)
        self.addCleanup(self.handler.stop)

    def latest(self):
        calls = self.publisher.publish.call_args_list
        return next(call.args[1] for call in reversed(calls)
                    if call.args[0] == b'HUDIY_PROJECTION')

    def media(self, source, playing=False):
        self.handler.on_media_status(None, SimpleNamespace(
            source=source, is_playing=playing, position_label='0:00'))

    def test_paused_idle_provider_does_not_require_media_playback(self):
        for reported, expected in ((1, 2), (2, 1)):
            self.media(reported)
            self.assertEqual(self.latest()['source'], expected)
            self.assertFalse(self.latest()['connection_known'])

    def test_hiding_projection_does_not_clear_reported_provider(self):
        self.media(2)
        self.handler.on_projection_status(None, SimpleNamespace(active=False))
        self.handler.publish_projection_source()
        self.assertEqual(self.latest()['source'], 1)

    def test_inactive_navigation_provider_survives_other_audio_source(self):
        self.handler.on_navigation_status(None, SimpleNamespace(source=1, state=2))
        self.media(3)
        self.assertEqual(self.latest()['source'], 2)
        self.handler.on_navigation_status(None, SimpleNamespace(source=0, state=2))
        self.assertEqual(self.latest()['source'], 0)

    def test_api_reset_and_repeated_snapshot_do_not_republish_stale_source(self):
        self.media(2)
        old = self.latest()
        self.handler.set_projection_api_connected(False)
        for _ in range(3):
            self.handler.publish_projection_source()
            self.assertEqual(self.latest()['source'], 0)
            self.assertEqual(self.latest()['evidence'], 'api_disconnected')
        self.assertEqual(old['source'], 1)
        self.handler.set_projection_api_connected(True)
        self.assertEqual(self.latest()['source'], 0)

    def test_heartbeat_snapshot_cannot_enqueue_after_a_new_provider_event(self):
        captured, release, started, new_enqueued = [threading.Event() for _ in range(4)]
        self.handler.projection_source.report('media', 1)
        original = self.handler.projection_source.snapshot
        published = []
        def publish(topic, data):
            if topic == b'HUDIY_PROJECTION':
                published.append(data['source'])
                if data['source'] == 1:
                    new_enqueued.set()
        self.publisher.publish.side_effect = publish
        def delayed_snapshot():
            result = original()
            if threading.current_thread().name == 'test-heartbeat':
                captured.set(); release.wait(2)
            return result
        self.handler.projection_source.snapshot = delayed_snapshot
        heartbeat = threading.Thread(target=self.handler.publish_projection_source, name='test-heartbeat')
        def update():
            self.handler.projection_source.report('media', 2)
            started.set()
            self.handler.publish_projection_source()
        callback = threading.Thread(target=update)
        heartbeat.start()
        try:
            self.assertTrue(captured.wait(1))
            callback.start(); self.assertTrue(started.wait(1))
            out_of_order = new_enqueued.wait(.1)
        finally:
            release.set(); heartbeat.join(2)
            if callback.ident is not None:
                callback.join(2)
        self.assertFalse(out_of_order)
        self.assertEqual(published, [2, 1])


if __name__ == '__main__':
    unittest.main()
