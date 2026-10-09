"""Measured text replacement and actual service packet-loop regressions."""
import ast
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dis_client'))
from text_render import text_bounds, text_update
from font_metrics import measure_text
from icons import encode_audscii

TREE = ast.parse((ROOT / 'dis_client/dis_service.py').read_text())
NAMES = {'_graphics_message_budget', '_bitmap_message_budget',
         'get_text_update_payload', 'get_clear_area_payload', 'get_text_payload',
         '_finish_frame', 'commit_frame', '_send_graphics', '_publish_frame_result',
         '_expand_draw_command', '_broadcast_status', '_reject_draw_commands',
         '_validate_native_bar_retirement', '_stock_custom_transition'}
MODE = SimpleNamespace(WHITE='white', RED='red')
STATE = SimpleNamespace(READY='ready', PAUSED='paused', SESSION_ACTIVE='init', DISCONNECTED='disconnected')
NS = {'List': list, 'logger': logging.getLogger(__name__), 'DisMode': MODE,
      'DDPState': STATE, 'DDPError': RuntimeError, 'time': __import__('time'),
      'zmq': SimpleNamespace(NOBLOCK=1, ZMQError=RuntimeError)}
exec(compile(ast.Module(body=[node for node in ast.walk(TREE)
    if isinstance(node, ast.FunctionDef) and node.name in NAMES], type_ignores=[]),
    'dis_service.py', 'exec'), NS)
Service = type('Service', (), {name: NS[name] for name in NAMES})
LOOP = max([node for node in ast.walk(TREE) if isinstance(node, ast.For)
    and isinstance(node.target, ast.Name) and node.target.id == 'cmd'
    and isinstance(node.iter, ast.Name) and node.iter.id == 'cmds'], key=lambda n: len(n.body))
BODY = next(value for node in ast.walk(TREE) for _, value in ast.iter_fields(node)
    if isinstance(value, list) and any(v is LOOP for v in value))
CODE = compile(ast.Module(body=BODY[BODY.index(LOOP):], type_ignores=[]), 'dis_service.py', 'exec')


class MeasuredReplacementTests(unittest.TestCase):
    def cmd(self, text, x=0, y=0, flags=6):
        return dict(text=text, x=x, y=y, flags=flags)

    def test_same_character_count_shrink_clears_measured_prior_bounds(self):
        for profile in ('native', 'legacy'):
            old, new = self.cmd('WWW'), self.cmd('iii')
            self.assertEqual(len(old['text']), len(new['text']))
            update = text_update(new, old, profile)
            self.assertEqual(update['clear_rect']['w'], text_bounds(old, profile)[2])
            self.assertGreater(update['clear_rect']['w'], text_bounds(new, profile)[2])

    def test_growth_overwrites_without_wipe(self):
        self.assertNotIn('clear_rect', text_update(self.cmd('WWW'), self.cmd('iii')))

    def test_centered_shorter_text_erases_both_old_edges(self):
        old, new = self.cmd('WWW', flags=0x26), self.cmd('iii', flags=0x26)
        update = text_update(new, old)
        self.assertEqual(tuple(update['clear_rect'][k] for k in ('x','y','w','h')), text_bounds(old))
        self.assertGreater(text_bounds(new)[0], text_bounds(old)[0])

    def test_moving_text_cleans_previous_footprint(self):
        update = text_update(self.cmd('Main St', 12), self.cmd('Main St', 1))
        self.assertEqual(update['clear_rect']['x'], 1)

    def test_viewport_preserves_distance_bar(self):
        for profile in ('native', 'legacy'):
            update = text_update(self.cmd('i', 1, 39), self.cmd('W'*20, 1, 39),
                profile=profile, viewport=(0,39,61,9))
            r = update['clear_rect']
            self.assertLessEqual(r['x'] + r['w'], 61)
            self.assertEqual((r['y'], r['h']), (39,9))

    def test_inverted_to_normal_clears_entire_painted_fill(self):
        old=self.cmd('A',x=4,y=8,flags=0xA6)
        for text in ('A',''):
            update=text_update(self.cmd(text,x=4,y=8,flags=0x26),old)
            self.assertEqual(update['clear_rect'],dict(x=4,y=8,w=60,h=9))
            self.assertEqual(text_bounds(old),(4,8,60,9))

    def test_bounded_focus_clears_only_its_field_without_wiping_neighbors(self):
        old = dict(text='▶', x=38, y=0, flags=0x82, highlight_width=8)
        new = dict(old, flags=2)
        update = text_update(new, old)
        self.assertEqual(text_bounds(old), (38,0,8,9))
        self.assertEqual(update['clear_rect'], dict(x=38,y=0,w=8,h=9))
        self.assertEqual(update['highlight_width'], 8)
        self.assertLess(update['clear_rect']['x'] + update['clear_rect']['w'], 48)
        self.assertEqual(text_update(dict(old, text=''), old)['clear_rect'],
                         dict(x=38,y=0,w=8,h=9))

    def test_shrinking_focus_height_erases_prior_bottom_edge(self):
        old = dict(text='▶', x=38, y=0, flags=0x82, highlight_width=4, highlight_height=9)
        new = dict(old, highlight_height=7)
        update = text_update(new, old)
        self.assertEqual(text_bounds(new), (38,0,4,7))
        self.assertEqual(update['highlight_height'], 7)
        self.assertEqual(update['clear_rect'], dict(x=38,y=0,w=4,h=9))

    def test_shifted_inversion_erases_previous_fill_and_clips_viewport(self):
        old=self.cmd('A',x=3,y=8,flags=0x86)
        new=self.cmd('A',x=9,y=8,flags=0x86)
        update=text_update(new,old,viewport=(0,8,61,9))
        self.assertEqual(update['clear_rect'],dict(x=3,y=8,w=58,h=9))
        self.assertEqual(text_bounds(new),(9,8,55,9))

    def test_removing_text_only_erases_prior_bounds(self):
        update = text_update(self.cmd(''), self.cmd('Hi', 3, 8))
        self.assertEqual(update['clear_rect']['x'], 3)
        self.assertEqual(update['clear_rect']['y'], 8)
        self.assertLess(update['clear_rect']['w'],64)


