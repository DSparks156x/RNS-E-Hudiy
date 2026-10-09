"""Actual DIS service/UI behavior for completed tiles, stale state and overlays."""
import ast
import logging
from pathlib import Path
import random
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parent.parent
if not (REPO/'dis_client').exists():
    REPO = Path(__file__).resolve().parent.parent/'RNS-E-Hudiy'
sys.path.insert(0, str(REPO/'dis_client'))
sys.path.insert(0, str(REPO/'tests'))
from native_bitmap import decode_bitmap, compile_native_payloads
from native_tiles import compile_tile_payloads
from test_native_bitmap_integration_candidate import NativeBitmapIntegrationTests


def replay(packets, previous):
    """Independent physical-pixel renderer, including ROI stride and padding."""
    pixels = [[bool(previous[y//2][x//2] & (1 << (2*(y%2)+x%2)))
               for x in range(128)] for y in range(96)]
    clip = (0, 0, 64, 48)
    for packet in packets:
        at = 0
        while at < len(packet):
            length = packet[at+1]+2
            record = packet[at:at+length]
            if record[0] == 0x52:
                clip = record[3], record[4]-27, record[5], record[6]
            elif record[0] == 0x55:
                x0, y0, w, h = clip
                stride = (w+7)//8
                for i, value in enumerate(record[5:]):
                    cy, bx = divmod(i, stride)
                    for bit in range(8):
                        cx = 8*bx+bit
                        if cx >= w or cy >= h:
                            continue
                        selected = bool(value & (128 >> bit))
                        for dy in range(2):
                            for dx in range(2):
                                x, y = 2*(x0+cx)+dx, 2*(y0+cy)+dy
                                if record[2] == 2:
                                    pixels[y][x] = selected
                                elif selected:
                                    pixels[y][x] = not pixels[y][x]
            elif record[0] == 0x63:
                x0, y0, _, _ = clip
                orientation, cx, cy, count = record[2:]
                x, y = 2*(x0+cx), 2*(y0+cy)
                coordinates = ([(x, y)] if orientation == 0 else
                    [(x, y+i) for i in range(count*2)] if orientation == 16 else
                    [(x+i, y) for i in range(count*2)])
                for x, y in coordinates:
                    pixels[y][x] = not pixels[y][x]
            else:
                raise AssertionError('Unknown graphics record')
            at += length
    return [[sum(1 << (2*dy+dx) for dy in range(2) for dx in range(2)
                 if pixels[2*y+dy][2*x+dx]) for x in range(64)] for y in range(48)]


class NativeTilePixels(unittest.TestCase):
    def test_full_and_changed_tiles_reconstruct_physical_pixels(self):
        rng = random.Random(3217)
        prior = bytes(rng.randrange(256) for _ in range(1536))
        target = bytearray(prior)
        for index in range(0, 1536, 29):
            target[index] ^= 0x96
        for before in (None, prior):
            packets = compile_tile_payloads(target, previous=before)
            self.assertTrue(all(len(p) <= 105 for p in packets))
            actual = replay(packets, decode_bitmap(prior))
            self.assertEqual(actual, decode_bitmap(target))
            self.assertEqual(packets[-1][-7:], [0x52, 5, 0, 0, 27, 64, 48])

    def test_unchanged_tile_image_only_restores_clip(self):
        data = bytes(1536)
        self.assertEqual(compile_tile_payloads(data, previous=data), [[0x52, 5, 0, 0, 27, 64, 48]])


class NativeTileService(NativeBitmapIntegrationTests):
    def setUp(self):
        super().setUp()
        self.s.ddp.state_generation = 1
        self.command.update(render_order='tiles', delta=True)

    # Inherited tests deliberately describe the original plane profile; this
    # subclass only contributes tile-specific cases below.
    def test_tile_delta_uses_only_an_intact_previous_image(self):
        self.expand_draw(self.command)
        self.sent.clear()
        self.expand_draw(self.command)
        self.assertEqual(self.sent, [[0x52, 5, 0, 0, 27, 64, 48], [0x39]])
        self.s._send_graphics([0x57, 4, 6, 2, 0, 65])
        self.sent.clear()
        self.expand_draw(self.command)
        self.assertGreater(len(self.sent), 2)

    def test_generation_change_or_failed_transfer_requires_full_snapshot(self):
        self.expand_draw(self.command)
        self.s.ddp.state_generation += 1
        self.sent.clear()
        self.expand_draw(self.command)
        self.assertGreater(len(self.sent), 2)
        self.outcomes[:] = [False]
        self.expand_draw(self.command)
        self.assertIsNone(self.s._native_known_image)
        self.sent.clear()
        self.expand_draw(self.command)
        self.assertGreater(len(self.sent), 2)

    def test_ownership_changes_mid_transfer_stop_and_nack(self):
        def interrupt():
            self.s.ddp.state_generation += 1
        self.s.ddp.poll_bus_events = interrupt
        self.expand_draw(self.command)
        self.assertEqual(self.results, ['DRAW_NACK 71'])
        self.assertEqual(len(self.sent), 1)
        self.assertIsNone(self.s._native_known_image)

    def test_failed_restore_can_retry_without_permanent_failure_latch(self):
        self.s.command_cache = {('draw_native_bitmap', 0, 0): self.command}
        self.outcomes = [False]
        self.assertFalse(self.s.handle_redraw())
        self.assertFalse(self.s._frame_failed)
        self.assertIsNone(self.s._native_known_image)
        failed_count = len(self.sent)
        self.assertTrue(self.s.handle_redraw())
        self.assertGreater(len(self.sent), failed_count)
        self.assertEqual(self.sent[-1], [0x39])
        self.assertFalse(self.s._frame_failed)

    def test_records_api_does_not_silently_substitute_bands_for_tiles(self):
        from native_bitmap import compile_native_records
        with self.assertRaisesRegex(ValueError, 'packet boundaries'):
            compile_native_records(bytes(1536), render_order='tiles')

    def test_invalid_delta_options_are_rejected_before_writes(self):
        for changes in (dict(delta='true'), dict(render_order='bands', delta=True)):
            self.results.clear()
            self.assertEqual(self.s._expand_draw_command(dict(self.command, **changes)), [])
            self.assertEqual(self.results, ['DRAW_NACK 71'])
        self.assertEqual(self.sent, [])


# Avoid running the inherited profile tests with a deliberately changed setup.
for name in vars(NativeBitmapIntegrationTests):
    if name.startswith('test_'):
        setattr(NativeTileService, name, None)

TREE = ast.parse((REPO/'dis_client/dis_display.py').read_text())
NAMES = {'_prepare_text_group', '_draw', '_queue_ui_frame', '_ui_frame_waiting', 'force_redraw', '_handle_ui_frame_result'}
NS = {'logger': logging.getLogger(__name__)}
exec(compile(ast.Module(body=[n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef)
    and n.name in NAMES], type_ignores=[]), str(REPO/'dis_client/dis_display.py'), 'exec'), NS)
Engine = type('Engine', (), {name: NS[name] for name in NAMES})


def view(data):
    return [{'type': 'nav_graphic_native'}, {'group': 'icon', 'cmd': 'native_bitmap', 'data_hex': data},
            {'group': 'dist', 'cmd': 'draw_text', 'text': '200M', 'x': 42, 'y': 8},
            {'group': 'street', 'cmd': 'draw_text', 'text': 'MAIN ST', 'x': 0, 'y': 39}]


class NativeAppFrames(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.e.cfg, self.e.last_sent, self.e.last_sent_flags = {}, {}, {}
        self.e.service_ready, self.e.user_paused = True, False
        self.e.frame_seq_counter, self.e._pending_ui_frame = 20, None
        self.e.Y = {'line1': 0}
        self.e._send_draw = Mock(return_value=True)
        self.e.publish_status = Mock()
        self.e.current_app = SimpleNamespace(get_view=Mock(return_value=view('00'*1536)),
            on_frame_sent=Mock(), on_frame_acked=Mock(), on_display_reset=Mock())

    def test_pending_frame_blocks_view_consumption_and_new_sequence(self):
        self.e._draw()
        self.e._draw()
        self.e.current_app.get_view.assert_called_once()
        self.e._send_draw.assert_called_once()
        self.assertEqual(self.e.frame_seq_counter, 21)
        envelope = self.e._send_draw.call_args.args[0]
        self.assertEqual([c['command'] for c in envelope['commands']],
            ['clear', 'draw_native_bitmap', 'update_text', 'update_text'])

    def test_new_icon_resends_unchanged_distance_and_street(self):
        self.e._draw()
        self.e._handle_ui_frame_result(21, True)
        self.e.current_app.get_view.return_value = view('ff'*1536)
        self.e._draw()
        commands = self.e._send_draw.call_args.args[0]['commands']
        self.assertEqual([c['command'] for c in commands], ['draw_native_bitmap', 'update_text', 'update_text'])

    def test_dropped_envelope_leaves_no_optimistic_presentation(self):
        self.e._send_draw.return_value = False
        self.e._draw()
        self.assertEqual(self.e.last_sent, {})
        self.assertIsNone(self.e._pending_ui_frame)
        self.e.current_app.on_frame_sent.assert_not_called()

    def test_lost_feedback_rebuilds_latest_full_view_and_ignores_stale_ack(self):
        self.e._draw()
        self.e._pending_ui_frame_started = 1
        self.e.current_app.get_view.return_value = view('ff'*1536)
        with patch('time.monotonic', return_value=32):
            self.e._draw()
        self.assertEqual(self.e._pending_ui_frame[0], 22)
        self.assertFalse(self.e._handle_ui_frame_result(21, True))
        self.assertTrue(self.e._handle_ui_frame_result(22, True))
        self.e.current_app.on_frame_acked.assert_called_once_with(22)


if __name__ == '__main__':
    unittest.main()
