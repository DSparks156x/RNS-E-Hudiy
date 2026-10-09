"""Regressions for provider callback ordering, bounded clears and power timers."""
import ast
import hashlib
import io
import json
import logging
import os
from queue import Empty, Queue
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dis_client.navigation_state import has_route_content, is_no_route
from hudiy_client.connection_manager import ConnectionManager, ManagerState


REPO = Path(__file__).resolve().parents[1]


def load_handler():
    # The deployed API files are installed separately. Exercise the actual
    # callback class without starting the service or importing that dependency.
    tree = ast.parse((REPO / 'hudiy_client/hudiy_data.py').read_text(encoding='utf-8'))
    constants = {'MANEUVER_TYPE_MAP', 'MANEUVER_SIDE_MAP', 'CALL_STATE_MAP',
                 'CONN_STATE_MAP', 'MEDIA_SOURCE_MAP', 'PROJECTION_PROVIDER_MAP'}
    nodes = [node for node in tree.body if
             (isinstance(node, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id in constants
                 for target in node.targets)) or
             (isinstance(node, ast.ClassDef) and node.name == 'HudiyEventHandler')]
    namespace = dict(ClientEventHandler=object, logger=logging.getLogger(__name__),
                     time=time, os=os, json=json, threading=threading,
                     hashlib=hashlib, io=io, has_route_content=has_route_content,
                     is_no_route=is_no_route,
                     open=Mock(side_effect=OSError('No cache writes in test')))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'hudiy_data.py', 'exec'), namespace)
    return namespace['HudiyEventHandler']


Handler = load_handler()


def load_publisher():
    tree = ast.parse((REPO / 'hudiy_client/hudiy_data.py').read_text(encoding='utf-8'))
    node = next(node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == 'SafePublisher')
    namespace = dict(threading=threading, Queue=Queue, Empty=Empty,
                     json=json, logger=logging.getLogger(__name__),
                     zmq=SimpleNamespace(Context=Mock(), PUB=1))
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'hudiy_data.py', 'exec'), namespace)
    return namespace['SafePublisher'], namespace['zmq']


class Publisher:
    def __init__(self):
        self.events = []

    def publish(self, topic, data):
        self.events.append((topic, data))
        return True

    def latest(self, topic):
        return next(data for name, data in reversed(self.events) if name == topic)


class ManualTimer:
    def __init__(self, interval, callback, args=None):
        self.interval, self.callback, self.args = interval, callback, args or []
        self.cancelled = False
        self.daemon = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        # A canceled real timer may already be waiting on the state lock.
        self.callback(*self.args)


