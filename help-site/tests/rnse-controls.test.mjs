import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createFaceplateControls } from '../src/rnseControlModel.js';
const runtimeConfig = new URL('../../config.json', import.meta.url);
const snapshot = JSON.parse(readFileSync(new URL('../data/control-defaults.json', import.meta.url), 'utf8'));
const masks = { nav:'8,0', tel:'0,8', media:'0,4', name:'4,0', info:'0,12', car:'12,0' };

test('faceplate defaults use shared press tables and match the runtime config when available', () => {
  if (existsSync(runtimeConfig)) assert.deepEqual(snapshot.input_mappings.mmi, JSON.parse(readFileSync(runtimeConfig, 'utf8')).input_mappings.mmi);
  assert.equal('panel_buttons' in snapshot.input_mappings.mmi, false);
  for (const table of ['short_press','long_press','extended_press']) {
    for (const mask of Object.values(masks)) assert.equal(Object.hasOwn(snapshot.input_mappings.mmi[table], mask), true);
  }
});

test('each clickable TV button describes its shared press and hold bindings', () => {
  const controls = createFaceplateControls(snapshot.input_mappings.mmi);
  const descriptions = { nav:'Navigation shortcut', tel:'Phone shortcut', media:'Current media player', name:'App menu', info:'DataView', car:'RNS-E Manager' };
  for (const [button, mask] of Object.entries(masks)) {
    assert.equal(controls[button].pattern, mask);
    assert.equal(controls[button].actions[0][1], descriptions[button]);
    assert.equal(controls[button].actions[1][1], 'Uses the press action on release');
    assert.equal(controls[button].actions[2][1], 'No additional action');
  }
  assert.equal(controls.setup.actions[0][1], 'Hudiy home');
  assert.match(controls.radio.actions[0][1], /factory radio/);
});

test('faceplate displays remapped key, Hudiy action and shell hold bindings from the same tables', () => {
  const mmi = structuredClone(snapshot.input_mappings.mmi);
  mmi.short_press['0,12'] = null;
  mmi.long_press['0,12'] = {action:'applications_menu'};
  mmi.extended_press['0,12'] = 'sudo reboot';
  const info = createFaceplateControls(mmi).info;
  assert.equal(info.actions[0][1], 'No Pi action');
  assert.equal(info.actions[1][1], 'App menu');
  assert.equal(info.actions[2][1], 'Reboot the Pi');
});
