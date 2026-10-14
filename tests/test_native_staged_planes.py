"""Staged native patches: base with the text, then one plane per frame, leavable."""
from pathlib import Path
import random
import sys
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / 'dis_client'), str(REPO / 'tests')]
from native_bitmap import compile_native_payloads, decode_bitmap
from readings_assets import icon_columns
from test_native_service_full_phase import replay
import test_native_service_full_phase as phase
import test_native_bitmap_integration_candidate as integration
from test_native_nav_icons import app_with_route

RECT = [6, 0, 72, 78]
FULL = [0x52, 5, 0, 0, 27, 64, 48]


def staged(target, rect, **options):
    return compile_native_payloads(target, render_order='planes', update_rect=rect,
                                   rows_per_command=12, **options)


class StagedCompiler(unittest.TestCase):
    def test_stages_in_order_equal_the_complete_patch(self):
        rng = random.Random(41)
        target = bytes(rng.randrange(256) for _ in range(1536))
        prior = decode_bitmap(bytes(rng.randrange(256) for _ in range(1536)))
        whole = replay(staged(target, RECT), prior)
        packets = []
        for stage in range(4):
            part = staged(target, RECT, stage=stage)
            self.assertEqual(part[-1][-7:], FULL)
            packets += part
        self.assertEqual(replay(packets, prior), whole)

    def test_through_replays_base_and_earlier_planes(self):
        rng = random.Random(7)
        target = bytes(rng.randrange(256) for _ in range(1536))
        prior = decode_bitmap(bytes(1536))
        for through in range(3):
            with self.subTest(through=through):
                steps = [p for stage in range(through + 1) for p in staged(target, RECT, stage=stage)]
                self.assertEqual(replay(staged(target, RECT, through=through), prior), replay(steps, prior))

    def test_stage_requires_bounded_planes(self):
        for options in (dict(stage=4), dict(stage=True), dict(stage=0, through=0)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                staged(bytes(1536), RECT, **options)
        with self.assertRaises(ValueError):
            compile_native_payloads(bytes(1536), render_order='planes', stage=0)
        with self.assertRaises(ValueError):
            compile_native_payloads(bytes(1536), render_order='tiles', update_rect=RECT, stage=0)


class StagedService(unittest.TestCase):
    def setUp(self):
        self.f = integration.NativeBitmapIntegrationTests()
        self.f.setUp()
        self.s = self.f.s
        self.s.ddp.state_generation = 1
        self.s._draw_waiting = lambda: False
        rng = random.Random(5)
        self.patch = dict(self.f.command, render_order='planes', update_rect=RECT,
                          data_hex=bytes(rng.randrange(256) for _ in range(1536)).hex())

    def test_waiting_command_stops_a_plane_restores_clip_and_nacks(self):
        self.s._draw_waiting = lambda: True
        self.f.expand_draw(dict(self.patch, stage=1))
        self.assertEqual(self.f.results, ['DRAW_NACK 71'])
        self.assertEqual(self.f.sent[-1], FULL)
        self.assertNotIn([0x39], self.f.sent)

    def test_unstaged_patch_is_not_interrupted(self):
        self.s._draw_waiting = lambda: True
        self.f.expand_draw(self.patch)
        self.assertEqual(self.f.results, ['DRAW_ACK 71'])

    def test_cache_restores_only_what_was_drawn(self):
        key = ('draw_native_bitmap', *RECT)
        for stage in range(3):
            self.f.expand_draw(dict(self.patch, stage=stage))
            self.assertEqual(self.s.command_cache[key]['through'], stage)
            self.assertNotIn('stage', self.s.command_cache[key])
        self.f.expand_draw(dict(self.patch, stage=3))
        self.assertNotIn('through', self.s.command_cache[key])
        restored = self.s._native_bitmap_command(dict(self.patch, through=1))
        self.assertEqual(restored['payloads'], staged(bytes.fromhex(self.patch['data_hex']), RECT, through=1))


def staged_view(data, text):
    view = [{'type': 'staged'}, {'group': 'value', 'cmd': 'draw_text', 'text': text, 'x': 42, 'y': 8}]
    for stage in range(4):
        view.append({'group': 'icon:%d' % stage, 'cmd': 'native_bitmap', 'render_order': 'planes',
                     'update_rect': RECT, 'stage': stage, 'preserves_overlays': True,
                     'deferred': stage > 0, 'data_hex': data})
    return view


class StagedFrontend(unittest.TestCase):
    def setUp(self):
        self.f = phase.NativeAppFrames()
        self.f.setUp()
        self.e = self.f.e

    def frame(self, view):
        self.e.current_app.get_view.return_value = view
        self.e._send_draw.reset_mock()
        self.e._draw()
        if not self.e._send_draw.called:
            return None
        sent = self.e._send_draw.call_args.args[0]
        self.e._handle_ui_frame_result(sent['seq'], True)
        return [(c['command'], c.get('stage')) for c in sent['commands']]

    def test_first_paint_is_text_and_base_then_one_plane_per_frame(self):
        self.assertEqual(self.frame(staged_view('00' * 1536, '1')),
                         [('clear', None), ('update_text', None), ('draw_native_bitmap', 0)])
        self.assertEqual(self.frame(staged_view('00' * 1536, '2')),
                         [('update_text', None), ('draw_native_bitmap', 1)])
        self.assertEqual(self.frame(staged_view('00' * 1536, '2')), [('draw_native_bitmap', 2)])
        self.assertEqual(self.frame(staged_view('00' * 1536, '2')), [('draw_native_bitmap', 3)])
        self.assertIsNone(self.frame(staged_view('00' * 1536, '2')))

    def test_new_icon_restarts_from_base(self):
        for _ in range(5):
            self.frame(staged_view('00' * 1536, '1'))
        self.assertEqual(self.frame(staged_view('ff' * 1536, '1')), [('draw_native_bitmap', 0)])
        self.assertEqual(self.frame(staged_view('ff' * 1536, '1')), [('draw_native_bitmap', 1)])

    def test_switching_away_drops_owed_planes(self):
        self.frame(staged_view('00' * 1536, '1'))
        other = [{'type': 'other'}, {'group': 'line', 'cmd': 'draw_text', 'text': 'x', 'x': 0, 'y': 0}]
        commands = self.frame(other)
        self.assertNotIn('draw_native_bitmap', [c for c, _ in commands])
        self.assertIsNone(self.frame(other))


class StagedApps(unittest.TestCase):
    def test_nav_bitmap_icon_is_base_plus_deferred_planes(self):
        view = app_with_route(True).get_view()
        icons = [item for item in view if item.get('cmd') == 'native_bitmap']
        self.assertEqual([(i['group'], i['stage'], i['deferred']) for i in icons],
                         [('icon_plane_1', 1, True), ('icon_plane_2', 2, True),
                          ('icon_plane_3', 3, True), ('icon', 0, False)])

    def test_nav_tiles_stay_one_patch(self):
        app = app_with_route(True)
        app.config['display']['center_display']['navigation']['native_render_order'] = 'tiles'
        icons = [item for item in app.get_view() if item.get('cmd') == 'native_bitmap']
        self.assertEqual(len(icons), 1)
        self.assertNotIn('stage', icons[0])

    def test_reading_icon_columns_avoid_value_text(self):
        # Values occupy physical x 12..52 and 76..116.
        for x, y, w, h in icon_columns(8):
            for start, end in ((12, 52), (76, 116)):
                self.assertTrue(x + w <= start or x >= end, (x, w))
        self.assertEqual(icon_columns(3)[0][3], 36)
        self.assertEqual(icon_columns(0), [])


if __name__ == '__main__':
    unittest.main()
