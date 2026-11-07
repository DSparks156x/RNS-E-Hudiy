const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, filename);
const { canSummary, chainSummary, flashTargets, formatSetting, sameValues } = require('../src/avsd/avsdModel.ts');

const chain = over => ({ active: 'active', disabled: false, supervisor: { state: 'running', detail: '' }, verdict: 'streaming', stat: {}, encoder_over: 0, ...over });

test('waiting shows what for, though the service is active', () => {
  const summary = chainSummary(chain({ supervisor: { state: 'waiting', detail: 'Teensy on USB' } }));
  assert.equal(summary.text, 'Waiting for Teensy on USB.');
  assert.equal(summary.tone, 'bad');
});

test('not on TV is normal, no frames is not', () => {
  assert.equal(chainSummary(chain({ verdict: 'not_on_tv' })).tone, 'quiet');
  assert.equal(chainSummary(chain({ verdict: 'no_frames' })).tone, 'bad');
  assert.equal(chainSummary(chain()).tone, 'good');
});

test('a switched-off chain says so before anything else', () => {
  assert.equal(chainSummary(chain({ disabled: true, active: 'inactive' })).text, 'Chain is off.');
});

test('CAN wording', () => {
  assert.equal(canSummary({ present: true, up: true, listen_only: true }), 'Ignition off (listen-only)');
  assert.equal(canSummary({ present: true, up: true, listen_only: false }), 'Ready');
  assert.equal(canSummary({ present: false, up: false, listen_only: false }), 'can0 is down');
});

test('values read in their own unit', () => {
  assert.equal(formatSetting({ kind: 'range', unit: 'MB/s', scale: 1000000, decimals: 1 }, 4500000), '4.5 MB/s');
  assert.equal(formatSetting({ kind: 'range', unit: 'dB' }, -9), '-9 dB');
  assert.equal(formatSetting({ kind: 'choice', options: [{ value: 0, label: 'Off' }, { value: 1, label: 'On' }] }, 1), 'On');
});

test('sameValues and flash wording', () => {
  assert.equal(sameValues({ a: 1, b: true }, { a: 1, b: true }), true);
  assert.equal(sameValues({ a: 1 }, { a: 2 }), false);
  assert.equal(flashTargets(['x.bin', 'y.bin'], [{ name: 'x.bin', sector: 96 }, { name: 'y.bin', sector: null }]), 'sector 96, y.bin');
});
