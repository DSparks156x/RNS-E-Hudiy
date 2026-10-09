"""Bounded native planes preserve arbitrary pixels outside their reserved ROI."""
from pathlib import Path
import random
import sys
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / 'dis_client'), str(REPO / 'tests')]
from native_bitmap import compile_native_payloads, decode_bitmap, validate_update_rect
from nav_icons import ICON_NAMES, canvas_for_icon
from test_native_service_full_phase import replay

FULL = [0x52, 5, 0, 0, 27, 64, 48]


def records(packets):
    for packet in packets:
        at = 0
        while at < len(packet):
            end = at + packet[at + 1] + 2
            yield packet[at:end]
            at = end


class BoundedPlaneTests(unittest.TestCase):
    def assert_patch(self, target, prior, rect, rows=12):
        packets = compile_native_payloads(target, render_order='planes',
                                         update_rect=rect, rows_per_command=rows)
        self.assertTrue(all(0 < len(packet) <= 105 for packet in packets))
        self.assertEqual(packets[-1][-7:], FULL)
        result, desired = replay(packets, prior), decode_bitmap(target)
        x0, y0, w, h = [value // 2 for value in rect]
        for y in range(48):
            for x in range(64):
                expected = desired[y][x] if x0 <= x < x0 + w and y0 <= y < y0 + h else prior[y][x]
                self.assertEqual(result[y][x], expected, (rect, x, y))
        return packets

    def test_all44_maps_icons_over_arbitrary_surroundings(self):
        rng = random.Random(3217)
        prior = decode_bitmap(bytes(rng.randrange(256) for _ in range(1536)))
        self.assertEqual(len(ICON_NAMES), 44)
        for name in ICON_NAMES:
            with self.subTest(icon=name):
                self.assert_patch(canvas_for_icon(name), prior, [6, 2, 72, 72])

    def test_random_rasters_small_edge_full_and_non_byte_aligned_rectangles(self):
        rng = random.Random(982)
        target = bytes(rng.randrange(256) for _ in range(1536))
        prior = decode_bitmap(bytes(rng.randrange(256) for _ in range(1536)))
        for rect in ([0, 0, 2, 2], [126, 94, 2, 2], [2, 4, 6, 30],
                     [12, 8, 34, 74], [0, 0, 128, 96]):
            with self.subTest(rect=rect):
                self.assert_patch(target, prior, rect)

    def test_base_chunks_have_own_clip_zero_raster_offset_and_requested_row_cap(self):
        prior = decode_bitmap(bytes(1536))
        packets = self.assert_patch(bytes([0xff]) * 1536, prior, [6, 2, 72, 72], rows=5)
        clip = None
        chunks = []
        previous = None
        for record in records(packets):
            if record[0] == 0x52:
                clip = record
            elif record[0] == 0x55 and record[2] == 2:
                self.assertEqual(previous, clip)
                self.assertEqual(record[3:5], [0, 0])
                self.assertLessEqual(clip[6], 5)
                self.assertEqual(len(record) - 5, 5 * clip[6])
                chunks.append(clip)
            previous = record
        self.assertEqual([chunk[4] for chunk in chunks], [28, 33, 38, 43, 48, 53, 58, 63])

    def test_every_correction_is_primed_in_the_same_message(self):
        rng = random.Random(55)
        packets = compile_native_payloads(bytes(rng.randrange(256) for _ in range(1536)),
            render_order='planes', update_rect=[6, 2, 72, 72], rows_per_command=12)
        count = 0
        for packet in packets:
            previous = None
            for record in records([packet]):
                if record[0] == 0x63:
                    self.assertEqual(previous, [0x55, 4, 1, 0, 0, 0])
                    count += 1
                previous = record
        self.assertGreater(count, 0)

    def test_unsupported_profiles_orders_and_delta_are_rejected(self):
        for changes in ({'budget': 42}, {'priming': 'message'}, {'selector_bytes': 8},
                        {'render_order': 'bands'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                compile_native_payloads(bytes(1536), update_rect=[6, 2, 72, 72],
                                        **dict({'render_order': 'planes'}, **changes))
        for order in ('planes', 'tiles', 'bands'):
            with self.subTest(order=order), self.assertRaises(ValueError):
                validate_update_rect([6, 2, 72, 72], order, delta=True)

    def test_malformed_rectangles_and_bitmap_size_are_rejected(self):
        for rect in ([5, 2, 72, 72], [6, 3, 72, 72], [6, 2, 71, 72], [6, 2, 72, 71],
                     [128, 2, 2, 2], [6, 2, 124, 72], [6, 2, 72, 96], [True, 2, 72, 72],
                     [6., 2, 72, 72], [6, 2, 0, 72], [6, 2, 72], '6,2,72,72'):
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                compile_native_payloads(bytes(1536), render_order='planes', update_rect=rect)
        with self.assertRaises(ValueError):
            compile_native_payloads(bytes(1535), render_order='planes', update_rect=[6, 2, 72, 72])


if __name__ == '__main__':
    unittest.main()
