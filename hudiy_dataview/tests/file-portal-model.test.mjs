import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const source = await readFile(new URL('../src/filePortalModel.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText;
const {collectionGroup,visibleFiles,validateFile} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
test('all backend collection types have a reachable group', () => {
  assert.equal(collectionGroup({id:'drive_logs',kind:'logs'}),'recordings');
  for(const id of ['service_logs','runtime_logs','hudiy_api','flash_logs','future_log']) assert.equal(collectionGroup({id,kind:'logs'}),'debug');
  for(const kind of ['firmware','readouts']) assert.equal(collectionGroup({id:'custom',kind}),'controllers');
});
test('search includes nested paths and sorting never changes catalog order', () => {
  const files = [{name:'z.log',path:'Saved Monday/z.log',size:10,modified:2},{name:'a.log',path:'a.log',size:100,modified:1}];
  assert.deepEqual(visibleFiles(files,' monday ','date').map(f=>f.name),['z.log']);
  assert.deepEqual(visibleFiles(files,'','name').map(f=>f.name),['a.log','z.log']);
  assert.deepEqual(visibleFiles(files,'','size').map(f=>f.name),['a.log','z.log']);
  assert.deepEqual(files.map(f=>f.name),['z.log','a.log']);
});
test('upload rejects wrong type, empty or oversized file, preserving server validation', () => {
  const target = {extensions:['.bin'],max_size:1024,label:'Haldex firmware'};
  assert.equal(validateFile({name:'firmware.BIN',size:1024},target),null);
  assert.match(validateFile({name:'firmware.txt',size:1},target),/\.bin/);
  assert.match(validateFile({name:'firmware.bin',size:1025},target),/exceeds/);
  assert.match(validateFile({name:'firmware.bin',size:0},target),/empty/);
});
test('capture catalog allows uploads to only the three real built-in firmware targets', async () => {
  const fixture = await readFile(new URL('../../help-site/scripts/capture-file-portal.jsx', import.meta.url), 'utf8');
  const catalogSource = fixture.slice(fixture.indexOf('const definitions = ['),fixture.indexOf('const loadCatalog ='));
  const createCatalog = new Function('params',`${catalogSource}; return catalog;`);
  const catalog = createCatalog(new URLSearchParams('pin=1'));
  assert.deepEqual(catalog.collections.filter(collection=>collection.upload).map(collection=>collection.id),[
    'firmware_haldex','firmware_pq-eps','firmware_exhaust-valve',
  ]);
  assert.equal(catalog.pin_required,true);
  assert.equal(createCatalog(new URLSearchParams()).pin_required,false);
  assert.equal(catalog.collections.find(collection=>collection.id==='firmware_exhaust-valve').max_size,1024*1024);
});
