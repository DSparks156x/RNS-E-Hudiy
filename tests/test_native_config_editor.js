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
    setAttribute(key, value) { this[key] = value; }
    removeAttribute(key) { delete this[key]; }
    querySelector() { return null; }
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
        clearTimeout() {},
    });
    vm.runInContext(script, context);
    return context;
}

function plain(value) { return JSON.parse(JSON.stringify(value)); }

test('legacy API capture options disappear during import because capture is always on', () => {
    const ctx = editor();
    const config = {diagnostics: {enabled: false, values: {diagnostic_hz: 2},
        hudiy_api_capture: {enabled: false, path: '/old/capture.log', max_size_mb: 1}}};
    ctx.addDataLogsDefaults(config);
    assert.equal(config.diagnostics.hudiy_api_capture, undefined);
    assert.equal(config.diagnostics.enabled, false);
    assert.deepEqual(config.diagnostics.values, {diagnostic_hz: 2});
});

test('example config uses one center-display resolution setting', () => {
    const config = JSON.parse(fs.readFileSync(path.join(root, 'config.json'), 'utf8'));
    const center = config.display.center_display;
    assert.equal(center.high_resolution, true);
    assert.equal(config.display.font_resolution, undefined);
    assert.equal(center.navigation.high_resolution, undefined);
    assert.equal(center.coverart.native_resolution, undefined);
    assert.equal(center.coverart.native_preset, 'legacy');
    assert.equal(center.coverart.native_render_order, 'planes');
    assert.equal(center.navigation.native_render_order, 'planes');
    assert.equal(center.navigation.native_message_delay_ms, 5);
    assert.equal(center.coverart.native_delta, false);
    assert.deepEqual(center.coverart.native_args, {});
});

test('older imports gain usable compatibility defaults', () => {
    const ctx = editor();
    const old = {display: {center_display: {navigation: {auto_switch: false},
        coverart: {args: {contrast: 1.9}}}}, custom: {keep: 17}};
    const updated = ctx.addNativeDisplayDefaults(old);
    assert.equal(updated, old);
    assert.equal(updated.display.center_display.high_resolution, true);
    assert.equal(updated.display.font_resolution, undefined);
    assert.deepEqual(updated.custom, {keep: 17});
    assert.equal(updated.display.center_display.navigation.auto_switch, false);
    assert.equal(updated.display.center_display.navigation.high_resolution, undefined);
    assert.equal(updated.display.center_display.navigation.native_render_order, 'planes');
    assert.equal(updated.display.center_display.navigation.native_message_delay_ms, 5);
    assert.deepEqual(updated.display.center_display.coverart.args, {contrast: 1.9});
    assert.equal(updated.display.center_display.coverart.native_preset, 'legacy');
});

test('existing native preferences and unknown settings survive imports', () => {
    const ctx = editor();
    const chosen = {display: {font_resolution: 'legacy', center_display: {navigation: {high_resolution: true, native_render_order: 'tiles', native_message_delay_ms: 10},
        coverart: {native_resolution: true, native_preset: 'text',
            native_args: {threshold: 170}, native_render_order: 'bands',
            native_delta: false, brief: false}}}};
    ctx.addNativeDisplayDefaults(chosen);
    assert.equal(chosen.display.center_display.high_resolution, false);
    assert.equal(chosen.display.font_resolution, 'legacy');
    assert.equal(chosen.display.center_display.navigation.high_resolution, undefined);
    assert.equal(chosen.display.center_display.coverart.native_resolution, undefined);
    assert.equal(chosen.display.center_display.navigation.native_render_order, 'tiles');
    assert.equal(chosen.display.center_display.navigation.native_message_delay_ms, 10);
    assert.equal(chosen.display.center_display.coverart.native_preset, 'text');
    assert.deepEqual(chosen.display.center_display.coverart.native_args, {threshold: 170});
    assert.equal(chosen.display.center_display.coverart.native_render_order, 'bands');
    assert.equal(chosen.display.center_display.coverart.brief, false);
});

