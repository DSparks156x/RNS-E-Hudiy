const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

function harness() {
  const slots = [], requests = [];
  let cursor = 0;
  const react = {
    useState(initial) { const index = cursor++; slots[index] ||= { value: initial }; return [slots[index].value, value => { slots[index].value = value; }]; },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useCallback(callback) { const index = cursor++; return slots[index] ||= callback; },
    useEffect() { cursor++; },
  };
  const compiled = ts.transpileModule(fs.readFileSync(require.resolve('../src/hooks/useDataLogs.ts'), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, Error, URLSearchParams,
    fetch: path => new Promise(resolve => requests.push({ path, resolve: (body, ok = true) => resolve({ ok, status: ok ? 200 : 503, json: async () => body }) })),
    require: name => { if (name !== 'react') throw new Error(`Unexpected dependency ${name}`); return react; },
  });
  return { requests, render() { cursor = 0; return exports.useDataLogs(null, false); } };
}

test('superseded review errors cannot end a newer request or display an obsolete failure', async () => {
  const h = harness(), hook = h.render();
  const old = hook.review('old-session'), current = hook.review('current-session');
  assert.equal(h.render().pending, true);
  h.requests[0].resolve({ error: 'Old failure' }, false);
  assert.equal(await old, null);
  assert.equal(h.render().pending, true);
  assert.equal(h.render().error, '');
  h.requests[1].resolve({ session: { id: 'current-session' }, samples: [] });
  assert.equal((await current).session.id, 'current-session');
  assert.equal(h.render().pending, false);
  assert.equal(h.render().error, '');
});

test('a late obsolete failure preserves the error from the latest review', async () => {
  const h = harness(), hook = h.render();
  const old = hook.review('old-session'), current = hook.review('current-session');
  h.requests[1].resolve({ error: 'Current failure' }, false);
  assert.equal(await current, null);
  h.requests[0].resolve({ error: 'Old failure' }, false);
  assert.equal(await old, null);
  assert.equal(h.render().error, 'Current failure');
  assert.equal(h.render().pending, false);
});

test('a superseded successful review cannot replace the requested session', async () => {
  const h = harness(), hook = h.render();
  const old = hook.review('old-session'), current = hook.review('current-session');
  h.requests[1].resolve({ session: { id: 'current-session' }, samples: [] });
  assert.equal((await current).session.id, 'current-session');
  h.requests[0].resolve({ session: { id: 'old-session' }, samples: [] });
  assert.equal(await old, null);
});
