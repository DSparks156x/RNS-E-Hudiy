import ast
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'dis_client'
sys.path.insert(0, str(SOURCE))
import dis_image
from apps.easteregg import EasterEggApp


class FullAnimationLoadTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.gif_path = str(Path(directory.name) / 'two_frames.gif')
        first = Image.new('1', (64, 48), 0)
        second = first.copy()
        second.putpixel((24, 20), 255)
        first.save(self.gif_path, save_all=True, append_images=[second], duration=100, loop=0)
        # Exercise real GIF loading/seeking and bitmap packing, holding only the
        # photometric processing constant so strategy assertions are independent
        # of dithering thresholds.
        processing = patch.object(dis_image, 'process_image', side_effect=lambda image, **kwargs: image.convert('1'))
        processing.start()
        self.addCleanup(processing.stop)

    def test_default_full_load_produces_complete_command_for_each_image(self):
        app = EasterEggApp()
        with patch.object(dis_image, 'extract_deltas', wraps=dis_image.extract_deltas) as granular:
            with patch.object(dis_image, 'extract_deltas_optimized', wraps=dis_image.extract_deltas_optimized) as adaptive:
                self.assertTrue(app.load_gif(self.gif_path))
                granular.assert_not_called()
                adaptive.assert_not_called()
        self.assertEqual(len(app.frames), 2)
        self.assertEqual(app.frames, app.full_frames)
        for frame in app.frames:
            self.assertEqual(len(frame), 1)
            self.assertEqual((frame[0]['w'], frame[0]['h'], frame[0]['x'], frame[0]['y']), (64, 48, 0, 0))
            self.assertEqual(len(bytes.fromhex(frame[0]['data_hex'])), 384)
        self.assertNotEqual(app.frames[0][0]['data_hex'], app.frames[1][0]['data_hex'])
        self.assertIsNot(app.frames[0][0], app.full_frames[0][0])

    def test_delta_optins_select_expected_extractors(self):
        for strategy in ('granular', 'rows', 'adaptive'):
            with self.subTest(strategy=strategy):
                app = EasterEggApp()
                with patch.object(dis_image, 'extract_deltas', wraps=dis_image.extract_deltas) as granular:
                    with patch.object(dis_image, 'extract_deltas_optimized', wraps=dis_image.extract_deltas_optimized) as adaptive:
                        self.assertTrue(app.load_gif(self.gif_path, delta_strategy=strategy))
                        if strategy == 'adaptive':
                            self.assertEqual(adaptive.call_count, 2)
                            granular.assert_not_called()
                        else:
                            self.assertEqual(granular.call_count, 2)
                            adaptive.assert_not_called()
                            self.assertTrue(all(call.kwargs['granular'] == (strategy == 'granular') for call in granular.call_args_list))
                self.assertNotEqual(app.frames, app.full_frames)

    def test_explicit_full_advances_only_after_ack_and_keeps_full_image(self):
        app = EasterEggApp()
        self.assertTrue(app.load_gif(self.gif_path, delta_strategy='full'))
        now = 10.0
        with patch.object(time, 'time', lambda: now), patch.object(time, 'monotonic', lambda: now):
            app.on_enter()
            app.on_frame_sent(1)
            now += 1
            self.assertEqual(app.get_view()[1]['data_hex'], app.full_frames[0][0]['data_hex'])
            app.on_frame_acked(1)
            view = app.get_view()
            self.assertEqual(view[1]['data_hex'], app.full_frames[1][0]['data_hex'])
            self.assertEqual((view[1]['w'], view[1]['h']), (64, 48))

    def test_unknown_strategy_fails_instead_of_silently_using_deltas(self):
        app = EasterEggApp()
        with patch('builtins.print'):
            self.assertFalse(app.load_gif(self.gif_path, delta_strategy='typo'))
        self.assertFalse(app.is_loaded)


class FullCliStrategyTests(unittest.TestCase):
    def test_full_cli_mode_includes_black_pixels_and_unchanged_images(self):
        cli = SOURCE / 'dis_tests/test_gif_ipc.py'
        tree = ast.parse(cli.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'extract_frame_blocks')
        namespace = {'dis_image': dis_image}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(cli), 'exec'), namespace)
        image = Image.new('1', (64, 48), 0)
        image.putpixel((24, 20), 255)
        with patch.object(dis_image, 'extract_deltas') as granular, patch.object(dis_image, 'extract_deltas_optimized') as adaptive:
            rows = namespace['extract_frame_blocks'](image, image, 'full')
            granular.assert_not_called()
            adaptive.assert_not_called()
        self.assertEqual(rows, [{'x': 0, 'y': 0, 'h': 48, 'data': dis_image.image_to_bitmap(image)}])
        self.assertEqual(len(rows[0]['data']), 384)


if __name__ == '__main__':
    unittest.main()
