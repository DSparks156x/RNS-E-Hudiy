"""Offline candidate row grouping, exact raster coverage, and matched frame feedback."""
import ast
import logging
import os
import unittest
from pathlib import Path
from types import SimpleNamespace

DEFAULT_SOURCE = Path(__file__).resolve().parent / 'dis_service_bitmap_rows_candidate.py'
if not DEFAULT_SOURCE.exists():
    DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / 'dis_client/dis_service.py'
SOURCE = Path(os.environ.get('DIS_BITMAP_ROWS_SOURCE', DEFAULT_SOURCE))
TREE = ast.parse(SOURCE.read_text())
NAMES = {'_bitmap_message_budget', '_bitmap_rows_per_command', '_bitmap_row_records',
         '_finish_frame', 'commit_frame', '_send_graphics', '_publish_frame_result',
         '_coalesce_bitmap_commands', '_raw_bitmap_payload', '_send_raw_bitmap_batch',
         'get_bitmap_payload', 'draw_bitmap', 'handle_redraw'}
ICON_DATA = bytes((i * 13 + 7) & 255 for i in range(8 * 9))
NS = dict(logger=logging.getLogger(__name__), List=list, DDPError=RuntimeError,
    DisMode=SimpleNamespace(WHITE='white'), BITMAPS={'probe': dict(w=64, h=9, data=ICON_DATA)},
    zmq=SimpleNamespace(NOBLOCK=1, ZMQError=RuntimeError))
exec(compile(ast.Module(body=[node for node in ast.walk(TREE)
    if isinstance(node, ast.FunctionDef) and node.name in NAMES], type_ignores=[]),
    str(SOURCE), 'exec'), NS)
Service = type('Service', (), {name: NS[name] for name in NAMES})
LOOP = max([node for node in ast.walk(TREE) if isinstance(node, ast.For)
    and isinstance(node.target, ast.Name) and node.target.id == 'cmd'
    and isinstance(node.iter, ast.Name) and node.iter.id == 'cmds'], key=lambda node: len(node.body))
BODY = next(value for node in ast.walk(TREE) for _, value in ast.iter_fields(node)
    if isinstance(value, list) and any(item is LOOP for item in value))
CODE = compile(ast.Module(body=BODY[BODY.index(LOOP):], type_ignores=[]), str(SOURCE), 'exec')


def decode(packets):
    records = []
    for packet in packets:
        at = 0
        while at < len(packet):
            opcode = packet[at]
            if opcode not in (0x52, 0x55, 0x39):
                raise AssertionError('Unexpected opcode')
            length = 1 if opcode == 0x39 else packet[at + 1] + 2
            if at + length > len(packet):
                raise AssertionError('Split application record')
            records.append(packet[at:at + length])
            at += length
    return records


