from pathlib import Path
import random
import sys
import unittest

REPO = Path(__file__).resolve().parent.parent
if not (REPO / 'dis_client').is_dir():
    REPO = REPO / 'RNS-E-Hudiy'
sys.path[:0] = [str(REPO / 'dis_client'), str(REPO / 'tests')]
from native_bitmap import changed_native_rect, decode_bitmap, compile_plane_delta_payloads
from test_native_service_full_phase import replay
from test_native_bitmap_candidate import wire_replay
import test_native_bitmap_integration_candidate as integration

class NativePlaneDeltaTests(unittest.TestCase):
    def fixture(self):
        fixture = integration.NativeBitmapIntegrationTests()
        fixture.setUp()
        fixture.s.ddp.state_generation = 1
        return fixture

    def test_single_pixel_changes_align_to_real_2x2_cells(self):
        for x, y in ((0, 0), (1, 1), (63, 47), (127, 95)):
            target = bytearray(1536)
            target[y * 16 + x // 8] = 0x80 >> (x % 8)
            self.assertEqual(changed_native_rect(target, bytes(1536)), [x & ~1, y & ~1, 2, 2])
        self.assertIsNone(changed_native_rect(bytes(1536), bytes(1536)))

    def test_real_service_partial_planes_match_full_image_and_preserve_prior(self):
        rng = random.Random(625)
        prior = bytes(rng.randrange(256) for _ in range(1536))
        target = bytearray(prior)
        for y in range(30, 50):
            for byte_x in range(5, 9):
                target[y * 16 + byte_x] = rng.randrange(256)
        f = self.fixture()
        f.s._native_known_image, f.s._native_known_generation = prior, 1
        command = dict(f.command, data_hex=target.hex(), render_order='planes', delta=True)
        f.expand_draw(command)
        self.assertEqual(f.results, ['DRAW_ACK 71'])
        self.assertTrue(all(len(packet) <= 105 for packet in f.sent))
        self.assertEqual(replay(f.sent[:-1], decode_bitmap(prior)), decode_bitmap(target))
        self.assertEqual(f.s._native_known_image, bytes(target))
        cached = next(iter(f.s.command_cache.values()))
        self.assertTrue(cached['delta'])
        self.assertNotIn('update_rect', cached)

    def test_all_subpixel_masks_and_edge_changes_replay_exactly(self):
        rng = random.Random(1239)
        prior = bytes(rng.randrange(256) for _ in range(1536))
        for mask in range(16):
            target = bytearray(prior)
            for x, y in ((0, 0), (126, 94), (42, 26)):
                for bit, dx, dy in ((1, 0, 0), (2, 1, 0), (4, 0, 1), (8, 1, 1)):
                    if mask & bit:
                        px, py = x + dx, y + dy
                        target[py * 16 + px // 8] ^= 0x80 >> (px % 8)
            packets = compile_plane_delta_payloads(target, prior)
            self.assertTrue(all(len(p) <= 105 for p in packets))
            self.assertEqual(replay(packets, decode_bitmap(prior)), decode_bitmap(target))

    def test_partial_failure_retries_opaque_keyframe(self):
        f = self.fixture()
        target = bytes([0x55, 0x63]) * 768
        command = dict(f.command, data_hex=target.hex(), render_order='planes', delta=True)
        f.s._native_known_image, f.s._native_known_generation = bytes(1536), 1
        f.outcomes[:] = [True, False]
        f.expand_draw(command)
        self.assertIsNone(f.s._native_known_image)
        self.assertEqual(f.results[-1], 'DRAW_NACK 71')
        f.sent.clear()
        f.expand_draw(command)
        self.assertEqual(f.results[-1], 'DRAW_ACK 71')
        arbitrary = decode_bitmap(bytes([255]) * 1536)
        self.assertEqual(wire_replay(f.sent[:-1], arbitrary), decode_bitmap(target))

    def test_unchanged_image_sends_no_pixel_updates(self):
        f = self.fixture()
        data = bytes(1536)
        f.s._native_known_image, f.s._native_known_generation = data, 1
        f.expand_draw(dict(f.command, data_hex=data.hex(), render_order='planes', delta=True))
        self.assertEqual(f.sent, [[0x52, 5, 0, 0, 27, 64, 48], [0x39]])

    def test_unknown_or_changed_ownership_forces_full_keyframe(self):
        for prior, generation in ((None, 1), (bytes(1536), 0)):
            f = self.fixture()
            f.s._native_known_image, f.s._native_known_generation = prior, generation
            f.expand_draw(dict(f.command, render_order='planes', delta=True))
            self.assertGreater(len(f.sent), 3)
            self.assertEqual(f.sent[0], [0x52, 5, 0, 0, 27, 64, 48])

    def test_failed_delta_forgets_prior_and_nacks(self):
        f = self.fixture()
        f.s._native_known_image, f.s._native_known_generation = bytes(1536), 1
        f.outcomes[:] = [False]
        f.expand_draw(dict(f.command, render_order='planes', delta=True))
        self.assertEqual(len(f.sent), 1)
        self.assertEqual(f.results, ['DRAW_NACK 71'])
        self.assertIsNone(f.s._native_known_image)

if __name__ == '__main__':
    unittest.main()
