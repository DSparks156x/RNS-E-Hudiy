const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

// Run the same pure helpers used by React, without a browser or a second implementation.
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, filename);
const model = require('../src/components/dataLogs/model.ts');
const { eventTime, tracePath } = require('../src/components/dataLogs/reviewMath.ts');

test('catalog search reaches canonical IDs, system names and functional groups', () => {
  const value = { id: 'transmission.clutch1.actual_pressure', label: 'Actual pressure clutch 1', unit: 'bar', type: 'number', providers: [] };
  assert.equal(model.catalogMatches(value, ' TRANSMISSION.CLUTCH1 '), true);
  assert.equal(model.catalogMatches(value, 'Clutches'), true);
  assert.equal(model.catalogMatches(value, 'Engine'), false);
  assert.equal(model.valueGroup({ id: 'engine.fuel_temperature' }), 'Temperatures & cooling');
  assert.equal(model.valueGroup({ id: 'engine.timing_retard.cylinder4' }), 'Ignition & knock');
});

test('profile provider policy inherits without erasing explicit per-value requests', () => {
  assert.deepEqual(model.profileRequests({ id: 'test', name: 'Test', allow_estimated: true, allow_unverified: true, values: [
    'engine.rpm', { id: 'engine.maf', allow_estimated: false, source: 'diag', rate_hz: 2 },
  ] }), [
    { id: 'engine.rpm', allow_estimated: true, allow_unverified: true },
    { id: 'engine.maf', allow_estimated: false, allow_unverified: true, source: 'diag', rate_hz: 2 },
  ]);
});

test('DIS offers compatible conversions and keeps reported units open to the source', () => {
  assert.deepEqual(model.unitOptions('mbar'), ['mbar', 'bar', 'kPa', 'psi']);
  assert.deepEqual(model.unitOptions('C'), ['C', 'F']);
  assert.equal(model.unitText('F'), '°F');
  assert.deepEqual(model.unitOptions('V'), ['V']);
  assert.deepEqual(model.unitOptions(null), ['']);
});

test('automatic icons distinguish fluid temperatures, airflow and drivetrain components', () => {
  for (const [id, icon] of [
    ['engine.oil_temperature', 'oil'], ['engine.coolant_temperature', 'cool'],
    ['engine.intake_temperature', 'intake'], ['engine.maf', 'flow'],
    ['engine.boost.actual_absolute', 'boost'], ['transmission.fluid_temperature', 'gear'],
    ['awd.oil_temperature', 'awd'], ['transmission.clutch1.actual_pressure', 'clutch'],
    ['engine.fuel_rail.actual', 'pressure'], ['engine.ignition_timing', 'spark'],
  ]) assert.equal(model.iconFor(id), icon, id);
});

const sample = (time, value = 1, extra = {}) => ({ id: 'engine.rpm', timestamp: time, event_at: time, status: 'ok', value, unit: 'rpm', ...extra });
test('expiration uses event time and preserves the earlier healthy interval', () => {
  const rows = [sample(0), sample(.5, 2), sample(.5, null, { status: 'stale', received_at: 2, event_at: 2 }), sample(2.5, 3)];
  assert.equal(eventTime(rows[2]), 2);
  const path = tracePath(rows, 'rpm', 0, 3, t => t, n => n);
  assert.match(path, /M0\.00 1\.00l0\.01 0 L0\.50 2\.00/);
  assert.match(path, /M2\.50 3\.00/);
  assert.equal((path.match(/M/g) || []).length, 2);
});

test('missing acquisitions and reported unit changes split graph segments', () => {
  const rows = [sample(0), sample(.5), sample(1), sample(8), sample(8.5), sample(9, 1, { unit: '%' }), sample(9.5)];
  const path = tracePath(rows, 'rpm', 0, 10, t => t, n => n);
  assert.equal((path.match(/M/g) || []).length, 3);
  assert.equal(path.includes('9.00'), false);
  assert.match(path, /M9\.50/);
});

test('null, stale and non-finite samples cannot become numeric graph points', () => {
  const rows = [sample(0, null), sample(1, NaN), sample(2, 100, { status: 'stale' })];
  assert.equal(tracePath(rows, 'rpm', 0, 3, t => t, n => n), '');
});