class AtomicServiceTextTests(unittest.TestCase):
    def setUp(self):
        self.s = Service()
        self.s.config = {}
        self.s.command_cache = {}
        self.s.region_y_offset, self.s.region_height = 27,48
        self.s.translate_to_audscii = lambda text: list(encode_audscii(text))
        self.frames, self.results = [], []
        self.s.ddp = SimpleNamespace(dis_mode='white', state='ready',
            renderer_command_family=lambda:0x52, renderer_ready=lambda:True,
            presentation_request_generation=0,
            send_ddp_frame=lambda payload, **kw: self.frames.append(list(payload)) or True,
            poll_bus_events=lambda:None, send_keepalive_if_needed=lambda:None)
        self.s.status_pub=SimpleNamespace(send_string=lambda message, **kw:self.results.append(message))
        self.s._frame_failed=False

    def process(self, commands):
        exec(CODE,dict(NS,self=self.s,cmds=commands,current_payload=[],must_colocate=False))

    def test_long_to_short_clear_and_text_are_in_same_message(self):
        update=text_update(dict(text='iii',x=1,y=39,flags=6),dict(text='WWW',x=1,y=39,flags=6))
        expected=self.s.get_text_update_payload(update)
        self.process([update,dict(command='commit',seq=7)])
        self.assertEqual(self.frames,[expected,[0x39]])
        self.assertEqual(self.results,['DRAW_ACK 7'])

    def test_bounded_native_inversion_reaches_wire_and_restores_region(self):
        command = dict(command='draw_text',text='□',x=38,y=0,flags=0x82,highlight_width=8)
        expected = [0x52,5,3,38,27,8,9,0x57,4,0,0,0,0xab,
                    0x52,5,0,0,27,64,48]
        self.assertEqual(self.s.get_text_payload('□',38,0,0x82,highlight_width=8), expected)
        self.process([command,dict(command='commit',seq=15)])
        self.assertEqual(self.frames,[expected,[0x39]])
        update = dict(command,command='update_text')
        self.assertEqual(self.s.get_text_update_payload(update),expected)
        for width in (0, -1, 27, True, 8.5):
            with self.subTest(width=width):
                self.assertRaises(ValueError,self.s.get_text_payload,'□',38,0,0x82,
                                  highlight_width=width)

    def test_native_glyph_inversion_clips_font_padding_and_checks_height(self):
        command = dict(command='draw_text',text='▶',x=38,y=0,flags=0x82,
                       highlight_width=4,highlight_height=7)
        expected = [0x52,5,3,38,27,4,7,0x57,4,0,0,0,0x69,0x52,5,0,0,27,64,48]
        self.process([command,dict(command='commit',seq=16)])
        self.assertEqual(self.frames,[expected,[0x39]])
        self.assertEqual(self.s.get_text_update_payload(command),expected)
        for height in (0, -1, 49, True, 7.5):
            with self.subTest(height=height):
                self.assertRaises(ValueError,self.s.get_text_payload,'▶',38,0,0x82,
                                  highlight_width=4,highlight_height=height)

    def test_atomic_pair_flushes_prior_packet_without_splitting(self):
        prefix=dict(command='draw_text',text='i'*85,x=0,y=0)
        update=text_update(dict(text='iii',x=1,y=39),dict(text='WWW',x=1,y=39))
        self.process([prefix,update,dict(command='commit',seq=8)])
        self.assertEqual(self.frames[1],self.s.get_text_update_payload(update))
        self.assertEqual(self.frames[-1],[0x39])
        self.assertTrue(all(len(p)<=105 for p in self.frames))

    def test_oversized_pair_rejected_before_its_clear(self):
        update=dict(command='update_text',text='i'*100,clear_rect=dict(x=0,y=0,w=64,h=9))
        self.assertRaises(ValueError,self.s.get_text_update_payload,update)
        self.process([update,dict(command='commit',seq=9)])
        self.assertEqual(self.frames,[])
        self.assertEqual(self.results,['DRAW_NACK 9'])

    def test_red_commit_does_not_overflow_full_application_message(self):
        self.s.ddp.dis_mode='red'
        update=dict(command='update_text',text='i'*30,clear_rect=dict(x=0,y=0,w=64,h=9))
        self.process([update,dict(command='commit',seq=11)])
        self.assertEqual([len(p) for p in self.frames],[49,1])
        self.assertEqual(self.results,['DRAW_ACK 11'])

    def test_partial_overlapping_move_erases_old_edges_atomically(self):
        old=dict(text='WWW',x=1,y=8,flags=6)
        new=dict(text='WWW',x=4,y=8,flags=6)
        update=text_update(new,old)
        self.process([update,dict(command='commit',seq=12)])
        self.assertEqual(self.frames,[self.s.get_text_update_payload(update),[0x39]])
        self.assertEqual(update['clear_rect']['x'],1)

    def test_frame_preflight_rejects_oversized_pair_without_draws(self):
        update=dict(command='update_text',text='i'*100,clear_rect=dict(x=0,y=0,w=64,h=9))
        self.assertEqual(self.s._expand_draw_command(dict(command='frame',seq=10,commands=[update])),[])
        self.assertEqual(self.frames,[])
        self.assertEqual(self.results,['DRAW_NACK 10'])

    def test_resume_control_cannot_poison_following_valid_frame(self):
        self.s._reject_draw_commands([dict(command='resume')])
        self.assertFalse(self.s._frame_failed)
        self.process([dict(command='update_text',text='Next'),dict(command='commit',seq=13)])
        self.assertEqual(self.results,['DRAW_ACK 13'])
        self.assertTrue(self.frames)

    def test_busy_sequenced_frame_is_still_rejected(self):
        self.s._reject_draw_commands([dict(command='frame',seq=14,commands=[])])
        self.assertEqual(self.results,['DRAW_NACK 14'])
        self.assertFalse(self.s._frame_failed)

    def test_red_caps_atomic_message_at49(self):
        self.s.ddp.dis_mode='red'
        self.assertRaises(ValueError,self.s.get_text_update_payload,
            dict(command='update_text',text='i'*31,clear_rect=dict(x=0,y=0,w=64,h=9)))

    def test_inactive_requested_generation_published_once_not_initial_ready(self):
        self.s.presentation_requested=False
        self.s.screen_is_active=False
        self.s._broadcast_status()
        self.assertFalse(any(m.startswith('DIS_REQUESTED') for m in self.results))
        self.s.ddp.presentation_request_generation=1
        self.s._broadcast_status()
        self.s._broadcast_status()
        self.assertEqual(self.results.count('DIS_REQUESTED 1'),1)

    def test_active_request_not_replayed_when_later_paused(self):
        self.s.presentation_requested=True
        self.s.screen_is_active=True
        self.s.ddp.presentation_request_generation=1
        self.s._broadcast_status()
        self.s.presentation_requested=False
        self.s.screen_is_active=False
        self.s._broadcast_status()
        self.assertFalse(any(m.startswith('DIS_REQUESTED') for m in self.results))


if __name__ == '__main__':
    unittest.main()
