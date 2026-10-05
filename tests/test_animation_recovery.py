import ast
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'dis_client/apps/easteregg.py'
if not SOURCE.exists():
    SOURCE = ROOT.parent / 'RNS-E-Hudiy/dis_client/apps/easteregg.py'
tree = ast.parse(SOURCE.read_text())
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
# No GIF decoding required: test the real sequence/view state transitions.
cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name != 'load_gif']
class Base:
    def __init__(self, config): pass
    def on_enter(self): pass
ns = {'BaseApp': Base, 'time': time}
exec(compile(ast.Module(body=[cls], type_ignores=[]), str(SOURCE), 'exec'), ns)
App = ns['EasterEggApp']

class AnimationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.clock = patch.object(time, 'time', lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.app = App()
        self.app.frames = [[{'cmd': 'draw_raw_bitmap', 'data_hex': str(i)}] for i in range(3)]
        self.app.full_frames = [[{'cmd': 'draw_raw_bitmap', 'data_hex': 'full' + str(i)}] for i in range(3)]
        self.app.is_loaded = True
        self.app.on_enter()

    def test_delayed_first_draw_is_full_frame_zero(self):
        self.now += 5
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'full0')
        self.assertEqual(self.app.current_frame_idx, 0)

    def test_no_advance_until_matching_ack(self):
        self.app.on_frame_sent(10)
        self.now += 1
        self.app.on_frame_acked(9)
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'full0')
        self.app.on_frame_acked(10)
        self.assertEqual(self.app.get_view()[1]['data_hex'], '1')

    def test_sequence_wrap_is_not_treated_as_already_acknowledged(self):
        self.app.last_acked_seq = 999999
        self.app.on_frame_sent(1)
        self.now += 1
        self.app.get_view()
        self.assertEqual(self.app.current_frame_idx, 0)
        self.app.on_frame_acked(1)
        self.app.get_view()
        self.assertEqual(self.app.current_frame_idx, 1)

    def test_rejected_delta_restores_full_snapshot_before_advancing(self):
        self.app._snapshot_pending = False
        self.now += 1
        self.app.get_view()
        self.app.on_frame_sent(11)
        self.app.on_frame_failed(11)
        self.now += 5
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'full1')
        self.assertEqual(self.app.current_frame_idx, 1)

    def test_type_descriptor_does_not_hide_first_bitmap_tile(self):
        view = self.app.get_view()
        self.assertEqual(view[0], {'type': 'easter_egg'})
        self.assertEqual([v['data_hex'] for v in view if 'type' not in v], ['full0'])

    def test_repeated_views_do_not_mutate_cached_delta_commands(self):
        self.app.get_view()
        self.app.get_view()
        self.assertEqual(self.app.full_frames[0], [{'cmd': 'draw_raw_bitmap', 'data_hex': 'full0'}])

if __name__ == '__main__':
    unittest.main()
