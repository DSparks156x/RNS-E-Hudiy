"""Power, door, NM and clock handling in rns-e_can/can_base_function.py.

Byte layouts are checked against references/PQ35_46_ICAN.dbc (and the same
tables in references/ICAN_rundown.md), not against the code's own comments:
  0x2C3 mZAS_Status   bit0 ZS1_ZAS_Kl_S (key in), bit1 ZS1_ZAS_Kl_15 (ignition)
  0x470 mBSG_Kombi    bits 8..13 FT, BT, HL, HR doors, MH (bonnet), HD_Hauptraste
  0x42B / 0x436 NM    bit 12 SleepInd
  0x623 mKombi_K2     bit1 KO2_Reset, byte1 hour, 2 min, 3 sec, 4 day, 5 month,
                      6 century, 7 year
Runs the real module with a fake clock, fake ZMQ sockets and no `ip`/`sudo`.
"""
import asyncio
from datetime import datetime as real_datetime
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import pytz

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT), str(ROOT / 'rns-e_can')):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def load_base_function():
    spec = importlib.util.spec_from_file_location(
        'can_base_function_under_test', ROOT / 'rns-e_can' / 'can_base_function.py')
    module = importlib.util.module_from_spec(spec)
    with patch.object(logging, 'FileHandler', lambda *a, **k: logging.NullHandler()):
        spec.loader.exec_module(module)
    return module


BASE = load_base_function()


class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def time(self):
        return self.now


class AsyncioProxy:
    """The module's asyncio, except sleep() advances the fake clock and stops the loop."""

    def __init__(self, clock, ticks, each=None):
        self.clock = clock
        self.ticks = ticks
        self.each = each
        self.sleeps = 0

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, seconds):
        self.sleeps += 1
        self.clock.now += seconds
        if self.each:
            self.each()   # periodic bus traffic arriving between ticks
        if self.sleeps >= self.ticks:
            BASE.RUNNING = False


def frame(data_hex):
    """The JSON can_handler publishes for one frame."""
    return {'arbitration_id': 0, 'dlc': len(data_hex) // 2, 'data_hex': data_hex,
            'is_extended_id': False, 'is_remote_frame': False, 'is_error_frame': False}