class ProducerReviewTests(unittest.TestCase):
    def setUp(self):
        self.publisher = Publisher()
        self.handler = Handler(self.publisher)
        self.addCleanup(self.handler.stop)

    def status(self, state=1, source=2):
        self.handler.on_navigation_status(None, SimpleNamespace(state=state, source=source))

    def details(self, description='Main St', maneuver_type=4):
        self.handler.on_navigation_maneuver_details(None, SimpleNamespace(
            description=description, maneuver_type=maneuver_type, maneuver_side=2,
            maneuver_angle=0, icon=b''))

    def distance(self, label='200 m'):
        self.handler.on_navigation_maneuver_distance(None, SimpleNamespace(label=label))

    def metadata(self, title='Track'):
        self.handler.on_media_metadata(None, SimpleNamespace(
            artist='Artist' if title else '', title=title, album='',
            duration_label='3:20' if title else '', coverart=b''))

    def media_status(self, source=2, is_playing=True):
        self.handler.on_media_status(None, SimpleNamespace(
            source=source, is_playing=is_playing, position_label='0:10'))

    def test_identical_details_refresh_preserves_matching_distance(self):
        self.status()
        self.details()
        self.distance()
        self.details()
        self.assertEqual(self.publisher.latest(b'HUDIY_NAV')['distance'], '200 m')
        self.details('Pine St')
        self.assertNotIn('distance', self.publisher.latest(b'HUDIY_NAV'))

    def test_known_maneuver_without_labels_waits_for_distance(self):
        self.status()
        self.details('', 4)
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV')['has_route'])
        self.distance()
        self.assertTrue(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.assertEqual(self.publisher.latest(b'HUDIY_NAV')['maneuver_type'], 4)

    def test_known_type_refresh_cannot_lift_explicit_route_end_latch(self):
        self.status()
        self.details()
        self.distance()
        self.details('No route', 4)
        self.details('', 4)
        self.distance()
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV')['has_route'])
        self.details('Pine St', 4)
        self.assertTrue(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])

    def test_inactive_to_active_starts_fresh_icon_and_distance_route(self):
        self.status(state=2)
        self.status()
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.details('', 4)
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.distance()
        self.assertTrue(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])

    def test_repeated_active_after_route_end_cannot_accept_late_distance(self):
        self.status()
        self.details()
        self.distance()
        self.details('No route', 4)
        self.status()
        self.details('', 4)
        self.distance()
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV')['has_route'])

    def test_confirmed_restart_after_route_end_accepts_icon_and_distance(self):
        self.status()
        self.details()
        self.distance()
        self.details('No route', 4)
        self.status(state=2)
        self.status()
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.details('', 4)
        self.distance()
        self.assertTrue(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])

    def test_active_provider_switch_starts_fresh_route_without_old_distance(self):
        self.status(source=1)
        self.details()
        self.distance('100 m')
        self.status(source=2)
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.assertNotIn('distance', self.publisher.latest(b'HUDIY_NAV'))
        self.details('', 4)
        self.distance('500 m')
        self.assertTrue(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])

    def test_distance_cannot_revive_empty_or_explicitly_ended_route(self):
        for clear in (lambda: self.details('', 0), lambda: self.distance('No route')):
            with self.subTest(clear=clear):
                self.status()
                self.details()
                self.distance()
                clear()
                self.status()
                self.distance()
                self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
                self.assertFalse(self.publisher.latest(b'HUDIY_NAV')['has_route'])
                self.details('Pine St')
                self.assertTrue(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])

    def test_distance_after_inactive_stays_cleared_until_confirmed_new_session(self):
        self.status()
        self.details()
        self.distance()
        self.status(state=2)
        self.distance()
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV_STATUS')['active'])
        self.assertFalse(self.publisher.latest(b'HUDIY_NAV')['has_route'])

    def test_absent_proto_state_cannot_activate_cached_route(self):
        self.status()
        self.details()
        self.handler.on_navigation_status(None, SimpleNamespace(
            source=2, state=1, HasField=lambda field: field == 'source'))
        status = self.publisher.latest(b'HUDIY_NAV_STATUS')
        self.assertFalse(status['active'])
        self.assertFalse(status['api_active'])
        self.assertEqual(status['state'], 2)

    def test_media_queue_snapshots_are_not_mutated_by_later_callbacks(self):
        self.media_status()
        snapshot = self.publisher.latest(b'HUDIY_MEDIA')
        self.metadata()
        self.assertEqual(snapshot['title'], '')
        self.metadata('Next Track')
        self.assertEqual(snapshot['title'], '')
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], 'Next Track')

    def test_metadata_after_paused_status_reclassifies_idle_as_paused(self):
        self.media_status(is_playing=False)
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['media_state'], 'IDLE')
        self.metadata()
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['media_state'], 'PAUSED')

    def test_none_source_cannot_leave_playing_true(self):
        self.media_status(source=0)
        self.assertFalse(self.publisher.latest(b'HUDIY_MEDIA')['playing'])
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['media_state'], 'NONE')

    @patch('threading.Timer', ManualTimer)
    def test_transient_blank_keeps_track_and_cover_until_replacement(self):
        self.media_status()
        self.metadata()
        count = len(self.publisher.events)
        self.metadata('')
        pending = self.handler._pending_media_clear
        self.assertEqual(len(self.publisher.events), count)
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], 'Track')
        self.metadata('Next Track')
        self.assertTrue(pending.cancelled)
        pending.fire()
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], 'Next Track')

    @patch('threading.Timer', ManualTimer)
    def test_repeated_empty_metadata_has_bounded_grace_and_clears_on_expiry(self):
        self.media_status()
        self.metadata()
        self.metadata('')
        pending = self.handler._pending_media_clear
        self.metadata('')
        self.assertIs(self.handler._pending_media_clear, pending)
        pending.fire()
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['title'], '')
        self.assertEqual(self.publisher.latest(b'HUDIY_COVERART')['bitmap_hex'], '')
        self.assertIsNone(self.handler._pending_media_clear)

    @patch('threading.Timer', ManualTimer)
    def test_stop_cancels_pending_media_clear(self):
        self.media_status()
        self.metadata()
        self.metadata('')
        pending = self.handler._pending_media_clear
        count = len(self.publisher.events)
        self.handler.stop()
        pending.fire()
        self.assertTrue(pending.cancelled)
        self.assertEqual(len(self.publisher.events), count)

    @patch('threading.Timer', ManualTimer)
    def test_source_switch_cancels_previous_provider_empty_metadata_timer(self):
        self.media_status()
        self.metadata()
        self.metadata('')
        pending = self.handler._pending_media_clear
        self.media_status(source=3)
        count = len(self.publisher.events)
        pending.fire()
        self.assertTrue(pending.cancelled)
        self.assertIsNone(self.handler._pending_media_clear)
        self.assertEqual(len(self.publisher.events), count)
        self.assertEqual(self.publisher.latest(b'HUDIY_MEDIA')['source_id'], 3)

    def test_missing_connection_state_and_disconnect_clear_phone_levels(self):
        self.handler.on_phone_levels_status(None, SimpleNamespace(battery_level=4, signal_level=90))
        self.handler.on_phone_connection_status(None, SimpleNamespace(
            state=1, name='Old Phone', HasField=lambda field: field == 'name'))
        phone = self.publisher.latest(b'HUDIY_PHONE')
        self.assertEqual(phone['connection_state'], 'DISCONNECTED')
        self.assertEqual((phone['name'], phone['battery'], phone['signal']), ('', 0, 0))


