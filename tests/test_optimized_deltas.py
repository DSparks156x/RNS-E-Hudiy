import ast
import random
import unittest
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'dis_client/dis_image.py'
if not SOURCE.exists():
    SOURCE = ROOT.parent / 'RNS-E-Hudiy/dis_client/dis_image.py'
tree = ast.parse(SOURCE.read_text())
node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'extract_deltas_optimized')
ns = {}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), ns)
extract = ns['extract_deltas_optimized']

def apply(previous, blocks):
    width = previous.width // 8
    data = bytearray(previous.tobytes())
    for b in blocks:
        row_width = len(b['data']) // b['h']
        for row in range(b['h']):
            start = (b['y'] + row) * width + b['x'] // 8
            data[start:start + row_width] = b['data'][row * row_width:(row + 1) * row_width]
    return bytes(data)

class DeltaTests(unittest.TestCase):
    def test_empty_diff(self):
        image = Image.new('1', (64, 48))
        self.assertEqual(extract(image, image), [])

    def test_sparse_and_dense_updates_reconstruct_every_pixel(self):
        rng = random.Random(25)
        for changes in (1, 8, 40, 200, 1000):
            previous = Image.frombytes('1', (64, 48), rng.randbytes(384))
            current = previous.copy()
            for _ in range(changes):
                x, y = rng.randrange(64), rng.randrange(48)
                current.putpixel((x, y), 0 if current.getpixel((x, y)) else 255)
            self.assertEqual(apply(previous, extract(previous, current)), current.tobytes())

    def test_initial_snapshot_includes_black_and_white(self):
        current = Image.new('1', (64, 48), 0)
        current.putpixel((16, 24), 255)
        wrong = Image.new('1', (64, 48), 255)
        self.assertEqual(apply(wrong, extract(None, current)), current.tobytes())

    def test_spatially_separate_changes_remain_correct(self):
        previous = Image.new('1', (64, 48))
        current = previous.copy()
        for point in ((0, 0), (63, 0), (0, 47), (63, 47), (32, 24)):
            current.putpixel(point, 255)
        blocks = extract(previous, current)
        self.assertEqual(apply(previous, blocks), current.tobytes())
        for b in blocks:
            self.assertGreater(b['h'], 0)
            self.assertGreater(len(b['data']), 0)

if __name__ == '__main__':
    unittest.main()
