"""Real UI/app state transitions for stale ACK/NACK and a rejected snapshot."""
import ast
import time
import unittest
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parent.parent / 'dis_client/dis_display.py'
TREE = ast.parse(SOURCE.read_text())
NAMES = {'_commit_ui_frame', '_handle_ui_frame_result', 'force_redraw'}
ns = {}
methods = [n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name in NAMES]
exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), 'exec'), ns)

class Base:
    def __init__(self, config): pass
    def on_enter(self): pass

APP_SOURCE = SOURCE.parent / 'apps/easteregg.py'
app_tree = ast.parse(APP_SOURCE.read_text())
app_cls = next(n for n in app_tree.body if isinstance(n, ast.ClassDef))
app_cls.body = [n for n in app_cls.body if isinstance(n, ast.FunctionDef) and n.name != 'load_gif']
app_ns = {'BaseApp': Base, 'time': time}
exec(compile(ast.Module(body=[app_cls], type_ignores=[]), str(APP_SOURCE), 'exec'), app_ns)

class FrameResultTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.clock = patch.object(time, 'time', lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.app = app_ns['EasterEggApp']()
        self.app.frames = [[{'cmd': 'draw_raw_bitmap', 'data_hex': 'delta0'}],
                           [{'cmd': 'draw_raw_bitmap', 'data_hex': 'delta1'}]]
        self.app.full_frames = [[{'cmd': 'draw_raw_bitmap', 'data_hex': 'full0'}],
                                [{'cmd': 'draw_raw_bitmap', 'data_hex': 'full1'}]]
        self.app.is_loaded = True
        self.app.on_enter()
        self.e = SimpleNamespace(current_app=self.app, frame_seq_counter=100,
            _pending_ui_frame=None, _send_draw=Mock(return_value=True),
            last_sent={'groups': {'frame': 'cached'}}, last_sent_flags={'line': 1},
            user_paused=False, boot_inactive_hold=False, publish_status=Mock())
        for name in NAMES:
            setattr(self.e, name, MethodType(ns[name], self.e))

    def commit(self):
        self.assertTrue(self.e._commit_ui_frame())
        self.assertEqual(self.e._pending_ui_frame, (101, self.app))

    def test_stale_nack_does_not_unlock_or_reset_current_frame(self):
        self.commit()
        generation = self.app._view_generation
        self.assertFalse(self.e._handle_ui_frame_result(100, False))
        self.assertEqual(self.e._pending_ui_frame, (101, self.app))
        self.assertEqual(self.app.last_sent_seq, 101)
        self.assertEqual(self.app.last_acked_seq, 0)
        self.assertEqual(self.app._view_generation, generation)
        self.assertEqual(self.e.last_sent['groups'], {'frame': 'cached'})
        self.assertEqual(self.e._send_draw.call_count, 1)

    def test_old_app_nack_does_not_reset_new_app_with_matching_sequence(self):
        self.commit()
        new_app = SimpleNamespace(on_frame_failed=Mock(), on_display_reset=Mock())
        self.e.current_app = new_app
        self.assertFalse(self.e._handle_ui_frame_result(101, False))
        new_app.on_frame_failed.assert_not_called()
        new_app.on_display_reset.assert_not_called()
        self.assertEqual(self.e._send_draw.call_count, 1)

    def test_matching_nack_restores_full_current_snapshot_once(self):
        self.app._snapshot_pending = False
        self.app._full_frame = False
        self.app.current_frame_idx = 1
        self.commit()
        self.assertTrue(self.e._handle_ui_frame_result(101, False))
        self.assertIsNone(self.e._pending_ui_frame)
        self.assertEqual(self.e.last_sent, {})
        self.assertEqual(self.app.get_view()[1]['data_hex'], 'full1')
        self.assertTrue(self.app._snapshot_pending)
        self.assertEqual([call.args[0] for call in self.e._send_draw.call_args_list][1:],
                         [{'command': 'clear'}, {'command': 'commit'}])
        generation = self.app._view_generation
        self.assertFalse(self.e._handle_ui_frame_result(101, False))
        self.assertEqual(self.app._view_generation, generation)

    def test_only_matching_ack_completes_pending_frame(self):
        self.commit()
        self.assertFalse(self.e._handle_ui_frame_result(100, True))
        self.assertEqual(self.app.last_acked_seq, 0)
        self.assertTrue(self.e._handle_ui_frame_result(101, True))
        self.assertEqual(self.app.last_acked_seq, 101)
        self.assertIsNone(self.e._pending_ui_frame)
        self.assertEqual(self.e._send_draw.call_count, 1)

    def test_dropped_commit_restores_snapshot_and_creates_no_pending_frame(self):
        self.e._send_draw.return_value = False
        self.assertFalse(self.e._commit_ui_frame())
        self.assertIsNone(self.e._pending_ui_frame)
        self.assertEqual(self.app.last_sent_seq, 0)
        self.assertTrue(self.app._snapshot_pending)
        self.assertEqual(self.e.last_sent, {})

    def test_ownership_redraw_invalidates_old_result_before_next_commit(self):
        self.commit()
        self.e.force_redraw()
        self.assertIsNone(self.e._pending_ui_frame)
        self.assertFalse(self.e._handle_ui_frame_result(101, False))

if __name__ == '__main__':
    unittest.main()