class BitmapRowsCandidateTests(unittest.TestCase):
    def setUp(self):
        self.s = Service()
        self.s.config = {}
        self.s.UNSAFE_BATCHING_BYPASS = False
        self.s.region_y_offset, self.s.region_height = 27, 48
        self.sent, self.results, self.outcomes = [], [], []
        def transfer(payload, pacing=True):
            self.sent.append(list(payload))
            return self.outcomes.pop(0) if self.outcomes else True
        self.s.ddp = SimpleNamespace(send_ddp_frame=transfer, dis_mode='white',
            poll_bus_events=lambda: None, send_keepalive_if_needed=lambda: None)
        self.s.status_pub = SimpleNamespace(send_string=lambda msg, flags: self.results.append(msg))
        self.raw = bytes((index * 37 + 11) & 255 for index in range(384))
        self.command = dict(command='draw_raw_bitmap', x=0, y=0, w=64, h=48,
                            data_hex=self.raw.hex(), mode_flag=0x82)

    def run_frame(self, command=None):
        exec(CODE, dict(NS, self=self.s, cmds=[command or self.command,
            dict(command='commit', seq=49)], current_payload=[], must_colocate=False))

    def assert_raster(self, records, expected, width, height, mode):
        raster = [record for record in records if record[0] == 0x55]
        current_y, result = 0, bytearray()
        for record in raster:
            self.assertEqual(record[2:5], [mode, 0, current_y])
            self.assertEqual(record[1], len(record) - 2)
            self.assertLessEqual(record[1], 255)
            rows = (len(record) - 5) // width
            self.assertGreater(rows, 0)
            self.assertEqual((len(record) - 5) % width, 0)
            self.assertLessEqual(current_y + rows, height)
            current_y += rows
            result.extend(record[5:])
        self.assertEqual(current_y, height)
        self.assertEqual(bytes(result), expected)

    def test_default_preserves_original_one_row_stream_and_42_byte_packing(self):
        self.run_frame()
        records = decode(self.sent)
        self.assert_raster(records, self.raw, 8, 48, 0x82)
        self.assertEqual(sum(record[0] == 0x55 for record in records), 48)
        self.assertEqual(list(map(len, self.sent)), [33] + [39] * 15 + [21])
        self.assertEqual(self.results, ['DRAW_ACK 49'])

    def test_all_opt_in_row_counts_exact_raster_and_single_commit_at105(self):
        for rows in range(1, 13):
            with self.subTest(rows=rows):
                self.setUp()
                self.s.config = dict(ddp_bitmap_rows_per_command=rows, ddp_bitmap_message_bytes=105)
                self.run_frame()
                self.assertTrue(all(len(packet) <= 105 for packet in self.sent))
                records = decode(self.sent)
                self.assert_raster(records, self.raw, 8, 48, 0x82)
                self.assertTrue(all(len(record) <= 105 for record in records if record[0] == 0x55))
                self.assertEqual(records.count([0x39]), 1)
                self.assertEqual([record for record in records if record[0] == 0x52],
                    [[0x52, 5, 0, 0, 27, 64, 48]] * 2)
                self.assertEqual(self.results, ['DRAW_ACK 49'])

    def test_rows12_caps_native_command_and_application_message(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=12, ddp_bitmap_message_bytes=105)
        self.run_frame()
        self.assertEqual(list(map(len, self.sent)), [7, 101, 101, 101, 101, 8])
        self.assertEqual(sum(map(len, self.sent)), 419)
        self.assertEqual([len(record) for record in decode(self.sent) if record[0] == 0x55], [101] * 4)
        self.assertEqual(self.sent[-1][-1], 0x39)

    def test_rows12_is_clamped_to_budget42_before_transmission(self):
        self.s.config['ddp_bitmap_rows_per_command'] = 12
        self.run_frame()
        self.assertTrue(all(len(packet) <= 42 for packet in self.sent))
        records = decode(self.sent)
        self.assertEqual([len(record) for record in records if record[0] == 0x55], [37] * 12)
        self.assert_raster(records, self.raw, 8, 48, 0x82)

    def test_non_byte_aligned_width_keeps_padding_out_of_following_rows(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=12, ddp_bitmap_message_bytes=105)
        raw = bytes((0x80, 0x80, 0x40, 0x00, 0x20, 0x80, 0x10, 0x00, 0x08, 0x80))
        command = dict(self.command, w=9, h=5, x=4, y=3, data_hex=raw.hex())
        self.run_frame(command)
        records = decode(self.sent)
        self.assertEqual([len(record) for record in records if record[0] == 0x55], [7] * 5)
        self.assert_raster(records, raw, 2, 5, 0x82)

    def test_icon_draw_get_payload_and_redraw_use_grouping_and_preserve_mode(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=8, ddp_bitmap_message_bytes=105)
        self.s.draw_bitmap(2, 4, 'probe', 0x06)
        self.assert_raster(decode(self.sent), ICON_DATA, 8, 9, 0x06)
        self.assertEqual([len(record) for record in decode(self.sent) if record[0] == 0x55], [69, 13])
        self.assertTrue(all(len(packet) <= 105 for packet in self.sent))
        self.assert_raster(decode([self.s.get_bitmap_payload(2, 4, 'probe', 0x06)]),
                           ICON_DATA, 8, 9, 0x06)
        self.sent.clear()
        self.s.clear_screen_payload = lambda: None
        self.s.command_cache = {'probe': dict(command='draw_bitmap', x=2, y=4,
                                               icon_name='probe', mode_flag=0x06)}
        self.s.handle_redraw()
        self.assert_raster(decode(self.sent), ICON_DATA, 8, 9, 0x06)
        self.assertEqual(self.sent[-1], [0x39])

    def test_grouped_builder_preserves_raster_but_explicit_batch_is_nacked(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=8, ddp_bitmap_message_bytes=105)
        self.assert_raster(decode([self.s._raw_bitmap_payload(self.command)]), self.raw, 8, 48, 0x82)
        self.run_frame(dict(command='draw_raw_bitmap_batch', commands=[self.command]))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.results, ['DRAW_NACK 49'])
        self.assertFalse(self.s._frame_failed)

    def test_bypass_path_uses_whole_grouped_commands_and_feedback(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=12, ddp_bitmap_message_bytes=105)
        self.s.UNSAFE_BATCHING_BYPASS = True
        self.run_frame()
        self.assertTrue(all(len(packet) <= 105 for packet in self.sent))
        self.assert_raster(decode(self.sent), self.raw, 8, 48, 0x82)
        self.assertEqual(self.results, ['DRAW_ACK 49'])

    def test_invalid_dimensions_data_or_window_is_nacked_before_any_graphics(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=12, ddp_bitmap_message_bytes=105)
        for changes in (dict(data_hex='80'), dict(w=0), dict(h=49), dict(x=1), dict(y=1)):
            with self.subTest(changes=changes):
                self.sent.clear()
                self.results.clear()
                self.run_frame(dict(self.command, **changes))
                self.assertEqual(self.sent, [])
                self.assertEqual(self.results, ['DRAW_NACK 49'])

    def test_transfer_failure_cannot_send_commit_or_publish_ack(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=12, ddp_bitmap_message_bytes=105)
        self.outcomes = [True, False]
        self.run_frame()
        self.assertEqual(list(map(len, self.sent)), [7, 101])
        self.assertNotIn([0x39], decode(self.sent))
        self.assertEqual(self.results, ['DRAW_NACK 49'])
        self.assertFalse(self.s._frame_failed)

    def test_invalid_setting_and_missing_config(self):
        for rows in (0, 13, 15, 16, 22, True, 1.5, '8', None):
            with self.subTest(rows=rows):
                self.s.config = dict(ddp_bitmap_rows_per_command=rows)
                with self.assertRaisesRegex(ValueError, '1 to 12'):
                    self.s._bitmap_rows_per_command()
        del self.s.config
        self.assertEqual(self.s._bitmap_rows_per_command(), 1)

    def test_large_budget_retained_for_single_rows_but_rejected_for_grouping(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=1, ddp_bitmap_message_bytes=195)
        self.assertEqual(self.s._bitmap_rows_per_command(), 1)
        self.run_frame()
        self.assertEqual(list(map(len, self.sent)), [189, 195, 195, 60])
        self.assert_raster(decode(self.sent), self.raw, 8, 48, 0x82)
        self.sent.clear()
        self.results.clear()
        self.s.config['ddp_bitmap_rows_per_command'] = 8
        with self.assertRaisesRegex(ValueError, 'requires ddp_bitmap_message_bytes <= 105'):
            self.s._bitmap_rows_per_command()
        self.run_frame()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.results, ['DRAW_NACK 49'])

    def test_grouping_plus_coalescing_is_rejected_from_config_or_runtime_flag(self):
        self.s.config = dict(ddp_bitmap_rows_per_command=8, ddp_bitmap_message_bytes=105,
                             ddp_coalesce_bitmaps=True)
        with self.assertRaisesRegex(ValueError, 'incompatible with bitmap coalescing'):
            self.s._bitmap_rows_per_command()
        self.s.config['ddp_coalesce_bitmaps'] = False
        self.s.coalesce_bitmaps = True
        with self.assertRaisesRegex(ValueError, 'incompatible with bitmap coalescing'):
            self.s._bitmap_rows_per_command()


if __name__ == '__main__':
    unittest.main()
