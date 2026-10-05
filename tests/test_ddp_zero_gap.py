"""Configured zero gap must send without yielding; safety and retries remain."""
import ast
import logging
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parent.parent / 'dis_client/ddp_protocol.py'
tree = ast.parse(SOURCE.read_text())
method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'send_can')

class ZeroGapTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.allowed = True
        @contextmanager
        def guard():
            self.events.append('guard_enter')
            try:
                yield self.allowed
            finally:
                self.events.append('guard_exit')
        self.sleep = Mock()
        namespace = {'List': list, 'logger': logging.getLogger(__name__),
            'DDPCANError': RuntimeError, 'time': SimpleNamespace(sleep=self.sleep),
            'can': SimpleNamespace(Message=lambda **kw: SimpleNamespace(**kw)),
            'transmission_guard': guard}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        self.send = namespace['send_can']
        self.gap = 0
        self.outcomes = []
        def send(message, timeout):
            self.assertEqual(message.arbitration_id, 0x6c0)
            self.assertEqual(message.data, [0x20, 0x55])
            self.assertEqual(timeout, .5)
            self.assertEqual(self.events[-1], 'guard_enter')
            self.events.append('send')
            if self.outcomes:
                error = self.outcomes.pop(0)
                if error:
                    raise error
        self.bus_send = Mock(side_effect=send)
        self.driver = SimpleNamespace(bus=SimpleNamespace(send=self.bus_send),
            _flashing_inhibited=Mock(return_value=False), _reset_for_flashing=Mock(),
            _transport_settings=lambda: SimpleNamespace(frame_gap_s=self.gap))

    def test_zero_gap_sends_under_guard_without_sleep_zero(self):
        self.send(self.driver, 0x6c0, [0x20, 0x55])
        self.sleep.assert_not_called()
        self.assertEqual(self.events, ['guard_enter', 'send', 'guard_exit'])
        self.bus_send.assert_called_once()

    def test_positive_gap_preserves_exact_pacing(self):
        self.gap = .002
        self.send(self.driver, 0x6c0, [0x20, 0x55])
        self.sleep.assert_called_once_with(.002)
        self.assertEqual(self.events, ['guard_enter', 'send', 'guard_exit'])

    def test_error_105_still_retries_with_fifty_ms_delay_at_zero_gap(self):
        self.outcomes = [RuntimeError('105: No buffer space available'), None]
        self.send(self.driver, 0x6c0, [0x20, 0x55])
        self.assertEqual(self.bus_send.call_count, 2)
        self.sleep.assert_called_once_with(.05)
        self.assertEqual(self.events, ['guard_enter', 'send', 'guard_exit'] * 2)

    def test_error_105_retry_retains_both_retry_delay_and_positive_gap(self):
        self.gap = .002
        self.outcomes = [RuntimeError('105: No buffer space available'), None]
        self.send(self.driver, 0x6c0, [0x20, 0x55])
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [.05, .002])

    def test_guard_rejection_prevents_send_and_pacing(self):
        self.allowed = False
        with self.assertRaisesRegex(RuntimeError, 'Flashing Mode inhibits'):
            self.send(self.driver, 0x6c0, [0x20, 0x55])
        self.bus_send.assert_not_called()
        self.driver._reset_for_flashing.assert_called_once()
        self.sleep.assert_not_called()
        self.assertEqual(self.events, ['guard_enter', 'guard_exit'])

if __name__ == '__main__':
    unittest.main()
