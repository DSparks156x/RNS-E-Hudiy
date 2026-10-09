"""Exercise video API access and validation without a compositor or real files."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from hudiy_manager.app import create_app
from hudiy_manager.video_control import DEFAULT_SETTINGS, validate_settings, VideoUnavailable


class FakeVideo:
    def __init__(self):
        self.calls = []
        self.failure = False
        self.state = {'available': True, 'status': 'ready', 'outputs': [{'output': 'HDMI-A-1'}],
                      'gamma_protocol': True, 'active': False, 'output': None,
                      'settings': DEFAULT_SETTINGS.copy(), 'saved_profile': None}

    def snapshot(self):
        return copy.deepcopy(self.state)

    def apply(self, settings, output):
        values = validate_settings(settings)
        if self.failure:
            raise VideoUnavailable('Another client owns this output.')
        self.calls.append(('apply', output, values))
        self.state.update(settings=values, output=output, active=True, status='active')
        return self.snapshot()

    def save_profile(self, settings, output):
        values = validate_settings(settings)
        self.calls.append(('profile', output, values))
        self.state['saved_profile'] = {'output': output, 'settings': values}
        return self.snapshot()

    def reset(self):
        self.calls.append(('reset',))
        self.state.update(active=False, status='ready', output=None, settings=DEFAULT_SETTINGS.copy(), saved_profile=None)
        return self.snapshot()

    def close(self):
        pass


class VideoRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'interfaces': {}, 'file_portal': {'upload_pin': '2468'}}))
        self.original = self.config.read_bytes()
        self.video = FakeVideo()
        self.app = create_app(self.root, self.root / 'home', video_controller=self.video,
                              theme_loader=lambda: (None, None))
        self.app.testing = True
        self.client = self.app.test_client()
        self.headers = {'X-Hudiy-Management': '1', 'X-Hudiy-Pin': '2468'}
        self.body = {'settings': DEFAULT_SETTINGS.copy(), 'output': 'HDMI-A-1'}

    def tearDown(self):
        self.temp.cleanup()

    def test_inventory_is_read_only_and_all_mutations_use_existing_access_rules(self):
        self.assertEqual(self.client.get('/api/manage/video').status_code, 200)
        for operation in ('apply', 'profile', 'reset'):
            url = '/api/manage/video/' + operation
            for headers in ({}, {'X-Hudiy-Management': '1'}, {**self.headers, 'Origin': 'https://other.example'}, {**self.headers, 'Sec-Fetch-Site': 'cross-site'}):
                self.assertEqual(self.client.post(url, json=self.body, headers=headers).status_code, 403)
        self.assertEqual(self.video.calls, [])

    def test_live_save_and_reset_are_separate_and_leave_integration_config_untouched(self):
        self.body['settings']['gamma'] = 1.25
        result = self.client.post('/api/manage/video/apply', json=self.body, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.get_json()['active'])
        self.assertIsNone(result.get_json()['saved_profile'])
        saved = self.client.post('/api/manage/video/profile', json=self.body, headers=self.headers)
        self.assertEqual(saved.get_json()['saved_profile']['settings']['gamma'], 1.25)
        reset = self.client.post('/api/manage/video/reset', json={}, headers=self.headers)
        self.assertFalse(reset.get_json()['active'])
        self.assertIsNone(reset.get_json()['saved_profile'])
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_bad_payloads_never_reach_the_compositor(self):
        for data in ('[]', '{bad', '{"settings":{"gamma":NaN}}', '{"padding":"' + 'x' * 8192 + '"}'):
            response = self.client.post('/api/manage/video/apply', data=data,
                                        content_type='application/json', headers=self.headers)
            self.assertEqual(response.status_code, 400)
        invalid = copy.deepcopy(self.body)
        invalid['settings']['black_point'] = .11
        self.assertEqual(self.client.post('/api/manage/video/apply', json=invalid, headers=self.headers).status_code, 400)
        self.assertEqual(self.video.calls, [])

    def test_native_failure_is_reported_as_unavailable_without_marking_applied(self):
        self.video.failure = True
        result = self.client.post('/api/manage/video/apply', json=self.body, headers=self.headers)
        self.assertEqual(result.status_code, 503)
        self.assertIn('Another client', result.get_json()['error'])
        self.assertFalse(self.video.state['active'])
