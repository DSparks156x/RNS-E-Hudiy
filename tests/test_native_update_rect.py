"""Actual bounded native compiler, service cache and frontend regressions."""
from pathlib import Path
import random
import sys
import unittest

REPO = Path(__file__).resolve().parent.parent
if not (REPO / 'dis_client').is_dir():
    REPO = Path(__file__).resolve().parent.parent / 'RNS-E-Hudiy'
sys.path[:0] = [str(REPO / 'dis_client'), str(REPO / 'tests')]
from native_bitmap import compile_native_payloads, decode_bitmap, validate_update_rect
from native_tiles import compile_tile_payloads
from nav_icons import ICON_NAMES, canvas_for_icon
import test_native_service_full_phase as phase
import test_native_bitmap_integration_candidate as integration
import test_native_bitmap_display_candidate as frontend

RECT = [6, 2, 72, 72]


class BoundedPixels(unittest.TestCase):
    def test_all44_icons_replace_only_rectangle_over_arbitrary_prior(self):
        rng = random.Random(3217)
        prior = decode_bitmap(bytes(rng.randrange(256) for _ in range(1536)))
        for name in ICON_NAMES:
            with self.subTest(icon=name):
                data = canvas_for_icon(name)
                packets = compile_native_payloads(data, render_order='tiles', update_rect=RECT)
                self.assertTrue(all(len(p) <= 105 for p in packets))
                actual, target = phase.replay(packets, prior), decode_bitmap(data)
                for y in range(48):
                    for x in range(64):
                        self.assertEqual(actual[y][x], target[y][x] if 3 <= x < 39 and 1 <= y < 37 else prior[y][x])

    def test_invalid_geometry_order_and_bounded_delta_are_rejected(self):
        for rect in ([5, 2, 72, 72], [6, 3, 72, 72], [6, 2, 71, 72],
                     [6, 2, 72, 71], [128, 2, 2, 2], [6, 2, 124, 72],
                     [6, 2, 72, 96], [True, 2, 72, 72], [6., 2, 72, 72],
                     [6, 2, 0, 72], [6, 2, 72], '6,2,72,72'):
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                validate_update_rect(rect)
        for order in ('planes', 'bands'):
            with self.assertRaises(ValueError):
                compile_native_payloads(bytes(1536), render_order=order, update_rect=RECT)
        with self.assertRaises(ValueError):
            compile_tile_payloads(bytes(1536), previous=bytes(1536), update_rect=RECT)


