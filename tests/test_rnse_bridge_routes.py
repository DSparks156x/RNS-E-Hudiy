"""Offline manager bridge contracts; no sockets, video worker or CAN hardware."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from hudiy_manager.app import create_app
from hudiy_manager.config_store import ConfigStore
from hudiy_manager.rnse_bridge import BridgeUnavailable, RnseBridgeClient


class BridgeRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.endpoint = 'ipc:///run/rnse_control/rnse_control.ipc'
        self.document = {'interfaces': {'zmq': {'rnse_control_command': self.endpoint}},
                         'file_portal': {'upload_pin': '2468'}}
        self.config.write_text(json.dumps(self.document))
        self.original = self.config.read_bytes()
        self.exchange = Mock(return_value={'state': 'ready', 'queued': False})
        self.bridge = RnseBridgeClient(ConfigStore(self.root, self.root / 'home'), self.exchange)
        self.app = create_app(self.root, self.root / 'home', video_controller=Mock(),
                              bridge_client=self.bridge, theme_loader=lambda: (None, None))
        self.app.testing = True
        self.client = self.app.test_client()
        self.headers = {'X-Hudiy-Management': '1', 'X-Hudiy-Pin': '2468'}
        self.url = '/api/manage/rnse-control'

    def test_get_only_requests_status_and_mutation_urls_reject_get(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.exchange.assert_called_once_with(self.endpoint, {'action': 'status'})
        for action in ('manual', 'reload', 'resume'):
            self.assertIn(self.client.get(self.url + '/' + action).status_code, (404, 405))
        self.assertEqual(self.exchange.call_count, 1)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_access_header_pin_origin_and_fetch_site_guard_both_mutations(self):
        for action in ('manual', 'reload'):
            for headers in ({}, {'X-Hudiy-Management': '1'},
                            {**self.headers, 'X-Hudiy-Pin': 'wrong'},
                            {**self.headers, 'Origin': 'https://other.example'},
                            {**self.headers, 'Sec-Fetch-Site': 'cross-site'},
                            {**self.headers, 'Sec-Fetch-Site': 'same-site'}):
                with self.subTest(action=action, headers=headers):
                    self.assertEqual(self.client.post(self.url + '/' + action, json={}, headers=headers).status_code, 403)
        self.exchange.assert_not_called()

    def test_manual_partial_bounds_and_reload_leave_saved_configuration_untouched(self):
        for values in ({'brightness': 0}, {'brightness': 10}, {'lcd_brightness': 0},
                       {'lcd_brightness': 100}, {'brightness': 5, 'lcd_brightness': 2}):
            result = self.client.post(self.url + '/manual', json=values, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.exchange.assert_called_with(self.endpoint, {'action': 'manual', 'values': values})
        self.assertEqual(self.client.post(self.url + '/reload', json={}, headers=self.headers).status_code, 200)
        self.exchange.assert_called_with(self.endpoint, {'action': 'reload'})
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_bad_values_json_body_and_reload_paths_never_reach_bridge(self):
        for values in ({}, {'brightness': -1}, {'brightness': 11}, {'brightness': True},
                       {'brightness': 1.5}, {'brightness': '5'}, {'brightness': None},
                       {'lcd_brightness': -1}, {'lcd_brightness': 101}, {'source': 2}):
            with self.subTest(values=values):
                self.assertEqual(self.client.post(self.url + '/manual', json=values, headers=self.headers).status_code, 400)
        for data in ('[]', '{bad', '{"brightness":NaN}', '{"padding":"' + 'x' * 4096 + '"}'):
            for action in ('manual', 'reload'):
                self.assertEqual(self.client.post(self.url + '/' + action, data=data,
                    content_type='application/json', headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post(self.url + '/reload', json={'path': 'other.json'}, headers=self.headers).status_code, 400)
        self.exchange.assert_not_called()

    def test_endpoint_is_exact_absolute_local_ipc_and_cannot_redirect_to_tcp(self):
        for endpoint in ('tcp://127.0.0.1:5555', 'ipc://relative', 'ipc:///bad\x00path', None):
            self.document['interfaces']['zmq']['rnse_control_command'] = endpoint
            self.config.write_text(json.dumps(self.document))
            self.assertEqual(self.client.get(self.url).status_code, 400)
        self.exchange.assert_not_called()

    def test_unavailable_and_invalid_replies_report_503(self):
        for result in (None, [], {'error': 'Producer stopped.', 'status': 503}):
            self.exchange.return_value = result
            self.assertEqual(self.client.get(self.url).status_code, 503)
        self.exchange.side_effect = BridgeUnavailable('Producer stopped.')
        self.assertEqual(self.client.post(self.url + '/manual', json={'brightness': 5}, headers=self.headers).status_code, 503)
        self.assertEqual(self.config.read_bytes(), self.original)
