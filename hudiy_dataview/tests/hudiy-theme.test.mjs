import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// Run the actual hook against a minimal React effect lifecycle. This makes the
// initial null socket and cleanup observable without a browser or live socket.
const source = await readFile(new URL('../src/hooks/useHudiyTheme.ts', import.meta.url),'utf8');
const compiled = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText
  .replace(/import \{ useEffect, useState \} from 'react';/, 'const {useEffect,useState} = globalThis.__themeHookLifecycle;');
function lifecycle() {
  const states = [],effects = [],pending = [];
  let stateIndex = 0,effectIndex = 0;
  return {
    useState(initial) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial;
      return [states[index],value=>{states[index] = typeof value === 'function' ? value(states[index]) : value;}];
    },
    useEffect(effect,deps) {
      const index = effectIndex++,previous = effects[index];
      if (!previous || deps.some((dep,i)=>!Object.is(dep,previous.deps[i]))) pending.push(()=>{
        previous?.cleanup?.(); effects[index] = {deps,cleanup:effect()};
      });
    },
    render(hook,socket) { stateIndex=0;effectIndex=0;const result=hook(socket);pending.splice(0).forEach(effect=>effect());return result; },
    cleanup() { effects.forEach(effect=>effect.cleanup?.()); },
  };
}
function socketFixture() {
  const handlers = new Map(),emitted = [];
  return {
    emitted,
    on(event,handler) { if (!handlers.has(event)) handlers.set(event,new Set());handlers.get(event).add(handler); },
    off(event,handler) { handlers.get(event)?.delete(handler); },
    emit(event,value) { emitted.push([event,structuredClone(value)]); },
    receive(event,value) { handlers.get(event)?.forEach(handler=>handler(value)); },
    count(event) { return handlers.get(event)?.size || 0; },
  };
}

test('native palette reaches a late socket, reconnect and change, preserving callbacks and cleanup',async()=>{
  const hooks = lifecycle();globalThis.__themeHookLifecycle = hooks;
  const {useHudiyTheme} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
  let nativeChanges=0,attached=0;
  const originalChange=()=>nativeChanges++,originalAttached=()=>attached++;
  globalThis.window = {hudiy:{colorScheme:{primary:'#aabbcc',darkThemeEnabled:true},onColorSchemeChanged:originalChange,onAttached:originalAttached}};
  const socket=socketFixture();
  try {
    hooks.render(useHudiyTheme,null);
    assert.equal(socket.emitted.length,0);
    hooks.render(useHudiyTheme,socket);
    assert.deepEqual(socket.emitted,[['log_theme',{primary:'#aabbcc',darkThemeEnabled:true}]]);
    assert.equal(socket.count('connect'),1);
    socket.receive('connect');
    assert.equal(socket.emitted.length,2);
    window.hudiy.colorScheme={primary:'#335544',darkThemeEnabled:false};
    window.hudiy.onColorSchemeChanged();
    assert.deepEqual(socket.emitted.at(-1),['log_theme',{primary:'#335544',darkThemeEnabled:false}]);
    assert.equal(nativeChanges,1);
    assert.equal(hooks.render(useHudiyTheme,socket).theme.primary,'#335544');
    window.hudiy.onAttached();assert.equal(attached,1);
    hooks.cleanup();
    assert.equal(window.hudiy.onColorSchemeChanged,originalChange);
    assert.equal(window.hudiy.onAttached,originalAttached);
    assert.equal(socket.count('connect'),0);assert.equal(socket.count('status'),0);
    const count=socket.emitted.length;socket.receive('connect');assert.equal(socket.emitted.length,count);
  } finally { delete globalThis.window;delete globalThis.__themeHookLifecycle; }
});