class BoundedService(unittest.TestCase):
    def setUp(self):
        self.f = integration.NativeBitmapIntegrationTests()
        self.f.setUp()
        self.s = self.f.s
        self.s.ddp.state_generation = 1
        self.patch = dict(self.f.command, render_order='tiles', update_rect=RECT)

    def cache(self, commands):
        expanded = self.s._expand_draw_command(dict(command='frame', seq=80, commands=commands))
        exec(integration.CACHE, dict(integration.NS, self=self.s, cmds=expanded, had_clear=False))

    def test_service_invalid_bounds_and_delta_reject_before_any_write(self):
        for changes in (dict(update_rect=[7, 2, 72, 72]), dict(update_rect=[6, 2, 128, 72]),
                        dict(render_order='planes'), dict(delta=True)):
            self.f.results.clear()
            self.assertEqual(self.s._expand_draw_command(dict(self.patch, **changes)), [])
            self.assertEqual(self.f.results, ['DRAW_NACK 71'])
            self.assertEqual(self.f.sent, [])

    def test_partial_never_seeds_full_delta_state(self):
        self.f.expand_draw(self.f.command)
        self.assertIsNotNone(self.s._native_known_image)
        self.f.expand_draw(self.patch)
        self.assertIsNone(self.s._native_known_image)
        self.f.sent.clear()
        self.f.expand_draw(dict(self.f.command, render_order='tiles', delta=True))
        self.assertGreater(len(self.f.sent), 2)

    def test_cache_restores_base_then_patch_and_overlays_in_submission_order(self):
        base = self.f.command
        distance = dict(command='draw_text', x=42, y=8, text='distance')
        street = dict(command='draw_text', x=0, y=39, text='street')
        self.cache([base, distance, self.patch, street])
        cached = list(self.s.command_cache.values())
        self.assertEqual([c.get('update_rect') if c['command'] == 'draw_native_bitmap' else c['text'] for c in cached],
                         [None, 'distance', RECT, 'street'])
        trace = []
        send = self.s._send_native_bitmap_frame
        self.s._send_native_bitmap_frame = lambda cmd: (trace.append(cmd['source'].get('update_rect')), send(cmd))[1]
        self.s.write_text = lambda text, *args: trace.append(text)
        self.assertTrue(self.s.handle_redraw())
        self.assertEqual(trace, [None, 'distance', RECT, 'street'])

    def test_same_rectangle_replaces_cache_entry_and_full_snapshot_wipes_patches(self):
        self.f.expand_draw(self.patch)
        self.f.expand_draw(dict(self.patch, data_hex='ff' * 1536))
        self.assertEqual(len(self.s.command_cache), 1)
        key = ('draw_native_bitmap', *RECT)
        self.assertEqual(self.s.command_cache[key]['data_hex'], 'ff' * 1536)
        self.f.expand_draw(dict(self.patch, update_rect=[80, 0, 8, 8]))
        self.assertEqual(len(self.s.command_cache), 2)
        self.f.expand_draw(self.f.command)
        self.assertEqual(list(self.s.command_cache), [('draw_native_bitmap', 0, 0)])

    def test_updated_overlay_is_reinserted_after_partial_only_cache(self):
        text = dict(command='draw_text', x=42, y=8, text='old')
        self.cache([text, self.patch, dict(text, text='new')])
        self.assertEqual([c['command'] for c in self.s.command_cache.values()], ['draw_native_bitmap', 'draw_text'])

    def test_partial_failure_nacks_once_and_invalidates_known_image(self):
        self.f.outcomes[:] = [False]
        self.f.expand_draw(self.patch)
        self.assertEqual(self.f.results, ['DRAW_NACK 71'])
        self.assertEqual(len(self.f.sent), 1)
        self.assertIsNone(self.s._native_known_image)


class BoundedFrontend(unittest.TestCase):
    def test_public_api_forwards_rectangle_with_existing_sequence_feedback(self):
        f = frontend.NativeDisplayTests()
        f.setUp()
        with self.assertRaises(ValueError):
            f.s.draw_native_bitmap(f.data, render_order='tiles', update_rect=RECT, delta=True)
        f.s._send_draw.assert_not_called()
        self.assertEqual(f.s.frame_seq_counter, 30)
        self.assertTrue(f.s.draw_native_bitmap(f.data, render_order='tiles', update_rect=RECT))
        command = f.s._send_draw.call_args.args[0]['commands'][0]
        self.assertEqual(command['update_rect'], RECT)
        self.assertTrue(f.s._handle_ui_frame_result(31, True))

    def prepare(self, flag=True, bounded=True):
        f = phase.NativeAppFrames()
        f.setUp()
        def view(data):
            items = phase.view(data)
            if bounded:
                items[1].update(update_rect=RECT)
            items[1]['preserves_overlays'] = flag
            return items
        f.e.current_app.get_view.return_value = view('00' * 1536)
        f.e._draw()
        initial = f.e._send_draw.call_args.args[0]['commands']
        f.e._handle_ui_frame_result(21, True)
        f.e.current_app.get_view.return_value = view('ff' * 1536)
        f.e._draw()
        return f, initial, f.e._send_draw.call_args.args[0]['commands']

    def test_reserved_bounded_icon_update_leaves_unchanged_overlays_alone(self):
        f, initial, changed = self.prepare()
        self.assertEqual([c['command'] for c in initial], ['clear', 'draw_native_bitmap', 'draw_text', 'draw_text'])
        self.assertEqual([c['command'] for c in changed], ['draw_native_bitmap'])
        self.assertEqual(changed[0]['update_rect'], RECT)
        self.assertNotIn('preserves_overlays', changed[0])

    def test_generic_bounded_and_unbounded_flag_still_resend_overlays(self):
        for flag, bounded in ((False, True), (True, False)):
            with self.subTest(flag=flag, bounded=bounded):
                f, initial, changed = self.prepare(flag, bounded)
                self.assertEqual([c['command'] for c in changed], ['draw_native_bitmap', 'draw_text', 'draw_text'])


if __name__ == '__main__':
    unittest.main()