class PowerReviewTests(unittest.TestCase):
    def setUp(self):
        with patch.object(ConnectionManager, '_load_config'):
            self.manager = ConnectionManager()
        self.manager._enable_connections = Mock()
        self.manager._disable_connections = Mock()
        self.addCleanup(self.manager.stop)

    def test_default_immediate_disconnect_does_not_deadlock_power_processing(self):
        self.manager.process_power_status({'kl15': True})
        thread = threading.Thread(target=self.manager.process_power_status, args=({},), daemon=True)
        thread.start()
        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive(), 'Immediate disconnect re-entered a non-reentrant lock')
        self.assertEqual(self.manager.state, ManagerState.IDLE_DISCONNECTED)
        self.manager._disable_connections.assert_called_once()

    @patch('hudiy_client.connection_manager.threading.Timer', ManualTimer)
    def test_repeated_inactive_power_messages_do_not_restart_disconnect_delay(self):
        self.manager.disconnect_delay_seconds = 5.0
        self.manager.process_power_status({'kl15': True})
        self.manager.process_power_status({})
        pending = self.manager.disconnect_timer
        for _ in range(10):
            self.manager.process_power_status({})
        self.assertIs(self.manager.disconnect_timer, pending)
        self.assertEqual(self.manager.state, ManagerState.DISCONNECTING)
        pending.fire()
        self.assertEqual(self.manager.state, ManagerState.IDLE_DISCONNECTED)
        self.manager._disable_connections.assert_called_once()

    @patch('hudiy_client.connection_manager.threading.Timer', ManualTimer)
    def test_restored_power_cancels_pending_disconnect(self):
        self.manager.disconnect_delay_seconds = 5.0
        self.manager.process_power_status({'kl15': True})
        self.manager.process_power_status({})
        pending = self.manager.disconnect_timer
        self.manager.process_power_status({'kl15': True})
        pending.fire()
        self.assertTrue(pending.cancelled)
        self.assertEqual(self.manager.state, ManagerState.ACTIVE_CONNECTED)
        self.manager._disable_connections.assert_not_called()

    @patch('hudiy_client.connection_manager.threading.Timer', ManualTimer)
    def test_stopped_manager_ignores_already_waiting_disconnect_callback(self):
        self.manager.disconnect_delay_seconds = 5.0
        self.manager.process_power_status({'kl15': True})
        self.manager.process_power_status({})
        pending = self.manager.disconnect_timer
        self.manager.stop()
        pending.fire()
        self.manager._disable_connections.assert_not_called()

    @patch('hudiy_client.connection_manager.threading.Timer', ManualTimer)
    def test_canceled_disconnect_cannot_fire_in_replacement_delay(self):
        self.manager.disconnect_delay_seconds = 5.0
        self.manager.process_power_status({'kl15': True})
        self.manager.process_power_status({})
        old = self.manager.disconnect_timer
        self.manager.process_power_status({'kl15': True})
        self.manager.process_power_status({})
        replacement = self.manager.disconnect_timer
        old.fire()
        self.assertIs(self.manager.disconnect_timer, replacement)
        self.manager._disable_connections.assert_not_called()
        replacement.fire()
        self.manager._disable_connections.assert_called_once()

    @patch('hudiy_client.connection_manager.threading.Timer', ManualTimer)
    def test_canceled_wake_window_cannot_expire_a_new_window(self):
        self.manager.process_power_status({'door_open': True})
        old = self.manager.window_timer
        self.manager.process_power_status({'door_event': True, 'door_open': True})
        replacement = self.manager.window_timer
        old.fire()
        self.assertIs(self.manager.window_timer, replacement)
        self.assertEqual(self.manager.state, ManagerState.WAKE_WINDOW_ACTIVE)
        self.manager._disable_connections.assert_not_called()
        replacement.fire()
        self.assertEqual(self.manager.state, ManagerState.IDLE_DISCONNECTED)
        self.manager._disable_connections.assert_called_once()


