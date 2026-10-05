"""Native cover quality, deterministic dithering and legacy API compatibility."""
import importlib.util
import inspect
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get('DIS_NATIVE_IMAGE_SOURCE', ROOT / 'dis_client/dis_image.py'))
if not SOURCE.exists():
    SOURCE = ROOT / 'RNS-E-Hudiy/dis_client/dis_image.py'
spec = importlib.util.spec_from_file_location('_native_image_under_test', SOURCE)
image_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image_tools)


class NativeImageProcessingTests(unittest.TestCase):
    def test_all_presets_are_deterministic_exact_native_snapshots(self):
        image = Image.new('RGB', (256, 192))
        image.putdata([(x % 256, y % 256, (x + y) % 256) for y in range(192) for x in range(256)])
        original = image.tobytes()
        rendered = []
        for preset in ('legacy', 'balanced', 'photo', 'text'):
            a = image_tools.process_native_image(image, preset)
            b = image_tools.process_native_image(image, preset)
            self.assertEqual((a.mode, a.size, len(a.tobytes())), ('1', (128, 96), 1536))
            self.assertEqual(a.tobytes(), b.tobytes())
            rendered.append(a.tobytes())
        self.assertEqual(len(set(rendered)), 4)
        self.assertEqual(image.tobytes(), original)

    def test_fixed_ordered_phase_has_eight_white_cells_per_flat_midgray_block(self):
        gray = Image.new('L', (4, 4), 128)
        output = image_tools._native_dither(gray, 'ordered')
        self.assertEqual(list(output.convert('L').tobytes()), [255, 0, 255, 0, 0, 255, 0, 255,
                                                  255, 0, 255, 0, 0, 255, 0, 255])

    def test_text_preset_preserves_single_pixel_strokes_without_local_enhancement(self):
        image = Image.new('RGB', (128, 96), 'black')
        for y in range(12, 80):
            image.putpixel((37, y), (255, 255, 255))
        with (patch.object(image_tools, 'apply_clahe', side_effect=AssertionError('CLAHE')),
              patch.object(image_tools.ImageOps, 'autocontrast', side_effect=AssertionError('autocontrast'))):
            output = image_tools.process_native_image(image, 'text')
        self.assertEqual(output.tobytes(), image.convert('1').tobytes())

    def test_native_midtones_survive_without_legacy_gamma_floor(self):
        image = Image.new('RGB', (128, 96), (64, 64, 64))
        native = image_tools.process_native_image(image, 'balanced')
        white_fraction = sum(bool(value) for value in native.convert('L').tobytes()) / (128 * 96)
        self.assertGreater(white_fraction, 0.15)
        self.assertLess(white_fraction, 0.35)
        self.assertFalse(any(image_tools.process_image(image).tobytes()))

    def test_contain_letterbox_and_transparency_are_black_with_explicit_crop_alternative(self):
        square = Image.new('RGB', (200, 200), 'white')
        contain = image_tools.process_native_image(square, 'text')
        cover = image_tools.process_native_image(square, 'text', fit='cover')
        self.assertEqual(contain.getpixel((0, 48)), 0)
        self.assertEqual(contain.getpixel((16, 48)), 255)
        self.assertEqual(cover.getpixel((0, 48)), 255)
        transparent = Image.new('RGBA', (100, 100), (255, 255, 255, 0))
        self.assertFalse(any(image_tools.process_native_image(transparent, 'balanced').tobytes()))

    def test_ordered_threshold_keeps_true_black_and_white_endpoints(self):
        for value in (0, 255):
            gray = Image.new('L', (4, 4), value)
            for threshold in (32, 128, 224):
                self.assertEqual(set(image_tools._native_dither(gray, 'ordered', threshold).convert('L').tobytes()), {value})

    def test_options_reject_unknown_or_nonfinite_controls_and_do_not_mutate_presets(self):
        before = image_tools.native_image_options('balanced')
        for options in ({'dither': 'random'}, {'contrast': float('nan')}, {'gamma': 0},
                        {'threshold': True}, {'black_floor': 200}, {'sharpen': '1'},
                        {'fit': 'stretch'}, {'clahe': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                image_tools.native_image_options('balanced', **options)
        with self.assertRaises(ValueError):
            image_tools.native_image_options('unrecognized')
        modified = image_tools.native_image_options('balanced', contrast=1.5)
        modified['contrast'] = 2
        self.assertEqual(image_tools.native_image_options('balanced'), before)

    def test_native_legacy_is_byte_identical_to_existing128_pipeline(self):
        image = Image.new('RGB', (256, 192))
        image.putdata([(x % 256, y % 256, (x + y) % 256) for y in range(192) for x in range(256)])
        for args in ({}, dict(contrast=1.9, gamma=2.2, black_floor=45),
                     dict(contrast=1.9, gamma=2.2, black_floor=45, dither='none'),
                     dict(dither='atkinson', diffusion=0.75), dict(no_enhance=True)):
            expected = image_tools.process_image(image, target_size=(128, 96), **args)
            actual = image_tools.process_native_image(image, **args)
            self.assertEqual((actual.mode, actual.size, len(actual.tobytes())), ('1', (128, 96), 1536))
            self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_legacy_explicit_defaults_and_atkinson_remain_available(self):
        signature = inspect.signature(image_tools.process_image)
        self.assertEqual(signature.parameters['target_size'].default, (64, 48))
        self.assertEqual(signature.parameters['dither'].default, 'fs')
        self.assertEqual(signature.parameters['gamma'].default, 2.2)
        image = Image.new('RGB', (160, 120), 'white')
        result = image_tools.process_image(image, target_size=(64, 48), dither='atkinson')
        self.assertEqual((result.mode, result.size, len(result.tobytes())), ('1', (64, 48), 384))


if __name__ == '__main__':
    unittest.main()