class BaseFunctionTestCase(unittest.TestCase):
    features = {}

    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        env = patch.dict(os.environ, {'HOME': home.name})
        env.start()
        self.addCleanup(env.stop)
        config = {
            'features': json.loads(json.dumps(self.features)),
            'interfaces': {'can': {'infotainment': 'can0'}, 'zmq': {
                'send_address': 'ipc:///tmp/test_send.ipc',
                'can_raw_stream': 'ipc:///tmp/test_stream.ipc',
                'system_events': 'ipc:///tmp/test_events.ipc'}},
        }
        path = Path(home.name) / 'config.json'
        path.write_text(json.dumps(config))
        BASE.CONFIG.clear()
        self.assertTrue(BASE.load_and_initialize_config(str(path)))
        BASE.RUNNING = True
        self.addCleanup(setattr, BASE, 'RUNNING', True)
        self.clock = FakeClock()
        patcher = patch.object(BASE, 'time', self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = BASE.AppState()
        self.published = []
        self.state.zmq_pub = Mock()
        self.state.zmq_pub.send_multipart.side_effect = lambda parts: self.published.append(
            json.loads(parts[1]))
        self.pushed = []
        push = Mock()
        push.send_multipart.side_effect = lambda parts: self.pushed.append(
            (int(parts[0]), parts[1].decode()))
        patcher = patch.object(BASE, 'ZMQ_PUSH_SOCKET', push)
        patcher.start()
        self.addCleanup(patcher.stop)

    def power(self, byte0):
        BASE.handle_power_status_message(frame(f'{byte0:02x}'), self.state)
        return self.published[-1]


class IgnitionFrameTests(BaseFunctionTestCase):
    def test_kl15_and_key_bits_follow_dbc_and_ignore_other_terminals(self):
        for byte0 in range(0x20):
            with self.subTest(byte0=hex(byte0)):
                status = self.power(byte0)
                self.assertEqual(status['kl15'], bool(byte0 & 0x02))   # ZS1_ZAS_Kl_15
                self.assertEqual(status['kls'], bool(byte0 & 0x01))    # ZS1_ZAS_Kl_S

    def test_short_or_garbage_frames_do_not_change_ignition_state(self):
        self.power(0x03)
        BASE.handle_power_status_message({'dlc': 0, 'data_hex': ''}, self.state)
        BASE.handle_power_status_message({'dlc': 1, 'data_hex': 'zz'}, self.state)
        self.assertEqual(self.state.last_kl15_status, 1)
        self.assertIsNone(self.state.ignition_off_timestamp)


class AutoShutdownTests(BaseFunctionTestCase):
    features = {'power_management': {'auto_shutdown': {
        'enabled': True, 'trigger': 'ignition_off', 'delay_seconds': 300}}}

    def test_ignition_off_arms_timer_and_ignition_on_cancels(self):
        self.power(0x03)
        self.assertFalse(self.state.shutdown_pending)
        self.power(0x01)
        self.assertTrue(self.state.shutdown_pending)
        self.assertEqual(self.state.shutdown_trigger_timestamp, self.clock.now)
        self.clock.now += 60
        self.power(0x01)   # repeated OFF frames must not restart the timer
        self.assertEqual(self.state.shutdown_trigger_timestamp, self.clock.now - 60)
        self.power(0x03)
        self.assertFalse(self.state.shutdown_pending)

    def test_shutdown_runs_only_after_delay_and_only_without_wake_signal(self):
        self.power(0x03)
        self.power(0x01)
        command = AsyncMock(return_value=True)
        with patch.object(BASE, 'execute_system_command_async', command):
            self.clock.now += 299
            self.assertFalse(asyncio.run(self.state.check_shutdown_condition(False)))
            self.clock.now += 1
            # Wake line still high (e.g. door open / KL15 relay): postpone, never halt.
            self.assertFalse(asyncio.run(self.state.check_shutdown_condition(True)))
            command.assert_not_called()
            self.assertTrue(self.state.shutdown_pending)
            self.clock.now += 29
            self.assertFalse(asyncio.run(self.state.check_shutdown_condition(False)))
            self.clock.now += 1
            self.assertTrue(asyncio.run(self.state.check_shutdown_condition(False)))
        command.assert_awaited_once_with(['sudo', 'shutdown', '-h', 'now'])

    def test_failed_shutdown_command_resets_state(self):
        self.power(0x01)
        self.clock.now += 300
        with patch.object(BASE, 'execute_system_command_async', AsyncMock(return_value=False)):
            self.assertFalse(asyncio.run(self.state.check_shutdown_condition(False)))
        self.assertFalse(self.state.shutdown_pending)


class KeyPulledShutdownTests(BaseFunctionTestCase):
    features = {'power_management': {'auto_shutdown': {
        'enabled': True, 'trigger': 'key_pulled', 'delay_seconds': 30}}}

    def test_key_trigger_ignores_ignition_and_follows_kl_s(self):
        self.power(0x03)
        self.power(0x01)   # ignition off, key still in
        self.assertFalse(self.state.shutdown_pending)
        self.power(0x00)   # key pulled
        self.assertTrue(self.state.shutdown_pending)
        self.assertEqual(self.state._current_shutdown_delay, 30)
        self.power(0x01)   # key back in
        self.assertFalse(self.state.shutdown_pending)


class DoorAndNmFrameTests(BaseFunctionTestCase):
    def test_door_bits_follow_dbc_byte1(self):
        names = ['driver', 'passenger', 'rear_left', 'rear_right', 'hood', 'trunk']
        for bit, name in enumerate(names):
            with self.subTest(door=name):
                state = BASE.AppState()
                # Byte 0 is turn signals etc.; it must not open a door.
                BASE.handle_door_status_message(frame(f'ff{1 << bit:02x}00000000000000'), state)
                self.assertEqual([n for n in names if state.doors[n]], [name])
        state = BASE.AppState()
        # Bit 14 BSK_HD_Vorraste and bit 15 Unterspannung are not doors.
        BASE.handle_door_status_message(frame('00c0000000000000'), state)
        self.assertFalse(state.any_door_open)

    def test_door_open_event_is_published_once_per_opening(self):
        BASE.handle_door_status_message(frame('0001000000000000'), self.state)
        BASE.handle_door_status_message(frame('0001000000000000'), self.state)
        BASE.handle_door_status_message(frame('0000000000000000'), self.state)
        BASE.handle_door_status_message(frame('0020000000000000'), self.state)
        self.assertEqual([p['door_event'] for p in self.published], [True, False, False, True])
        self.assertEqual([p['door_open'] for p in self.published], [True, True, False, True])

    def test_nm_sleep_indication_is_bit_12(self):
        BASE.handle_gateway_nm_message(frame('001000000000'), self.state)
        self.assertTrue(self.state.gateway_sleep_ind)
        # Bit 13 SleepAck and bit 8 CmdRing are not SleepInd.
        BASE.handle_gateway_nm_message(frame('002100000000'), self.state)
        self.assertFalse(self.state.gateway_sleep_ind)
        BASE.handle_nav_nm_message(frame('0102000000000000'), self.state)
        self.assertFalse(self.state.nav_sleep_ind)
        self.assertTrue(self.state.is_radio_active())
        self.clock.now += 5.0
        self.assertFalse(self.state.is_radio_active())   # NM timed out


class ListenOnlyTests(BaseFunctionTestCase):
    features = {'tv_simulation': {'enabled': True},
                'power_management': {'listen_only_mode': {
                    'enabled': True, 'delay_seconds': 10, 'fallback_seconds': 900}}}

    def setUp(self):
        super().setUp()
        self.switches = []
        self.switch_ok = True
        self.live_nm = None   # (gateway_sleep, nav_sleep) repeated every tick

        async def set_listen_only(enable):
            self.switches.append(enable)
            return self.switch_ok
        patcher = patch.object(BASE, 'set_listen_only_async', set_listen_only)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tick(self, seconds=1, step=1.0):
        BASE.RUNNING = True
        nm = self.live_nm
        each = (lambda: self.nm(*nm)) if nm else None
        proxy = AsyncioProxy(self.clock, max(1, int(seconds / step)), each)
        with patch.object(BASE, 'asyncio', proxy):
            asyncio.run(BASE.shutdown_monitor_task(self.state))
        BASE.RUNNING = True

    def bus_nm(self, gateway_sleep, nav_sleep):
        """NM frames now, and again after every tick (~real NM cadence)."""
        self.live_nm = (gateway_sleep, nav_sleep)
        self.nm(gateway_sleep, nav_sleep)

    def nm(self, gateway_sleep, nav_sleep=True):
        BASE.handle_gateway_nm_message(frame('00' + ('10' if gateway_sleep else '00') + '00000000'), self.state)
        BASE.handle_nav_nm_message(frame('00' + ('10' if nav_sleep else '00') + '000000000000'), self.state)

    def test_never_listen_only_while_ignition_on(self):
        self.power(0x03)
        self.bus_nm(True, True)
        self.tick(30)
        self.live_nm = None
        self.tick(30)   # NM silent too
        self.assertEqual(self.switches, [])
        self.assertFalse(self.state.can_listen_only)

    def test_ignition_off_and_bus_sleep_goes_listen_only_after_delay_then_back(self):
        self.power(0x03)
        self.power(0x01)
        self.bus_nm(False, False)   # gateway + radio still awake
        self.tick(20)
        self.assertEqual(self.switches, [], 'bus still awake: must keep transmitting')
        self.bus_nm(False, True)    # radio asleep, gateway awake
        self.tick(20)
        self.assertEqual(self.switches, [], 'gateway awake: must keep transmitting')
        self.bus_nm(True, True)
        self.tick(9)
        self.assertEqual(self.switches, [], 'listen-only before configured delay')
        self.tick(2)
        self.assertEqual(self.switches, [True])
        self.assertTrue(self.state.can_listen_only)
        # Ignition back on: CAN must leave listen-only so the Pi can talk again.
        self.power(0x03)
        self.tick(1)
        self.assertEqual(self.switches, [True, False])
        self.assertFalse(self.state.can_listen_only)

    def test_quiet_bus_counts_as_asleep(self):
        self.power(0x01)
        self.clock.now += 6   # no NM frames for > 5 s
        self.tick(11)
        self.assertEqual(self.switches, [True])

    def test_fallback_forces_listen_only_if_nm_never_sleeps(self):
        self.power(0x01)
        self.bus_nm(False, False)
        self.tick(899)
        self.assertEqual(self.switches, [])
        self.tick(12)   # 900 s fallback + 10 s delay
        self.assertEqual(self.switches, [True])

    def test_failed_switch_is_retried_and_state_not_claimed(self):
        self.power(0x01)
        self.bus_nm(True, True)
        self.switch_ok = False
        self.tick(12)
        self.assertFalse(self.state.can_listen_only)
        retries = len(self.switches)
        self.assertGreaterEqual(retries, 2)
        self.switch_ok = True
        self.tick(1)
        self.assertTrue(self.state.can_listen_only)

    def test_no_application_transmit_while_listen_only(self):
        self.state.is_radio_active = lambda: True
        self.state.desired_listen_only = True
        self.assertFalse(BASE.send_adc_frame(self.state, 0x7B0, 'BB05000000000000'))
        proxy = AsyncioProxy(self.clock, 1)
        with patch.object(BASE, 'asyncio', proxy):
            asyncio.run(BASE.send_periodic_messages_task(self.state))
        self.assertEqual(self.pushed, [])
        self.state.desired_listen_only = False
        BASE.RUNNING = True
        proxy = AsyncioProxy(self.clock, 1)
        with patch.object(BASE, 'asyncio', proxy):
            asyncio.run(BASE.send_periodic_messages_task(self.state))
        # mTV_A_1 0x602 with the default payload, decimal ID on the wire.
        self.assertEqual(self.pushed, [(0x602, '0912302020202020')])

    def test_ip_link_sequence_for_listen_only(self):
        calls = []
        with patch.object(BASE, 'execute_system_command', side_effect=lambda c: calls.append(c) or True):
            self.assertTrue(BASE.CanInterfaceManager.set_listen_only(True))
            self.assertTrue(BASE.CanInterfaceManager.set_listen_only(False))
        self.assertEqual(calls, [
            ['sudo', 'ip', 'link', 'set', 'can0', 'down'],
            ['sudo', 'ip', 'link', 'set', 'can0', 'type', 'can', 'listen-only', 'on'],
            ['sudo', 'ip', 'link', 'set', 'can0', 'up'],
            ['sudo', 'ip', 'link', 'set', 'can0', 'down'],
            ['sudo', 'ip', 'link', 'set', 'can0', 'type', 'can', 'listen-only', 'off'],
            ['sudo', 'ip', 'link', 'set', 'can0', 'up'],
        ])
        calls.clear()
        with patch.object(BASE, 'execute_system_command', side_effect=lambda c: calls.append(c) and False):
            self.assertFalse(BASE.CanInterfaceManager.set_listen_only(True))
        self.assertEqual(len(calls), 1, 'must not bring the link up after a failed down')


class FixedDatetime(real_datetime):
    fixed_utc = real_datetime(2020, 1, 1, tzinfo=pytz.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.fixed_utc.astimezone(tz) if tz else cls.fixed_utc.replace(tzinfo=None)


class TimeSyncTests(BaseFunctionTestCase):
    features = {'car_time_zone': 'Europe/Berlin',
                'time_sync': {'enabled': True, 'data_format': 'new_logic', 'threshold_minutes': 1}}

    def sync(self, data_hex, pi_utc=real_datetime(2020, 1, 1, tzinfo=pytz.utc)):
        command = AsyncMock(return_value=True)

        async def run():
            await BASE.handle_time_data_message(frame(data_hex), self.state)
            if self.state.time_sync_task:
                await self.state.time_sync_task
        FixedDatetime.fixed_utc = pi_utc
        with patch.object(BASE, 'execute_system_command_async', command), \
                patch.object(BASE, 'datetime', FixedDatetime):
            asyncio.run(run())
        return [c.args[0] for c in command.await_args_list]

    def test_binary_kombi_time_sets_utc_system_clock(self):
        # 2026-10-11 13:45:30 local (CEST, UTC+2) per mKombi_K2 byte layout.
        data = bytes([0x00, 13, 45, 30, 11, 10, 20, 26]).hex()
        self.assertEqual(self.sync(data), [['sudo', 'date', '-u', '101111452026.30']])
        self.assertFalse(self.state.time_sync_in_progress)

    def test_small_difference_does_not_touch_clock(self):
        data = bytes([0x00, 13, 45, 30, 11, 10, 20, 26]).hex()
        pi = real_datetime(2026, 10, 11, 11, 45, 0, tzinfo=pytz.utc)
        self.assertEqual(self.sync(data, pi), [])

    def test_invalid_date_bytes_are_ignored(self):
        self.assertEqual(self.sync(bytes([0, 25, 61, 0, 32, 13, 20, 26]).hex()), [])
        self.assertEqual(self.sync('00112233'), [])   # DLC < 8

    @unittest.expectedFailure
    def test_kombi_reset_flag_means_time_is_not_valid(self):
        """DBC/ICAN_rundown: KO2_Reset (bit 1) = 'transmitted time is not valid'.

        handle_time_data_message ignores byte 0, so a cluster clock reset can
        set the Pi's system clock to whatever the cluster reports.
        """
        data = bytes([0x02, 0, 0, 0, 1, 1, 20, 0]).hex()
        self.assertEqual(self.sync(data), [])


class BcdTimeSyncTests(TimeSyncTests):
    features = {'car_time_zone': 'UTC',
                'time_sync': {'enabled': True, 'data_format': 'old_logic'}}

    def test_binary_kombi_time_sets_utc_system_clock(self):
        data = '0013453011102026'
        self.assertEqual(self.sync(data), [['sudo', 'date', '-u', '101113452026.30']])

    def test_small_difference_does_not_touch_clock(self):
        pi = real_datetime(2026, 10, 11, 13, 45, 0, tzinfo=pytz.utc)
        self.assertEqual(self.sync('0013453011102026', pi), [])

    def test_invalid_date_bytes_are_ignored(self):
        self.assertEqual(self.sync('001A453011102026'), [])   # not BCD


class FakeStream:
    def __init__(self, messages):
        self.messages = list(messages)
        self.transport = Mock()
        self.close = Mock()

    async def read(self):
        if not self.messages:
            BASE.RUNNING = False
            return []
        topic, body = self.messages.pop(0)
        return [topic.encode(), json.dumps(body).encode()]


class ListenerDispatchTests(BaseFunctionTestCase):
    features = {'power_management': {'listen_only_mode': {'enabled': True}}}

    def run_listener(self, messages):
        stream = FakeStream(messages)
        with patch.object(BASE.aiozmq, 'create_zmq_stream', AsyncMock(return_value=stream)):
            asyncio.run(BASE.listen_for_can_messages_task(self.state))
        return stream

    def test_subscriptions_match_gateway_topics(self):
        stream = self.run_listener([])
        topics = {c.args[0] for c in stream.transport.subscribe.call_args_list}
        # Gateway topics are f"CAN_{id:03X}" (see test_can_handler); 0x7B6 = ADC reply.
        self.assertEqual(topics, {b'CAN_2C3', b'CAN_470', b'CAN_42B', b'CAN_436', b'CAN_7B6'})
        stream.close.assert_called_once()

    def test_gateway_messages_are_routed_by_id(self):
        def gw(can_id, data_hex):
            body = frame(data_hex)
            body['arbitration_id'] = can_id
            return (f'CAN_{can_id:03X}', body)
        self.run_listener([
            gw(0x2C3, '03'),
            gw(0x470, '0001000000000000'),
            gw(0x436, '0010000000000000'),
            ('CAN_42B', {'dlc': 6, 'data_hex': '001000000000'}),   # no arbitration_id
            ('CAN_2C3', {'arbitration_id': 0x2C3, 'dlc': 8, 'data_hex': '01'}),  # truncated
        ])
        self.assertEqual(self.state.last_kl15_status, 1)
        self.assertTrue(self.state.doors['driver'])
        self.assertTrue(self.state.nav_sleep_ind)
        self.assertTrue(self.state.gateway_sleep_ind)   # ID taken from topic


class LoggingTests(unittest.TestCase):
    def test_service_log_file_is_opened(self):
        """setup_logging() swallows errors, so a broken import silently drops the log file."""
        with patch.object(logging, 'FileHandler') as handler, patch('os.makedirs'):
            BASE.setup_logging()
        handler.assert_called_once_with('/var/log/rnse_control/can_base_function.log')


if __name__ == '__main__':
    unittest.main()