class PublisherReviewTests(unittest.TestCase):
    def setUp(self):
        self.publisher_class, self.zmq = load_publisher()
        self.publisher = self.publisher_class.__new__(self.publisher_class)
        self.publisher.running = True
        self.publisher.zmq_addr = 'test'
        self.publisher.queue = Queue()
        self.context = self.zmq.Context.return_value
        self.socket = self.context.socket.return_value

    def test_bind_failure_closes_resources_and_rejects_future_publications(self):
        self.socket.bind.side_effect = OSError('Address already bound')
        self.publisher._worker()
        self.socket.close.assert_called_once_with(linger=0)
        self.context.term.assert_called_once()
        self.assertFalse(self.publisher.publish(b'TOPIC', {'value': 1}))
        self.assertTrue(self.publisher.queue.empty())

    def test_bad_payload_does_not_break_later_publications_or_queue_accounting(self):
        self.publisher.queue.put((b'BAD', {'value': object()}))
        self.publisher.queue.put((b'GOOD', {'value': 1}))
        self.socket.send_multipart.side_effect = lambda parts: setattr(self.publisher, 'running', False)
        self.publisher._worker()
        self.socket.send_multipart.assert_called_once_with([b'GOOD', b'{"value": 1}'])
        self.assertEqual(self.publisher.queue.unfinished_tasks, 0)
        self.socket.close.assert_called_once_with(linger=0)
        self.context.term.assert_called_once()


if __name__ == '__main__':
    unittest.main()
