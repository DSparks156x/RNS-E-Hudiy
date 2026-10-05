// Run: node tests/test_native_config_editor.js
// Exercise the actual editor script without a browser or hardware.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'tools/config_editor.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

class Element {
    constructor(tag = 'div') {
        this.tagName = tag.toUpperCase();
        this.children = [];
        this.style = {};
        this.classList = {add() {}, remove() {}};
    }
    appendChild(child) { this.children.push(child); }
    addEventListener() {}
}

function editor() {
    const nodes = new Map();
    const context = vm.createContext({
        document: {
            createElement: tag => new Element(tag),
            getElementById: id => {
                if (!nodes.has(id)) nodes.set(id, new Element());
                return nodes.get(id);
            },
        },
        alert: message => { context.lastAlert = message; },
        setTimeout() {},
    });
    vm.runInContext(script, context);
    return context;
}

function plain(value) { return JSON.parse(JSON.stringify(value)); }

test('example defaults leave native graphics disabled', () => {
    const config = JSON.parse(fs.readFileSync(path.join(root, 'config.json'), 'utf8'));
    const center = config.display.center_display;
    assert.equal(center.navigation.high_resolution, false);
    assert.equal(center.coverart.native_resolution, false);
    assert.equal(center.coverart.native_preset, 'legacy');
    assert.equal(center.coverart.native_render_order, 'tiles');
    assert.equal(center.coverart.native_delta, false);
    assert.deepEqual(center.coverart.native_args, {});
});

test('older imports gain usable compatibility defaults', () => {
    const ctx = editor();
    const old = {display: {center_display: {navigation: {auto_switch: false},
        coverart: {args: {contrast: 1.9}}}}, custom: {keep: 17}};
    const updated = ctx.addNativeDisplayDefaults(old);
    assert.equal(updated, old);
    assert.equal(updated.display.font_resolution, 'native');
    assert.deepEqual(updated.custom, {keep: 17});
    assert.equal(updated.display.center_display.navigation.auto_switch, false);
    assert.equal(updated.display.center_display.navigation.high_resolution, false);
    assert.deepEqual(updated.display.center_display.coverart.args, {contrast: 1.9});
    assert.equal(updated.display.center_display.coverart.native_preset, 'legacy');
});

test('existing native preferences and unknown settings survive imports', () => {
    const ctx = editor();
    const chosen = {display: {font_resolution: 'legacy', center_display: {navigation: {high_resolution: true},
        coverart: {native_resolution: true, native_preset: 'text',
            native_args: {threshold: 170}, native_render_order: 'bands',
            native_delta: false, brief: false}}}};
    const before = JSON.stringify(chosen);
    ctx.addNativeDisplayDefaults(chosen);
    assert.equal(JSON.stringify(chosen), before);
});

test('import defaults are idempotent and do not share argument objects', () => {
    const ctx = editor();
    const first = ctx.addNativeDisplayDefaults({});
    const second = ctx.addNativeDisplayDefaults({});
    first.display.center_display.coverart.native_args.threshold = 150;
    assert.deepEqual(plain(second.display.center_display.coverart.native_args), {});
    const before = JSON.stringify(first);
    ctx.addNativeDisplayDefaults(first);
    assert.equal(JSON.stringify(first), before);
});

test('malformed existing parents are preserved rather than overwritten', () => {
    const ctx = editor();
    for (const display of [null, false, 'custom', []]) {
        const existing = {display};
        ctx.addNativeDisplayDefaults(existing);
        assert.equal(existing.display, display);
    }
});

test('editor exposes supported native presets and draw orders', () => {
    const ctx = editor();
    const schema = vm.runInContext('SCHEMA', ctx);
    assert.deepEqual(plain(schema['display.center_display.coverart.native_preset'].options),
        ['legacy', 'balanced', 'photo', 'text']);
    assert.deepEqual(plain(schema['display.center_display.coverart.native_render_order'].options),
        ['tiles', 'planes', 'bands']);
    assert.deepEqual(plain(schema['display.font_resolution'].options), ['native', 'legacy']);
    assert.equal(schema['display.center_display.navigation.high_resolution'].type, 'boolean');
    assert.equal(schema['display.center_display.coverart.native_args'].type, 'json');
});

test('JSON override parser accepts objects and rejects scalars, arrays and null', () => {
    const ctx = editor();
    assert.deepEqual(plain(ctx.parseObjectSetting('{"contrast":1.4}')), {contrast: 1.4});
    for (const bad of ['null', 'true', '[]', '"text"', '2', '{broken']) {
        assert.throws(() => ctx.parseObjectSetting(bad));
    }
});

test('recursive editor renders argument objects through their JSON field', () => {
    const ctx = editor();
    const container = new Element();
    ctx.renderRecursive({native_args: {threshold: 140}}, 'display.center_display.coverart', container);
    assert.equal(container.children.length, 1);
    const textarea = container.children[0].children[0];
    assert.equal(textarea.tagName, 'TEXTAREA');
    assert.deepEqual(JSON.parse(textarea.value), {threshold: 140});
});

test('editing JSON overrides stores an object and rejects invalid replacement', () => {
    const ctx = editor();
    vm.runInContext('currentConfig = addNativeDisplayDefaults({})', ctx);
    const container = new Element();
    ctx.renderNode('display.center_display.coverart.native_args', {}, container, 'native_args');
    const textarea = container.children[0].children[0];
    textarea.onchange({target: {value: '{"threshold":150}'}});
    const current = () => plain(vm.runInContext('currentConfig.display.center_display.coverart.native_args', ctx));
    assert.deepEqual(current(), {threshold: 150});
    textarea.onchange({target: {value: '"bad"'}});
    assert.deepEqual(current(), {threshold: 150});
    assert.match(ctx.lastAlert, /Expected a JSON object/);
});
