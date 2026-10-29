const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, filename);
const { adcField, encodeAdcField, decodeAdcField, validateClampWindow, suggestedVcoRange, ReleasedDraft, adcWriteMessage, adcDisplayByte, adcCommandsBusy, ADC_WRITABLE, ADC_WRITABLE_NOW, ADC_FIELDS, ADC_FIRMWARE } = require('../src/rnseAdcModel.ts');
const bytes = map => register => map[register] ?? null;

test('every control decodes the firmware bytes to its firmware value', () => {
  for (const field of ADC_FIELDS) assert.equal(decodeAdcField(field, bytes(ADC_FIRMWARE)), field.firmware, field.id);
});

test('line length packs 12 bits across 01 and 02, first byte first', () => {
  assert.deepEqual(Object.entries(encodeAdcField(adcField('lineLength'), 1014)), [['01', 0x3f], ['02', 0x50]]);
  assert.throws(() => encodeAdcField(adcField('lineLength'), 223), RangeError);
});

test('shared registers keep the other field and clear unowned bits', () => {
  assert.deepEqual(encodeAdcField(adcField('chargePump'), 5, bytes({ '03': 0x77 })), { '03': 0x68 });
  assert.deepEqual(encodeAdcField(adcField('vcoRange'), 1, bytes({ '03': 0x30 })), { '03': 0x70 });
  assert.throws(() => encodeAdcField(adcField('vcoRange'), 3), RangeError);
  assert.deepEqual(encodeAdcField(adcField('driveData'), 2, bytes({ '28': 0xf0 })), { '28': 0xb0 });
  assert.deepEqual(encodeAdcField(adcField('loopUpdate'), 1, bytes({ '23': 0x02 })), { '23': 0x03 });
  assert.throws(() => encodeAdcField(adcField('driveClock'), 1), RangeError);
});

test('black targets and manual offsets are 9-bit pairs', () => {
  assert.deepEqual(Object.entries(encodeAdcField(adcField('targetR'), -16)), [['1D', 1], ['1E', 0xf0]]);
  assert.equal(decodeAdcField(adcField('targetR'), bytes({ '1D': 1, '1E': 0xf0 })), -16);
  assert.deepEqual(encodeAdcField(adcField('offsetG'), 255), { '19': 0, '1A': 0 });
  assert.deepEqual(encodeAdcField(adcField('offsetG'), -256), { '19': 1, '1A': 0xff });
  assert.equal(decodeAdcField(adcField('offsetG'), bytes({ '19': 0, '1A': 0xff })), 0);
});

test('enum registers only send the allowed bytes', () => {
  assert.deepEqual(encodeAdcField(adcField('clampSlow'), 1), { '24': 0x78 });
  assert.deepEqual(encodeAdcField(adcField('syncSource'), 0), { '0E': 0x25 });
  assert.equal(decodeAdcField(adcField('clampSlow'), bytes({ '24': 0x18 })), null);
});

test('writable sets follow the stock BC range and the widening patch', () => {
  for (const r of ['00', '0B', '0C', '0D', '0F', '14', '15', '16', '29']) assert.equal(ADC_WRITABLE.has(r), false, r);
  for (const r of ['01', '02', '03', '0E', '19', '1A', '1B']) assert.equal(ADC_WRITABLE_NOW.has(r), true, r);
  for (const r of ['17', '1C', '23', '24', '28']) assert.deepEqual([ADC_WRITABLE.has(r), ADC_WRITABLE_NOW.has(r)], [true, false], r);
});

test('clamp window and VCO suggestion', () => {
  assert.equal(validateClampWindow(22, 47), true);
  assert.equal(validateClampWindow(24, 80), true);
  assert.equal(validateClampWindow(25, 80), false);
  assert.equal(validateClampWindow(0, 40), false);
  assert.equal(suggestedVcoRange(1014), 0);
  assert.equal(suggestedVcoRange(1100), 1);
});

test('slider draft commits once on release and cancellation never writes', () => {
  const draft = new ReleasedDraft(12);
  draft.change(18); draft.change(20);
  assert.equal(draft.release(), 20);
  assert.equal(draft.release(), null);
  draft.change(24);
  assert.equal(draft.cancel(), 20);
  assert.equal(draft.release(), null);
});

test('write status distinguishes queueing, readback failure and unpatched rejection', () => {
  const queued = { writes: { '09': { requested: 90, readback: null, status: null, state: 'queued' } } };
  assert.match(adcWriteMessage(queued, '09'), /waiting to send/);
  assert.equal(adcDisplayByte(queued, '09'), 90);
  assert.match(adcWriteMessage({ writes: { '08': { requested: 90, readback: 91, status: 0, state: 'ok' } } }, '08'), /0x5B/);
  assert.match(adcWriteMessage({ writes: { '23': { requested: 1, readback: 0, status: 0xee, state: 'rejected' } } }, '23'), /needs BC widening/);
  assert.doesNotMatch(adcWriteMessage({ writes: { '08': { requested: 1, readback: 0, status: 0xee, state: 'rejected' } } }, '08'), /widening/);
  assert.match(adcWriteMessage({ writes: { '08': { requested: 1, readback: 0, status: 0xfc, state: 'readback_failed' } } }, '08'), /readback failed/);
});

test('all ADC controls wait for the whole serialized command to finish', () => {
  assert.equal(adcCommandsBusy({ busy: true }), true);
  assert.equal(adcCommandsBusy({ writes: { '08': { state: 'pending' }, '09': { state: 'queued' } } }), true);
  assert.equal(adcCommandsBusy({ dump: { state: 'receiving' } }), true);
  assert.equal(adcCommandsBusy({ writes: { '08': { state: 'timeout' }, '09': { state: 'not_sent' } }, dump: { state: 'complete' } }), false);
});

test('unconfirmed slider writes stay at their requested value until a reply resolves them', () => {
  const snapshot = { registers: [{ register: '08', value: 112, baseline: 112 }], writes: { '08': { requested: 95, readback: null, status: null, state: 'pending' } } };
  assert.equal(adcDisplayByte(snapshot, '08'), 95);
  snapshot.writes['08'].state = 'timeout';
  assert.equal(adcDisplayByte(snapshot, '08'), 95);
  snapshot.writes['08'].state = 'ok'; snapshot.writes['08'].readback = 97;
  snapshot.registers[0].value = 97;
  assert.equal(adcDisplayByte(snapshot, '08'), 97);
  snapshot.writes['08'].state = 'queue_failed'; snapshot.registers[0].value = 112;
  assert.equal(adcDisplayByte(snapshot, '08'), 112);
});
