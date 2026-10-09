"""Run actual service bitmap/commit logic offline; never open IPC or CAN."""
import ast
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'dis_client/dis_service.py'
if not SOURCE.exists():
    SOURCE = ROOT.parent / 'RNS-E-Hudiy/dis_client/dis_service.py'
TREE = ast.parse(SOURCE.read_text())
NAMES = {'_graphics_message_budget', '_bitmap_message_budget', '_bitmap_rows_per_command', '_bitmap_row_records', '_finish_frame', 'commit_frame', '_send_graphics',
         '_publish_frame_result', '_coalesce_bitmap_commands', '_raw_bitmap_payload'}
NS = {'logger': logging.getLogger(__name__), 'DDPError': RuntimeError,
      'DisMode': SimpleNamespace(WHITE='white', RED='red'),
      'zmq': SimpleNamespace(NOBLOCK=1, ZMQError=RuntimeError)}
exec(compile(ast.Module(body=[n for n in ast.walk(TREE)
    if isinstance(n, ast.FunctionDef) and n.name in NAMES], type_ignores=[]), str(SOURCE), 'exec'), NS)
Service = type('Service', (), {name: NS[name] for name in NAMES})
LOOPS = [n for n in ast.walk(TREE) if isinstance(n, ast.For)
    and isinstance(n.target, ast.Name) and n.target.id == 'cmd'
    and isinstance(n.iter, ast.Name) and n.iter.id == 'cmds']
LOOP = max(LOOPS, key=lambda n: len(n.body))
BODY = next(value for n in ast.walk(TREE) for _, value in ast.iter_fields(n)
    if isinstance(value, list) and any(v is LOOP for v in value))
CODE = compile(ast.Module(body=BODY[BODY.index(LOOP):], type_ignores=[]), str(SOURCE), 'exec')


