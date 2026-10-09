"""Native tile renderer pacing through actual service and TP2 methods; offline."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
if not (REPO / 'dis_client').is_dir():
    REPO = Path(__file__).resolve().parent.parent / 'RNS-E-Hudiy'
sys.path.insert(0, str(REPO / 'tests'))
sys.path.insert(0, str(REPO / 'dis_client'))
import test_native_bitmap_integration_candidate as service_fixture
import test_ddp_framing as transport_fixture


class NativeTilePacing(unittest.TestCase):
    def setUp(self):
        self.fixture = service_fixture.NativeBitmapIntegrationTests()
        self.fixture.setUp()
        self.service = self.fixture.s
        self.service.ddp.state_generation = 1
        self.calls = []
        transfer = self.service.ddp.send_ddp_frame

        def record(payload, pacing=True):
            self.calls.append((list(payload), pacing))
            return transfer(payload, pacing=pacing)

        self.service.ddp.send_ddp_frame = record
        self.command = dict(self.fixture.command, render_order='tiles', delta=True)

    def assert_paced_body(self):
        self.assertTrue(self.calls)
        self.assertTrue(all(pacing for payload, pacing in self.calls))

    def test_full_tiles_are_paced_and_publish_one_matched_result(self):
        self.fixture.expand_draw(self.command)
        self.assertGreater(len(self.calls), 2)
        self.assert_paced_body()
        self.assertEqual(self.calls[-1][0], [0x39])
        self.assertEqual(self.fixture.results, ['DRAW_ACK 71'])

    def test_planes_and_bands_keep_unpaced_native_body(self):
        for order in ('planes', 'bands'):
            with self.subTest(render_order=order):
                self.setUp()
                self.fixture.expand_draw(dict(self.fixture.command, render_order=order))
                self.assertGreater(len(self.calls), 2)
                self.assertTrue(all(not pacing for payload, pacing in self.calls[:-1]))
                self.assertEqual(self.calls[-1], ([0x39], True))
                self.assertEqual(self.fixture.results, ['DRAW_ACK 71'])

    def test_bounded_icons_pause_once_per_message_and_preserve_settings_on_redraw(self):
        command = dict(self.fixture.command, render_order='planes',
                       update_rect=[6, 2, 72, 72], post_message_delay_s=.005)
        with patch.object(service_fixture.time, 'sleep') as sleep:
            self.fixture.expand_draw(command)
        self.assertTrue(all(not paced for _, paced in self.calls[:-1]))
        self.assertEqual(sleep.call_count, len(self.calls) - 1)
        self.assertTrue(all(call.args == (.005,) for call in sleep.call_args_list))
        cached = next(iter(self.service.command_cache.values()))
        self.assertEqual(cached['post_message_delay_s'], .005)
        self.calls.clear()
        with patch.object(service_fixture.time, 'sleep') as sleep:
            self.assertTrue(self.service.handle_redraw())
        self.assertEqual(sleep.call_count, len(self.calls) - 1)

    def test_invalid_message_delays_reject_before_any_drawing(self):
        for delay in (True, -1, .101, '5', float('nan'), float('inf')):
            with self.subTest(delay=delay):
                self.fixture.results.clear()
                self.assertEqual(self.service._expand_draw_command(
                    dict(self.fixture.command, post_message_delay_s=delay)), [])
                self.assertEqual(self.calls, [])
                self.assertEqual(self.fixture.results, ['DRAW_NACK 71'])

    def test_trusted_delta_and_cached_redraw_keep_tile_pacing(self):
        self.fixture.expand_draw(self.command)
        self.calls.clear()
        self.fixture.expand_draw(self.command)
        self.assertEqual(self.calls, [([0x52, 5, 0, 0, 27, 64, 48], True), ([0x39], True)])
        self.calls.clear()
        self.service._native_known_image = None
        self.assertTrue(self.service.handle_redraw())
        self.assertGreater(len(self.calls), 2)
        self.assert_paced_body()
        self.assertEqual(self.calls[-1][0], [0x39])

    def test_mid_body_failure_stops_paced_transfer_without_commit(self):
        self.fixture.outcomes[:] = [True, False]
        self.fixture.expand_draw(self.command)
        self.assertEqual(len(self.calls), 2)
        self.assert_paced_body()
        self.assertNotIn([0x39], [p for p, pacing in self.calls])
        self.assertEqual(self.fixture.results, ['DRAW_NACK 71'])
        self.assertIsNone(self.service._native_known_image)

    def test_generation_change_stops_paced_transfer_and_nacks(self):
        self.service.ddp.poll_bus_events = lambda: setattr(self.service.ddp, 'state_generation', 2)
        self.fixture.expand_draw(self.command)
        self.assertEqual(len(self.calls), 1)
        self.assert_paced_body()
        self.assertEqual(self.fixture.results, ['DRAW_NACK 71'])
        self.assertIsNone(self.service._native_known_image)


class ConfiguredTransportPacing(unittest.TestCase):
    def test_configured_delay_applies_per_ack_block_only_when_enabled(self):
        fixture = transport_fixture.FramingTests()
        for ack_budget, paced, expected_sleeps in ((15, True, 1), (6, True, 3), (15, False, 0)):
            with self.subTest(ack_budget=ack_budget, pacing=paced):
                driver = fixture.driver(byte_budget=ack_budget * 7, frame_budget=ack_budget)
                driver.transport_profile = replace(driver.transport_profile, white_post_message_delay_s=.017)
                with patch.object(transport_fixture.ddp.time, 'sleep') as sleep:
                    self.assertTrue(driver.send_ddp_frame(list(range(105)), pacing=paced))
                self.assertEqual(sleep.call_count, expected_sleeps)
                self.assertEqual([call.args for call in sleep.call_args_list], [(.017,)] * expected_sleeps)
                self.assertEqual([b for frame in fixture.sent for b in frame[1:]], list(range(105)))


if __name__ == '__main__':
    unittest.main()
