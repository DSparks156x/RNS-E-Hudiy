const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

function createStore() {
  const source = fs.readFileSync(require.resolve('../src/store/DataStore.ts'), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, performance: { now: () => 0 } });
  return exports.DataStore;
}
const sample = {
  id: 'engine.rpm', status: 'ok', value: 900, age_ms: 100, max_age_ms: 1000,
  quality: { valid: true, fresh: true, verified: true, estimated: false },
};

test('an expired snapshot never briefly publishes a healthy value', () => {
  const store = createStore(), changes = [];
  store.subscribeValue('value:engine.rpm', 0, value => changes.push(value));
  changes.length = 0;
  store.updateValues([{ ...sample, age_ms: 1001 }], 0);
  assert.deepEqual(changes, ['--']);
  assert.equal(store.getValue(sample.id).status, 'stale');
});

test('non-finite values are invalid and a valid sample recovers normally', () => {
  const store = createStore(), changes = [];
  store.subscribeValue('value:engine.rpm', 0, value => changes.push(value));
  for (const value of [NaN, Infinity, -Infinity]) {
    store.updateValues([{ ...sample, value }], 0);
    assert.equal(changes.at(-1), '--');
    assert.equal(store.getValue(sample.id).status, 'invalid');
  }
  store.updateValues([sample], 10);
  assert.equal(changes.at(-1), 900);
});

test('unbounded ages and text status values retain their original meaning', () => {
  const store = createStore(), changes = [];
  store.subscribeValue('value:engine.rpm', 0, value => changes.push(value));
  store.updateValues([{ ...sample, value: '00100100', max_age_ms: null }], 0);
  store.expireValues(1e9);
  assert.equal(changes.at(-1), '00100100');
  assert.equal(store.getValue(sample.id).status, 'ok');
});

test('literal placeholder text still becomes stale when acquisitions stop', () => {
  const store = createStore();
  store.updateValues([{ ...sample, value: '--' }], 0);
  store.expireValues(1000);
  assert.equal(store.getValue(sample.id).status, 'stale');
});
