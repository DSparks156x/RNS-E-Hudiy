"""Offline actual-service native candidate dispatch, feedback and full-image cache."""
import ast
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

REPO_MODULES = Path(__file__).resolve().parent.parent / 'dis_client'
if REPO_MODULES.exists():
    sys.path.insert(0, str(REPO_MODULES))

DEFAULT_SOURCE = Path(__file__).resolve().parent / 'dis_service_native_bitmap_candidate.py'
if not DEFAULT_SOURCE.exists():
    DEFAULT_SOURCE = Path(__file__).resolve().parent.parent / 'dis_client/dis_service.py'
SOURCE = Path(os.environ.get('DIS_NATIVE_BITMAP_SOURCE', DEFAULT_SOURCE))
TREE = ast.parse(SOURCE.read_text())
NAMES = {'_native_bitmap_command', '_send_native_bitmap_frame', '_expand_draw_command',
         '_reject_draw_commands', '_send_graphics', '_finish_frame', '_bitmap_message_budget',
         'commit_frame', '_publish_frame_result', 'handle_redraw', '_coalesce_bitmap_commands'}
NS = dict(logger=logging.getLogger(__name__), DDPError=RuntimeError,
          DisMode=SimpleNamespace(WHITE='white'),
          zmq=SimpleNamespace(NOBLOCK=1, ZMQError=RuntimeError))
exec(compile(ast.Module(body=[node for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef)
    and node.name in NAMES], type_ignores=[]), str(SOURCE), 'exec'), NS)
Service = type('Service', (), {name: NS[name] for name in NAMES})
LOOPS = [node for node in ast.walk(TREE) if isinstance(node, ast.For)
    and isinstance(node.target, ast.Name) and node.target.id == 'cmd'
    and isinstance(node.iter, ast.Name) and node.iter.id == 'cmds']
LOOP = max(LOOPS, key=lambda node: len(node.body))
BODY = next(value for node in ast.walk(TREE) for _, value in ast.iter_fields(node)
    if isinstance(value, list) and any(item is LOOP for item in value))
DRAW = compile(ast.Module(body=BODY[BODY.index(LOOP):], type_ignores=[]), str(SOURCE), 'exec')
CACHE_LOOP = next(node for node in LOOPS if any(isinstance(child, ast.Assign)
    and any(isinstance(target, ast.Attribute) and target.attr == 'command_cache'
            for target in child.targets) for child in ast.walk(node)))
CACHE = compile(ast.Module(body=[CACHE_LOOP], type_ignores=[]), str(SOURCE), 'exec')


