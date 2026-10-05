"""Opt-in cover app source processing, bounded decode and legacy fallback."""
import importlib.util
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PIL import Image
from test_native_image_processing import image_tools

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / 'dis_client'
if not CLIENT.exists():
    CLIENT = ROOT / 'RNS-E-Hudiy/dis_client'
sys.path.insert(0, str(CLIENT))
SOURCE = Path(os.environ.get('DIS_NATIVE_COVER_SOURCE', CLIENT / 'apps/coverart.py'))
spec = importlib.util.spec_from_file_location('apps.coverart_under_test', SOURCE)
cover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cover)
cover.dis_image = image_tools


def config(**settings):
    return {'display': {'center_display': {'coverart': settings}}}


def png_hex(size=(128, 96)):
    output = io.BytesIO()
    Image.new('RGB', size, 'white').save(output, format='PNG')
    return output.getvalue().hex()


class NativeCoverArtTests(unittest.TestCase):
    legacy = 'ab' * 384

    def test_native_legacy_default_reuses_cover_args_and_forces128_geometry(self):
        args = dict(contrast=1.9, gamma=2.2, black_floor=45, dither='fs', target_size=[64, 48])
        app = cover.CoverArtApp(config(native_resolution=True, args=args))
        original = png_hex((256, 192))
        app.update_hudiy(b'HUDIY_COVERART', {'image_hex': original, 'bitmap_hex': self.legacy})
        with Image.open(io.BytesIO(bytes.fromhex(original))) as source:
            expected = image_tools.process_image(source, target_size=(128, 96),
                                                  **{key: value for key, value in args.items() if key != 'target_size'})
        self.assertEqual(app.native_preset, 'legacy')
        self.assertNotIn('target_size', app.native_args)
        self.assertEqual(bytes.fromhex(app.get_view()[1]['data_hex']), expected.tobytes())
        self.assertEqual(args['target_size'], [64, 48])
        override = cover.CoverArtApp(config(native_resolution=True, args=args, native_args={'dither': 'none'}))
        self.assertEqual(override.native_args['dither'], 'none')
        comparison = cover.CoverArtApp(config(native_resolution=True, native_preset='text', args=args))
        self.assertEqual(comparison.native_args, {})

    def test_legacy_cover_to_empty_transition_dispatches_clear_separately(self):
        app = cover.CoverArtApp()
        app.update_hudiy(b'HUDIY_COVERART', {'bitmap_hex': self.legacy})
        app.update_hudiy(b'HUDIY_COVERART', {'bitmap_hex': ''})
        view = app.get_view()
        self.assertEqual(view[0], {'type': 'cover_art'})
        self.assertEqual([item['cmd'] for item in view if 'type' not in item], ['clear_area', 'draw_text'])
        self.assertEqual(view[1], dict(cmd='clear_area', x=0, y=0, w=64, h=48))

    def test_delta_is_opt_in_and_restricted_to_completed_tiles(self):
        app = cover.CoverArtApp(config(native_resolution=True, native_delta=True))
        app.update_hudiy(b'HUDIY_COVERART', {'native_bitmap_hex': 'ff' * 1536})
        self.assertTrue(app.get_view()[1]['delta'])
        app = cover.CoverArtApp(config(native_resolution=True))
        app.update_hudiy(b'HUDIY_COVERART', {'native_bitmap_hex': 'ff' * 1536})
        self.assertNotIn('delta', app.get_view()[1])
        for settings in (dict(native_delta='true'), dict(native_delta=True, native_render_order='planes')):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                cover.CoverArtApp(config(**settings))

    def test_disabled_native_preserves_legacy_view_without_decoding_original(self):
        app = cover.CoverArtApp()
        with patch.object(image_tools, 'process_native_image', side_effect=AssertionError('unexpected conversion')):
            app.update_hudiy(b'HUDIY_COVERART', {'bitmap_hex': self.legacy, 'image_hex': png_hex()})
        self.assertEqual(app.get_view()[1], dict(cmd='draw_raw_bitmap', data_hex=self.legacy,
                                               w=64, h=48, x=0, y=0, mode_flag=2))

    def test_native_original_is_processed_once_on_receipt_not_in_draw_loop(self):
        app = cover.CoverArtApp(config(native_resolution=True))
        payload = dict(bitmap_hex=self.legacy, image_hex=png_hex())
        with patch.object(image_tools, 'process_native_image', wraps=image_tools.process_native_image) as process:
            app.update_hudiy(b'HUDIY_COVERART', payload)
            app.update_hudiy(b'HUDIY_COVERART', payload)
            views = [app.get_view() for _ in range(3)]
        self.assertEqual(process.call_count, 1)
        self.assertEqual(views[0][0], {'type': 'cover_art'})
        self.assertEqual(views[0][1]['cmd'], 'native_bitmap')
        self.assertEqual(views[0][1]['render_order'], 'tiles')
        self.assertEqual(len(bytes.fromhex(views[0][1]['data_hex'])), 1536)
        self.assertEqual(views[0], views[2])

    def test_already_packed_native_payload_is_validated_and_render_order_forwarded(self):
        app = cover.CoverArtApp(config(native_resolution=True, native_render_order='bands'))
        app.update_hudiy(b'HUDIY_COVERART', {'native_bitmap_hex': 'ff' * 1536, 'bitmap_hex': self.legacy})
        self.assertEqual(app.get_view()[1]['render_order'], 'bands')
        self.assertEqual(app.get_view()[1]['data_hex'], 'ff' * 1536)

    def test_malformed_native_source_replaces_old_art_with_legacy_fallback(self):
        app = cover.CoverArtApp(config(native_resolution=True))
        app.update_hudiy(b'HUDIY_COVERART', {'image_hex': png_hex(), 'bitmap_hex': self.legacy})
        with self.assertLogs(cover.logger, level='WARNING'):
            app.update_hudiy(b'HUDIY_COVERART', {'image_hex': 'not hex', 'bitmap_hex': self.legacy})
        self.assertEqual(app.native_bitmap_hex, '')
        self.assertEqual(app.get_view()[1]['cmd'], 'draw_raw_bitmap')
        with self.assertLogs(cover.logger, level='WARNING'):
            app.update_hudiy(b'HUDIY_COVERART', {'native_bitmap_hex': 'ff' * 384, 'bitmap_hex': self.legacy})
        self.assertEqual(app.get_view()[1]['cmd'], 'draw_raw_bitmap')

    def test_clear_or_legacy_only_source_drops_prior_native_image(self):
        app = cover.CoverArtApp(config(native_resolution=True))
        app.update_hudiy(b'HUDIY_COVERART', {'native_bitmap_hex': 'ff' * 1536})
        app.update_hudiy(b'HUDIY_COVERART', {'bitmap_hex': self.legacy})
        self.assertEqual(app.get_view()[1]['cmd'], 'draw_raw_bitmap')
        app.update_hudiy(b'HUDIY_COVERART', {'bitmap_hex': ''})
        empty = app.get_view()
        self.assertEqual(empty[0], {'type': 'cover_art'})
        self.assertEqual(empty[1], dict(cmd='clear_area', x=0, y=0, w=64, h=48))
        self.assertEqual(empty[2]['text'], 'No Cover Art')

    def test_bounded_encoded_and_decoded_sources_fall_back_before_processing(self):
        app = cover.CoverArtApp(config(native_resolution=True))
        app.MAX_ENCODED_BYTES = 2
        with patch.object(image_tools, 'process_native_image') as process, self.assertLogs(cover.logger, level='WARNING'):
            app.update_hudiy(b'HUDIY_COVERART', {'image_hex': png_hex(), 'bitmap_hex': self.legacy})
        process.assert_not_called()
        app.MAX_ENCODED_BYTES = 4 * 1024 * 1024
        app.MAX_SOURCE_PIXELS = 4
        with patch.object(image_tools, 'process_native_image') as process, self.assertLogs(cover.logger, level='WARNING'):
            app.update_hudiy(b'HUDIY_COVERART', {'image_hex': png_hex((20, 20)), 'bitmap_hex': self.legacy})
        process.assert_not_called()
        self.assertEqual(app.get_view()[1]['cmd'], 'draw_raw_bitmap')

    def test_quality_options_are_validated_and_used(self):
        for settings in (dict(native_resolution='true'), dict(native_args=[]),
                         dict(native_preset='invalid'), dict(native_render_order='invalid'),
                         dict(native_args={'dither': 'invalid'})):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                cover.CoverArtApp(config(**settings))
        app = cover.CoverArtApp(config(native_resolution=True, native_preset='text', native_args={'threshold': 100}))
        with patch.object(image_tools, 'process_native_image', wraps=image_tools.process_native_image) as process:
            app.update_hudiy(b'HUDIY_COVERART', {'image_hex': png_hex()})
        self.assertEqual(process.call_args.args[1], 'text')
        self.assertEqual(process.call_args.kwargs, {'threshold': 100})


if __name__ == '__main__':
    unittest.main()
