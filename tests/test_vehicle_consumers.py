"""Consumer migration behavior without importing Flask or hardware services."""
import ast
import logging
import json
from pathlib import Path
import shutil
import subprocess
import threading
import types
import unittest
from unittest.mock import Mock, patch

from dis_client.apps.car_info import CarInfoApp


ROOT = Path(__file__).resolve().parents[1]


def sample(value_id, value, **overrides):
    return {'id': value_id, 'value': value, 'status': 'ok', 'age_ms': 0,
            'max_age_ms': 2000, **overrides}


class DISValueConsumerTest(unittest.TestCase):
    def publish(self, app, *values, client_id='dis_display'):
        app.update_hudiy(b'HUDIY_VALUES', {'client_id': client_id, 'values': list(values)})

    def test_named_values_format_metric_units_and_signed_timing(self):
        app = CarInfoApp()
        with patch('dis_client.apps.car_info.time.monotonic', return_value=100):
            self.publish(app, sample('engine.boost.actual_absolute', 2134.2),
                         sample('engine.maf', 125.9), sample('engine.ignition_timing', -4.25),
                         sample('engine.oil_temperature', 90), sample('engine.coolant_temperature', 95))
            view = app.get_view()
        self.assertEqual(view['line1'][0], 'Boost: 2134mb')
        self.assertEqual(view['line2'][0], 'Air: 125gs')
        self.assertEqual(view['line3'][0], 'Timing: -4.2°')
        self.assertEqual(view['line4'][0], 'Oil: 90°C')
        self.assertEqual(view['line5'][0], 'Coolant: 95°C')

    def test_imperial_units_and_car_unit_resolution(self):
        app = CarInfoApp({'display': {'units': {'boost': 'car', 'cartemp': 'car'}},
                          'car_units': {'pressure': 'psi', 'temp': 'imperial'}})
        with patch('dis_client.apps.car_info.time.monotonic', return_value=100):
            self.publish(app, sample('engine.boost.actual_absolute', 2000), sample('engine.oil_temperature', 100))
            view = app.get_view()
        self.assertEqual(view['line1'][0], 'Boost: 29.0psi')
        self.assertEqual(view['line4'][0], 'Oil: 212°F')

    def test_relative_boost_requires_current_atmosphere(self):
        app = CarInfoApp({'display': {'units': {'boost_mode': 'relative'}}})
        self.assertIn('engine.atmospheric_pressure', app.value_requests)
        now = [100]
        with patch('dis_client.apps.car_info.time.monotonic', side_effect=lambda: now[0]):
            self.publish(app, sample('engine.boost.actual_absolute', 2100, max_age_ms=5000))
            self.assertEqual(app.get_view()['line1'][0], 'Boost: --')
            self.publish(app, sample('engine.atmospheric_pressure', 900, max_age_ms=1000))
            self.assertEqual(app.get_view()['line1'][0], 'Boost: +1200mb')
            now[0] += 1.1
            self.assertEqual(app.get_view()['line1'][0], 'Boost: --')
            self.publish(app, sample('engine.atmospheric_pressure', 1000, status='unavailable'))
            self.assertEqual(app.get_view()['line1'][0], 'Boost: --')

    def test_value_expiry_invalidates_cached_view_without_new_messages(self):
        app = CarInfoApp()
        now = [100]
        with patch('dis_client.apps.car_info.time.monotonic', side_effect=lambda: now[0]), \
                patch('dis_client.apps.car_info.time.time', return_value=1000):
            self.publish(app, sample('engine.oil_temperature', 90, age_ms=800, max_age_ms=1000))
            self.assertEqual(app.get_view()['line4'][0], 'Oil: 90°C')
            # Wall time is frozen inside the 500ms view throttle; local expiry
            # must still clear the cached text when acquisition age exceeds max.
            now[0] += .3
            self.assertEqual(app.get_view()['line4'][0], 'Oil: --')

    def test_other_client_ignored_and_real_engine_group1_not_synthetic_can_group(self):
        app = CarInfoApp()
        with patch('dis_client.apps.car_info.time.monotonic', return_value=100):
            self.publish(app, sample('engine.oil_temperature', 90), client_id='dataview_values:one')
        self.assertFalse(app.value_api_active)
        self.assertEqual(app.values, {})
        app.update_hudiy(b'HUDIY_DIAG', {'module': 1, 'group': 1,
            'data': [{'value': 800, 'unit': 'rpm'}, {'value': 90, 'unit': 'C'},
                     {'value': 0, 'unit': '%'}, {'value': '10101010', 'unit': 'bitval'}]})
        self.assertEqual(app.data['boost'], '--')
        self.assertEqual(app.data['load'], '--')

    def test_named_api_does_not_get_overwritten_by_legacy_groups(self):
        app = CarInfoApp()
        with patch('dis_client.apps.car_info.time.monotonic', return_value=100):
            self.publish(app, sample('engine.oil_temperature', 90))
            app.update_hudiy(b'HUDIY_DIAG', {'module': 0, 'group': 0,
                'data': [{'value': 123, 'unit': 'C'}]})
            self.assertEqual(app.get_view()['line4'][0], 'Oil: 90°C')


