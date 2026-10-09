"""Offline regression tests executing the actual service's draw-command loop."""
import ast
import logging
import unittest
from enum import Enum
from pathlib import Path
from typing import List, Optional
from types import SimpleNamespace
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / 'dis_client/dis_service.py'
tree = ast.parse(SOURCE.read_text())
loops = [node for node in ast.walk(tree) if isinstance(node, ast.For)
         and isinstance(node.target, ast.Name) and node.target.id == 'cmd'
         and isinstance(node.iter, ast.Name) and node.iter.id == 'cmds']
loop = max(loops, key=lambda node: len(node.body))
container = next(value for node in ast.walk(tree) for _, value in ast.iter_fields(node)
                 if isinstance(value, list) and any(item is loop for item in value))
# Include the final pending-payload flush following the processing loop.
statements = container[container.index(loop):]
code = compile(ast.Module(body=statements, type_ignores=[]), str(SOURCE), 'exec')
class DisMode(Enum):
    RED = 1
    WHITE = 2

finish_ns = {'DisMode': DisMode, 'logger': logging.getLogger(__name__), 'List': List, 'Optional': Optional}
finish_names = {'_finish_frame', '_bitmap_message_budget', '_graphics_message_budget', 'commit_frame', 'get_line_payload', 'get_clear_area_payload'}
exec(compile(ast.Module(body=[node for node in ast.walk(tree)
    if isinstance(node, ast.FunctionDef) and node.name in finish_names],
    type_ignores=[]), str(SOURCE), 'exec'), finish_ns)

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.frames = []
        self.commits = []
        protocol = SimpleNamespace(dis_mode=DisMode.WHITE, send_ddp_frame=lambda p, **kw: self.frames.append(list(p)) or True,
                                   poll_bus_events=Mock(), send_keepalive_if_needed=Mock())
        self.service = SimpleNamespace(ddp=protocol, _send_graphics=protocol.send_ddp_frame,
            _publish_frame_result=lambda seq, success: self.commits.append(success),
            get_text_payload=lambda text, *args: list(text),
            get_line_payload=lambda *args: [0x63, 4, 0x20, 0, 0, 8],
            get_clear_area_payload=lambda *args: [0x52, 5, 2, 0, 0x1b, 64, 9],
            _frame_failed=False)
        self.service._bitmap_message_budget = lambda: finish_ns['_bitmap_message_budget'](self.service)
        self.service._graphics_message_budget = lambda: finish_ns['_graphics_message_budget'](self.service)
        self.service.commit_frame = lambda: finish_ns['commit_frame'](self.service)
        self.service._finish_frame = lambda seq, pending_payload=None: finish_ns['_finish_frame'](
            self.service, seq, pending_payload=pending_payload)
    def process(self, commands):
        exec(code, {'self': self.service, 'cmds': commands, 'current_payload': [],
                    'must_colocate': False, 'logger': logging.getLogger(__name__)})
    def test_two_draws_and_commit_send_each_command_once(self):
        self.process([{'command': 'draw_text', 'text': [1, 2]},
                      {'command': 'draw_text', 'text': [3, 4]}, {'command': 'commit'}])
        self.assertEqual(self.frames, [[1, 2, 3, 4, 0x39]])
        self.assertEqual(self.commits, [True])
    def test_batch_without_commit_flushes_tail_once(self):
        self.process([{'command': 'draw_text', 'text': [1]},
                      {'command': 'draw_text', 'text': [2]}])
        self.assertEqual(self.frames, [[1, 2]])
    def test_size_limit_sends_two_distinct_payloads(self):
        self.service.ddp.dis_mode = DisMode.RED
        self.process([{'command': 'draw_text', 'text': [1] * 30},
                      {'command': 'draw_text', 'text': [2] * 20}])
        self.assertEqual(self.frames, [[1] * 30, [2] * 20])
    def test_white_default_combines_text_within105(self):
        self.process([{'command':'draw_text','text':[1]*30},
                      {'command':'draw_text','text':[2]*20}])
        self.assertEqual(self.frames,[[1]*30+[2]*20])

    def test_clear_area_and_paired_draw_share_one_send(self):
        self.process([{'command': 'clear_area'},
                      {'command': 'draw_text', 'text': [0x57, 3, 6, 0, 0]},
                      {'command': 'commit'}])
        self.assertEqual(self.frames, [[0x52, 5, 2, 0, 0x1b, 64, 9, 0x57, 3, 6, 0, 0], [0x39]])
        self.assertEqual(self.commits, [True])


    def use_real_bar_payloads(self):
        self.service.region_y_offset = 27
        self.service.region_height = 48
        self.service.get_line_payload = lambda *args: finish_ns['get_line_payload'](self.service, *args)
        self.service.get_clear_area_payload = lambda *args: finish_ns['get_clear_area_payload'](self.service, *args)

    def test_bar_clear_and_all_three_strokes_share_one_message(self):
        self.use_real_bar_payloads()
        clear = self.service.get_clear_area_payload(61, 0, 3, 48)
        lines = [self.service.get_line_payload(x, 30, 18, True, None) for x in (61, 62, 63)]
        for mode in (DisMode.WHITE, DisMode.RED):
            with self.subTest(mode=mode):
                self.frames.clear()
                self.commits.clear()
                self.service.ddp.dis_mode = mode
                self.process([{'command': 'clear_area', 'x': 61, 'y': 0, 'w': 3, 'h': 48}]
                    + [{'command': 'draw_line', 'x': x, 'y': 30, 'length': 18, 'vertical': True}
                       for x in (61, 62, 63)] + [{'command': 'commit'}])
                self.assertEqual(self.frames, [clear + sum(lines, []) + [0x39]])
                self.assertEqual(self.commits, [True])

    def test_bar_disappearance_sends_clear_without_strokes(self):
        self.use_real_bar_payloads()
        self.process([{'command': 'clear_area', 'x': 61, 'y': 0, 'w': 3, 'h': 48},
                      {'command': 'commit'}])
        self.assertEqual(self.frames, [self.service.get_clear_area_payload(61, 0, 3, 48) + [0x39]])
        self.assertEqual(self.commits, [True])

    def test_next_clear_flushes_complete_bar_before_text_pair(self):
        self.use_real_bar_payloads()
        clear_bar = self.service.get_clear_area_payload(61, 0, 3, 48)
        lines = [self.service.get_line_payload(x, 30, 18, True, None) for x in (61, 62, 63)]
        clear_text = self.service.get_clear_area_payload(42, 8, 19, 9)
        text = [0x57, 4, 6, 42, 8, 1]
        self.process([{'command': 'clear_area', 'x': 61, 'y': 0, 'w': 3, 'h': 48}]
            + [{'command': 'draw_line', 'x': x, 'y': 30, 'length': 18} for x in (61, 62, 63)]
            + [{'command': 'clear_area', 'x': 42, 'y': 8, 'w': 19, 'h': 9},
               {'command': 'draw_text', 'text': text}])
        self.assertEqual(self.frames, [clear_bar + sum(lines, []), clear_text + text])

    def test_clear_line_pair_exceeding_budget_is_rejected_without_exposing_clear(self):
        self.use_real_bar_payloads()
        self.service.ddp.dis_mode = DisMode.RED
        self.service.get_line_payload = lambda *args: [0x63] * 29
        with self.assertLogs(__name__, level='ERROR') as captured:
            self.process([{'command': 'clear_area', 'x': 61, 'y': 0, 'w': 3, 'h': 48},
                          {'command': 'draw_line', 'x': 61, 'y': 30, 'length': 18}])
        self.assertEqual(self.frames, [])
        self.assertTrue(self.service._frame_failed)
        self.assertIn('Clear/draw pair exceeds', captured.output[0])

    def test_line_tail_still_splits_at_application_budget(self):
        self.use_real_bar_payloads()
        self.service.ddp.dis_mode = DisMode.RED
        clear = self.service.get_clear_area_payload(61, 0, 3, 48)
        line = self.service.get_line_payload(61, 30, 18, True, None)
        self.process([{'command': 'clear_area', 'x': 61, 'y': 0, 'w': 3, 'h': 48}]
                     + [{'command': 'draw_line', 'x': 61, 'y': 30, 'length': 18}] * 6)
        self.assertEqual(self.frames, [clear + line * 4, line * 2])
        self.assertTrue(all(len(frame) <= 42 for frame in self.frames))

    def test_text_pair_still_flushes_before_following_text(self):
        self.use_real_bar_payloads()
        clear = self.service.get_clear_area_payload(1, 39, 60, 9)
        first, second = [0x57, 4, 6, 1, 39, 1], [0x57, 4, 6, 1, 39, 2]
        self.process([{'command': 'clear_area', 'x': 1, 'y': 39, 'w': 60, 'h': 9},
                      {'command': 'draw_text', 'text': first},
                      {'command': 'draw_text', 'text': second}])
        self.assertEqual(self.frames, [clear + first, second])

if __name__ == '__main__':
    unittest.main()
