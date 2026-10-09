import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const source = await readFile(new URL('../src/managementModel.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { applyEdits, changedCount, displayValue, fieldsFor, filesPortalUrl, parseSetting, managementRequest, formatHexPayload } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('TV payloads display whole bytes and save compact uppercase hex without accepting malformed data', () => {
  const meta = { type: 'hex-payload' };
  assert.equal(displayValue('0912abcdef202020', meta), '09 12 AB CD EF 20 20 20');
  assert.equal(parseSetting('09 12 ab cd ef 20 20 20', '', meta), '0912ABCDEF202020');
  assert.equal(parseSetting('ff', '', meta), 'FF');
  for (const invalid of ['', '0', '0 9', '091', '09 1234', 'GG', '0x09', '09-12', '00'.repeat(9)]) {
    assert.throws(() => parseSetting(invalid, '', meta), /complete hex bytes/);
    assert.equal(formatHexPayload(invalid), invalid, 'invalid input remains editable rather than truncated');
  }
});

test('older TV configs expose the wire default and only persist it when edited', () => {
  const original = { features: { tv_simulation: { enabled: true, custom: 'keep' } } };
  const fields = fieldsFor(original, { schema: { 'features.tv_simulation.payload': { type: 'hex-payload' } } });
  const payload = fields.find(field => field.path === 'features.tv_simulation.payload');
  assert.equal(payload.value, '0912302020202020');
  assert.deepEqual(applyEdits(original, fields, {}), original);
  const next = applyEdits(original, fields, { [payload.id]: 'AB CD EF' });
  assert.deepEqual(next.features.tv_simulation, { enabled: true, custom: 'keep', payload: 'ABCDEF' });
  assert.equal(original.features.tv_simulation.payload, undefined);
});

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

test('new RNS-E controls appear on an older config without changing it on read or unrelated save', () => {
  const original = { interfaces: {}, custom: 'keep', rnse: { auto_brightness: { enabled: true, day_brightness: 8, night_brightness: 2, custom: 9 } } };
  const fields = fieldsFor(original, {});
  assert.equal(fields.find(field => field.path === 'rnse.auto_lcd_brightness.day_brightness').value, 100);
  assert.equal(fields.find(field => field.path === 'rnse.source_label.enabled').value, false);
  assert.equal(original.rnse.auto_lcd_brightness, undefined);
  assert.deepEqual(applyEdits(original, fields, {}), original);
  const next = applyEdits(original, fields, { custom: 'new' });
  assert.deepEqual(next.rnse, original.rnse);
});

test('enabling a new automatic group writes its required levels and preserves other groups', () => {
  const original = { interfaces: {}, rnse: { auto_brightness: { enabled: true, day_brightness: 8, night_brightness: 2, custom: 9 } } };
  const fields = fieldsFor(original, {});
  const next = applyEdits(original, fields, { 'rnse.auto_lcd_brightness.enabled': 'true' });
  assert.deepEqual(next.rnse.auto_lcd_brightness, { enabled: true, day_brightness: 100, night_brightness: 6 });
  assert.deepEqual(next.rnse.auto_brightness, original.rnse.auto_brightness);
  assert.equal(next.rnse.manual_brightness, undefined);
  assert.equal(next.rnse.source_label, undefined);
});

test('a config without any RNS-E section can explicitly enable automation without losing unknown keys', () => {
  const original = { interfaces: {}, custom: ['keep'] };
  const next = applyEdits(original, fieldsFor(original, {}), { 'rnse.auto_brightness.enabled': 'true' });
  assert.deepEqual(next.rnse.auto_brightness, { enabled: true, day_brightness: 10, night_brightness: 5 });
  assert.deepEqual(next.custom, original.custom);
  assert.equal(original.rnse, undefined);
});
