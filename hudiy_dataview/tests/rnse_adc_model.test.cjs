const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, filename);
const { encodeAdcControl, decodeAdcControl, encodeVco, validateClampWindow, ReleasedDraft, adcWriteMessage, adcDisplayByte, adcIdentificationMessage, adcCommandsBusy, ADC_WRITABLE } = require('../src/rnseAdcModel.ts');

test('register encodings round-trip packed offsets and phase and preserve RGB bytes', () => {
  assert.deepEqual(encodeAdcControl('offsetR', 127), { register: '0B', byte: 254 });
  assert.equal(decodeAdcControl('offsetR', 254), 127);
  assert.throws(() => encodeAdcControl('offsetR', 128), RangeError);
  assert.deepEqual(encodeAdcControl('phase', 31), { register: '04', byte: 248 });
  assert.equal(decodeAdcControl('phase', 248), 31);
  assert.deepEqual(encodeAdcControl('gainG', 255), { register: '09', byte: 255 });
});

test('PLL divider registers are locked out from writes and presets', () => {
  assert.equal(ADC_WRITABLE.has('01'), false);
  assert.equal(ADC_WRITABLE.has('02'), false);
  assert.equal(ADC_WRITABLE.has('03'), true);
});

test('VCO range and charge-pump share a byte without losing either field', () => {
  assert.equal(encodeVco(1, 3), 0x58);
  assert.equal(decodeAdcControl('vcoRange', 0x58), 1);
  assert.equal(decodeAdcControl('vcoCurrent', 0x58), 3);
  assert.throws(() => encodeVco(4, 0), RangeError);
});

test('clamp settings must remain strictly within the 110-clock back porch', () => {
  assert.equal(validateClampWindow(22, 47), true);
  assert.equal(validateClampWindow(63, 47), false);
  assert.equal(validateClampWindow(256, 0), false);
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

test('write status distinguishes queueing from an acknowledged readback', () => {
  const queued = { writes: { '09': { requested: 90, readback: null, status: null, state: 'queued' } } };
  assert.match(adcWriteMessage(queued, '09'), /waiting to send/);
  assert.equal(adcDisplayByte(queued, '09'), 90);
  assert.match(adcWriteMessage({ writes: { '08': { requested: 90, readback: null, status: null, state: 'queued_unconfirmed' } } }, '08'), /unconfirmed/);
  assert.match(adcWriteMessage({ writes: { '08': { requested: 90, readback: 91, status: 0, state: 'ok' } } }, '08'), /0x5B/);
});

test('all ADC controls wait for the whole serialized command to finish', () => {
  assert.equal(adcCommandsBusy({ busy: true }), true);
  assert.equal(adcCommandsBusy({ writes: { '08': { state: 'pending' }, '09': { state: 'queued' } } }), true);
  assert.equal(adcCommandsBusy({ dump: { state: 'receiving' } }), true);
  assert.equal(adcCommandsBusy({ identification: { state: 'restoring' } }), true);
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

test('chip result requires a successful probe reply and reports restore confirmation', () => {
  assert.equal(adcIdentificationMessage({ state: 'pending' }), 'Probe sent · waiting for readback');
  assert.equal(adcIdentificationMessage({ state: 'unconfirmed', chip: null }), 'Unconfirmed (no reply)');
  assert.equal(adcIdentificationMessage({ state: 'error', chip: null, error: 'Probe failed' }), 'Probe failed');
  assert.match(adcIdentificationMessage({ state: 'identified', chip: 'AD9985', probe: { readback: 4 }, restore: { state: 'ok' }, restore_confirmed: true }), /AD9985.*read 0x04.*restore confirmed/);
  assert.match(adcIdentificationMessage({ state: 'error', chip: 'AD9985', probe: { readback: 4 }, restore: { state: 'timeout' }, restore_confirmed: false, error: 'Restore timed out' }), /AD9985.*read 0x04.*restore timeout.*Restore timed out/);
});
