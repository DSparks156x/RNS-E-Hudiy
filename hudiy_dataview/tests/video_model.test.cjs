const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, filename);
const { LatestVideoWriter, VIDEO_DEFAULTS, validateVideoSettings, sameVideoSettings } = require('../src/videoModel.ts');
const tick = () => new Promise(resolve => setImmediate(resolve));

test('video values reject non-finite values and each channel outside its actual slider range', () => {
  assert.doesNotThrow(() => validateVideoSettings(VIDEO_DEFAULTS));
  assert.doesNotThrow(() => validateVideoSettings({ gamma: 2, contrast: .5, black_point: .1, gain_r: 1.5, gain_g: .5, gain_b: 1 }));
  for (const [key, value] of [['gamma', .49], ['contrast', 1.51], ['black_point', -.001], ['black_point', .101], ['gain_r', NaN], ['gain_g', Infinity], ['gain_b', 0]]) {
    assert.throws(() => validateVideoSettings({ ...VIDEO_DEFAULTS, [key]: value }), /must be between/);
  }
});

test('matching applied values includes all six channels', () => {
  assert.equal(sameVideoSettings(VIDEO_DEFAULTS, { ...VIDEO_DEFAULTS }), true);
  for (const key of Object.keys(VIDEO_DEFAULTS)) assert.equal(sameVideoSettings(VIDEO_DEFAULTS, { ...VIDEO_DEFAULTS, [key]: VIDEO_DEFAULTS[key] + .01 }), false);
});

test('dragging while apply is pending writes only the newest waiting value, serially', async () => {
  const requests = [], completed = [];
  const queue = new LatestVideoWriter(value => new Promise(resolve => requests.push({ value, resolve })), (ticket, result) => completed.push({ ticket, result }));
  queue.submit({ gamma: 1.1 }, 1);
  queue.submit({ gamma: 1.2 }, 2);
  queue.submit({ gamma: 1.3 }, 3);
  assert.equal(requests.length, 1);
  requests[0].resolve('first applied'); await tick();
  assert.equal(requests.length, 2);
  assert.deepEqual(requests[1].value, { gamma: 1.3 });
  requests[1].resolve('latest applied'); await tick();
  assert.deepEqual(completed, [{ ticket: 1, result: 'first applied' }, { ticket: 3, result: 'latest applied' }]);
  queue.close();
});

test('a failed compositor apply does not prevent a newer adjustment from running', async () => {
  const requests = [], completed = [];
  const queue = new LatestVideoWriter(value => new Promise((resolve, reject) => requests.push({ value, resolve, reject })), (ticket, result, error) => completed.push({ ticket, result, error }));
  queue.submit('old output', 1); queue.submit('new output', 2);
  const error = new Error('Gamma control denied'); requests[0].reject(error); await tick();
  assert.equal(requests[1].value, 'new output');
  requests[1].resolve('new applied'); await tick();
  assert.equal(completed[0].error, error);
  assert.equal(completed[1].result, 'new applied');
  queue.close();
});

test('leaving the panel cancels waiting writes and ignores in-flight completion', async () => {
  const requests = [], completed = [];
  const queue = new LatestVideoWriter(value => new Promise(resolve => requests.push({ value, resolve })), (...result) => completed.push(result));
  queue.submit('first', 1); queue.submit('waiting', 2); queue.close(); queue.submit('after close', 3);
  requests[0].resolve('late result'); await tick();
  assert.equal(requests.length, 1);
  assert.deepEqual(completed, []);
});
