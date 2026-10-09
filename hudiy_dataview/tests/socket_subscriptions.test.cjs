const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

// Execute the actual hook with deterministic effects and a fake transport.
// This catches subscription behavior without tying tests to source spelling.
function harness() {
  const slots = [], pendingEffects = [], intervals = new Map(), handlers = new Map(), emitted = [];
  let cursor = 0, intervalId = 0;
  const socket = {
    connected: false,
    emit: (event, payload) => emitted.push({ event, payload: JSON.parse(JSON.stringify(payload)) }),
    on: (event, callback) => handlers.set(event, callback),
    disconnect: () => { socket.connected = false; handlers.get('disconnect')?.(); },
  };
  const react = {
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) { const index = cursor++; slots[index] ||= { value: initial }; return [slots[index].value, value => { slots[index].value = value; }]; },
    useEffect(callback, dependencies) {
      const index = cursor++, previous = slots[index];
      if (!previous || dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))) {
        pendingEffects.push(() => { previous?.cleanup?.(); slots[index] = { dependencies, cleanup: callback() }; });
      }
    },
  };
  const compiled = ts.transpileModule(fs.readFileSync(require.resolve('../src/hooks/useSocket.ts'), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, console: { log() {}, warn() {}, error() {} },
    window: { setInterval(callback) { intervals.set(++intervalId, callback); return intervalId; }, clearInterval(id) { intervals.delete(id); } },
    require(name) {
      if (name === 'react') return react;
      if (name === 'socket.io-client') return { io: () => socket };
      if (name === '../store/DataStore') return { DataStore: { clearValues() {}, update() {}, updateValues() {}, expireValues() {} } };
      if (name === '../store/mockValues') return { mockValues: () => [] };
      throw new Error(`Unexpected hook dependency ${name}`);
    },
  });
  return {
    exports, emitted,
    render(tab, values = []) { cursor = 0; exports.useSocket(tab, values); while (pendingEffects.length) pendingEffects.shift()(); },
    connect() { socket.connected = true; handlers.get('connect')(); },
    status(mock_mode) { handlers.get('status')({ mock_mode }); },
    renew() { for (const callback of intervals.values()) callback(); },
    latestValues() { return emitted.filter(message => message.event === 'sync_values').at(-1)?.payload.values; },
    close() { for (const slot of slots) slot?.cleanup?.(); },
  };
}

test('live tabs subscribe to canonical values and renew the selected tab', () => {
  const h = harness();
  h.render('transmission'); h.connect();
  assert.deepEqual(h.latestValues(), JSON.parse(JSON.stringify(h.exports.TRANSMISSION_VALUES)));
  assert.equal(h.emitted.some(message => message.event === 'toggle_group'), false);
  h.render('awd'); h.renew();
  assert.deepEqual(h.latestValues(), JSON.parse(JSON.stringify(h.exports.AWD_VALUES)));
  assert.ok(h.latestValues().some(value => value.id === 'awd.estimated_torque' && value.allow_estimated));
  h.close();
});

test('mock tabs use diagnostic groups, while Data & Logs keeps named-value requests', () => {
  const h = harness();
  h.render('engine'); h.connect(); h.status(true);
  assert.deepEqual(h.latestValues(), []);
  const additions = h.emitted.filter(message => message.event === 'toggle_group' && message.payload.action === 'add');
  assert.deepEqual(additions.map(message => message.payload.group).sort((a, b) => a - b), [3, 20, 102, 106, 115]);
  const requests = [{ id: 'engine.rpm', source: 'ican', rate_hz: 2 }];
  h.render('data_logs', requests); h.renew();
  assert.deepEqual(h.latestValues(), requests);
  assert.equal(h.emitted.filter(message => message.event === 'toggle_group' && message.payload.action === 'remove').length, 5);
  h.close();
});

test('reconnect and profile edits restore the current Data & Logs subscription', () => {
  const h = harness();
  h.render('data_logs', ['engine.rpm']); h.connect();
  h.render('data_logs', ['engine.maf']);
  assert.deepEqual(h.latestValues(), ['engine.maf']);
  h.connect();
  assert.deepEqual(h.latestValues(), ['engine.maf']);
  h.render('diagnostics');
  assert.deepEqual(h.latestValues(), []);
  h.close();
});