def load_backend_handlers():
    """Compile only the handlers under review, with decorators removed."""
    names = {'set_logger_subscriptions', 'handle_toggle', 'handle_disconnect', 'handle_values'}
    parsed = ast.parse((ROOT / 'hudiy_dataview' / 'app.py').read_text(encoding='utf-8'))
    selected = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            selected.append(node)
    namespace = {'current_subscriptions': {}, 'logger_subscriptions': {},
                 '_subscription_lock': threading.RLock(), '_connected_sids': {'one', 'two'},
                 'worker': Mock(), 'value_bridge': Mock(), 'logger': logging.getLogger(__name__),
                 'emit': Mock(), 'request': types.SimpleNamespace(sid='one'),
                 'interpolator': Mock(), 'SMOOTHING_ENABLED': False}
    namespace['interpolator'].get_raw.return_value = None
    namespace['value_bridge'].replace.return_value = {'status': 'ok'}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / 'hudiy_dataview' / 'app.py'), 'exec'), namespace)
    return namespace


class DataViewSubscriptionConsumerTest(unittest.TestCase):
    def setUp(self):
        self.backend = load_backend_handlers()

    def toggle(self, sid, module, group, action='add', priority='normal'):
        self.backend['request'].sid = sid
        self.backend['handle_toggle']({'module': module, 'group': group,
                                       'action': action, 'priority': priority})

    def test_two_browsers_can_request_same_group_independently(self):
        self.toggle('one', 1, 3)
        self.toggle('two', 1, 3)
        self.toggle('one', 1, 3, 'remove')
        interests = self.backend['current_subscriptions']
        self.assertNotIn('one', interests)
        self.assertEqual(interests['two'][1]['normal'], {3})
        latest = self.backend['worker'].send_command.call_args
        self.assertEqual(latest.kwargs['client_id'], 'dataview:one')
        self.assertEqual(latest.kwargs['groups'], [])

    def test_disconnect_clears_owner_modules_keeps_other_browser_and_logger(self):
        self.toggle('one', 1, 3)
        self.toggle('one', 2, 19, priority='low')
        self.toggle('two', 1, 3)
        self.backend['set_logger_subscriptions']([{'module': 1, 'group': 115}])
        logger_interests = self.backend['logger_subscriptions'].copy()
        self.backend['worker'].send_command.reset_mock()
        self.backend['request'].sid = 'one'
        self.backend['handle_disconnect']()
        self.assertEqual(set(self.backend['current_subscriptions']), {'two'})
        self.assertEqual(self.backend['logger_subscriptions'], logger_interests)
        self.assertNotIn('one', self.backend['_connected_sids'])
        commands = self.backend['worker'].send_command.call_args_list
        self.assertEqual({call.kwargs['module'] for call in commands}, {1, 2})
        self.assertTrue(all(call.kwargs['client_id'] == 'dataview:one' for call in commands))
        self.assertTrue(all(call.kwargs['groups'] == [] and call.kwargs['low_priority_groups'] == [] for call in commands))
        self.backend['value_bridge'].release.assert_called_once_with('one')

    def test_logger_replacement_clears_only_its_previous_groups(self):
        self.toggle('two', 1, 3)
        self.backend['set_logger_subscriptions']([{'module': 1, 'group': 115},
                                                  {'module': 2, 'group': 19, 'priority': 'low'}])
        self.backend['worker'].send_command.reset_mock()
        self.backend['set_logger_subscriptions']([{'module': 1, 'group': 106}])
        self.assertEqual(self.backend['current_subscriptions']['two'][1]['normal'], {3})
        calls = self.backend['worker'].send_command.call_args_list
        self.assertTrue(all(call.kwargs['client_id'] == 'dataview_logger' for call in calls))
        commands = {call.kwargs['module']: call.kwargs for call in calls}
        self.assertEqual(commands[1]['groups'], [106])
        self.assertEqual(commands[2]['groups'], [])
        self.assertEqual(commands[2]['low_priority_groups'], [])

    def test_invalid_toggle_preserves_interests(self):
        self.toggle('one', 1, 3)
        self.backend['emit'].reset_mock()
        self.toggle('one', 256, 3)
        self.assertEqual(self.backend['current_subscriptions']['one'][1]['normal'], {3})
        response = self.backend['emit'].call_args.args[1]
        self.assertEqual(response['status'], 'error')

    def test_delayed_raw_toggle_cannot_resurrect_disconnected_browser(self):
        self.toggle('one', 1, 3)
        self.backend['request'].sid = 'one'
        self.backend['handle_disconnect']()
        self.backend['worker'].send_command.reset_mock()
        self.toggle('one', 1, 115)
        self.assertNotIn('one', self.backend['current_subscriptions'])
        self.backend['worker'].send_command.assert_not_called()

    def test_values_returning_after_disconnect_are_released_again(self):
        self.backend['request'].sid = 'one'
        def replace(_sid, _values):
            self.backend['_connected_sids'].discard('one')
            return {'status': 'ok'}
        self.backend['value_bridge'].replace.side_effect = replace
        self.backend['handle_values']({'values': ['engine.rpm']})
        self.backend['value_bridge'].release.assert_called_once_with('one')
        self.backend['emit'].assert_not_called()


