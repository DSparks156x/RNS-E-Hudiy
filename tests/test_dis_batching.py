"""Offline regression tests executing the actual service's draw-command loop."""
import ast
import logging
import unittest
from pathlib import Path
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
finish_ns = {'logger': logging.getLogger(__name__)}
finish_names = {'_finish_frame', '_bitmap_message_budget', 'commit_frame'}
exec(compile(ast.Module(body=[node for node in ast.walk(tree)
    if isinstance(node, ast.FunctionDef) and node.name in finish_names],
    type_ignores=[]), str(SOURCE), 'exec'), finish_ns)

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.frames = []
        self.commits = []
        protocol = SimpleNamespace(send_ddp_frame=lambda p, **kw: self.frames.append(list(p)) or True,
                                   poll_bus_events=Mock(), send_keepalive_if_needed=Mock())
        self.service = SimpleNamespace(ddp=protocol, _send_graphics=protocol.send_ddp_frame,
            _publish_frame_result=lambda seq, success: self.commits.append(success),
            get_text_payload=lambda text, *args: list(text),
            get_line_payload=lambda *args: [0x63, 4, 0x20, 0, 0, 8],
            get_clear_area_payload=lambda *args: [0x52, 5, 2, 0, 0x1b, 64, 9],
            _frame_failed=False)
        self.service._bitmap_message_budget = lambda: finish_ns['_bitmap_message_budget'](self.service)
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
        self.process([{'command': 'draw_text', 'text': [1] * 30},
                      {'command': 'draw_text', 'text': [2] * 20}])
        self.assertEqual(self.frames, [[1] * 30, [2] * 20])
    def test_clear_area_and_paired_draw_share_one_send(self):
        self.process([{'command': 'clear_area'},
                      {'command': 'draw_text', 'text': [0x57, 3, 6, 0, 0]},
                      {'command': 'commit'}])
        self.assertEqual(self.frames, [[0x52, 5, 2, 0, 0x1b, 64, 9, 0x57, 3, 6, 0, 0], [0x39]])
        self.assertEqual(self.commits, [True])

if __name__ == '__main__':
    unittest.main()
