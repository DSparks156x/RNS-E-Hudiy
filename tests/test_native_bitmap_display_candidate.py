"""Native public wrapper uses existing UI sequence, feedback and backpressure."""
import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent
MODULES = ROOT.parent / 'dis_client'
if MODULES.exists():
    sys.path.insert(0, str(MODULES))
DEFAULT_SOURCE = ROOT / 'dis_display_native_bitmap_candidate.py'
if not DEFAULT_SOURCE.exists():
    DEFAULT_SOURCE = MODULES / 'dis_display.py'
SOURCE = Path(os.environ.get('DIS_NATIVE_DISPLAY_SOURCE', DEFAULT_SOURCE))
TREE = ast.parse(SOURCE.read_text())
NAMES = {'draw_native_bitmap', '_handle_ui_frame_result'}
NS = {}
exec(compile(ast.Module(body=[n for n in ast.walk(TREE)
    if isinstance(n, ast.FunctionDef) and n.name in NAMES], type_ignores=[]), str(SOURCE), 'exec'), NS)
Engine = type('Engine', (), {name: NS[name] for name in NAMES})


class NativeDisplayTests(unittest.TestCase):
    def setUp(self):
        self.s = Engine()
        self.s.frame_seq_counter = 30
        self.s._pending_ui_frame = None
        self.s.service_ready, self.s.user_paused = True, False
        self.s._send_draw = Mock(return_value=True)
        self.s.current_app = SimpleNamespace(on_frame_sent=Mock(), on_frame_acked=Mock(),
                                             on_frame_failed=Mock(), on_display_reset=Mock())
        self.s.force_redraw = Mock()
        self.s.last_sent, self.s.last_sent_flags = {'groups': {'old': 'image'}}, {'line': 1}
        self.data = bytes((n * 29) & 255 for n in range(1536))

    def test_atomic_envelope_exact_pixels_and_matching_feedback(self):
        self.assertTrue(self.s.draw_native_bitmap(self.data))
        envelope = self.s._send_draw.call_args.args[0]
        self.assertEqual(envelope['command'], 'frame')
        self.assertEqual(envelope['seq'], 31)
        self.assertEqual(envelope['commands'], [dict(command='draw_native_bitmap',
            x=0, y=0, w=128, h=96, data_hex=self.data.hex(), render_order='planes', band_rows=12)])
        self.assertEqual(self.s._pending_ui_frame, (31, self.s.current_app))
        self.s.current_app.on_frame_sent.assert_called_once_with(31)
        self.assertTrue(self.s._handle_ui_frame_result(31, True))
        self.s.current_app.on_frame_acked.assert_called_once_with(31)
        self.assertIsNone(self.s._pending_ui_frame)

    def test_stale_feedback_and_second_frame_cannot_release_or_replace_pending(self):
        self.s.draw_native_bitmap(self.data)
        self.assertFalse(self.s._handle_ui_frame_result(30, True))
        self.assertFalse(self.s.draw_native_bitmap(bytes(1536)))
        self.assertEqual(self.s.frame_seq_counter, 31)
        self.s._send_draw.assert_called_once()
        self.s.current_app.on_frame_acked.assert_not_called()

    def test_band_option_is_forwarded_and_invalid_option_never_queues(self):
        for fields in (dict(render_order='invalid'), dict(band_rows=False), dict(band_rows=49)):
            with self.assertRaises(ValueError):
                self.s.draw_native_bitmap(self.data, **fields)
        self.s._send_draw.assert_not_called()
        self.assertEqual(self.s.frame_seq_counter, 30)
        self.assertTrue(self.s.draw_native_bitmap(self.data, render_order='bands', band_rows=12))
        command = self.s._send_draw.call_args.args[0]['commands'][0]
        self.assertEqual((command['render_order'], command['band_rows']), ('bands', 12))

    def test_nack_uses_existing_snapshot_reset_contract(self):
        self.s.draw_native_bitmap(self.data)
        self.assertTrue(self.s._handle_ui_frame_result(31, False))
        self.s.current_app.on_frame_failed.assert_called_once_with(31)
        self.s.force_redraw.assert_called_once_with(send_clear=True)
        self.assertIsNone(self.s._pending_ui_frame)

    def test_ipc_backpressure_never_waits_for_unqueued_frame(self):
        self.s._send_draw.return_value = False
        self.assertFalse(self.s.draw_native_bitmap(self.data))
        self.assertIsNone(self.s._pending_ui_frame)
        self.s.current_app.on_frame_sent.assert_not_called()
        self.s.current_app.on_display_reset.assert_called_once()
        self.assertEqual(self.s.last_sent, {})
        self.assertEqual(self.s.last_sent_flags, {})

    def test_not_ready_or_paused_does_not_queue_or_change_sequence(self):
        for ready, paused in ((False, False), (True, True)):
            self.s.service_ready, self.s.user_paused = ready, paused
            self.assertFalse(self.s.draw_native_bitmap(self.data))
        self.s._send_draw.assert_not_called()
        self.assertEqual(self.s.frame_seq_counter, 30)

    def test_invalid_pixels_fail_before_queue_sequence_or_cache_changes(self):
        for source in (bytes(1535), SimpleNamespace(mode='L', size=(128, 96)),
                       SimpleNamespace(mode='1', size=(64, 48))):
            with self.assertRaises(ValueError):
                self.s.draw_native_bitmap(source)
        self.s._send_draw.assert_not_called()
        self.assertEqual(self.s.frame_seq_counter, 30)
        self.assertEqual(self.s.last_sent, {'groups': {'old': 'image'}})

    def test_exact_pil_mode1_is_not_transformed_and_sequence_wraps_nonzero(self):
        image = SimpleNamespace(mode='1', size=(128, 96), tobytes=Mock(return_value=self.data))
        self.s.frame_seq_counter = 999999
        self.assertTrue(self.s.draw_native_bitmap(image))
        self.assertEqual(self.s._send_draw.call_args.args[0]['seq'], 1)
        self.assertEqual(self.s._send_draw.call_args.args[0]['commands'][0]['data_hex'], self.data.hex())
        image.tobytes.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