class BitmapMessageBudgetTests(unittest.TestCase):
    def setUp(self):
        self.s = Service()
        self.s.config = {}
        self.s.UNSAFE_BATCHING_BYPASS = False
        self.s.region_y_offset, self.s.region_height = 27, 48
        self.sent, self.results = [], []
        self.outcomes = []
        def transfer(payload, pacing=True):
            self.sent.append(list(payload))
            return self.outcomes.pop(0) if self.outcomes else True
        self.s.ddp = SimpleNamespace(send_ddp_frame=transfer, dis_mode='white',
            poll_bus_events=lambda: None, send_keepalive_if_needed=lambda: None,
            renderer_command_family=lambda: 0x57, renderer_ready=lambda: True)
        self.s.status_pub = SimpleNamespace(send_string=lambda message, flags: self.results.append(message))
        self.raw = bytes((i * 37 + 11) & 255 for i in range(8 * 48))
        self.bitmap = {'command': 'draw_raw_bitmap', 'x': 0, 'y': 0,
                       'w': 64, 'h': 48, 'mode_flag': 2, 'data_hex': self.raw.hex()}

    def run_frame(self, command=None, seq=42):
        exec(CODE, dict(NS, self=self.s, cmds=[command or self.bitmap,
             {'command': 'commit', 'seq': seq}], current_payload=[], must_colocate=False))

    def decode(self):
        commands = []
        for packet in self.sent:
            at = 0
            while at < len(packet):
                if packet[at] == 0x39:
                    length = 1
                else:
                    self.assertIn(packet[at], (0x52, 0x55))
                    length = packet[at + 1] + 2
                self.assertLessEqual(at + length, len(packet), 'Application command split across packets')
                commands.append(packet[at:at + length])
                at += length
        return commands

    def assert_complete_frame(self, budget):
        self.assertTrue(all(len(packet) <= budget for packet in self.sent))
        commands = self.decode()
        clip = [0x52, 5, 0, 0, 27, 64, 48]
        expected = [clip]
        expected += [[0x55, 11, 2, 0, row] + list(self.raw[row * 8:(row + 1) * 8])
                     for row in range(48)]
        expected += [clip, [0x39]]
        self.assertEqual(commands, expected)
        self.assertEqual(self.results, ['DRAW_ACK 42'])

    def test_full_64x48_at_105_preserves_rows_windows_and_exactly_one_commit(self):
        self.run_frame()
        self.assert_complete_frame(105)
        self.assertEqual([len(packet) for packet in self.sent], [98] + [104] * 5 + [20, 1])
        self.assertEqual(self.sent[-1], [0x39])

    def test_red_caps_global_white_budget_without_losing_raster(self):
        self.s.ddp.dis_mode='red'
        self.run_frame()
        self.assertEqual(self.s._bitmap_message_budget(),42)
        self.assert_complete_frame(42)
        self.assertEqual([len(packet) for packet in self.sent],[33]+[39]*15+[20,1])

    def test_internal_limit_before_driver_mode_exists(self):
        del self.s.ddp
        self.assertEqual(self.s._bitmap_message_budget(),105)

    def test_default_white_preserves_installed_105_byte_packing(self):
        self.run_frame()
        self.assertEqual(self.s._bitmap_message_budget(), 105)
        self.assert_complete_frame(105)
        self.assertEqual(list(map(len, self.sent)), [98] + [104] * 5 + [20, 1])

    def test_cluster_modes_keep_all_commands_whole(self):
        for mode, budget in (('white', 105), ('red', 42)):
            with self.subTest(mode=mode):
                self.setUp()
                self.s.ddp.dis_mode = mode
                self.run_frame()
                self.assert_complete_frame(budget)

    def test_failure_before_commit_cannot_publish_ack_or_send_remaining_rows(self):
        self.outcomes = [False]
        self.run_frame(seq=73)
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn([0x39], self.decode())
        self.assertEqual(self.results, ['DRAW_NACK 73'])
        self.assertFalse(self.s._frame_failed)

    def test_combined_tail_commit_failure_has_one_matched_nack(self):
        self.outcomes = [True] * 7 + [False]
        self.run_frame(seq=91)
        self.assertEqual(len(self.sent), 8)
        self.assertEqual(self.sent[-1][-1], 0x39)
        self.assertEqual(self.results, ['DRAW_NACK 91'])
        self.assertFalse(self.s._frame_failed)

    def test_full_tail_sends_commit_separately_when_one_byte_will_not_fit(self):
        tail = [0x55, 11, 2, 0, 0] + [0xaa] * 8
        self.assertTrue(self.s._finish_frame(57, pending_payload=tail))
        self.assertEqual(self.sent, [tail, [0x39]])
        self.assertEqual(self.results, ['DRAW_ACK 57'])

    def test_failed_full_tail_suppresses_separate_commit_and_publishes_nack(self):
        tail = [0x55, 11, 2, 0, 0] + [0xaa] * 8
        self.outcomes = [False]
        self.assertFalse(self.s._finish_frame(57, pending_payload=tail))
        self.assertEqual(self.sent, [tail])
        self.assertEqual(self.results, ['DRAW_NACK 57'])

    def test_missing_config_defaults_to_105_and_coalescing_stays_disabled(self):
        del self.s.config
        self.assertEqual(self.s._bitmap_message_budget(), 105)
        commands = [self.bitmap, dict(self.bitmap)]
        self.assertIs(self.s._coalesce_bitmap_commands(commands), commands)

    def test_removed_setting_cannot_override_packet_limits(self):
        for stale_value in (13, 42, 195, True, '105', None):
            for mode, budget in (('white', 105), ('red', 42)):
                with self.subTest(stale_value=stale_value, mode=mode):
                    self.setUp()
                    self.s.config['ddp_bitmap_message_bytes'] = stale_value
                    self.s.ddp.dis_mode = mode
                    self.run_frame()
                    self.assertEqual(self.s._bitmap_message_budget(), budget)
                    self.assert_complete_frame(budget)



if __name__ == '__main__':
    unittest.main()
