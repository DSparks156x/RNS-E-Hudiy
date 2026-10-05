import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'dis_client/dis_display.py'
if not SOURCE.exists():
    SOURCE = ROOT.parent / 'RNS-E-Hudiy/dis_client/dis_display.py'
tree = ast.parse(SOURCE.read_text())
node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_commit_ui_frame')
ns = {}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), ns)

class CommitBackpressureTests(unittest.TestCase):
    def setUp(self):
        self.s = SimpleNamespace(frame_seq_counter=100, _send_draw=Mock(return_value=True),
            current_app=SimpleNamespace(on_frame_sent=Mock(), on_display_reset=Mock()),
            last_sent={'groups': {'frame': 'cached'}}, last_sent_flags={'line': 1})

    def test_queued_commit_waits_for_ack(self):
        self.assertTrue(ns['_commit_ui_frame'](self.s))
        self.s.current_app.on_frame_sent.assert_called_once_with(101)
        self.s.current_app.on_display_reset.assert_not_called()

    def test_full_ipc_queue_never_enters_wait_for_missing_ack(self):
        self.s._send_draw.return_value = False
        self.assertFalse(ns['_commit_ui_frame'](self.s))
        self.s.current_app.on_frame_sent.assert_not_called()
        self.s.current_app.on_display_reset.assert_called_once()
        self.assertEqual(self.s.last_sent, {})
        self.assertEqual(self.s.last_sent_flags, {})

    def test_wrap_keeps_nonzero_sequence(self):
        self.s.frame_seq_counter = 999999
        ns['_commit_ui_frame'](self.s)
        self.s.current_app.on_frame_sent.assert_called_once_with(1)

if __name__ == '__main__':
    unittest.main()
