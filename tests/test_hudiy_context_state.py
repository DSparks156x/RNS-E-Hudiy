"""API event sequences without starting Hudiy clients or ZMQ sockets."""
import ast
import json
import logging
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'dis_client'))
from navigation_state import has_route_content
from apps.nav import NavApp
from apps.phone import PhoneApp


def handler_class():
    tree = ast.parse((REPO / 'hudiy_client/hudiy_data.py').read_text(encoding='utf-8'))
    names = {'MANEUVER_TYPE_MAP', 'MANEUVER_SIDE_MAP', 'CALL_STATE_MAP',
             'CONN_STATE_MAP', 'MEDIA_SOURCE_MAP', 'PROJECTION_PROVIDER_MAP'}
    selected = [node for node in tree.body if
                (isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id in names
                    for target in node.targets)) or
                (isinstance(node, ast.ClassDef) and node.name == 'HudiyEventHandler')]
    from navigation_state import is_no_route
    namespace = {'ClientEventHandler': object, 'logger': logging.getLogger(__name__),
                 'time': time, 'os': os, 'json': json,
                 'has_route_content': has_route_content, 'is_no_route': is_no_route,
                 'open': Mock(side_effect=OSError('Test has no disk cache'))}
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'hudiy_data.py', 'exec'), namespace)
    return namespace['HudiyEventHandler']


Handler = handler_class()


class Publisher:
    def __init__(self):
        self.events = []

    def publish(self, topic, data):
        # Keep actual objects to detect mutable snapshots handed to the queue.
        self.events.append((topic, data))
        return True

    def latest(self, topic):
        return next(data for name, data in reversed(self.events) if name == topic)


class NavigationProducerTests(unittest.TestCase):
    def setUp(self):
        self.publisher = Publisher()
        self.handler = Handler(self.publisher)
        self.app = NavApp({})

    def status(self, source=2, state=1):
        self.handler.on_navigation_status(None, SimpleNamespace(source=source, state=state))

    def details(self, description='Main St', maneuver=4):
        self.handler.on_navigation_maneuver_details(None, SimpleNamespace(
            description=description, maneuver_type=maneuver,
            maneuver_side=2, maneuver_angle=0, icon=b''))

    def distance(self, label='200 m'):
        self.handler.on_navigation_maneuver_distance(None, SimpleNamespace(label=label))

    def active(self):
        return self.publisher.latest(b'HUDIY_NAV_STATUS')['active']

    def consumer(self):
        self.app.update_hudiy(b'HUDIY_NAV', self.publisher.latest(b'HUDIY_NAV'))
        return self.app

    def test_carplay_active_without_route_never_activates_navigation(self):
        self.status()
        self.assertFalse(self.active())
        self.assertTrue(self.publisher.latest(b'HUDIY_NAV_STATUS')['api_active'])
        self.details('', 0)
        self.distance('')
        self.assertFalse(self.active())
        self.assertFalse(self.consumer().has_route)

    def test_empty_details_clear_old_distance_despite_carplay_active_status(self):
        self.status()
        self.details()
        self.distance()
        self.assertTrue(self.active())
        self.assertTrue(self.consumer().has_route)
        self.details('', 0)
        self.assertFalse(self.active())
        self.assertFalse(self.consumer().has_route)
        self.assertEqual(self.app.distance_label, '')
        self.status()
        self.assertFalse(self.active())

    def test_no_route_placeholder_overrides_stale_known_maneuver(self):
        self.status()
        self.details()
        self.distance()
        self.details('No route', 4)
        self.assertFalse(self.active())
        self.assertFalse(self.consumer().has_route)

    def test_explicit_no_route_distance_clears_maneuver(self):
        self.status()
        self.details()
        self.distance('No route')
        self.assertFalse(self.active())
        self.assertFalse(self.consumer().has_route)

    def test_aa_status_before_details_and_details_before_status_both_work(self):
        for status_first in (False, True):
            self.setUp()
            if status_first:
                self.status(source=1)
                self.assertFalse(self.active())
            self.details()
            if not status_first:
                self.assertFalse(self.active())
                self.status(source=1)
            self.assertTrue(self.active())
            self.assertTrue(self.consumer().has_route)

    def test_details_before_activation_after_initial_none_status_are_preserved(self):
        self.status(source=0, state=2)
        self.details()
        self.status(source=1)
        self.assertTrue(self.active())
        self.assertEqual(self.consumer().description, 'Main St')

    def test_source_none_cannot_activate_navigation(self):
        self.details()
        self.status(source=0, state=1)
        self.assertFalse(self.active())

    def test_absent_proto2_side_defaults_to_unspecified_not_left(self):
        self.status(source=1)
        message = SimpleNamespace(description='Continue', maneuver_type=14,
                                  maneuver_side=1, maneuver_angle=0, icon=b'',
                                  HasField=lambda field: False)
        self.handler.on_navigation_maneuver_details(None, message)
        self.assertEqual(self.publisher.latest(b'HUDIY_NAV')['maneuver_side'], 3)

    def test_known_maneuver_without_street_waits_for_matching_distance(self):
        self.status(source=1)
        self.details('', 14)
        self.assertFalse(self.active())
        self.assertFalse(self.consumer().has_route)
        self.distance('200 m')
        self.assertTrue(self.active())
        self.assertTrue(self.consumer().has_route)

    def test_new_maneuver_never_inherits_previous_distance(self):
        self.status(source=1)
        self.details()
        self.distance()
        previous = self.publisher.latest(b'HUDIY_NAV')
        self.details('Pine St', 14)
        self.assertNotIn('distance', self.publisher.latest(b'HUDIY_NAV'))
        self.assertEqual(previous['description'], 'Main St')
        self.assertEqual(previous['distance'], '200 m')
        self.assertEqual(self.consumer().meters, -1)

    def test_inactive_status_clears_route_and_repeated_active_cannot_restore_it(self):
        self.status(source=1)
        self.details()
        self.distance()
        self.status(source=1, state=2)
        self.assertFalse(self.active())
        self.assertFalse(self.consumer().has_route)
        self.status(source=1)
        self.assertFalse(self.active())

    def test_switching_provider_cannot_reuse_old_route(self):
        self.status(source=1)
        self.details()
        self.distance()
        self.status(source=2)
        self.assertFalse(self.active())
        self.assertFalse(self.consumer().has_route)
        self.details('Oak Avenue', 3)
        self.assertTrue(self.active())

    def test_distance_zero_without_description_is_route_content(self):
        self.status(source=1)
        self.distance(0)
        self.assertTrue(self.active())
        self.assertTrue(self.consumer().has_route)

    def test_blank_partial_distance_preserves_existing_maneuver(self):
        self.status(source=1)
        self.details()
        self.distance('')
        self.assertTrue(self.active())
        self.assertTrue(self.consumer().has_route)
        self.assertEqual(self.app.meters, -1)


