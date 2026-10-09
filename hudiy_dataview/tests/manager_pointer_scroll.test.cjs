const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, filename);
const { installManagerPointerScroll } = require('../src/managerPointerScroll.ts');

class Surface {
  constructor(parent = null, excluded = false) {
    this.parentElement = parent; this.excluded = excluded; this.listeners = new Map(); this.captured = new Set();
    this.style = { overflowY: 'visible', overflowX: 'visible' };
    this.clientHeight = this.scrollHeight = this.clientWidth = this.scrollWidth = 100;
    this.scrollTop = this.scrollLeft = 0;
  }
  closest(selector) { return selector === '*' ? this : this.excluded ? this : null; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  removeEventListener(name) { this.listeners.delete(name); }
  setPointerCapture(id) { this.captured.add(id); }
  hasPointerCapture(id) { return this.captured.has(id); }
  releasePointerCapture(id) { this.captured.delete(id); }
}
global.Element = Surface;
global.getComputedStyle = node => node.style;
function fixture() {
  const root = new Surface(), pane = new Surface(root), button = new Surface(pane);
  pane.scrollHeight = 500; pane.style.overflowY = 'auto';
  const close = installManagerPointerScroll(root);
  const send = (type, overrides = {}) => {
    const event = { target: button, pointerType: 'mouse', pointerId: 1, button: 0, isPrimary: true, clientX: 100, clientY: 100, detail: 1,
      prevented: false, stopped: false, preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; }, ...overrides };
    root.listeners.get(type)?.(event); return event;
  };
  return { root, pane, button, close, send };
}
test('mouse-like touch drags scroll from the original pane and cancel the resulting button click', () => {
  const { root, pane, send, close } = fixture();
  send('pointerdown');
  assert.equal(send('pointermove', { clientY: 50, target: root }).prevented, true);
  assert.equal(pane.scrollTop, 50);
  assert.equal(root.hasPointerCapture(1), true);
  send('pointerup', { clientY: 50 });
  const click = send('click'); assert.equal(click.prevented, true); assert.equal(click.stopped, true);
  assert.equal(root.hasPointerCapture(1), false); close();
});
test('ordinary taps, small finger jitter, and keyboard activation retain their action', () => {
  const { pane, send, close } = fixture();
  send('pointerdown'); send('pointermove', { clientY: 96 }); send('pointerup');
  assert.equal(pane.scrollTop, 0); assert.equal(send('click').prevented, false);
  send('pointerdown'); send('pointermove', { clientY: 50 }); send('pointerup');
  assert.equal(send('click', { detail: 0 }).prevented, false);
  send('pointerdown'); send('pointerup'); assert.equal(send('click').prevented, false); close();
});
test('native touch and excluded slider, editor, and keyboard surfaces keep native handling', () => {
  const { pane, send, close } = fixture();
  send('pointerdown', { pointerType: 'touch' }); assert.equal(send('pointermove', { clientY: 50, pointerType: 'touch' }).prevented, false);
  const input = new Surface(pane, true);
  send('pointerdown', { target: input }); assert.equal(send('pointermove', { clientY: 50, target: input }).prevented, false);
  assert.equal(pane.scrollTop, 0); close();
});
test('horizontal section lists scroll without changing the vertical pane', () => {
  const { pane, send, close } = fixture();
  pane.scrollWidth = 600; pane.style.overflowX = 'auto';
  send('pointerdown'); send('pointermove', { clientX: 50 }); send('pointercancel');
  assert.equal(pane.scrollLeft, 50); assert.equal(pane.scrollTop, 0); close();
});
test('unmount releases a drag capture and removes all handlers', () => {
  const { root, send, close } = fixture();
  send('pointerdown'); send('pointermove', { clientY: 50 }); close();
  assert.equal(root.captured.size, 0); assert.equal(root.listeners.size, 0);
});
