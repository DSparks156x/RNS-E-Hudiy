import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vehicle_data.broker import VehicleDataBroker


class FakeTime:
    def __init__(self):
        self.mono = 100.0
        self.wall = 10000.0

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds


def diag(group, block=1, *, verified=True, module=1):
    return {'id': f'diag:{module}:{group}:{block}', 'kind': 'diag',
            'module': module, 'group': group, 'block': block,
            'verified': verified, 'estimated': False, 'stale_after_ms': 1000}


def passive(*, estimated=False, verified=True):
    return {'id': 'ican:123:value', 'kind': 'ican', 'can_id': 0x123,
            'start': 0, 'length': 8, 'frame_length': 1, 'invalid_raw': [255],
            'verified': verified, 'estimated': estimated, 'stale_after_ms': 1000}


def catalog(providers=None):
    return {'test.value': {'id': 'test.value', 'label': 'Test', 'unit': 'rpm',
                           'type': 'number', 'providers': providers or [passive(), diag(1)]}}


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.time = FakeTime()

    def broker(self, registry=None, **options):
        return VehicleDataBroker(catalog=registry, clock=lambda: self.time.mono,
                                 wall_clock=lambda: self.time.wall, **options)

    def ingest(self, broker, group=1, value=1000, **extra):
        broker.ingest_diagnostic({'module': 1, 'group': group,
                                  'data': [{'value': value, 'unit': 'rpm'}],
                                  'acquisition_timestamp': self.time.wall, **extra})

    def test_group_cover_uses_combination_across_consumers(self):
        broker = self.broker()
        broker.sync('dis', ['engine.maf'])
        broker.sync('web', ['engine.ignition_timing'])
        self.assertEqual(broker.plan()['groups'], [{'module': 1, 'group': 3, 'period_ms': 500}])
        broker.sync('web', ['engine.injection_time'])
        self.assertEqual(broker.plan()['groups'], [{'module': 1, 'group': 2, 'period_ms': 500}])
        broker.sync('dis', ['engine.boost.actual_absolute', 'engine.intake_temperature'])
        broker.sync('web', ['engine.n75_duty'])
        self.assertEqual(broker.plan()['groups'], [{'module': 1, 'group': 118, 'period_ms': 500}])

    def test_fastest_consumer_controls_one_shared_read(self):
        broker = self.broker()
        broker.sync('dis', [{'id': 'engine.maf', 'rate_hz': 2}])
        broker.sync('web', [{'id': 'engine.ignition_timing', 'period_ms': 100}])
        self.assertEqual(broker.plan()['groups'], [{'module': 1, 'group': 3, 'period_ms': 100}])

    def test_passive_is_preferred_only_when_fresh(self):
        broker = self.broker(catalog())
        broker.sync('display', ['test.value'])
        self.assertEqual(len(broker.plan()['groups']), 1)
        broker.ingest_can(0x123, bytes([45]), timestamp=self.time.wall)
        self.assertEqual(broker.plan()['groups'], [])
        sample = broker.tick()[0]
        self.assertEqual(sample['value'], 45)
        self.assertEqual(sample['source']['kind'], 'ican')
        self.assertEqual(broker.plan()['selected'][0]['period_ms'], 100)
        self.time.advance(1.01)
        self.assertEqual(len(broker.plan()['groups']), 1)
        self.assertEqual(broker.snapshot(client_id='display')[0]['source']['kind'], 'diag')

    def test_default_verified_oil_and_six_byte_battery_frames_need_no_diagnostic_reads(self):
        broker = self.broker()
        broker.sync('display', ['engine.oil_temperature', 'vehicle.battery_voltage'])
        broker.ingest_can(0x555, bytes([0, 100, 128, 0, 110, 0, 0, 150]))
        broker.ingest_can(0x571, bytes([150, 0, 0, 0, 0, 0]))
        samples = {sample['id']: sample for sample in broker.tick()}
        self.assertEqual(samples['engine.oil_temperature']['value'], 90)
        self.assertEqual(samples['vehicle.battery_voltage']['value'], 12.5)
        self.assertTrue(all(s['status'] == 'ok' and s['quality']['verified'] for s in samples.values()))
        self.assertEqual(broker.plan()['groups'], [])

    def test_stale_and_error_transitions_do_not_refresh_timestamp(self):
        broker = self.broker(catalog([passive()]))
        broker.sync('display', ['test.value'])
        broker.ingest_can(0x123, bytes([45]), timestamp=self.time.wall)
        acquired = broker.tick()[0]
        self.time.advance(.1)
        self.assertEqual(broker.tick(), [])
        self.time.advance(1)
        stale = broker.tick()[0]
        self.assertEqual(stale['status'], 'stale')
        self.assertEqual(stale['timestamp'], acquired['timestamp'])
        self.assertEqual(stale['sample_sequence'], acquired['sample_sequence'])
        self.assertGreater(stale['age_ms'], 1000)
        broker.ingest_can(0x123, bytes([255]), timestamp=self.time.wall)
        invalid = broker.tick()[0]
        self.assertIsNone(invalid['value'])
        self.assertEqual(invalid['status'], 'invalid')

    def test_publication_cap_retains_latest_acquisition_timestamp(self):
        broker = self.broker(catalog([passive()]))
        broker.sync('display', ['test.value'])
        broker.ingest_can(0x123, bytes([1]))
        broker.tick()
        self.time.advance(.02)
        broker.ingest_can(0x123, bytes([2]))
        self.assertEqual(broker.tick(), [])
        timestamp = self.time.wall
        self.time.advance(.08)
        sample = broker.tick()[0]
        self.assertEqual(sample['timestamp'], timestamp)
        self.assertEqual(sample['value'], 2)
        self.assertAlmostEqual(sample['age_ms'], 80)

    def test_same_numeric_value_with_new_acquisition_is_published(self):
        broker = self.broker(catalog([passive()]))
        broker.sync('display', ['test.value'])
        broker.ingest_can(0x123, bytes([1]))
        first = broker.tick()[0]
        self.time.advance(.1)
        broker.ingest_can(0x123, bytes([1]))
        second = broker.tick()[0]
        self.assertGreater(second['sample_sequence'], first['sample_sequence'])

    def test_recovery_hysteresis_prevents_immediate_source_flapping(self):
        broker = self.broker(catalog())
        broker.sync('display', ['test.value'])
        broker.ingest_can(0x123, bytes([45]))
        broker.tick()
        self.time.advance(1.1)
        broker.tick()
        self.ingest(broker)
        broker.ingest_can(0x123, bytes([46]))
        self.assertEqual(broker.snapshot(client_id='display')[0]['source']['kind'], 'diag')
        self.time.advance(.6)
        broker.ingest_can(0x123, bytes([47]))
        self.assertEqual(broker.snapshot(client_id='display')[0]['source']['kind'], 'ican')
        self.assertEqual(broker.plan()['groups'], [])

    def test_pinned_clients_keep_independent_sources(self):
        broker = self.broker(catalog())
        broker.sync('can', [{'id': 'test.value', 'source': 'ican'}])
        broker.sync('ecu', [{'id': 'test.value', 'source': 'diag'}])
        broker.ingest_can(0x123, bytes([45]))
        self.ingest(broker, value=1500)
        samples = {s['client_id']: s for s in broker.tick()}
        self.assertEqual(samples['can']['value'], 45)
        self.assertEqual(samples['ecu']['value'], 1500)
        self.assertEqual(len(broker.plan()['groups']), 1)
        self.assertEqual(broker.snapshot(client_id='ecu')[0]['value'], 1500)

    def test_estimate_and_unverified_need_separate_explicit_opt_ins(self):
        broker = self.broker(catalog([passive(estimated=True, verified=False)]))
        broker.sync('normal', ['test.value'])
        broker.sync('estimate', [{'id': 'test.value', 'allow_estimated': True}])
        broker.sync('both', [{'id': 'test.value', 'allow_estimated': True, 'allow_unverified': True}])
        broker.ingest_can(0x123, bytes([40]))
        self.assertEqual(broker.snapshot(client_id='normal')[0]['status'], 'unavailable')
        self.assertEqual(broker.snapshot(client_id='estimate')[0]['status'], 'unavailable')
        sample = broker.snapshot(client_id='both')[0]
        self.assertEqual(sample['status'], 'ok')
        self.assertTrue(sample['quality']['estimated'])
        self.assertFalse(sample['quality']['verified'])

    def test_sync_is_atomic_and_validates_bad_rates_and_sources(self):
        broker = self.broker(catalog())
        broker.sync('display', ['test.value'])
        for options in ({'id': 'unknown'}, {'id': 'test.value', 'rate_hz': 0},
                        {'id': 'test.value', 'period_ms': float('nan')},
                        {'id': 'test.value', 'period_ms': True},
                        {'id': 'test.value', 'rate_hz': 2, 'period_ms': 500},
                        {'id': 'test.value', 'source': 'diag:2:99:1'},
                        {'id': 'test.value', 'allow_estimated': 'yes'}):
            self.assertEqual(broker.sync('display', [options])['status'], 'error')
            self.assertEqual(len(broker.plan()['groups']), 1)
        self.assertEqual(broker.sync('display', ['test.value', 'test.value'])['status'], 'error')

    def test_lease_expiration_and_atomic_replacement_release_reads(self):
        broker = self.broker(catalog())
        broker.sync('first', ['test.value'])
        self.time.advance(10)
        broker.sync('second', ['test.value'])
        self.time.advance(5)
        self.assertEqual(broker.status()['client_count'], 1)
        broker.sync('second', [])
        self.assertEqual(broker.plan()['groups'], [])
        self.assertEqual(broker.tick(), [])

    def test_failures_choose_an_alternative_and_resume_after_cooldown(self):
        broker = self.broker(catalog([diag(1), diag(2)]))
        broker.sync('display', ['test.value'])
        broker.ingest_observation({'module': 1, 'group': 1, 'error': 'unsupported',
                                   'transient': False, 'acquisition_timestamp': self.time.wall})
        self.assertEqual(broker.plan()['groups'][0]['group'], 2)
        self.ingest(broker, group=2)
        self.assertEqual(broker.snapshot(client_id='display')[0]['status'], 'ok')
        self.time.advance(31)
        broker.sync('display', ['test.value'])
        self.assertEqual(broker.plan()['groups'][0]['group'], 1)

    def test_invalid_field_uses_alternative_without_trusting_units(self):
        broker = self.broker(catalog([diag(1), diag(2)]))
        broker.sync('display', ['test.value'])
        broker.ingest_diagnostic({'module': 1, 'group': 1, 'data': [{'value': 50, 'unit': 'C'}]})
        self.assertEqual(broker.plan()['groups'][0]['group'], 2)

    def test_eight_fields_work_when_provider_is_explicitly_registered(self):
        broker = self.broker(catalog([diag(11, block=8, verified=False)]))
        broker.sync('normal', ['test.value'])
        broker.sync('explore', [{'id': 'test.value', 'allow_unverified': True}])
        broker.ingest_diagnostic({'module': 1, 'group': 11,
                                  'data': [{'value': 1, 'unit': 'rpm'}] * 7 +
                                          [{'value': 8800, 'unit': 'rpm'}], 'complete': True})
        self.assertEqual(broker.snapshot(client_id='normal')[0]['status'], 'unavailable')
        self.assertEqual(broker.snapshot(client_id='explore')[0]['value'], 8800)
        self.assertEqual(broker.plan()['groups'][0]['group'], 11)

    def test_incomplete_group_is_never_published_as_a_good_sample(self):
        broker = self.broker(catalog([diag(1)]))
        broker.sync('display', ['test.value'])
        self.ingest(broker, complete=False)
        sample = broker.tick()[0]
        self.assertEqual(sample['status'], 'invalid')
        self.assertIsNone(sample['value'])
        self.assertEqual(broker.plan()['groups'], [])

    def test_pause_affects_diagnostics_but_passive_continues(self):
        broker = self.broker(catalog())
        broker.sync('ecu', [{'id': 'test.value', 'source': 'diag'}])
        broker.sync('can', [{'id': 'test.value', 'source': 'ican'}])
        self.ingest(broker)
        broker.ingest_can(0x123, bytes([20]))
        broker.tick()
        broker.set_diagnostic_status({'diagnostic_owner': 'flasher', 'enabled': True})
        samples = {s['client_id']: s for s in broker.tick()}
        self.assertEqual(samples['ecu']['status'], 'paused')
        self.assertEqual(broker.snapshot(client_id='can')[0]['status'], 'ok')
        self.assertFalse(broker.plan()['diagnostics_available'])
        self.assertEqual(len(broker.plan()['groups']), 1)
        broker.set_diagnostic_status({'diagnostic_owner': None})
        self.assertEqual(broker.tick()[0]['status'], 'ok')

    def test_transport_unavailable_status_recovers_from_authoritative_worker_status(self):
        broker = self.broker(catalog([diag(1)]))
        broker.sync('display', ['test.value'])
        self.ingest(broker)
        acquired = broker.tick()[0]
        broker.set_diagnostic_status({'status': 'error', 'available': False})
        paused = broker.tick()[0]
        self.assertEqual(paused['status'], 'paused')
        self.assertEqual(paused['timestamp'], acquired['timestamp'])
        self.assertFalse(broker.plan()['diagnostics_available'])
        broker.set_diagnostic_status({'status': 'ok', 'enabled': True, 'running': True,
                                      'ignition': True, 'diagnostic_owner': None,
                                      'flashing': False, 'available': True, 'sessions': []})
        recovered = broker.tick()[0]
        self.assertEqual(recovered['status'], 'ok')
        self.assertEqual(recovered['timestamp'], acquired['timestamp'])
        self.assertTrue(broker.plan()['diagnostics_available'])

    def test_acquisition_age_and_leases_use_monotonic_clock(self):
        broker = self.broker(catalog([passive()]))
        broker.sync('display', ['test.value'])
        broker.ingest_can(0x123, bytes([20]))
        acquired = broker.tick()[0]
        self.time.wall -= 3600
        self.time.mono += .5
        sample = broker.snapshot(client_id='display')[0]
        self.assertEqual(sample['timestamp'], acquired['timestamp'])
        self.assertEqual(sample['status'], 'ok')
        self.assertEqual(sample['age_ms'], 500)
        self.time.mono += 15
        self.assertEqual(broker.status()['client_count'], 0)

    def test_new_acquisition_after_wall_clock_correction_is_not_dropped(self):
        broker = self.broker(catalog([passive()]))
        broker.sync('display', ['test.value'])
        broker.ingest_can(0x123, bytes([20]))
        broker.tick()
        self.time.wall -= 3600
        self.time.advance(.1)
        broker.ingest_can(0x123, bytes([21]))
        sample = broker.tick()[0]
        self.assertEqual(sample['value'], 21)
        self.assertEqual(sample['timestamp'], self.time.wall)
        self.assertEqual(sample['age_ms'], 0)

    def test_delayed_frame_cannot_replace_newer_acquisition(self):
        broker = self.broker(catalog([passive()]))
        broker.sync('display', ['test.value'])
        broker.ingest_can(0x123, bytes([20]), timestamp=self.time.wall)
        broker.ingest_can(0x123, bytes([10]), timestamp=self.time.wall - 10)
        self.assertEqual(broker.tick()[0]['value'], 20)

    def test_observed_group_is_preferred_for_reuse_and_metrics_are_serializable(self):
        broker = self.broker(catalog([diag(1), diag(2)]))
        broker.sync('display', ['test.value'])
        broker.set_diagnostic_status({'sessions': [{'module': 1, 'group_stats': {'2': {
            'last_successful_acquisition_timestamp': self.time.wall, 'request_duration_ms': 10,
            'requested_period_ms': 500, 'achieved_hz': 1.98}}}]})
        self.assertEqual(broker.plan()['groups'][0]['group'], 2)
        self.ingest(broker, group=2, request_duration_ms=20)
        self.time.advance(.5)
        self.ingest(broker, group=2, request_duration_ms=18)
        state = broker.status()
        self.assertEqual(state['groups'][0]['achieved_hz'], 2)
        json.dumps(state, allow_nan=False)

    def test_multiple_modules_are_planned_independently(self):
        registry = catalog([diag(1)])
        registry['transmission.value'] = {'id': 'transmission.value', 'unit': 'rpm', 'providers': [diag(1, module=2)]}
        broker = self.broker(registry)
        broker.sync('display', ['test.value', 'transmission.value'])
        self.assertEqual(broker.plan()['groups'], [{'module': 1, 'group': 1, 'period_ms': 500},
                                                 {'module': 2, 'group': 1, 'period_ms': 500}])

    def test_real_timings_do_not_cause_walking_all_unknown_alternatives(self):
        broker = self.broker(catalog([diag(1), diag(2), diag(3)]))
        broker.sync('display', ['test.value'])
        self.ingest(broker, group=1, request_duration_ms=100)
        self.assertEqual(broker.plan()['groups'][0]['group'], 1)

    def external_status(self, period=500, client_id='legacy', last_sync=None):
        return {'sessions': [{'module': 1, 'client_subs': {client_id: {
            'groups': [], 'low_groups': [], 'group_periods_ms': {'2': period, '10': period},
            'last_sync': self.time.mono if last_sync is None else last_sync}}}]}

    def test_external_read_reuse_avoids_new_group_even_if_two_existing_groups(self):
        broker = self.broker()
        broker.sync('display', ['engine.maf', 'engine.ignition_timing'])
        broker.set_diagnostic_status(self.external_status())
        plan = broker.plan()
        self.assertEqual(plan['groups'], [{'module': 1, 'group': 2, 'period_ms': 500},
                                         {'module': 1, 'group': 10, 'period_ms': 500}])
        self.assertEqual({s['reason'] for s in plan['selected']}, {'shared external diagnostic group'})

    def test_slow_external_reads_have_incremental_cost_and_do_not_win_by_being_free(self):
        broker = self.broker()
        broker.sync('display', ['engine.maf', 'engine.ignition_timing'])
        broker.set_diagnostic_status(self.external_status(period=1000))
        self.assertEqual(broker.plan()['groups'], [{'module': 1, 'group': 3, 'period_ms': 500}])

    def test_broker_own_interests_are_excluded_from_external_free_reads(self):
        broker = self.broker()
        broker.sync('display', ['engine.maf', 'engine.ignition_timing'])
        broker.set_diagnostic_status(self.external_status(client_id='vehicle_data'))
        self.assertEqual(broker.plan()['groups'][0]['group'], 3)

    def test_external_leases_expire_and_authoritative_snapshots_clear_disappeared_clients(self):
        broker = self.broker(lease_seconds=60)
        broker.sync('display', ['engine.maf', 'engine.ignition_timing'])
        broker.set_diagnostic_status(self.external_status())
        self.assertEqual(len(broker.plan()['groups']), 2)
        # The short stream status message does not revoke the last STATUS lease.
        broker.set_diagnostic_status({'enabled': True})
        self.assertEqual(len(broker.plan()['groups']), 2)
        self.time.advance(15)
        self.assertEqual(broker.plan()['groups'][0]['group'], 3)
        broker.set_diagnostic_status(self.external_status())
        self.assertEqual(len(broker.plan()['groups']), 2)
        broker.set_diagnostic_status({'sessions': [{'module': 1, 'client_subs': {}}]})
        self.assertEqual(broker.plan()['groups'][0]['group'], 3)

    def test_external_source_reuse_respects_source_pins_and_stale_leases(self):
        broker = self.broker()
        broker.sync('display', [{'id': 'engine.maf', 'source': 'diag:01:3:2'},
                                {'id': 'engine.ignition_timing', 'source': 'diag:01:3:4'}])
        broker.set_diagnostic_status(self.external_status())
        self.assertEqual(broker.plan()['groups'][0]['group'], 3)
        broker.sync('display', ['engine.maf', 'engine.ignition_timing'])
        broker.set_diagnostic_status(self.external_status(last_sync=self.time.mono - 15))
        self.assertEqual(broker.plan()['groups'][0]['group'], 3)

    def test_external_normal_groups_are_fast_and_low_groups_are_slow(self):
        broker = self.broker()
        broker.sync('display', ['engine.maf', 'engine.ignition_timing'])
        status = self.external_status()
        interest = status['sessions'][0]['client_subs']['legacy']
        interest.update(group_periods_ms={}, groups=[2, 10], low_groups=[2, 10])
        broker.set_diagnostic_status(status)
        self.assertEqual(len(broker.plan()['groups']), 2)
        interest['groups'] = []
        broker.set_diagnostic_status(status)
        self.assertEqual(broker.plan()['groups'][0]['group'], 3)

    def test_malformed_diagnostic_and_status_payloads_are_contained(self):
        broker = self.broker(catalog([diag(1)]))
        broker.sync('display', ['test.value'])
        broker.ingest_diagnostic({'module': 1, 'group': 1, 'data': None})
        self.assertEqual(broker.tick()[0]['status'], 'invalid')
        broker.set_diagnostic_status({'sessions': None})
        broker.set_diagnostic_status({'sessions': [{'module': 'bad', 'group_stats': {'1': {}}}]})
        json.dumps(broker.status(), allow_nan=False)


if __name__ == '__main__':
    unittest.main()
