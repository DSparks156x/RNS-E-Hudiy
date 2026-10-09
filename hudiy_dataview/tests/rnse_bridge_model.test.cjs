const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, filename);
const { ReleasedValue, lcdLabel, sourceLabel } = require('../src/rnseBridgeModel.ts');
test('slider movement produces no commits until release and release/keyup/blur commit once', () => {
  const slider = new ReleasedValue(5);
  slider.change(6); slider.change(8); slider.change(10);
  assert.equal(slider.release(), 10);
  assert.equal(slider.release(), null);
  assert.equal(slider.release(), null);
});
test('cancelled drag restores the last committed value without requesting a write', () => {
  const slider = new ReleasedValue(4); slider.change(8);
  assert.equal(slider.cancel(), 4); assert.equal(slider.release(), null);
});
test('updated automatic state becomes the next slider baseline', () => {
  const slider = new ReleasedValue(10); slider.change(5); assert.equal(slider.release(), 5);
  slider.sync(6); slider.change(6); assert.equal(slider.release(), null);
  slider.change(7); assert.equal(slider.release(), 7);
});
test('LCD labels show follow-cluster and the firmware minimum truthfully', () => {
  assert.equal(lcdLabel(0), 'Follow cluster');
  for (let value = 1; value <= 5; value++) assert.equal(lcdLabel(value), `${value} · effective 6`);
  assert.equal(lcdLabel(6), '6 / 100'); assert.equal(lcdLabel(100), '100 / 100');
  assert.equal(sourceLabel(0), 'Hudiy'); assert.equal(sourceLabel(1), 'CarPlay'); assert.equal(sourceLabel(2), 'Android Auto');
});
