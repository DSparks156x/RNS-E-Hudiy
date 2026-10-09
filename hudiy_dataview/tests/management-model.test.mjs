import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const source = await readFile(new URL('../src/managementModel.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { applyEdits, changedCount, displayValue, fieldsFor, filesPortalUrl, parseSetting, managementRequest } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('editing installed settings preserves unknown keys, primitive types and original snapshot', () => {
  const original = { display: { enabled: true, speed: 80, label: 'daily', extra: ['custom', null] }, future: { untouched: 'retain' } };
  const fields = fieldsFor(original, { schema: { 'display.speed': { integer: true, min: 0, max: 100 } } });
  const next = applyEdits(original, fields, { 'display.enabled': 'false', 'display.speed': '90', 'display.label': 'new', 'display.extra': '["branch-specific",null]' });
  assert.deepEqual(next, { display: { enabled: false, speed: 90, label: 'new', extra: ['branch-specific', null] }, future: { untouched: 'retain' } });
  assert.equal(original.display.speed, 80);
  assert.equal(changedCount(fields, { 'display.enabled': 'true', 'display.speed': '90' }), 1);
});

test('JSON-value command fields quote strings and permit explicit null rather than losing type', () => {
  const meta = { type: 'json-value' };
  assert.equal(displayValue('KEY_ENTER', meta), '"KEY_ENTER"');
  assert.equal(parseSetting('"KEY_ENTER"', 'KEY_ENTER', meta), 'KEY_ENTER');
  assert.equal(parseSetting('null', 'KEY_ENTER', meta), null);
  assert.throws(() => parseSetting('KEY_ENTER', 'KEY_ENTER', meta), /valid JSON/);
});

test('branch-specific keys containing dots and prototype names remain literal keys', () => {
  const original = JSON.parse('{"custom.name":3,"custom":{"name":4},"constructor":"keep","__proto__":{"safe":true}}');
  const fields = fieldsFor(original, {});
  const dotted = fields.find(field => field.keys.length === 1 && field.path === 'custom.name');
  const next = applyEdits(original, fields, { [dotted.id]: '9', '/custom/name': '11' });
  assert.equal(next['custom.name'], 9);
  assert.equal(next.custom.name, 11);
  assert.equal(next.constructor, 'keep');
  assert.deepEqual(next.__proto__, { safe: true });
  assert.equal({}.safe, undefined);
});

test('invalid values cannot become a writable config document', () => {
  for (const text of ['', 'Infinity', 'NaN']) assert.throws(() => parseSetting(text, 1), /number/);
  assert.throws(() => parseSetting('5.5', 1, { integer: true }), /whole/);
  assert.throws(() => parseSetting('11', 10, { min: 0, max: 10 }), /Maximum/);
  assert.throws(() => parseSetting('{broken', []), /valid JSON/);
  assert.throws(() => parseSetting('{}', []), /array/);
  assert.throws(() => parseSetting('[]', {}), /object/);
  assert.throws(() => parseSetting('{"n":1e999}', {}, { type: 'json' }), /finite/);
});

test('Hudiy documents keep their schema independent of same-named RNSE settings', () => {
  const fields = fieldsFor({ enabled: true, applications: [{ action: 'custom', extra: 1 }] }, { schema: { enabled: { help: 'RNSE only' } } }, false);
  assert.deepEqual(fields[0].metadata, {});
  const next = applyEdits({ enabled: true, applications: [{ action: 'custom', extra: 1 }] }, fields, { enabled: 'false' });
  assert.deepEqual(next.applications, [{ action: 'custom', extra: 1 }]);
});

test('conflict response remains an error instead of an apparent successful save', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 409, json: async () => ({ error: 'Configuration changed on disk; reload before applying.' }) });
  try { await assert.rejects(managementRequest('/configs/rnse', { method: 'PUT' }), error => error.status === 409 && /changed on disk/.test(error.message)); }
  finally { globalThis.fetch = originalFetch; }
});

test('file portal targets the car hostname and DataView port from independent manager', () => {
  assert.equal(filesPortalUrl({ protocol: 'http:', hostname: '192.168.4.1' }), 'http://192.168.4.1:5003/files');
  assert.equal(filesPortalUrl({ protocol: 'http:', hostname: '[::1]' }), 'http://[::1]:5003/files');
});
