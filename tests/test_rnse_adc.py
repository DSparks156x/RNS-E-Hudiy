"""ADC wire protocol, complete dumps, explicit commands and protected presets."""
import json
import unittest
from unittest.mock import Mock

from hudiy_manager.rnse_adc_protocol import (AdcController, COMMAND_ID, DEFAULTS,
    REGISTERS, REVERT_DEFAULTS, reply_identifier, validate_values)

try:
    import test_rnse_control as control_tests
    import test_rnse_bridge_routes as route_tests
    from test_rnse_bridge_runtime import RUNTIME
except ModuleNotFoundError:
    from tests import test_rnse_control as control_tests
    from tests import test_rnse_bridge_routes as route_tests
    from tests.test_rnse_bridge_runtime import RUNTIME


def dump_frames(values=None, failures=0):
    values = list(range(39)) if values is None else values
    result = [b'ADC' + bytes((39, values[0], values[8], values[21], values[30]))]
    padded = bytes(values) + bytes(3)
    for sequence in range(1, 7):
        offset = (sequence - 1) * 7
        result.append(bytes((sequence,)) + padded[offset:offset + 7])
    result.append(bytes((7,)) + failures.to_bytes(5, 'little') + bytes(2))
    return result


class AdcProtocolTests(unittest.TestCase):
    def setUp(self):
        self.clock = Mock(return_value=0)
        self.adc = AdcController(0x462, self.clock)
        self.send = Mock(return_value=True)

    def observe(self, frame, **kwargs):
        return self.adc.observe(0x462, frame, **kwargs)

    def complete(self, values=None, failures=0):
        for frame in dump_frames(values, failures):
            self.assertTrue(self.observe(frame))

    def ack(self, register, value, status=0):
        return self.observe(bytes((0x57, register, value, status, 0, 0, 0, 0)))

    def test_mapped_writes_exact_standard_id_dlc_and_linked_three_frames(self):
        self.assertTrue(self.adc.write({'08': 112, '09': 113, '0a': 114}, self.send))
        self.send.assert_called_once_with(COMMAND_ID, 'bc08700000000000')
        self.assertEqual([self.adc.writes[key]['state'] for key in ('08', '09', '0A')],
                         ['pending', 'queued', 'queued'])
        self.assertTrue(self.adc.snapshot()['busy'])
        self.assertFalse(self.ack(9, 113))
        self.assertEqual(self.send.call_count, 1)
        self.assertTrue(self.ack(8, 112))
        self.assertTrue(self.ack(9, 113))
        self.assertTrue(self.ack(10, 114))
        self.assertEqual([call.args for call in self.send.call_args_list], [
            (COMMAND_ID, 'bc08700000000000'), (COMMAND_ID, 'bc09710000000000'),
            (COMMAND_ID, 'bc0a720000000000')])
        for _ in range(3):
            self.adc.snapshot()
        self.assertEqual(self.send.call_count, 3)
        self.assertFalse(self.adc.snapshot()['busy'])

    def test_validation_locked_registers_encodings_and_atomic_invalid_batch(self):
        for values in ({}, {'01': 63}, {'02': 80}, {'00': 1}, {'07': 1}, {'0E': 1},
                       {'0F': 1}, {'10': 1}, {'14': 1}, {'15': 1}, {'19': 1}, {'1A': 4}, {'1B': 1}, {'24': 1}, {'FF': 1},
                       {'08': True}, {'08': 256}, {'08': -1}, {'08': '1'}, {'8': 1},
                       {'0B': 127}, {'0C': 1}, {'04': 1}, {'03': 17},
                       {'0a': 1, '0A': 2}, {'08': 112, '01': 63}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.adc.write(values, self.send)
        self.send.assert_not_called()
        self.assertEqual(validate_values(DEFAULTS), DEFAULTS)
        self.assertEqual(validate_values({'04': 248, '03': 248, '0D': 254}),
                         {'04': 248, '03': 248, '0D': 254})

    def test_fixed_revert_only_restores_stock_writable_boot_list(self):
        self.adc.revert(self.send)
        self.assertEqual(self.send.call_count, 1)
        for key, value in REVERT_DEFAULTS.items():
            self.assertTrue(self.ack(int(key, 16), value))
        calls = self.send.call_args_list
        self.assertEqual(len(calls), 19)
        self.assertEqual({int(call.args[1][2:4], 16) for call in calls}, set(range(1, 0x14)))
        self.assertEqual(calls[0].args, (COMMAND_ID, 'bc013f0000000000'))
        self.assertEqual(calls[1].args, (COMMAND_ID, 'bc02500000000000'))
        self.assertFalse(self.observe(bytes.fromhex('57013f0000000000')))
        self.assertEqual(self.adc.writes['01']['state'], 'ok')
        self.assertEqual(REVERT_DEFAULTS['06'], 47)
        self.assertEqual(REVERT_DEFAULTS['03'], 0x30)
        self.assertEqual(REVERT_DEFAULTS['12'], 6)
        self.assertNotIn('24', REVERT_DEFAULTS)

    def test_ack_reports_readback_status_and_changes_only_successful_values(self):
        self.complete([112] * 39)
        for register, status, expected in ((8, 0, 'ok'), (9, 0xEE, 'rejected'), (10, 3, 'i2c_error')):
            self.adc.write({f'{register:02X}': 120}, self.send)
            self.assertTrue(self.observe(bytes((0x57, register, 119, status, 0, 0, 0, 0))))
            item = self.adc.snapshot()['writes'][f'{register:02X}']
            self.assertEqual((item['state'], item['readback'], item['status']), (expected, 119, status))
        rows = {row['register']: row for row in self.adc.snapshot()['registers']}
        self.assertTrue(rows['08']['changed'])
        self.assertEqual(rows['09']['value'], 112)
        self.assertFalse(rows['09']['changed'])

    def test_unconfigured_reply_never_claims_ack_or_dump_completion(self):
        adc = AdcController(None, self.clock)
        adc.write({'08': 112}, self.send)
        self.assertTrue(adc.snapshot()['busy'])
        with self.assertRaises(ValueError):
            adc.request_dump(self.send)
        self.clock.return_value = 0.2
        adc.request_dump(self.send)
        self.assertFalse(adc.observe(0x462, bytes.fromhex('5708700000000000')))
        self.clock.return_value = 100
        result = adc.snapshot()
        self.assertEqual(result['writes']['08']['state'], 'queued_unconfirmed')
        self.assertEqual(result['dump']['state'], 'queued_unconfirmed')
        self.assertFalse(result['baseline_available'])
        self.assertFalse(result['busy'])

    def test_ack_timeout_and_same_register_pending_rejection_never_retry(self):
        self.adc.write({'08': 120}, self.send)
        for values in ({'08': 121, '09': 122}, {'09': 122}):
            with self.assertRaises(ValueError):
                self.adc.write(values, self.send)
        with self.assertRaises(ValueError):
            self.adc.request_dump(self.send)
        self.assertEqual(self.send.call_count, 1)
        self.clock.return_value = 2
        self.assertEqual(self.adc.snapshot()['writes']['08']['state'], 'timeout')
        self.assertFalse(self.observe(bytes.fromhex('5708780000000000')))
        self.adc.write({'08': 121}, self.send)
        self.assertEqual(self.send.call_count, 2)

    def test_gateway_failure_identifies_partial_batch_and_unsent_channels(self):
        self.send.side_effect = [True, False]
        self.assertTrue(self.adc.write({'08': 112, '09': 112, '0A': 112}, self.send))
        self.assertTrue(self.ack(8, 112))
        writes = self.adc.snapshot()['writes']
        self.assertEqual([writes[key]['state'] for key in ('08', '09', '0A')],
                         ['ok', 'queue_failed', 'not_sent'])
        self.assertEqual(self.send.call_count, 2)
        self.adc.advance(self.send)
        self.assertEqual(self.send.call_count, 2)

    def test_initial_send_failure_stops_entire_batch(self):
        self.send.return_value = False
        self.assertFalse(self.adc.write({'08': 112, '09': 112}, self.send))
        self.assertEqual([self.adc.writes[key]['state'] for key in ('08', '09')],
                         ['queue_failed', 'not_sent'])
        self.assertFalse(self.adc.snapshot()['busy'])

    def test_timeout_stops_batch_and_late_or_wrong_reply_cannot_release_queue(self):
        self.adc.write({'08': 112, '09': 113, '0A': 114}, self.send)
        self.assertFalse(self.ack(9, 113))
        self.assertFalse(self.observe(bytes.fromhex('5708700000000001')))
        self.clock.return_value = 2
        self.adc.advance(self.send)
        self.assertEqual([self.adc.writes[key]['state'] for key in ('08', '09', '0A')],
                         ['timeout', 'not_sent', 'not_sent'])
        self.assertFalse(self.ack(8, 112))
        self.adc.advance(self.send)
        self.assertEqual(self.send.call_count, 1)
        self.assertFalse(self.adc.snapshot()['busy'])

    def test_ack_errors_and_unexpected_readbacks_stop_remaining_batch(self):
        for readback, status in ((112, 0xEE), (112, 3), (111, 0)):
            self.adc = AdcController(0x462, self.clock)
            self.send.reset_mock()
            self.adc.write({'08': 112, '09': 113}, self.send)
            self.assertTrue(self.ack(8, readback, status))
            self.assertEqual(self.adc.writes['09']['state'], 'not_sent')
            self.assertEqual(self.send.call_count, 1)
            self.assertFalse(self.adc.snapshot()['busy'])

    def test_dump_frames_and_failure_bitmap_commit_all_39_atomically(self):
        self.adc.request_dump(self.send)
        self.send.assert_called_once_with(COMMAND_ID, 'bd00000000000000')
        frames = dump_frames(failures=(1 << 8) | (1 << 38))
        for frame in frames[:-1]:
            self.assertTrue(self.observe(frame))
            self.assertFalse(self.adc.snapshot()['baseline_available'])
            self.assertTrue(all(row['value'] is None for row in self.adc.snapshot()['registers']))
        self.assertTrue(self.observe(frames[-1]))
        snapshot = self.adc.snapshot()
        self.assertEqual(len(snapshot['registers']), 39)
        self.assertEqual(snapshot['dump']['received_sequences'], list(range(8)))
        self.assertEqual(snapshot['dump']['state'], 'complete')
        self.assertTrue(snapshot['baseline_available'])
        rows = {row['register']: row for row in snapshot['registers']}
        self.assertEqual(rows['45']['value'], 37)
        self.assertTrue(rows['46']['failed'])
        self.assertIsNone(rows['46']['value'])
        self.assertTrue(rows['08']['failed'])

    def test_header_last_and_arbitrary_order_commit_once_with_first_baseline(self):
        frames = dump_frames([2] * 39, failures=1 << 38)
        for sequence in (7, 4, 2, 6, 1, 5, 3):
            self.assertTrue(self.observe(frames[sequence]))
            self.assertFalse(self.adc.snapshot()['baseline_available'])
        self.assertTrue(self.observe(frames[0]))
        self.assertEqual(self.adc.snapshot()['dump']['generation'], 1)
        self.assertEqual(self.adc.snapshot()['dump']['chip_ids'], [2] * 4)
        self.assertIsNone(self.adc.values[0x46])
        self.assertTrue(all(row['baseline'] == 2 for row in self.adc.snapshot()['registers'][:-1]))
        self.complete([3] * 39)
        self.assertTrue(all(row['changed'] for row in self.adc.snapshot()['registers'][:-1]))

    def test_all_eight_frame_rotations_allow_data_before_header(self):
        for offset in range(8):
            with self.subTest(offset=offset):
                self.adc = AdcController(0x462, self.clock)
                self.adc.request_dump(self.send)
                frames = dump_frames([offset] * 39)
                for frame in frames[offset:] + frames[:offset]:
                    self.assertTrue(self.observe(frame))
                self.assertEqual(self.adc.dump_generation, 1)
                self.assertTrue(all(value == offset for value in self.adc.values.values()))

    def test_duplicate_frames_invalidate_generation_and_preserve_last_complete(self):
        self.complete([10] * 39)
        for sequence in (0, 1, 7):
            self.adc.request_dump(self.send)
            frames = dump_frames([20] * 39)
            self.assertTrue(self.observe(frames[sequence]))
            self.assertFalse(self.observe(frames[sequence]))
            for frame in frames:
                self.assertFalse(self.observe(frame))
            self.assertEqual(self.adc.snapshot()['dump']['state'], 'invalid')
            self.assertEqual(self.adc.dump_generation, 1)
            self.assertTrue(all(value == 10 for value in self.adc.values.values()))
        self.adc.request_dump(self.send)
        self.complete([2] * 39)
        self.assertTrue(all(row['baseline'] == 10 for row in self.adc.snapshot()['registers']))
        self.assertEqual(self.adc.dump_generation, 2)

    def test_bad_header_last_never_commits_data_or_changes_baseline(self):
        self.complete([10] * 39)
        self.adc.request_dump(self.send)
        frames = dump_frames([20] * 39)
        for frame in frames[1:]:
            self.assertTrue(self.observe(frame))
        self.assertFalse(self.observe(b'ADC' + bytes((38, 0, 0, 0, 0))))
        self.assertEqual(self.adc.dump_generation, 1)
        self.assertTrue(all(value == 10 for value in self.adc.values.values()))
        self.assertTrue(all(value == 10 for value in self.adc.baseline.values()))
        self.assertFalse(self.observe(frames[0]))
        self.adc.request_dump(self.send)
        self.assertFalse(self.observe(b'AXC' + bytes((39, 0, 0, 0, 0))))

    def test_data_before_header_starts_busy_assembly_and_blocks_bc_bd_probe(self):
        self.assertTrue(self.observe(dump_frames()[3]))
        self.assertTrue(self.adc.snapshot()['busy'])
        for action in (lambda: self.adc.write({'08': 112}, self.send),
                       lambda: self.adc.request_dump(self.send),
                       lambda: self.adc.identify(self.send)):
            with self.assertRaises(ValueError):
                action()
        self.send.assert_not_called()

    def test_dump_timeout_late_frames_cannot_publish_partial_and_new_request_is_explicit(self):
        frames = dump_frames()
        self.adc.request_dump(self.send)
        self.observe(frames[0]); self.observe(frames[1])
        self.clock.return_value = 3
        self.assertEqual(self.adc.snapshot()['dump']['state'], 'timeout')
        for frame in frames[2:]:
            self.assertFalse(self.observe(frame))
        self.assertFalse(self.adc.snapshot()['baseline_available'])
        self.assertEqual(self.send.call_count, 1)
        self.adc.request_dump(self.send)
        self.assertEqual(self.send.call_count, 2)

    def test_invalid_reply_id_dlc_extended_remote_header_and_padding(self):
        self.adc.write({'08': 112}, self.send)
        ack = bytes.fromhex('5708700000000000')
        self.assertFalse(self.adc.observe(0x463, ack))
        for kwargs in ({'dlc': 7}, {'extended': True}, {'remote': True}):
            self.assertFalse(self.observe(ack, **kwargs))
        self.assertFalse(self.observe(ack[:-1]))
        self.assertFalse(self.observe(ack[:-1] + b'\x01'))
        self.assertTrue(self.observe(ack))
        self.assertFalse(self.observe(b'ADC' + bytes((38, 0, 0, 0, 0))))
        for sequence, byte in ((6, 7), (7, 5), (7, 7)):
            self.adc.request_dump(self.send)
            frames = dump_frames()
            damaged = bytearray(frames[sequence]); damaged[byte] = 0x80
            for frame in frames[:sequence]:
                self.observe(frame)
            self.assertFalse(self.observe(bytes(damaged)))
            self.assertEqual(self.adc.snapshot()['dump']['state'], 'invalid')

    def test_write_dump_conflicts_do_not_send_additional_frames(self):
        self.adc.request_dump(self.send)
        with self.assertRaises(ValueError):
            self.adc.request_dump(self.send)
        with self.assertRaises(ValueError):
            self.adc.write({'08': 112}, self.send)
        self.assertEqual(self.send.call_count, 1)

    def test_clamp_is_validated_atomically_using_defaults_and_confirmed_bytes(self):
        for values in ({'05': 63}, {'06': 88}, {'08': 112, '05': 50, '06': 60}):
            with self.assertRaises(ValueError):
                self.adc.write(values, self.send)
        self.send.assert_not_called()
        self.adc.write({'05': 60, '06': 49}, self.send)
        self.observe(bytes.fromhex('57053c0000000000'))
        self.observe(bytes.fromhex('5706310000000000'))
        with self.assertRaises(ValueError):
            self.adc.write({'05': 61, '08': 112}, self.send)
        self.assertEqual(self.send.call_count, 2)
        self.adc.write({'05': 59}, self.send)
        with self.assertRaises(ValueError):
            self.adc.write({'06': 48}, self.send)
        self.assertEqual(self.send.call_count, 3)

    def test_reply_disabled_batches_reject_before_sending_and_singles_are_paced(self):
        adc = AdcController(None, self.clock)
        for action in (lambda: adc.write({'05': 60, '06': 49}, self.send), lambda: adc.revert(self.send)):
            with self.assertRaisesRegex(ValueError, 'reply CAN ID'):
                action()
        self.send.assert_not_called()
        adc.write({'05': 60}, self.send)
        for now in (0, 0.199):
            self.clock.return_value = now
            with self.assertRaises(ValueError):
                adc.write({'08': 120}, self.send)
        self.clock.return_value = 0.2
        adc.advance(self.send)
        with self.assertRaises(ValueError):
            adc.write({'06': 50}, self.send)
        adc.write({'06': 49}, self.send)
        self.assertEqual(self.send.call_count, 2)

    def test_clamp_batch_reduces_duration_before_increasing_placement(self):
        values = [0] * 39
        values[5], values[6] = 10, 99
        self.complete(values)
        self.adc.write({'05': 60, '06': 49}, self.send)
        self.assertEqual(self.send.call_count, 1)
        self.assertTrue(self.ack(6, 49))
        self.assertEqual([call.args[1] for call in self.send.call_args_list],
                         ['bc06310000000000', 'bc053c0000000000'])

    def test_clamp_unexpected_reduction_readback_does_not_send_increase(self):
        values = [0] * 39
        values[5], values[6] = 10, 99
        self.complete(values)
        self.adc.write({'05': 60, '06': 49}, self.send)
        self.assertTrue(self.ack(6, 99))
        self.assertEqual(self.adc.writes['05']['state'], 'not_sent')
        self.assertEqual(self.send.call_count, 1)

    def test_uncertain_clamp_timeout_requires_new_successful_dump(self):
        self.adc.write({'05': 60}, self.send)
        self.clock.return_value = 2
        with self.assertRaises(ValueError):
            self.adc.write({'06': 40}, self.send)
        self.assertTrue(self.adc.snapshot()['clamp_uncertain'])
        self.complete([0] * 39, failures=1 << 5)
        with self.assertRaises(ValueError):
            self.adc.write({'06': 40}, self.send)
        self.complete([0] * 39)
        self.adc.write({'06': 40}, self.send)
        self.assertFalse(self.adc.snapshot()['clamp_uncertain'])

    def test_reply_identifier_bounds_and_null(self):
        for value in ('0x800', '0x7B0', '462', 0x462, True, 'tcp://host'):
            with self.assertRaises(ValueError):
                reply_identifier(value)
        self.assertEqual(reply_identifier('0x462'), 0x462)
        self.assertIsNone(reply_identifier(None))


class AdcBaseServiceTests(unittest.TestCase):
    def test_batch_continuation_checks_live_guards_and_stops_without_retry(self):
        helper = control_tests.BaseServiceBrightnessTests()
        for flag in ('can_listen_only', 'desired_listen_only', 'listen_only_transition_in_progress', 'flashing', 'radio'):
            with self.subTest(flag=flag):
                namespace, state = helper.namespace(), helper.state()
                self.assertTrue(helper.load(namespace, helper.fixture(enabled=False)))
                adc = namespace['CONFIG']['rnse_adc']
                namespace['process_rnse_bridge_request'](
                    {'action': 'adc_write', 'values': {'08': 112, '09': 113, '0A': 114}}, state)
                namespace['send_can_message'].assert_called_once_with(COMMAND_ID, 'bc08700000000000')
                if flag == 'flashing':
                    namespace['flashing_mode_enabled'].return_value = True
                elif flag == 'radio':
                    state.is_radio_active.return_value = False
                else:
                    setattr(state, flag, True)
                self.assertTrue(adc.observe(0x462, bytes.fromhex('5708700000000000')))
                self.assertEqual([adc.writes[key]['state'] for key in ('08', '09', '0A')],
                                 ['ok', 'queue_failed', 'not_sent'])
                if flag == 'flashing':
                    namespace['flashing_mode_enabled'].return_value = False
                elif flag == 'radio':
                    state.is_radio_active.return_value = True
                else:
                    setattr(state, flag, False)
                namespace['advance_rnse_adc'](state)
                self.assertEqual(namespace['send_can_message'].call_count, 1)

    def test_probe_timeout_is_restored_by_service_timer_without_ui_poll(self):
        import asyncio
        helper = control_tests.BaseServiceBrightnessTests()
        namespace, state = helper.namespace(), helper.state()
        self.assertTrue(helper.load(namespace, helper.fixture(enabled=False)))
        clock = Mock(return_value=0)
        adc = AdcController(0x462, clock)
        namespace['CONFIG']['rnse_adc'] = adc
        for frame in dump_frames([0] * 39):
            adc.observe(0x462, frame)
        namespace['process_rnse_bridge_request']({'action': 'adc_identify'}, state)
        namespace['send_can_message'].assert_called_once_with(COMMAND_ID, 'bc1a040000000000')
        clock.return_value = 2
        async def stop(_delay):
            namespace['RUNNING'] = False
        namespace['asyncio'] = control_tests.SimpleNamespace(sleep=stop, CancelledError=asyncio.CancelledError)
        asyncio.run(namespace['send_periodic_messages_task'](state))
        self.assertEqual(namespace['send_can_message'].call_count, 2)
        namespace['send_can_message'].assert_called_with(COMMAND_ID, 'bc1a000000000000')
        self.assertEqual(adc.identification['state'], 'restoring')

    def test_probe_restore_checks_live_inhibition_and_does_not_retry(self):
        helper = control_tests.BaseServiceBrightnessTests()
        for flag in ('can_listen_only', 'desired_listen_only', 'listen_only_transition_in_progress', 'flashing', 'radio'):
            namespace, state = helper.namespace(), helper.state()
            self.assertTrue(helper.load(namespace, helper.fixture(enabled=False)))
            adc = namespace['CONFIG']['rnse_adc']
            for frame in dump_frames([0] * 39):
                adc.observe(0x462, frame)
            namespace['process_rnse_bridge_request']({'action': 'adc_identify'}, state)
            if flag == 'flashing':
                namespace['flashing_mode_enabled'].return_value = True
            elif flag == 'radio':
                state.is_radio_active.return_value = False
            else:
                setattr(state, flag, True)
            adc.observe(0x462, bytes.fromhex('571a040000000000'))
            self.assertEqual(adc.identification['state'], 'error')
            self.assertFalse(adc.identification['restore_confirmed'])
            self.assertEqual(adc.identification['restore']['state'], 'queue_failed')
            namespace['send_can_message'].assert_called_once_with(COMMAND_ID, 'bc1a040000000000')
            namespace['advance_rnse_adc'](state)
            self.assertEqual(namespace['send_can_message'].call_count, 1)

    def test_malformed_adc_payloads_are_ignored_before_hex_decode(self):
        helper = control_tests.BaseServiceBrightnessTests()
        namespace = helper.namespace()
        self.assertTrue(helper.load(namespace, helper.fixture(enabled=False)))
        observe = namespace['observe_rnse_adc_message']
        for message in ({'dlc': 8, 'data_hex': 'not-valid-hex1234'},
                        {'dlc': 8, 'data_hex': None}, {'dlc': '8', 'data_hex': '00' * 8},
                        {'dlc': 8, 'data_hex': '00' * 9},
                        {'dlc': 8, 'data_hex': '00' * 8, 'is_error_frame': True}):
            self.assertFalse(observe(0x462, message))
        namespace['CONFIG']['rnse_adc'].write({'08': 112}, namespace['send_can_message'])
        self.assertTrue(observe(0x462, {'dlc': 8, 'data_hex': '5708700000000000'}))

    def test_every_inhibition_and_radio_sleep_reject_without_deferred_send(self):
        helper = control_tests.BaseServiceBrightnessTests()
        namespace, state = helper.namespace(), helper.state()
        self.assertTrue(helper.load(namespace, helper.fixture(enabled=False)))
        process = namespace['process_rnse_bridge_request']
        for flag in ('can_listen_only', 'desired_listen_only', 'listen_only_transition_in_progress'):
            setattr(state, flag, True)
            for action in ('adc_write', 'adc_dump', 'adc_revert', 'adc_identify'):
                self.assertEqual(process({'action': action, 'values': {'08': 112}}, state)['status'], 503)
            setattr(state, flag, False)
        namespace['flashing_mode_enabled'].return_value = True
        self.assertEqual(process({'action': 'adc_dump'}, state)['status'], 503)
        namespace['flashing_mode_enabled'].return_value = False
        state.is_radio_active.return_value = False
        self.assertEqual(process({'action': 'adc_dump'}, state)['status'], 503)
        state.is_radio_active.return_value = True
        process({'action': 'adc_status'}, state)
        namespace['send_can_message'].assert_not_called()
        self.assertEqual(namespace['CONFIG']['can_ids']['rnse_adc_reply'], 0x462)

    def test_local_bridge_parser_only_accepts_bounded_actions(self):
        for action in ('adc_status', 'adc_dump', 'adc_revert', 'adc_identify'):
            self.assertEqual(RUNTIME.parse_request([json.dumps({'action': action}).encode()]), {'action': action})
            with self.assertRaises(ValueError):
                RUNTIME.parse_request([json.dumps({'action': action, 'values': {}}).encode()])
        with self.assertRaises(ValueError):
            RUNTIME.parse_request([b'{"action":"adc_raw","address":1}'])


class AdcRouteTests(unittest.TestCase):
    setUp = route_tests.BridgeRouteTests.setUp

    def test_adc_get_reads_only_and_write_batches_preserve_saved_config(self):
        self.assertEqual(self.client.get('/api/manage/rnse-adc').status_code, 200)
        self.exchange.assert_called_with(self.endpoint, {'action': 'adc_status'})
        result = self.client.post('/api/manage/rnse-adc/write', json={'values': {'08': 112, '09': 112, '0A': 112}}, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.exchange.assert_called_with(self.endpoint, {'action': 'adc_write', 'values': {'08': 112, '09': 112, '0A': 112}})
        for action in ('dump', 'revert', 'identify'):
            self.assertEqual(self.client.post('/api/manage/rnse-adc/' + action, json={}, headers=self.headers).status_code, 200)
            self.exchange.assert_called_with(self.endpoint, {'action': 'adc_' + action})
            self.assertIn(self.client.get('/api/manage/rnse-adc/' + action).status_code, (404, 405))
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_adc_mutations_require_pin_header_and_same_origin(self):
        for action in ('write', 'dump', 'revert', 'identify', 'presets'):
            for headers in ({}, {**self.headers, 'X-Hudiy-Pin': 'wrong'},
                            {**self.headers, 'Origin': 'https://foreign.example'},
                            {**self.headers, 'Sec-Fetch-Site': 'same-site'}):
                self.assertEqual(self.client.post('/api/manage/rnse-adc/' + action, json={}, headers=headers).status_code, 403)
        self.exchange.assert_not_called()

    def test_invalid_addresses_or_bodies_never_reach_gateway(self):
        for body in ({'values': {'01': 63}}, {'values': {'08': 112, '24': 88}},
                     {'values': {'0B': 255}}, {'values': {'04': 1}}, {'values': {}},
                     {'values': {'08': 112}, 'id': 0x7B0}, {}):
            self.assertEqual(self.client.post('/api/manage/rnse-adc/write', json=body, headers=self.headers).status_code, 400)
        for action in ('dump', 'revert', 'identify'):
            self.assertEqual(self.client.post('/api/manage/rnse-adc/' + action, json={'values': {}}, headers=self.headers).status_code, 400)
        self.exchange.assert_not_called()


class AdcIdentificationTests(unittest.TestCase):
    def setUp(self):
        self.clock = Mock(return_value=0)
        self.adc = AdcController(0x462, self.clock)
        self.send = Mock(return_value=True)

    def seed(self, value=0, failed=False):
        values = [0] * 39
        values[0x1D] = value
        for frame in dump_frames(values, (1 << 0x1D) if failed else 0):
            self.adc.observe(0x462, frame)

    def ack(self, value, status=0):
        return self.adc.observe(0x462, bytes((0x57, 0x1A, value, status, 0, 0, 0, 0)))

    def test_requires_complete_successful_auto_offset_off_dump(self):
        for value, failed in ((None, False), (1, False), (0, True)):
            if value is not None:
                self.seed(value, failed)
            with self.assertRaises(ValueError):
                self.adc.identify(self.send)
        self.send.assert_not_called()
        self.seed()
        self.assertTrue(self.adc.identify(self.send))

    def test_probe_classes_and_restore_have_separate_confirmed_status(self):
        for value, expected in ((4, 'AD9985'), (0, 'AD9883A'), (2, 'unknown')):
            self.adc = AdcController(0x462, self.clock)
            self.send.reset_mock()
            self.seed()
            self.adc.identify(self.send)
            self.send.assert_called_once_with(COMMAND_ID, 'bc1a040000000000')
            self.assertTrue(self.ack(value))
            result = self.adc.snapshot()['identification']
            self.assertEqual(result['state'], 'restoring')
            self.assertEqual(result['chip'], expected)
            self.assertEqual(result['probe']['readback'], value)
            self.assertFalse(result['restore_confirmed'])
            self.send.assert_called_with(COMMAND_ID, 'bc1a000000000000')
            self.assertTrue(self.ack(0))
            result = self.adc.snapshot()['identification']
            self.assertEqual(result['state'], 'identified')
            self.assertTrue(result['restore_confirmed'])
            self.assertEqual(result['restore']['readback'], 0)
            self.assertEqual(self.send.call_count, 2)
            self.assertFalse(self.ack(0))

    def test_probe_rejection_and_i2c_errors_still_restore_once_without_chip_claim(self):
        for status in (0xEE, 3):
            self.adc = AdcController(0x462, self.clock)
            self.send.reset_mock()
            self.seed()
            self.adc.identify(self.send)
            self.ack(4, status)
            self.assertIsNone(self.adc.identification['chip'])
            self.assertEqual(self.send.call_count, 2)
            self.ack(0)
            self.assertEqual(self.adc.identification['state'], 'error')
            self.assertTrue(self.adc.identification['restore_confirmed'])

    def test_probe_timeout_restores_once_and_restore_timeout_never_claims_success(self):
        self.seed()
        self.adc.identify(self.send)
        self.clock.return_value = 2
        self.adc.advance(self.send)
        self.assertEqual(self.adc.identification['probe']['state'], 'timeout')
        self.assertEqual(self.adc.identification['state'], 'restoring')
        self.assertIsNone(self.adc.identification['chip'])
        self.assertEqual(self.send.call_count, 2)
        self.clock.return_value = 4
        self.adc.advance(self.send)
        self.adc.advance(self.send)
        self.assertEqual(self.adc.identification['state'], 'unconfirmed')
        self.assertEqual(self.adc.identification['restore']['state'], 'timeout')
        self.assertFalse(self.adc.identification['restore_confirmed'])
        self.assertEqual(self.send.call_count, 2)

    def test_probe_queue_failure_needs_no_restore_but_restore_queue_failure_is_explicit(self):
        self.seed()
        self.send.return_value = False
        self.assertFalse(self.adc.identify(self.send))
        self.clock.return_value = 10
        self.adc.advance(self.send)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.adc.identification['restore']['state'], 'not_sent')
        self.send.return_value = True
        self.adc.identify(self.send)
        self.send.return_value = False
        self.ack(4)
        self.assertEqual(self.adc.identification['restore']['state'], 'queue_failed')
        self.assertFalse(self.adc.identification['restore_confirmed'])

    def test_active_probe_blocks_writes_dump_and_another_probe_and_ignores_dump_header(self):
        self.seed()
        self.adc.identify(self.send)
        for action in (lambda: self.adc.write({'08': 112}, self.send),
                       lambda: self.adc.revert(self.send),
                       lambda: self.adc.request_dump(self.send),
                       lambda: self.adc.identify(self.send)):
            with self.assertRaises(ValueError):
                action()
        self.assertFalse(self.adc.observe(0x462, dump_frames([1] * 39)[0]))
        self.assertEqual(self.send.call_count, 1)

    def test_restore_rejection_i2c_error_and_nonzero_readback_stay_unconfirmed(self):
        for value, status in ((0, 0xEE), (0, 3), (4, 0)):
            self.adc = AdcController(0x462, self.clock)
            self.seed()
            self.adc.identify(self.send)
            self.ack(4)
            self.ack(value, status)
            self.assertEqual(self.adc.identification['state'], 'error')
            self.assertFalse(self.adc.identification['restore_confirmed'])

class AdcPresetRouteTests(unittest.TestCase):
    setUp = route_tests.BridgeRouteTests.setUp

    def test_presets_save_load_are_separate_json_and_never_send_can(self):
        url = '/api/manage/rnse-adc/presets'
        self.assertEqual(self.client.get(url).get_json(), {'presets': {}})
        saved = self.client.post(url, json={'name': 'Warm trim', 'values': {'08': 110, '0a': 113}}, headers=self.headers)
        self.assertEqual(saved.status_code, 200)
        expected = {'presets': {'Warm trim': {'08': 110, '0A': 113}}}
        self.assertEqual(saved.get_json(), expected)
        self.assertEqual(self.client.get(url).get_json(), expected)
        path = self.root / 'home/.hudiy/rnse-adc-presets.json'
        self.assertEqual(json.loads(path.read_text()), expected['presets'])
        self.exchange.assert_not_called()
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_locked_presets_corrupt_files_names_limits_and_duplicate_json_reject(self):
        url = '/api/manage/rnse-adc/presets'
        for body in ({'name': 'Bad', 'values': {'02': 80}}, {'name': '', 'values': {'08': 1}},
                     {'name': ' x ', 'values': {'08': 1}}, {'name': 'x' * 65, 'values': {'08': 1}}):
            self.assertEqual(self.client.post(url, json=body, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post(url, data='{"name":"x","name":"y","values":{"08":1}}', content_type='application/json', headers=self.headers).status_code, 400)
        self.client.get(url)
        path = self.root / 'home/.hudiy/rnse-adc-presets.json'
        path.write_text(json.dumps({'tampered': {'01': 63}}))
        self.assertEqual(self.client.get(url).status_code, 400)
        path.write_text(json.dumps({str(index): {'08': 1} for index in range(32)}))
        self.assertEqual(self.client.post(url, json={'name': 'extra', 'values': {'08': 1}}, headers=self.headers).status_code, 400)
        self.exchange.assert_not_called()