test('explicit center-display choice wins and old graphics-only configs migrate', () => {
    const ctx = editor();
    for (const enabled of [false, true]) {
        const config = {display: {font_resolution: enabled ? 'legacy' : 'native', center_display: {
            high_resolution: enabled, navigation: {high_resolution: !enabled}, coverart: {native_resolution: !enabled}}}};
        ctx.addNativeDisplayDefaults(config);
        assert.equal(config.display.center_display.high_resolution, enabled);
        assert.equal(config.display.font_resolution, enabled ? 'legacy' : undefined);
    }
    for (const [navigation, coverart, expected] of [[false, false, false], [true, false, true], [false, true, true]]) {
        const config = {display: {center_display: {navigation: {high_resolution: navigation}, coverart: {native_resolution: coverart}}}};
        ctx.addNativeDisplayDefaults(config);
        assert.equal(config.display.center_display.high_resolution, expected);
        assert.equal(config.display.center_display.navigation.high_resolution, undefined);
        assert.equal(config.display.center_display.coverart.native_resolution, undefined);
    }
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

test('data logging import migration preserves mappings without adding a car-info switch', () => {
    const ctx = editor();
    const old = {display: {phone: {claim_on_phone: true, scroll_wheel_phone_menu: false}},
        input_mappings: {mfsw: {short_press: {mode: 'KEY_ENTER'}}}, custom: {keep: 42}};
    ctx.addDataLogsDefaults(old);
    assert.equal(old.display.center_display?.car_info, undefined);
    assert.equal(old.input_mappings.mfsw.double_click_ms, 350);
    assert.equal(old.input_mappings.mfsw.short_press.mode, 'KEY_ENTER');
    assert.equal(old.display.phone.scroll_wheel_phone_menu, false);
    assert.equal(old.display.phone.claim_on_phone, true);
    assert.equal(old.custom.keep, 42);
    assert.equal(old.data_logs.directory, '~/logs/data-logs');
    const before = JSON.stringify(old);
    ctx.addDataLogsDefaults(old);
    assert.equal(JSON.stringify(old), before);
    old.display.center_display = {applist: ['phone', 'car_info'], car_info: {high_resolution: false, custom: 7}};
    old.input_mappings.mfsw.double_click_ms = 500;
    ctx.addDataLogsDefaults(old);
    assert.equal(old.display.center_display.car_info.high_resolution, undefined);
    assert.equal(old.display.center_display.car_info.custom, 7);
    assert.deepEqual(plain(old.display.center_display.applist), ['phone', 'car_info']);
    assert.equal(old.input_mappings.mfsw.double_click_ms, 500);
    old.display.center_display.car_info = {high_resolution: true};
    ctx.addDataLogsDefaults(old);
    assert.equal(old.display.center_display.car_info, undefined);
});

test('editor exposes supported native presets and draw orders', () => {
    const ctx = editor();
    const schema = vm.runInContext('SCHEMA', ctx);
    assert.deepEqual(plain(schema['display.center_display.coverart.native_preset'].options),
        ['legacy', 'balanced', 'photo', 'text']);
    assert.deepEqual(plain(schema['display.center_display.coverart.native_render_order'].options),
        ['tiles', 'planes', 'bands']);
    assert.equal(schema['display.center_display.high_resolution'].type, 'boolean');
    assert.equal(schema['display.font_resolution'], undefined);
    assert.equal(schema['display.center_display.navigation.high_resolution'], undefined);
    assert.equal(schema['display.center_display.coverart.native_resolution'], undefined);
    assert.deepEqual(plain(schema['display.center_display.navigation.native_render_order'].options), ['planes', 'tiles']);
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
    const error = container.children[0].children[1];
    assert.match(error.textContent, /Expected a JSON object/);
    assert.equal(textarea['aria-invalid'], 'true');
    assert.equal(ctx.document.getElementById('export-config').disabled, true);
});
