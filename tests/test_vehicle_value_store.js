// Verify acquisition freshness at the consumer boundary, without a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const projectRequire = createRequire(path.resolve(__dirname, '../hudiy_dataview/package.json'));
const ts = projectRequire('typescript');
const source = fs.readFileSync(path.resolve(__dirname, '../hudiy_dataview/src/store/DataStore.ts'), 'utf8');
const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
}).outputText;
const exportsObject = {};
vm.runInNewContext(compiled, { exports: exportsObject, performance: { now: () => 0 } });
const store = exportsObject.DataStore;
const received = [];
store.subscribeValue('value:engine.rpm', 0, value => received.push(value));
assert.equal(received.at(-1), '--');
const sample = {
    version: 1, id: 'engine.rpm', value: 2000, unit: 'rpm', status: 'ok',
    timestamp: 123, age_ms: 200, max_age_ms: 1000, sample_sequence: 1,
    source: { id: 'ican:35B:rpm', kind: 'ican' },
    quality: { valid: true, fresh: true, verified: true, estimated: false, reason: null },
};
store.updateValues([sample], 0);
assert.equal(received.at(-1), 2000);
store.expireValues(799);
assert.equal(received.at(-1), 2000);
store.expireValues(801);
assert.equal(received.at(-1), '--');
assert.equal(store.getValue('engine.rpm').status, 'stale');
assert.equal(store.getValue('engine.rpm').timestamp, 123);
assert.equal(store.getValue('engine.rpm').quality.fresh, false);
store.updateValues([{ ...sample, timestamp: 124, age_ms: 0, sample_sequence: 2 }], 900);
assert.equal(received.at(-1), 2000);
store.updateValues([{ ...sample, status: 'invalid', value: null }], 950);
assert.equal(received.at(-1), '--');
store.updateValues([sample], 1000);
store.clearValues();
assert.equal(received.at(-1), '--');
assert.equal(store.getValue('engine.rpm'), undefined);
// Real raw diagnostic groups still address fields 5..8 independently.
const extended = [];
store.subscribeValue('1:11', 7, value => extended.push(value));
store.update([{ module: 1, group: 11, data: Array.from({ length: 8 }, (_, i) => ({ value: i + 1, unit: '' })) }]);
assert.equal(extended.at(-1), 8);
console.log('Vehicle value store freshness and extended-field checks passed');
