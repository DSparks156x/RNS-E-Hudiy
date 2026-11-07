const { test, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, filename);
const { installHudiyKeyNav } = require('../src/hudiyKeyNav.ts');

/** Just enough DOM: attribute selectors, tag lists, boxes and event logging. */
class Node {
  constructor(tagName, attributes = {}, children = []) {
    this.tagName = tagName; this.attributes = { ...attributes }; this.children = []; this.parentElement = null;
    this.events = []; this.clicks = 0; this.focuses = 0; this.blurs = 0; this.isConnected = true;
    this.overflowY = 'visible'; this.overflowX = 'visible'; this.visibility = 'visible'; this.boxes = 1;
    this.scrollTop = 0; this.scrollLeft = 0; this.scrollHeight = 40; this.clientHeight = 40; this.top = 0; this.bottom = 40;
    this.onClick = null; this.disabled = false; this.textContent = '';
    children.forEach(child => this.append(child));
  }
  append(child) { child.parentElement = this; this.children.push(child); return child; }
  remove(child) { this.children = this.children.filter(item => item !== child); child.isConnected = false; }
  contains(node) { for (; node; node = node.parentElement) if (node === this) return true; return false; }
  hasAttribute(name) { return name in this.attributes; }
  getAttribute(name) { return name in this.attributes ? this.attributes[name] : null; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  getClientRects() { return new Array(this.boxes); }
  getBoundingClientRect() { return { top: this.top - this.scrollOffset(), bottom: this.bottom - this.scrollOffset(), left: 0, right: 10 }; }
  scrollOffset() { let total = 0; for (let parent = this.parentElement; parent; parent = parent.parentElement) total += parent.scrollTop; return total; }
  matches(selector) {
    if (selector === 'details:not([open])') return this.tagName === 'DETAILS' && !this.hasAttribute('open');
    if (selector === '[inert]') return this.hasAttribute('inert');
    if (selector === '[aria-hidden="true"]') return this.attributes['aria-hidden'] === 'true';
    if (selector === '[aria-modal="true"]') return this.attributes['aria-modal'] === 'true';
    if (selector === '[data-key-back]') return this.hasAttribute('data-key-back');
    if (selector === '.tab.active') return this.attributes.class === 'tab active';
    if (selector.startsWith('button, a[href]')) return ['BUTTON', 'SELECT', 'TEXTAREA', 'SUMMARY'].includes(this.tagName) || (this.tagName === 'INPUT' && this.type !== 'file') || this.hasAttribute('data-key-scroll');
    throw new Error(`Unexpected selector ${selector}`);
  }
  closest(selector) { for (let node = this; node; node = node.parentElement) if (node.matches(selector)) return node; return null; }
  querySelectorAll(selector) { const found = []; const walk = node => node.children.forEach(child => { if (child.matches(selector)) found.push(child); walk(child); }); walk(this); return found; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  click() { this.clicks++; this.onClick?.(); }
  focus() { this.focuses++; this.onFocus?.(); }
  blur() { this.blurs++; }
  dispatchEvent(event) { this.events.push(event.type); }
}
class Input extends Node {
  constructor(type, attributes = {}) { super('INPUT', attributes); this.type = type; this.currentValue = '0'; this.min = '0'; this.max = '10'; this.step = '1'; this.readOnly = false; }
  get value() { return this.currentValue; }
  set value(next) { this.currentValue = next; }
}
class Select extends Node {
  constructor(values) { super('SELECT'); this.options = values.map(value => ({ value, disabled: value.startsWith('off') })); this.value = values[0]; }
  get selectedIndex() { return this.options.findIndex(option => option.value === this.value); }
}
const button = (label, attributes) => { const node = new Node('BUTTON', attributes); node.textContent = label; return node; };

let probes, documentBody;
beforeEach(() => {
  probes = [];
  global.HTMLInputElement = Input;
  global.Event = class { constructor(type) { this.type = type; } };
  global.KeyboardEvent = global.Event;
  global.getComputedStyle = node => node;
  const elements = {};
  global.document = {
    body: documentBody = new Node('BODY'),
    querySelectorAll: selector => documentBody.querySelectorAll(selector),
    addEventListener() {}, removeEventListener() {},
    getElementById: id => elements[id] || null,
    createElement: () => ({ set id(value) { elements[value] = this; }, remove() {} }),
    head: { appendChild() {} },
  };
  global.window = { location: { port: '5004' }, addEventListener() {}, removeEventListener() {} };
  global.fetch = async () => ({});
  console.error = message => probes.push(message);
});
const originalConsoleError = console.error;
afterEach(() => { console.error = originalConsoleError; });

function fixture(children, options = {}) {
  const root = documentBody.append(new Node('DIV', {}, children));
  const hudiy = { inputFocus: true, activated: true, ...options.hudiy };
  const close = installHudiyKeyNav({ ...options, root, hudiy });
  return { root, hudiy, close };
}
const settled = () => new Promise(resolve => setTimeout(resolve, 90));
const highlighted = root => root.querySelectorAll('button, a[href]').filter(node => node.hasAttribute('data-key-focus'));

test('install highlights the first control only while Hudiy reports key input', () => {
  const first = button('first'), second = button('second');
  const { root, hudiy } = fixture([first, second]);
  assert.deepEqual(highlighted(root), [first]);
  hudiy.activated = false; hudiy.onActivatedChanged();
  assert.deepEqual(highlighted(root), []);
  hudiy.activated = true; hudiy.onActivatedChanged();
  assert.deepEqual(highlighted(root), [first]);
  assert.equal(second.focuses, 0);
});

test('the knob walks enabled controls and hands off to Hudiy at each end', () => {
  const a = button('a'), off = button('off'), b = button('b');
  off.disabled = true;
  const { root, hudiy } = fixture([a, off, b]);
  assert.equal(hudiy.onMoveToNextControl(), true);
  assert.deepEqual(highlighted(root), [b]);
  assert.equal(hudiy.onMoveToNextControl(), false);
  assert.deepEqual(highlighted(root), [b], 'the highlight is kept for when focus comes back');
  assert.equal(hudiy.onMoveToPreviousControl(), true);
  assert.equal(hudiy.onMoveToPreviousControl(), false);
  assert.deepEqual(highlighted(root), [a]);
});

test('without key focus the knob moves nothing and is not handed to the next scope', () => {
  const a = button('a'), b = button('b');
  const { root, hudiy } = fixture([a, b]);
  hudiy.inputFocus = false;
  assert.equal(hudiy.onMoveToNextControl(), true);
  hudiy.inputFocus = true; hudiy.onInputFocusChanged();
  assert.deepEqual(highlighted(root), [a]);
});

test('inert tabs, hidden boxes, closed details and marked controls are skipped', () => {
  const visible = button('visible'), summary = new Node('SUMMARY'), end = button('end');
  const inner = button('inner'), hidden = button('hidden'), skipped = button('skipped', { 'data-key-skip': '' });
  const inert = button('inert'), collapsed = button('collapsed');
  hidden.boxes = 0;
  const details = new Node('DETAILS', {}, [summary, inner]);
  const slide = new Node('DIV', { inert: '' }, [inert]);
  const { root, hudiy } = fixture([visible, slide, collapsed, details, hidden, skipped, end]);
  collapsed.visibility = 'hidden';
  hudiy.onMoveToNextControl();
  assert.equal(root.querySelectorAll('button, a[href]').find(node => node.hasAttribute('data-key-focus')), summary);
  hudiy.onMoveToNextControl();
  assert.deepEqual(highlighted(root), [end]);
});

test('press clicks buttons and asks a text field to open its keyboard', async () => {
  const action = button('go'), text = new Input('text'), locked = new Input('text'), check = new Input('checkbox');
  locked.readOnly = true;
  const { hudiy } = fixture([action, text, locked, check]);
  hudiy.onTriggered();
  assert.equal(action.clicks, 1);
  assert.equal(action.focuses, 0);
  hudiy.onMoveToNextControl(); hudiy.onTriggered();
  assert.deepEqual(text.events, ['key-activate']);
  assert.equal(text.clicks, 0);
  hudiy.onMoveToNextControl(); hudiy.onTriggered();
  assert.equal(locked.clicks, 1, 'read-only fields open their own keypad on click');
  hudiy.onMoveToNextControl(); hudiy.onTriggered();
  assert.equal(check.clicks, 1);
  await settled();
});

test('moving past a text field never focuses it, so the keyboard stays closed', () => {
  const text = new Input('text'), after = button('after');
  const { hudiy } = fixture([button('before'), text, after]);
  hudiy.onMoveToNextControl(); hudiy.onMoveToNextControl();
  assert.equal(text.focuses, 0);
});

test('a slider edits a draft and sends one release on press', () => {
  const slider = new Input('range');
  const { root, hudiy } = fixture([slider, button('next')]);
  hudiy.onTriggered();
  assert.equal(slider.getAttribute('data-key-focus'), 'edit');
  assert.deepEqual(slider.events, ['keydown']);
  hudiy.onMoveToNextControl(); hudiy.onMoveToNextControl();
  assert.equal(slider.value, '2');
  assert.deepEqual(slider.events, ['keydown', 'input', 'input']);
  hudiy.onTriggered();
  assert.deepEqual(slider.events, ['keydown', 'input', 'input', 'keyup']);
  assert.equal(slider.blurs, 1);
  assert.equal(slider.getAttribute('data-key-focus'), 'true');
  hudiy.onMoveToNextControl();
  assert.equal(root.querySelectorAll('button, a[href]').find(node => node.hasAttribute('data-key-focus')).textContent, 'next');
});

test('RETURN restores a slider before releasing it, so nothing new is sent', () => {
  const slider = new Input('range');
  const { hudiy } = fixture([slider]);
  hudiy.onTriggered(); hudiy.onMoveToNextControl();
  assert.equal(hudiy.onGoBack(), true);
  assert.equal(slider.value, '0');
  assert.deepEqual(slider.events, ['keydown', 'input', 'input', 'keyup']);
});

test('sliders clamp, and only wide sliders speed up on a fast turn', () => {
  const narrow = new Input('range'), wide = new Input('range');
  wide.max = '255';
  const { hudiy } = fixture([narrow, wide]);
  hudiy.onTriggered();
  hudiy.onMoveToPreviousControl();
  assert.equal(narrow.value, '0');
  hudiy.onMoveToNextControl(); hudiy.onMoveToNextControl();
  assert.equal(narrow.value, '2');
  hudiy.onTriggered();
  hudiy.onMoveToNextControl(); hudiy.onTriggered();
  hudiy.onMoveToNextControl(); hudiy.onMoveToNextControl();
  assert.equal(wide.value, '6');
});

test('a dropdown changes on each tick, skips disabled options and stops at its ends', () => {
  const select = new Select(['a', 'off', 'b']);
  const { hudiy } = fixture([select]);
  hudiy.onTriggered();
  hudiy.onMoveToNextControl();
  assert.equal(select.value, 'b');
  hudiy.onMoveToNextControl();
  assert.equal(select.value, 'b');
  assert.deepEqual(select.events, ['change']);
  hudiy.onGoBack();
  assert.equal(select.value, 'a');
});

test('a dialog holds the knob and wraps, then gives the highlight back when it closes', async () => {
  const opener = button('open');
  const cancel = button('cancel', { 'data-key-back': '' }), done = button('done');
  const dialog = new Node('DIV', { 'aria-modal': 'true' }, [cancel, done]);
  const { root, hudiy } = fixture([opener]);
  opener.onClick = () => root.append(dialog);
  hudiy.onTriggered();
  await settled();
  assert.deepEqual(highlighted(root), [cancel]);
  hudiy.onMoveToNextControl();
  assert.deepEqual(highlighted(root), [done]);
  assert.equal(hudiy.onMoveToNextControl(), true);
  assert.deepEqual(highlighted(root), [cancel]);
  assert.equal(hudiy.onMoveToPreviousControl(), true);
  assert.deepEqual(highlighted(root), [done]);
  cancel.onClick = () => root.remove(dialog);
  assert.equal(hudiy.onGoBack(), true);
  assert.equal(cancel.clicks, 1);
  await settled();
  assert.deepEqual(highlighted(root), [opener]);
});

test('a dialog portalled to body still holds the knob and RETURN, so nothing behind it can be pressed', async () => {
  const opener = button('Flash Controller'), behind = button('Clear DTCs');
  const close = button('Back', { 'data-key-back': '' }), start = button('Start');
  const dialog = new Node('DIV', { 'aria-modal': 'true' }, [close, start]);
  const { hudiy } = fixture([opener, behind]);
  opener.onClick = () => documentBody.append(dialog);
  hudiy.onTriggered();
  await settled();
  assert.equal(close.getAttribute('data-key-focus'), 'true');
  assert.equal(hudiy.onMoveToNextControl(), true);
  assert.equal(start.getAttribute('data-key-focus'), 'true');
  hudiy.onTriggered();
  assert.equal(start.clicks, 1);
  assert.equal(behind.clicks, 0);
  assert.equal(behind.hasAttribute('data-key-focus'), false);
  close.onClick = () => documentBody.remove(dialog);
  assert.equal(hudiy.onGoBack(), true);
  assert.equal(close.clicks, 1);
  await settled();
  assert.equal(opener.getAttribute('data-key-focus'), 'true');
});

test('when Hudiy cycles focus back in, the next push starts over instead of handing off again', () => {
  const a = button('a'), b = button('b');
  const { root, hudiy } = fixture([a, b]);
  hudiy.onMoveToNextControl();
  assert.equal(hudiy.onMoveToNextControl(), false);
  hudiy.inputFocus = false; hudiy.onInputFocusChanged();
  hudiy.inputFocus = true; hudiy.onInputFocusChanged();
  assert.equal(hudiy.onMoveToNextControl(), true);
  assert.deepEqual(highlighted(root), [a]);
  assert.equal(hudiy.onMoveToPreviousControl(), false, 'the hand-off works again from the other end');
});

test('coming back by turning the other way carries on from the same control', () => {
  const a = button('a'), b = button('b');
  const { root, hudiy } = fixture([a, b]);
  hudiy.onMoveToNextControl();
  assert.equal(hudiy.onMoveToNextControl(), false);
  assert.equal(hudiy.onMoveToPreviousControl(), true);
  assert.deepEqual(highlighted(root), [a]);
  hudiy.onMoveToNextControl();
  assert.equal(hudiy.onMoveToNextControl(), false, 'a move in between resets the hand-off');
});

test('when the pressed control disappears the highlight stays in its section', async () => {
  const nav = button('nav'), gone = button('module'), back = button('back');
  const list = new Node('DIV', {}, [gone]);
  const slide = new Node('DIV', {}, [list]);
  const { root, hudiy } = fixture([nav, slide]);
  hudiy.onMoveToNextControl();
  assert.deepEqual(highlighted(root), [gone]);
  gone.onClick = () => { slide.remove(list); gone.isConnected = false; slide.append(back); };
  hudiy.onTriggered();
  await settled();
  assert.deepEqual(highlighted(root), [back]);
});

test('a knob tick after the highlighted control vanished lands in the same section', () => {
  const nav = button('nav'), gone = button('gone'), after = button('after');
  const slide = new Node('DIV', {}, [gone, after]);
  const { root, hudiy } = fixture([nav, slide]);
  hudiy.onMoveToNextControl();
  slide.remove(gone);
  assert.equal(hudiy.onMoveToNextControl(), true);
  assert.deepEqual(highlighted(root), [after]);
});

test('RETURN stays in a dialog with no way out, and leaves the app when there is nothing to close', () => {
  const dialog = new Node('DIV', { 'aria-modal': 'true' }, [button('flashing')]);
  const page = fixture([button('page')]);
  assert.equal(page.hudiy.onGoBack(), false);
  const blocked = fixture([dialog]);
  assert.equal(blocked.hudiy.onGoBack(), true);
});

test('RETURN uses the page back button before leaving the app', () => {
  const back = button('back', { 'data-key-back': '' });
  const { hudiy } = fixture([button('a'), back]);
  assert.equal(hudiy.onGoBack(), true);
  assert.equal(back.clicks, 1);
});

test('a text pane scrolls through before the knob moves on', () => {
  const pane = new Node('PRE', { 'data-key-scroll': '' });
  pane.overflowY = 'auto'; pane.clientHeight = 100; pane.scrollHeight = 200;
  const after = button('after');
  const { root, hudiy } = fixture([pane, after]);
  assert.equal(pane.getAttribute('data-key-focus'), 'true');
  assert.equal(hudiy.onMoveToNextControl(), true);
  assert.equal(pane.scrollTop, 70);
  hudiy.onMoveToNextControl();
  assert.equal(pane.scrollTop, 100);
  hudiy.onMoveToNextControl();
  assert.deepEqual(highlighted(root), [after]);
  pane.scrollHeight = pane.clientHeight;
  assert.equal(hudiy.onMoveToPreviousControl(), false, 'a pane with nothing to scroll is not a stop');
});

test('a long gap scrolls in pages so text between controls is not skipped', () => {
  const near = button('near'), far = button('far');
  const pane = new Node('DIV', {}, [near, far]);
  pane.overflowY = 'auto'; pane.top = 0; pane.bottom = 100; pane.clientHeight = 100; pane.scrollHeight = 1000;
  near.top = 0; near.bottom = 40; far.top = 500; far.bottom = 540;
  const { root, hudiy } = fixture([pane]);
  hudiy.onMoveToNextControl();
  assert.equal(pane.scrollTop, 70);
  assert.deepEqual(highlighted(root), [near]);
  for (let i = 0; i < 6; i++) hudiy.onMoveToNextControl();
  assert.deepEqual(highlighted(root), [far]);
  assert.ok(pane.scrollTop >= 448, 'the target ends up inside the pane');
  assert.equal(hudiy.onMoveToNextControl(), true, 'text after the last control can still be read');
  assert.ok(pane.scrollTop > 448);
});

test('long press switches tabs, and is ignored inside a dialog', async () => {
  const seen = [];
  const tab = button('tab', { class: 'tab active' }), other = button('other');
  const { root, hudiy } = fixture([other, tab], { onTab: delta => seen.push(delta), activeTab: '.tab.active' });
  hudiy.onGoRight();
  hudiy.onGoLeft();
  assert.deepEqual(seen, [1, -1]);
  await settled();
  assert.deepEqual(highlighted(root), [tab]);
  root.append(new Node('DIV', { 'aria-modal': 'true' }, [button('x')]));
  hudiy.onGoRight();
  assert.equal(seen.length, 2);
});

test('long press adjusts the control being edited instead of switching tabs', () => {
  const seen = [], slider = new Input('range');
  const { hudiy } = fixture([slider], { onTab: delta => seen.push(delta) });
  hudiy.onTriggered(); hudiy.onGoRight();
  assert.equal(slider.value, '1');
  assert.deepEqual(seen, []);
});

test('a control disabled mid-edit releases on the next settle', () => {
  const slider = new Input('range');
  const { hudiy } = fixture([slider]);
  hudiy.onTriggered();
  slider.disabled = true;
  hudiy.onInputFocusChanged();
  assert.deepEqual(slider.events, ['keydown', 'keyup']);
});

test('the probe reports each callback and cleanup restores the old handlers', () => {
  const previousBack = () => true;
  const { root, hudiy, close } = fixture([button('a')], { hudiy: { onGoBack: previousBack } });
  hudiy.onMoveToNextControl();
  assert.ok(probes.some(line => line.includes('onMoveToNextControl -> ')));
  close();
  assert.equal(hudiy.onGoBack, previousBack);
  assert.equal(hudiy.onMoveToNextControl, undefined);
  assert.deepEqual(highlighted(root), []);
});