class NativeBitmapIntegrationTests(unittest.TestCase):
    def test_band_options_are_cached_and_restored_without_losing_order(self):
        self.setUp()
        command = dict(self.command, render_order='bands', band_rows=12)
        prepared = self.s._expand_draw_command(command)[0]
        self.assertEqual((prepared['source']['render_order'], prepared['source']['band_rows']), ('bands', 12))
        restored = self.s._native_bitmap_command(prepared['source'])
        self.assertEqual(prepared['payloads'], restored['payloads'])
        for fields in (dict(render_order='bad'), dict(band_rows=0), dict(band_rows=True), dict(band_rows=49)):
            self.results.clear()
            self.assertEqual(self.s._expand_draw_command(dict(command, **fields)), [])
            self.assertEqual(self.results, ['DRAW_NACK 71'])
        self.assertEqual(self.sent, [])

    def setUp(self):
        self.s = Service()
        self.s.config, self.s.command_cache = {}, {}
        self.s.region_y_offset, self.s.region_height = 27, 48
        self.s.UNSAFE_BATCHING_BYPASS = False
        self.sent, self.results, self.outcomes, self.trace = [], [], [], []
        def transfer(payload, pacing=True):
            self.sent.append(list(payload))
            self.trace.append(('wire', list(payload)))
            return self.outcomes.pop(0) if self.outcomes else True
        self.s.ddp = SimpleNamespace(dis_mode='white', send_ddp_frame=transfer,
            poll_bus_events=lambda: None, send_keepalive_if_needed=lambda: None)
        self.s.status_pub = SimpleNamespace(send_string=lambda value, flags: self.results.append(value))
        self.s._presentation_control = lambda command: False
        self.s.clear_screen_payload = lambda: self.trace.append(('clear',))
        self.s.write_text = lambda *args: self.trace.append(('text',))
        self.s.draw_line = lambda *args: self.trace.append(('line',))
        self.s.draw_bitmap = lambda *args: None
        raw = bytearray(1536)
        raw[0] = 0x80
        self.command = dict(command='draw_native_bitmap', data_hex=raw.hex(), seq=71)

    def expand_draw(self, envelope):
        cmds = self.s._expand_draw_command(envelope)
        exec(CACHE, dict(NS, self=self.s, cmds=cmds, had_clear=False))
        exec(DRAW, dict(NS, self=self.s, cmds=cmds, current_payload=[], must_colocate=False))
        return cmds

    def test_direct_snapshot_has_one_commit_and_matched_ack(self):
        commands = self.expand_draw(self.command)
        self.assertEqual([cmd['command'] for cmd in commands], ['_native_bitmap_frame', 'commit'])
        self.assertEqual(self.results, ['DRAW_ACK 71'])
        self.assertEqual(self.sent[-1], [0x39])
        self.assertEqual(self.sent.count([0x39]), 1)
        self.assertTrue(all(len(packet) <= 105 for packet in self.sent))
        self.assertEqual(self.sent[0], [0x52, 5, 0, 0, 27, 64, 48])
        self.assertIn([0x55, 4, 1, 0, 47, 0, 0x63, 4, 0, 0, 0, 1], self.sent)

    def test_frame_child_uses_parent_seq_and_one_final_result(self):
        self.expand_draw(dict(command='frame', seq=82, commands=[self.command]))
        self.assertEqual(self.results, ['DRAW_ACK 82'])
        self.assertEqual(self.sent.count([0x39]), 1)

    def test_invalid_input_or_private_ipc_is_rejected_before_any_write(self):
        for changes in (dict(data_hex='zz'), dict(data_hex='00' * 1535), dict(w=64),
                        dict(h=48), dict(x=1), dict(y=1), dict(command='_native_bitmap_frame')):
            with self.subTest(changes=changes):
                self.results.clear()
                self.assertEqual(self.s._expand_draw_command(dict(self.command, **changes)), [])
                self.assertEqual(self.results, ['DRAW_NACK 71'])
                self.assertEqual(self.sent, [])

    def test_unsupported_mode_region_and_region_change_preflight(self):
        for mode, y, h in (('red', 27, 48), ('white', 0, 88), ('white', 27, 61)):
            self.s.ddp.dis_mode, self.s.region_y_offset, self.s.region_height = mode, y, h
            self.assertEqual(self.s._expand_draw_command(self.command), [])
        self.s.ddp.dis_mode, self.s.region_y_offset, self.s.region_height = 'white', 27, 48
        self.assertEqual(self.s._expand_draw_command(dict(command='frame', seq=90,
            commands=[self.command, dict(command='set_region', region='full')])), [])
        self.assertEqual(self.sent, [])

    def test_failure_latch_stops_body_suppresses_commit_and_nacks_once(self):
        self.outcomes = [False]
        self.expand_draw(self.command)
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn([0x39], self.sent)
        self.assertEqual(self.results, ['DRAW_NACK 71'])
        self.assertFalse(self.s._frame_failed)

    def test_unowned_or_paused_direct_native_receives_matched_nack(self):
        self.s._reject_draw_commands([self.command])
        self.assertEqual(self.results, ['DRAW_NACK 71'])
        self.assertEqual(self.sent, [])

    def test_full_snapshot_replaces_stale_region_cache_and_keeps_new_overlay_order(self):
        self.s.command_cache = {('draw_text', 10, 3): dict(command='draw_text', text='old')}
        expanded = self.s._expand_draw_command(self.command)
        overlay = dict(command='draw_text', x=2, y=4, text='new')
        line = dict(command='draw_line', x=0, y=0, length=1)
        cmds = expanded[:-1] + [overlay, line, dict(overlay, text='newer')]
        exec(CACHE, dict(NS, self=self.s, cmds=cmds, had_clear=False))
        cached = list(self.s.command_cache.values())
        self.assertEqual([command['command'] for command in cached],
                         ['draw_native_bitmap', 'draw_line', 'draw_text'])
        self.assertEqual(cached[0]['data_hex'], self.command['data_hex'])
        self.assertNotIn('payloads', cached[0])
        self.assertEqual(cached[-1]['text'], 'newer')

    def test_redraw_rebuilds_opaque_native_before_new_overlays(self):
        self.expand_draw(self.command)
        self.s.command_cache[('draw_text', 3, 3)] = dict(command='draw_text', text='overlay')
        self.sent.clear()
        self.results.clear()
        self.trace.clear()
        self.s.handle_redraw()
        self.assertEqual(self.trace[0], ('clear',))
        self.assertEqual(self.trace[-2], ('text',))
        self.assertEqual(self.sent[0], [0x52, 5, 0, 0, 27, 64, 48])
        self.assertEqual(self.sent[-1], [0x39])
        self.assertEqual(self.results, [])

    def test_unsupported_restore_has_no_clear_or_partial_native_write(self):
        prepared = self.s._native_bitmap_command(self.command)
        self.s.command_cache = {('draw_native_bitmap', 0, 0): prepared['source']}
        self.s.ddp.dis_mode = 'red'
        self.assertFalse(self.s.handle_redraw())
        self.assertEqual(self.trace, [])
        self.assertTrue(self.s._frame_failed)


if __name__ == '__main__':
    unittest.main()
