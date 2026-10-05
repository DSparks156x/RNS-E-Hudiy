import time
import unittest
from unittest.mock import patch

from test_animation_recovery import App


class AnimationWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.wall = 100.0
        self.monotonic = 20.0
        for clock_name, getter in (('time', lambda: self.wall), ('monotonic', lambda: self.monotonic)):
            clock = patch.object(time, clock_name, getter)
            clock.start()
            self.addCleanup(clock.stop)
        self.app = App({'display': {'animation_ack_timeout_s': 3}})
        self.app.frames = [[{'cmd': 'draw_raw_bitmap', 'data_hex': f'delta{i}'}] for i in range(3)]
        self.app.full_frames = [[{'cmd': 'draw_raw_bitmap', 'data_hex': f'full{i}'}] for i in range(3)]
        self.app.is_loaded = True
        self.app.on_enter()

    def advance(self, seconds):
        self.wall += seconds
        self.monotonic += seconds

    def pending_delta(self):
        self.app.on_frame_sent(10)
        self.app.on_frame_acked(10)
        self.advance(0.2)
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'delta1')
        self.app.on_frame_sent(11)

    def test_pending_frame_does_not_advance_or_resend_before_deadline(self):
        self.pending_delta()
        generation = self.app._view_generation
        self.advance(2.99)
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'delta1')
        self.assertEqual(self.app._view_generation, generation)
        self.assertFalse(self.app._snapshot_pending)

    def test_lost_ack_restores_same_image_snapshot_at_deadline(self):
        self.pending_delta()
        old_group = self.app.get_view()[1]['group']
        self.advance(3)
        view = self.app.get_view()
        self.assertEqual(view[1]['data_hex'], 'full1')
        self.assertEqual(self.app.current_frame_idx, 1)
        self.assertNotEqual(view[1]['group'], old_group)
        self.assertTrue(self.app._snapshot_pending)
        self.assertIsNone(self.app._pending_since)
        self.advance(20)
        self.assertEqual(self.app.get_view(), view)

    def test_late_ack_cannot_skip_unsent_recovery_snapshot(self):
        self.pending_delta()
        self.advance(3)
        self.app.get_view()
        self.app.on_frame_acked(11)
        self.advance(0.2)
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'full1')
        self.assertEqual(self.app.current_frame_idx, 1)

    def test_late_ack_cannot_ack_newer_recovery_frame(self):
        self.pending_delta()
        self.advance(3)
        self.app.get_view()
        self.app.on_frame_sent(12)
        self.app.on_frame_acked(11)
        self.advance(0.2)
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'full1')
        self.app.on_frame_acked(12)
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'delta2')
        self.assertIsNone(self.app._pending_since)

    def test_acked_frame_does_not_expire_and_advances_normally(self):
        self.pending_delta()
        self.app.on_frame_acked(11)
        generation = self.app._view_generation
        self.advance(3)
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'delta2')
        self.assertEqual(self.app._view_generation, generation)

    def test_wall_clock_jump_does_not_expire_pending_frame(self):
        self.pending_delta()
        self.wall += 100000
        self.monotonic += 1
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'delta1')
        self.wall = -100000
        self.monotonic += 2
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'full1')

    def test_new_entry_clears_old_pending_deadline(self):
        self.pending_delta()
        self.app.on_enter()
        generation = self.app._view_generation
        self.advance(30)
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'full0')
        self.assertEqual(self.app._view_generation, generation)
        self.assertIsNone(self.app._pending_since)

    def test_timeout_configuration_is_finite_and_positive(self):
        self.assertEqual(App().ack_timeout_s, 10)
        self.assertEqual(App({'display': {'animation_ack_timeout_s': '2.5'}}).ack_timeout_s, 2.5)
        for invalid in (0, -1, float('inf'), float('nan'), None, 'bad'):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'finite and positive'):
                    App({'display': {'animation_ack_timeout_s': invalid}})


if __name__ == '__main__':
    unittest.main()
