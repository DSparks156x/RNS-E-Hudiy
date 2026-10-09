// Run: node --test tests/test_config_editor.js
// Test the shipped standalone script: config coverage, exact round trips,
// malformed edits, safe imported keys and GitHub loading failures/races.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const html = fs.readFileSync(path.join(__dirname, '../tools/config_editor.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const example = JSON.parse(fs.readFileSync(path.join(__dirname, '../config.json'), 'utf8'));
const plain = value => JSON.parse(JSON.stringify(value));

class Element {
  constructor(tag = 'div') {this.tagName=tag.toUpperCase();this.children=[];this.style={};this.value='';this.textContent='';this.classList={add(){},remove(){}};this.listeners={};}
  appendChild(child){this.children.push(child);return child;}
  replaceChildren(){this.children=[];}
  setAttribute(key,value){this[key]=value;}
  removeAttribute(key){delete this[key];}
  addEventListener(name,handler){this.listeners[name]=handler;}
  querySelector(){return null;}
  querySelectorAll(selector){const matches=[];const visit=node=>{if(selector==='.form-group'&&node.className==='form-group')matches.push(node);node.children.forEach(visit);};this.children.forEach(visit);return matches;}
}
function editor(fetcher, query='') {
  const nodes=new Map();
  const documentListeners={};
  const context=vm.createContext({document:{createElement:tag=>new Element(tag),getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},addEventListener:(name,handler)=>{documentListeners[name]=handler;},querySelectorAll:()=>[],querySelector:()=>null},window:{location:{search:query}},setTimeout(){return 1;},clearTimeout(){},AbortController,fetch:fetcher,Date,URL,URLSearchParams,TypeError});
  vm.runInContext(script,context);
  context.document.getElementById('source-repo').value='DSparks156x/RNS-E-Hudiy';
  context.document.getElementById('source-branch').value='testing';
  context.document.getElementById('source-repo').options=[{value:'DSparks156x/RNS-E-Hudiy'},{value:'custom'}];
  context.document.getElementById('source-branch').options=[{value:'testing'},{value:'main'},{value:'custom'}];
  context.initialize=()=>documentListeners.DOMContentLoaded();
  return context;
}
function leaves(ctx,object,path=[]){const result=[];for(const[key,value]of Object.entries(object)){const next=[...path,key];const meta=ctx.metadataFor(next.join('.'));if(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length&&!meta.type?.startsWith('json'))result.push(...leaves(ctx,value,next));else result.push(next.join('.'));}return result;}
function allFields(ctx){return vm.runInContext('renderedFields',ctx);}
function field(ctx,path){return allFields(ctx).find(item=>item.search.startsWith(path.toLowerCase()+' '));}

test('URL search filters bundled settings on the first render',()=>{
  const query='display.center_display.navigation';
  const ctx=editor(undefined,'?'+new URLSearchParams({search:query}));
  ctx.initialize();
  assert.equal(ctx.document.getElementById('search-input').value,query);
  const visible=allFields(ctx).filter(item=>!item.group.hidden);
  assert.ok(visible.length>0,'URL search must leave matching settings visible');
  assert.ok(visible.every(item=>item.search.includes(query)));
  assert.equal(field(ctx,'branch').group.hidden,true);
  assert.equal(ctx.document.getElementById('empty-search').hidden,true);
});

test('URL search remains applied after automatically loading the selected branch',async()=>{
  const requested={search:'display.center_display.navigation',repo:'DSparks156x/RNS-E-Hudiy',branch:'testing',load:'1'};
  const calls=[];
  const remote={display:{center_display:{navigation:{enabled:false}}},unrelated_setting:42};
  const ctx=editor(async(url)=>{calls.push(url);return{ok:true,text:async()=>JSON.stringify(remote)};},'?'+new URLSearchParams(requested));
  ctx.initialize();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.length,1);
  assert.match(calls[0],/DSparks156x\/RNS-E-Hudiy\/testing\/config\.json$/);
  assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),remote);
  assert.equal(ctx.document.getElementById('search-input').value,requested.search);
  assert.equal(field(ctx,'display.center_display.navigation.enabled').group.hidden,false);
  assert.equal(field(ctx,'unrelated_setting').group.hidden,true);
  assert.equal(ctx.document.getElementById('empty-search').hidden,true);
});