class ContextConsumerTests(unittest.TestCase):
    def test_explicit_absence_overrides_old_route_fields(self):
        app = NavApp({})
        app.update_hudiy(b'HUDIY_NAV', {'description': 'Main St', 'distance': '100 m'})
        app.update_hudiy(b'HUDIY_NAV', {'description': 'Main St', 'distance': '100 m',
                                     'maneuver_type': 4, 'has_route': False})
        self.assertFalse(app.has_route)
        self.assertEqual(app.description, '')
        self.assertEqual(app.meters, -1)

    def test_unknown_status_labels_and_whitespace_are_not_a_route(self):
        for data in ({'description': '  ', 'distance': ''},
                     {'distance': 'Unknown'}, {'distance': 'Soon'},
                     {'description': 'No route', 'maneuver_type': 4},
                     {'has_route': True}):
            with self.subTest(data=data):
                app = NavApp({})
                app.update_hudiy(b'HUDIY_NAV', data)
                self.assertFalse(app.has_route)

    def test_phone_active_flags_or_connection_alone_are_not_live_call(self):
        for data in ({'connection_state': 'CONNECTED'}, {'active': True},
                     {'state': 'CONNECTED'}, {'call_active': True},
                     {'state': 'ACTIVE', 'call_active': False}):
            with self.subTest(data=data):
                app = PhoneApp({})
                app.update_hudiy(b'HUDIY_PHONE', data)
                self.assertFalse(app.has_phone)

    def test_all_live_call_states_and_return_to_idle(self):
        app = PhoneApp({})
        for state in ('INCOMING', 'ALERTING', 'DIALING', 'ACTIVE'):
            app.update_hudiy(b'HUDIY_PHONE', {'state': state, 'caller_name': 'Alice'})
            self.assertTrue(app.has_phone)
        app.update_hudiy(b'HUDIY_PHONE', {'state': 'IDLE', 'caller_name': 'Alice'})
        self.assertFalse(app.has_phone)
        self.assertEqual(app.caller_name, '')


class PhoneProducerTests(unittest.TestCase):
    def setUp(self):
        self.publisher = Publisher()
        self.handler = Handler(self.publisher)
        self.app = PhoneApp({})

    def connection(self, state=1):
        self.handler.on_phone_connection_status(None, SimpleNamespace(state=state, name='Android'))

    def call(self, state):
        self.handler.on_phone_voice_call_status(None, SimpleNamespace(
            state=state, caller_name='Alice', caller_id='123456'))

    def consumer(self):
        self.app.update_hudiy(b'HUDIY_PHONE', self.publisher.latest(b'HUDIY_PHONE'))
        return self.app

    def test_connection_and_levels_never_activate_page(self):
        self.connection()
        self.handler.on_phone_levels_status(None, SimpleNamespace(battery_level=4, signal_level=80))
        self.assertFalse(self.consumer().has_phone)
        self.assertFalse(self.publisher.latest(b'HUDIY_PHONE')['call_active'])

    def test_call_lifecycle_uses_call_state_and_clears_caller_on_end(self):
        self.connection()
        for state in (1, 2, 3):
            self.call(state)
            self.assertTrue(self.consumer().has_phone)
        self.call(0)
        self.assertFalse(self.consumer().has_phone)
        self.assertEqual(self.publisher.latest(b'HUDIY_PHONE')['caller_id'], '')

    def test_disconnect_clears_stale_call_and_reconnect_does_not_resurrect_it(self):
        self.connection()
        self.call(3)
        old = self.publisher.latest(b'HUDIY_PHONE')
        self.connection(2)
        self.assertFalse(self.consumer().has_phone)
        self.assertEqual(old['state'], 'ACTIVE')
        self.assertEqual(old['caller_name'], 'Alice')
        self.connection(1)
        self.assertFalse(self.consumer().has_phone)


if __name__ == '__main__':
    unittest.main()