class DataViewStoreConsumerTest(unittest.TestCase):
    def test_named_store_preserves_units_and_precision_and_expires_locally(self):
        typescript = ROOT / 'hudiy_dataview' / 'node_modules' / 'typescript' / 'lib' / 'typescript.js'
        bundled_node = Path.home() / '.cache' / 'codex-runtimes' / 'codex-primary-runtime' / 'dependencies' / 'node' / 'bin' / 'node.exe'
        node = shutil.which('node') or (str(bundled_node) if bundled_node.exists() else None)
        if node is None or not typescript.exists():
            self.skipTest('Node and local TypeScript compiler required for DataStore behavioral test')
        javascript = r'''
const fs = require('fs'), vm = require('vm'), ts = require(process.argv[2]);
const source = fs.readFileSync(process.argv[1], 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020
}}).outputText;
const sandbox = {exports: {}, performance: {now: () => 0}};
vm.runInNewContext(compiled, sandbox);
const store = sandbox.exports.DataStore, received = [], late = [], missing = [];
store.subscribeValue('value:engine.maf', 0, v => received.push(v));
store.subscribeValue('value:engine.oil_temperature', 0, v => missing.push(v));
store.updateValues([{id: 'engine.maf', value: 4.512345, unit: 'g/s', status: 'ok',
    timestamp: 1000, age_ms: 900, max_age_ms: 1000}], 100);
const original = {...store.getValue('engine.maf')};
store.expireValues(201);
store.subscribeValue('value:engine.maf', 0, v => late.push(v));
store.updateValues([{id: 'engine.maf', value: null, unit: 'g/s', status: 'unavailable',
    timestamp: 1001, age_ms: null, max_age_ms: 1000}], 202);
console.log(JSON.stringify({received, late, missing, original}));
'''
        result = subprocess.run([node, '-e', javascript,
                                 str(ROOT / 'hudiy_dataview' / 'src' / 'store' / 'DataStore.ts'), str(typescript)],
                                cwd=ROOT, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['received'], ['--', 4.512345, '--', '--'])
        self.assertEqual(output['late'], ['--', '--'])
        self.assertEqual(output['missing'], ['--'])
        self.assertEqual(output['original']['unit'], 'g/s')
        self.assertEqual(output['original']['timestamp'], 1000)
        self.assertEqual(output['original']['value'], 4.512345)


if __name__ == '__main__':
    unittest.main()