test('every editable example setting has specific consumer-backed help and is rendered',()=>{
  const ctx=editor();
  const settings=leaves(ctx,example);
  const incomplete=settings.filter(setting=>{const meta=ctx.metadataFor(setting);return !meta.help||meta.help.length<=25||meta.help.includes('Custom setting from');});
  assert.deepEqual(incomplete,[], 'Settings without specific, useful descriptions');
  ctx.loadConfiguration(example,'Fixture');
  assert.equal(allFields(ctx).length,settings.length);
  for(const setting of settings)assert.ok(field(ctx,setting),'Hidden setting: '+setting);
});
test('known legacy testing-branch settings have version-aware help and survive loading',()=>{
  const ctx=editor();
  const config={display:{center_display:{navigation:{high_resolution:true},coverart:{native_resolution:false}}},diagnostics:{hudiy_api_capture:{enabled:false,path:'~/old-capture.log',max_size_mb:12}}};
  for(const setting of leaves(ctx,config)){const help=ctx.metadataFor(setting).help;assert.match(help,/Legacy/);assert.match(help,/Current/);assert.doesNotMatch(help,/Custom setting from/);}
  ctx.loadConfiguration(config,'Older testing branch');assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),config);assert.equal(allFields(ctx).length,5);
  assert.match(ctx.metadataFor('branch').help,/track-\* tag/);
});
test('file import preserves unknown settings, legacy markers, arrays, null and prototype-like keys exactly',async()=>{
  const ctx=editor();
  const imported=JSON.parse('{"display":{"font_resolution":"legacy"},"custom":{"dotted.key":null,"items":[0,false,null,{"a":1}],"__proto__":{"safe":true}}}');
  ctx.loadConfiguration(example,'Example');
  const input=ctx.document.getElementById('file-input');
  await input.listeners.change({target:{files:[{name:'custom.json',text:async()=>JSON.stringify(imported)}],value:'custom.json'}});
  assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),imported);
  assert.equal(input.value,'');
  ctx.setValueByPath(['custom','dotted.key'],3);
  assert.equal(vm.runInContext('currentConfig.custom["dotted.key"]',ctx),3);
  ctx.setValueByPath(['custom','__proto__'],{stillSafe:true});
  assert.equal(vm.runInContext('({}).stillSafe',ctx),undefined);
});
test('malformed imports leave the edited config unchanged',async()=>{
  const ctx=editor();ctx.loadConfiguration({custom:{keep:2}},'Original');
  for(const contents of ['null','[]','"x"','{broken']){await ctx.document.getElementById('file-input').listeners.change({target:{files:[{name:'bad.json',text:async()=>contents}],value:'bad.json'}});assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),{custom:{keep:2}});assert.match(ctx.document.getElementById('source-status').textContent,/Import failed/);}
});
test('JSON arrays retain structured item types and reject invalid replacement',()=>{
  const ctx=editor();ctx.loadConfiguration({...example,ddp_bitmap_message_bytes:105},'Example');
  const item=field(ctx,'file_portal.firmware_targets');
  const replacement=[{id:'new',extensions:['.bin'],max_size_mb:2}];
  item.input.onchange({target:{value:JSON.stringify(replacement)}});
  assert.deepEqual(plain(vm.runInContext('currentConfig.file_portal.firmware_targets',ctx)),replacement);
  item.input.onchange({target:{value:'{}'}});
  assert.deepEqual(plain(vm.runInContext('currentConfig.file_portal.firmware_targets',ctx)),replacement);
  assert.equal(ctx.document.getElementById('export-config').disabled,true);
  item.input.onchange({target:{value:'[]'}});
  assert.equal(ctx.document.getElementById('export-config').disabled,false);
});
test('number validation retains old values and null mappings stay null when disabled',()=>{
  const ctx=editor();ctx.loadConfiguration({...example,ddp_bitmap_message_bytes:105},'Example');
  const budget=field(ctx,'ddp_bitmap_message_bytes');
  for(const invalid of ['','NaN','200','1','42.5']){budget.input.onchange({target:{value:invalid}});assert.equal(vm.runInContext('currentConfig.ddp_bitmap_message_bytes',ctx),105);assert.equal(ctx.document.getElementById('export-config').disabled,true);}
  budget.input.onchange({target:{value:'42'}});assert.equal(ctx.document.getElementById('export-config').disabled,false);
  const action=field(ctx,'input_mappings.mmi.long_press.64,0');
  action.input.onchange({target:{value:'KEY_UP'}});assert.equal(vm.runInContext('currentConfig.input_mappings.mmi.long_press["64,0"]',ctx),'KEY_UP');
  action.input.onchange({target:{value:'null'}});assert.equal(vm.runInContext('currentConfig.input_mappings.mmi.long_press["64,0"]',ctx),null);
});
test('unknown select choices remain selected and imported labels are escaped',()=>{
  const ctx=editor();ctx.loadConfiguration({display:{center_display:{navigation:{icon_style:'future-style'}}},'<img src=x onerror=bad()>':false},'Future');
  const choice=field(ctx,'display.center_display.navigation.icon_style');assert.equal(choice.input.value,'future-style');assert.equal(choice.input.children[0].value,'future-style');
  const malicious=allFields(ctx).find(item=>item.search.includes('<img'));assert.doesNotMatch(malicious.group.innerHTML,/<img/);assert.match(malicious.group.innerHTML,/&lt;img/);
});

