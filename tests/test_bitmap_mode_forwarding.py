"""Exercise actual icon raster sends via normal IPC dispatch and redraw dispatch."""
import ast
import unittest
import test_bitmap_message_budget as budget_tests

SOURCE, NS = budget_tests.SOURCE, budget_tests.NS

ICON = {'w': 8, 'h': 2, 'data': bytes((0x80, 0x40))}
TREE = ast.parse(SOURCE.read_text())
METHODS = {'draw_bitmap', 'handle_redraw'}
GLOBALS = dict(NS, BITMAPS={'probe': ICON})
exec(compile(ast.Module(body=[node for node in ast.walk(TREE)
    if isinstance(node, ast.FunctionDef) and node.name in METHODS], type_ignores=[]),
    str(SOURCE), 'exec'), GLOBALS)


class BitmapModeForwardingTests(unittest.TestCase):
    def make_fixture(self):
        fixture = budget_tests.BitmapMessageBudgetTests()
        fixture.setUp()
        for name in METHODS:
            setattr(fixture.s, name, GLOBALS[name].__get__(fixture.s))
        fixture.s.clear_screen_payload = lambda: None
        return fixture

    def assert_raster(self, fixture, mode):
        records = [record for record in fixture.decode() if record[0] == 0x55]
        self.assertEqual(records, [[0x55, 4, mode, 0, 0, 0x80],
                                   [0x55, 4, mode, 0, 1, 0x40]])

    def test_normal_command_dispatch_forwards_explicit_mode_and_keeps_default(self):
        for mode in (None, 0x82):
            with self.subTest(mode=mode):
                fixture = self.make_fixture()
                command = dict(command='draw_bitmap', x=0, y=0, icon_name='probe')
                if mode is not None:
                    command['mode_flag'] = mode
                fixture.run_frame(command)
                self.assert_raster(fixture, 2 if mode is None else mode)
                self.assertEqual(fixture.results, ['DRAW_ACK 42'])

    def test_redraw_dispatch_retains_explicit_mode_and_default(self):
        for mode in (None, 0x06):
            with self.subTest(mode=mode):
                fixture = self.make_fixture()
                command = dict(command='draw_bitmap', x=0, y=0, icon_name='probe')
                if mode is not None:
                    command['mode_flag'] = mode
                fixture.s.command_cache = {'probe': command}
                fixture.s.handle_redraw()
                self.assert_raster(fixture, 2 if mode is None else mode)
                self.assertEqual(fixture.sent[-1], [0x39])


if __name__ == '__main__':
    unittest.main()
