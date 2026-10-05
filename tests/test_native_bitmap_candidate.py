"""Portable compiler consistency for the physically verified native XOR basis."""
import random
from pathlib import Path
import sys
import unittest

REPO_MODULES = Path(__file__).resolve().parent.parent / 'dis_client'
if REPO_MODULES.exists():
    sys.path.insert(0, str(REPO_MODULES))
from native_bitmap import MODEL, compile_native_bitmap, compile_native_payloads, decode_bitmap, pack_native_records


def encode_grid(grid):
    data = bytearray(1536)
    for y, row in enumerate(grid):
        for x, pattern in enumerate(row):
            for bit, dx, dy in ((1, 0, 0), (2, 1, 0), (4, 0, 1), (8, 1, 1)):
                if pattern & bit:
                    px, py = x * 2 + dx, y * 2 + dy
                    data[py * 16 + px // 8] |= 0x80 >> (px % 8)
    return bytes(data)


def replay(commands, initial):
    grid = [list(row) for row in initial]
    for command in commands:
        if command['command'] == 'draw_raw_bitmap':
            data = bytes.fromhex(command['data_hex'])
            for row in range(command['h']):
                y = command['y'] + row
                for x in range(64):
                    selected = bool(data[row * 8 + x // 8] & (0x80 >> (x % 8)))
                    if command['mode_flag'] == 2:
                        grid[y][x] = 15 if selected else 0
                    elif selected:
                        grid[y][x] ^= 15
        else:
            orientation, x, y = command['orientation'], command['x'], command['y']
            for offset in range(command['length']):
                px, py = (x, y + offset) if orientation == 0x10 else (x + offset, y)
                if orientation == 0x10:
                    grid[py][px] ^= 5
                elif orientation == 0x20:
                    grid[py][px] ^= 3
                else:
                    grid[py][px] ^= 1
    return grid


def wire_replay(packets, initial):
    grid = [list(row) for row in initial]
    for packet in packets:
        at, last = 0, None
        while at < len(packet):
            length = packet[at + 1] + 2
            record = packet[at:at + length]
            if len(record) != length:
                raise AssertionError('Split record')
            if record[0] == 0x55:
                for index, value in enumerate(record[5:]):
                    y, byte_x = record[4] + index // 8, index % 8
                    for bit in range(8):
                        x, selected = byte_x * 8 + bit, bool(value & (0x80 >> bit))
                        if record[2] == 2:
                            grid[y][x] = 15 if selected else 0
                        elif selected:
                            grid[y][x] ^= 15
            elif record[0] == 0x63:
                if last not in ([0x55, 11, 1, 0, 47] + [0] * 8, [0x55, 4, 1, 0, 47, 0]):
                    raise AssertionError('Stroke lacks immediate same-packet selector')
                orientation, x, y, count = record[2:]
                for offset in range(count):
                    px, py = (x, y + offset) if orientation == 0x10 else (x + offset, y)
                    grid[py][px] ^= {0: 1, 0x10: 5, 0x20: 3}[orientation]
            elif record != [0x52, 5, 0, 0, 27, 64, 48]:
                raise AssertionError('Unexpected command')
            last, at = record, at + length
    return grid


class NativeBitmapCandidateTests(unittest.TestCase):
    def test_planes_and_bands_exact_all_patterns_and_random_prior_pixels(self):
        rng = random.Random(52163)
        grids = ([[((x + y) % 16) for x in range(64)] for y in range(48)],
                 [[rng.randrange(16) for _ in range(64)] for _ in range(48)])
        for grid in grids:
            prior = [[rng.randrange(16) for _ in range(64)] for _ in range(48)]
            for order, band in (('planes', 12), ('bands', 1), ('bands', 7), ('bands', 12), ('bands', 48)):
                with self.subTest(order=order, band=band):
                    packets = compile_native_payloads(encode_grid(grid), rows_per_command=12,
                                                       render_order=order, band_rows=band)
                    self.assertTrue(all(len(packet) <= 105 for packet in packets))
                    self.assertEqual(wire_replay(packets, prior), grid)

    def test_band_order_completes_first_band_before_next_opaque_base(self):
        from native_bitmap import compile_native_records
        records = compile_native_records(encode_grid([[1] * 64 for _ in range(48)]),
                                         rows_per_command=12, render_order='bands', band_rows=12)
        bases = [i for i, record in enumerate(records) if record[0] == 0x55 and record[2] == 2]
        self.assertEqual([records[i][4] for i in bases], [0, 12, 24, 36])
        for index, base in enumerate(bases):
            end = bases[index + 1] if index + 1 < len(bases) else len(records)
            self.assertTrue(any(record[0] == 0x63 for record in records[base + 1:end]))
            base_y = index * 12
            self.assertTrue(all(base_y <= record[4] < base_y + 12 for record in records[base + 1:end]
                                if record[0] == 0x63))

    def test_render_order_and_band_height_validation(self):
        for fields in (dict(render_order='unknown'), dict(render_order=[]), dict(band_rows=0),
                       dict(band_rows=49), dict(band_rows=True), dict(band_rows=12.0)):
            with self.assertRaises(ValueError):
                compile_native_payloads(bytes(1536), **fields)

    def test_msb_physical_rows_decode_all_sixteen_cell_patterns(self):
        grid = [[(x + y * 64) % 16 for x in range(64)] for y in range(48)]
        self.assertEqual(decode_bitmap(encode_grid(grid)), grid)
        data = bytearray(1536)
        data[0], data[16] = 0x80, 0x40
        self.assertEqual(decode_bitmap(data)[0][0], 9)

    def test_random_full_snapshot_overwrites_arbitrary_prior_under_explicit_model(self):
        rng = random.Random(519)
        grid = [[rng.randrange(16) for _ in range(64)] for _ in range(48)]
        prior = [[rng.randrange(16) for _ in range(64)] for _ in range(48)]
        commands = compile_native_bitmap(encode_grid(grid), model=MODEL)
        self.assertEqual(replay(commands, prior), grid)
        self.assertEqual(commands[0]['h'], 48)
        self.assertEqual(commands[0]['mode_flag'], 2)
        self.assertTrue(commands[0]['_native_bitmap_snapshot'])
        self.assertEqual(len(bytes.fromhex(commands[0]['data_hex'])), 384)

    def test_all_patterns_keep_strokes_bounded_and_prime_each_plane(self):
        grid = [[(x + y) % 16 for x in range(64)] for y in range(48)]
        commands = compile_native_bitmap(encode_grid(grid), model=MODEL)
        self.assertEqual(replay(commands, [[7] * 64 for _ in range(48)]), grid)
        self.assertTrue(all(command['_native_bitmap_ephemeral'] for command in commands))
        self.assertFalse(any(command['command'] in ('commit', 'frame') for command in commands))
        for command in commands:
            self.assertGreaterEqual(command['x'], 0)
            self.assertGreaterEqual(command['y'], 0)
            if command['command'] == 'draw_line':
                if command['orientation'] == 0:
                    self.assertEqual(command['length'], 1)
                else:
                    self.assertLessEqual(command['length'], 15)
                    axis = command['y'] if command['orientation'] == 0x10 else command['x']
                    self.assertLessEqual(axis + command['length'], 48 if command['orientation'] == 0x10 else 64)
            else:
                self.assertLessEqual(command['y'] + command['h'], 48)
                self.assertIn(command['mode_flag'], (1, 2))
                self.assertEqual(len(bytes.fromhex(command['data_hex'])), command['h'] * 8)

    def test_invalid_input_or_unspecified_model_is_rejected(self):
        for data in (bytes(1535), bytes(1537), '00' * 1536):
            with self.assertRaises(ValueError):
                compile_native_bitmap(data, model=MODEL)
        with self.assertRaises(ValueError):
            compile_native_bitmap(bytes(1536), model='unverified-other')
        self.assertEqual(len(compile_native_bitmap(bytes(1536))), 1)

    def test_full_black_and_white_need_no_native_line_strokes(self):
        for value in (0, 255):
            commands = compile_native_bitmap(bytes([value]) * 1536, model=MODEL)
            self.assertEqual(len(commands), 1)
            self.assertEqual(bytes.fromhex(commands[0]['data_hex']), bytes([value]) * 384)

    def test_pil_mode1_and_bytes_have_identical_commands_without_implicit_transform(self):
        from PIL import Image
        packed = bytes([0xaa, 0xcc] * 768)
        image = Image.frombytes('1', (128, 96), packed)
        self.assertEqual(compile_native_bitmap(image), compile_native_bitmap(packed))
        for bad in (Image.new('L', (128, 96)), Image.new('1', (64, 48))):
            with self.assertRaises(ValueError):
                compile_native_bitmap(bad)

    def test_prime_is_zero_mask_mode1_before_every_axis_group(self):
        grid = [[(x + y) % 16 for x in range(64)] for y in range(48)]
        commands = compile_native_bitmap(encode_grid(grid))
        current_axis, primes = None, []
        for command in commands[1:]:
            if command.get('_native_rop_prime'):
                primes.append(command)
                current_axis = None
                self.assertEqual(command['mode_flag'], 1)
                self.assertEqual(command['y'], 47)
                self.assertEqual(command['data_hex'], '00' * 8)
            else:
                if current_axis is None:
                    self.assertTrue(primes)
                    current_axis = command['orientation']
                self.assertEqual(command['orientation'], current_axis)
        self.assertEqual(len(primes), 3)

    def test_wire_every_stroke_primed_after_run_split_and_packet_flush(self):
        rng = random.Random(521)
        grid = [[rng.randrange(16) for _ in range(64)] for _ in range(48)]
        prior = [[rng.randrange(16) for _ in range(64)] for _ in range(48)]
        for budget, rows in ((42, 1), (105, 8), (19, 12)):
            with self.subTest(budget=budget, rows=rows):
                packets = compile_native_payloads(encode_grid(grid), budget=budget, rows_per_command=rows)
                self.assertTrue(all(len(packet) <= budget for packet in packets))
                self.assertEqual(packets[0], [0x52, 5, 0, 0, 27, 64, 48])
                self.assertEqual(wire_replay(packets, prior), grid)

    def test_verified_short_selector_reduces_cost_with_identical_geometry(self):
        grid = [[1] * 64 for _ in range(48)]
        source = encode_grid(grid)
        long_selector = compile_native_payloads(source, selector_bytes=8)
        short_selector = compile_native_payloads(source, selector_bytes=1)
        self.assertLess(sum(map(len, short_selector)), sum(map(len, long_selector)))
        self.assertEqual(wire_replay(short_selector, [[15] * 64 for _ in range(48)]), grid)
        with self.assertRaises(AssertionError):
            wire_replay(compile_native_payloads(source, priming='message'), grid)

    def test_native_wire_rejects_unknown_opcode_malformed_length_and_bounds(self):
        for record in ([0xa8], [0x57, 4, 2, 0, 0, 0], [0x63, 4, 0, 0, 0, 0],
                       [0x63, 4, 0x20, 63, 0, 15], [0x55, 4, 1, 0, 47, 0xff],
                       [0x55, 11, 2, 0, 48] + [0] * 8):
            with self.subTest(record=record):
                with self.assertRaises(ValueError):
                    pack_native_records([record])


if __name__ == '__main__':
    unittest.main()