test('bundled RNS-E brightness settings use confirmed integer levels from zero to ten',()=>{
  const ctx=editor();ctx.initialize();
  assert.deepEqual(plain(vm.runInContext('currentConfig.rnse.auto_brightness',ctx)),{enabled:false,day_brightness:10,night_brightness:5});
  const brightness=field(ctx,'rnse.auto_brightness.day_brightness');
  for(const invalid of ['-1','11','5.5']){
    brightness.input.onchange({target:{value:invalid}});
    assert.equal(vm.runInContext('currentConfig.rnse.auto_brightness.day_brightness',ctx),10);
    assert.equal(ctx.document.getElementById('export-config').disabled,true);
  }
  brightness.input.onchange({target:{value:'0'}});
  assert.equal(vm.runInContext('currentConfig.rnse.auto_brightness.day_brightness',ctx),0);
  assert.equal(ctx.document.getElementById('export-config').disabled,false);
});
test('source URLs validate repository names and encode slash-containing branches',()=>{
  const ctx=editor();const selected=ctx.repositorySelection('https://github.com/DSparks156x/RNS-E-Hudiy.git','feature/ui');assert.equal(selected.rawUrl,'https://raw.githubusercontent.com/DSparks156x/RNS-E-Hudiy/feature%2Fui/config.json');assert.equal(selected.pageUrl,'https://github.com/DSparks156x/RNS-E-Hudiy/tree/feature%2Fui');
  for(const repo of ['owner/repo/other','file:///x','https://evil.test/a/b','owner'])assert.throws(()=>ctx.repositorySelection(repo,'testing'));
  for(const branch of ['','bad?query','../x','bad branch'])assert.throws(()=>ctx.repositorySelection('owner/repo',branch));
  assert.match(html,/<option value="DSparks156x\/RNS-E-Hudiy" selected>/);assert.match(html,/<option selected>testing<\/option>/);
});
test('Open fetches the selected branch without cache and Undo restores prior edits',async()=>{
  const calls=[];const ctx=editor(async(url,options)=>{calls.push({url,options});return{ok:true,text:async()=>'{"repo":"custom-runtime-repo","branch":"feature/ui","unknown":null}'};});
  ctx.loadConfiguration({custom:8},'Original');ctx.setValueByPath(['custom'],9);
  ctx.document.getElementById('source-branch').value='custom';ctx.document.getElementById('custom-branch').value='feature/ui';
  await ctx.openRepositoryConfig();assert.equal(calls.length,1);assert.match(calls[0].url,/feature%2Fui\/config.json$/);assert.equal(calls[0].options.cache,'no-store');
  assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),{repo:'custom-runtime-repo',branch:'feature/ui',unknown:null});
  ctx.undoLoad();assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),{custom:9});
});
test('404, malformed remote JSON and non-object remote configs retain local edits',async()=>{
  for(const response of [{ok:false,status:404},{ok:true,text:async()=>'{bad'},{ok:true,text:async()=>'[]'}]){
    const ctx=editor(async()=>response);ctx.loadConfiguration({keep:7},'Local');await ctx.openRepositoryConfig();assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),{keep:7});assert.equal(ctx.document.getElementById('source-status').className,'source-status error');assert.equal(ctx.document.getElementById('open-config').disabled,false);
  }
});
test('an in-flight fetch cannot overwrite a newer edit or changed source',async()=>{
  let resolve;const ctx=editor(()=>new Promise(done=>resolve=done));ctx.loadConfiguration({keep:7},'Local');const opening=ctx.openRepositoryConfig();ctx.setValueByPath(['keep'],8);resolve({ok:true,text:async()=>'{"remote":1}'});await opening;assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),{keep:8});assert.match(ctx.document.getElementById('source-status').textContent,/edited the form/);
  const another=ctx.openRepositoryConfig();ctx.sourceSelectionChanged();resolve({ok:true,text:async()=>'{"remote":2}'});await another;assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),{keep:8});
});
test('Undo load cancels a pending fetch and restores usable Open controls',async()=>{
  let resolve;const ctx=editor(()=>new Promise(done=>resolve=done));ctx.loadConfiguration({first:1},'First');ctx.loadConfiguration({second:2},'Second');const opening=ctx.openRepositoryConfig();assert.equal(ctx.document.getElementById('open-config').disabled,true);ctx.undoLoad();assert.equal(ctx.document.getElementById('open-config').disabled,false);resolve({ok:true,text:async()=>'{"remote":3}'});await opening;assert.deepEqual(plain(vm.runInContext('currentConfig',ctx)),{first:1});
});
