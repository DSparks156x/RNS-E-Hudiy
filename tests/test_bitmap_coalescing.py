import ast
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'dis_client/dis_service.py'
if not SOURCE.exists():
    SOURCE = ROOT.parent / 'RNS-E-Hudiy/dis_client/dis_service.py'
tree = ast.parse(SOURCE.read_text())
names = {'_raw_bitmap_payload', '_coalesce_bitmap_commands', '_send_raw_bitmap_batch',
         '_bitmap_message_budget', '_bitmap_rows_per_command', '_bitmap_row_records'}
ns = {'DisMode': SimpleNamespace(WHITE='white', RED='red'), 'logger': logging.getLogger(__name__)}
exec(compile(ast.Module(body=[n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names],
                       type_ignores=[]), str(SOURCE), 'exec'), ns)
Service = type('Service', (), {name: ns[name] for name in names})

def tile(x=0, y=0, w=8, h=1):
    return {'command': 'draw_raw_bitmap', 'x': x, 'y': y, 'w': w, 'h': h,
            'data_hex': (b'\xaa' * ((w + 7) // 8) * h).hex()}

class BitmapCoalescingTests(unittest.TestCase):
    def setUp(self):
        self.s = Service()
        self.s.ddp = SimpleNamespace(dis_mode='white')
        self.s.UNSAFE_BATCHING_BYPASS = False
        self.s.coalesce_bitmaps = True
        self.s.region_y_offset, self.s.region_height = 27, 48
        self.s._send_graphics = lambda p, **kw: self.s.sent.append((p, kw)) or True
        self.s.sent = []

    def test_consecutive_tiles_share_message_with_one_region_reset(self):
        commands = [tile(), tile(8, 2)]
        grouped = self.s._coalesce_bitmap_commands(commands)
        self.assertEqual(len(grouped), 1)
        self.s._send_raw_bitmap_batch(grouped[0]['commands'])
        payload, options = self.s.sent[0]
        self.assertEqual(payload, [0x52, 5, 0, 0, 27, 8, 1, 0x55, 4, 2, 0, 0, 0xaa,
                                   0x52, 5, 0, 8, 29, 8, 1, 0x55, 4, 2, 0, 0, 0xaa,
                                   0x52, 5, 0, 0, 27, 64, 48])
        self.assertEqual(options, {'pacing': False})

    def test_text_clear_and_commit_preserve_order(self):
        commands = [tile(), tile(), {'command': 'draw_text'}, tile(), {'command': 'commit'}]
        self.assertEqual([c['command'] for c in self.s._coalesce_bitmap_commands(commands)],
                         ['draw_raw_bitmap_batch', 'draw_text', 'draw_raw_bitmap', 'commit'])

    def test_batch_message_bound_does_not_change_tp2_ack_limit(self):
        grouped = self.s._coalesce_bitmap_commands([tile(h=48)] * 9)
        for batch in grouped:
            if batch['command'] == 'draw_raw_bitmap_batch':
                size = sum(len(self.s._raw_bitmap_payload(t)) for t in batch['commands']) + 7
                self.assertLessEqual(size, 768)
        self.assertGreater(len(grouped), 1)

    def test_red_display_keeps_existing_path(self):
        self.s.ddp.dis_mode = 'red'
        commands = [tile(), tile()]
        self.assertEqual(self.s._coalesce_bitmap_commands(commands), commands)

    def test_unverified_coalescing_is_disabled_by_default(self):
        del self.s.coalesce_bitmaps
        commands = [tile(), tile()]
        self.assertEqual(self.s._coalesce_bitmap_commands(commands), commands)

    def test_bad_bitmap_cannot_be_transferred_as_successful_batch(self):
        bad = tile()
        bad['data_hex'] = ''
        self.assertFalse(self.s._send_raw_bitmap_batch([bad]))
        self.assertTrue(self.s._frame_failed)
        self.assertEqual(self.s.sent, [])

    def test_clear_area_and_coalesced_bitmap_are_one_atomic_send(self):
        loops = [n for n in ast.walk(tree) if isinstance(n, ast.For)
                 and isinstance(n.target, ast.Name) and n.target.id == 'cmd'
                 and isinstance(n.iter, ast.Name) and n.iter.id == 'cmds']
        loop = max(loops, key=lambda n: len(n.body))
        body = next(value for n in ast.walk(tree) for _, value in ast.iter_fields(n)
                    if isinstance(value, list) and any(v is loop for v in value))
        code = compile(ast.Module(body=body[body.index(loop):], type_ignores=[]), str(SOURCE), 'exec')
        clear = [0x52, 5, 2, 0, 27, 64, 48, 0x52, 5, 0, 0, 27, 64, 48]
        self.s.get_clear_area_payload = lambda *args: clear
        self.s._finish_frame = lambda seq: True
        self.s.ddp.poll_bus_events = lambda: None
        self.s.ddp.send_keepalive_if_needed = lambda: None
        commands = [{'command': 'clear_area'},
                    {'command': 'draw_raw_bitmap_batch', 'commands': [tile(), tile(8)]},
                    {'command': 'commit'}]
        exec(code, {'self': self.s, 'cmds': commands, 'current_payload': [], 'must_colocate': False})
        self.assertEqual(len(self.s.sent), 1)
        self.assertEqual(self.s.sent[0][0][:len(clear)], clear)
        self.assertEqual(self.s.sent[0][0][len(clear):len(clear) + 2], [0x52, 5])

if __name__ == '__main__':
    unittest.main()
