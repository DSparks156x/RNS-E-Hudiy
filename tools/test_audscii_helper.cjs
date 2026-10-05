/* Offline DOM/canvas verification; no browser, server or hardware. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const htmlPath = process.argv[2] || path.join(__dirname, 'audscii_helper.html');
const assetDir = process.argv[3] || path.join(path.dirname(htmlPath),'../dis_emulator/static');
const html = fs.readFileSync(htmlPath, 'utf8');
assert.match(html, /src="\.\.\/dis_emulator\/static\/native_font_data\.js"/);
assert.match(html, /src="\.\.\/dis_emulator\/static\/native_font\.js"/);
assert.match(html, /src="\.\.\/dis_emulator\/static\/font_data\.js"/);
assert.match(html, /src="\.\.\/dis_emulator\/static\/audscii_data\.js"/);
assert.match(html, />Character mapping<\/option>/);
assert.doesNotMatch(html, /const audscii_trans =/);
assert.ok(html.indexOf('native_font_data.js') < html.indexOf('native_font.js'));
assert.match(html, /value="native-proportional" selected/);
assert.match(html, /value="raw" selected/);
assert.doesNotMatch(html, /value="ascii" selected/);
for(const mode of ['native-fixed','native-graphics','legacy-proportional','legacy-fixed','legacy-graphics'])
    assert.ok(html.includes(`value="${mode}"`));
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n');

function element(tag='div') {
    const node = { tag, style: {}, children: [], events: {}, className: '', value: '', innerText: '',
        classList: { add(name) { node.className += ' ' + name; } },
        appendChild(child) { this.children.push(child); },
        addEventListener(name, callback) { this.events[name] = callback; } };
    Object.defineProperty(node, 'innerHTML', { set() { this.children = []; } });
    if (tag === 'canvas') {
        const context = { fillStyle: '', fills: [], strokes: [],
            fillRect(...args) { this.fills.push({colour:this.fillStyle,args}); },
            strokeRect(...args) { this.strokes.push(args); } };
        node.getContext = () => context;
    }
    return node;
}

function fixture(code,font='proportional') {
    if (code === 0 || code === 0xD7) return {code,status:'ambiguous',size:null,mask_hex:null,advance_px:null};
    if (code === 32) return {code,status:'observed_blank',size:null,mask_hex:null,advance_px:4};
    const bytes = Buffer.alloc(20);
    bytes[18] = 0x10; // Captured native pixel x3,y18: beyond legacy's seven rows.
    return {code,status:'verified',size:[4,20],mask_hex:bytes.toString('hex'),advance_px:font==='proportional'?4:12,left_bearing_px:3};
}

function boot(nativeFont=true) {
    const nodes = Object.fromEntries(['main-grid','search','font-mode','glyph-view','status'].map(id => [id,element()]));
    nodes['font-mode'].value = 'native-proportional';
    nodes['glyph-view'].value = 'raw';
    const sandbox = { document: {getElementById:id=>nodes[id],createElement:element} };
    if (nativeFont === true) sandbox.NativeFont = {
        getGlyph(font,code) { assert.ok(['fixed','proportional','graphics'].includes(font));return fixture(code,font); },
        forEachPixel(glyph,callback) {
            const bytes=Buffer.from(glyph.mask_hex,'hex'),stride=Math.ceil(glyph.size[0]/8);
            for(let y=0;y<glyph.size[1];y++)for(let x=0;x<glyph.size[0];x++)
                if(bytes[y*stride+(x>>3)] & (0x80>>(x&7)))callback(x,y);
        }
    };
    const context=vm.createContext(sandbox);
    for (const file of ['audscii_data.js','font_data.js'])
        vm.runInContext(fs.readFileSync(path.join(assetDir,file),'utf8'),context,{filename:file});
    if (nativeFont === 'real') {
        for (const file of ['native_font_data.js','native_font.js'])
            vm.runInContext(fs.readFileSync(path.join(assetDir,file),'utf8'),context,{filename:file});
    }
    vm.runInContext(inline,context,{filename:htmlPath});
    return {nodes,context};
}

const {nodes,context}=boot();
function mappingCell(ascii) { return nodes['main-grid'].children.find(cell=>cell.children[0].innerText===ascii); }
function canvas(cell) { return cell.children.find(child=>child.tag==='canvas'); }
function metrics(cell) { return cell.children.find(child=>child.className.includes('metrics')).innerText; }

// The complete captured chart is the initial view, including Unicode aliases.
assert.equal(nodes['main-grid'].children.length,256);
assert.equal(mappingCell(0xBE).children.find(child=>child.className==='id-val').innerText,'0xBE');
assert.match(mappingCell(0xBE).children.find(child=>child.className==='info').innerText,/¾/);
assert.equal(mappingCell(0xBE).children.find(child=>child.className==='char-label').innerText,'¾');
assert.ok(canvas(mappingCell(0xBE)).getContext().fills.some(fill=>fill.colour==='#38bdf8'));
nodes['glyph-view'].value='ascii';nodes['glyph-view'].events.change();

// Mapping still uses AUDSCII, rather than assuming ASCII byte equals raw glyph.
const i=mappingCell(105);
assert.equal(i.children.find(child=>child.className==='id-val').innerText,'0x09');
assert.match(metrics(i),/advance 4 physical px/);
const nativeCanvas=canvas(i),nativeContext=nativeCanvas.getContext();
assert.equal(nativeCanvas.height,20);
assert.equal(nativeCanvas.width,16);
assert.equal(nativeCanvas.style.height,'80px');
assert.equal(nativeContext.imageSmoothingEnabled,false);
assert.deepEqual(nativeContext.fills.filter(fill=>fill.colour==='#38bdf8').map(fill=>fill.args),[[3,18,1,1]]);

// Known blank advances remain blank; unknowns never use invented legacy widths.
const space=mappingCell(32);
assert.match(metrics(space),/Observed blank · advance 4 physical px/);
assert.equal(canvas(space).getContext().strokes.length,0);
assert.equal(canvas(space).getContext().fills.length,1);
assert.match(metrics(mappingCell(0)),/advance unknown/);
assert.equal(canvas(mappingCell(0)).getContext().strokes.length,1);
nodes.search.value='0xD7';nodes.search.events.input({target:nodes.search});
assert.equal(nodes['main-grid'].children.length,1);
assert.match(metrics(nodes['main-grid'].children[0]),/Unsupported\/control or unresolved · advance unknown/);

// Comparison selection keeps the active search and uses the original chart.
nodes['font-mode'].value='legacy';nodes['font-mode'].events.change();
assert.equal(nodes['main-grid'].children.length,1);
assert.match(metrics(nodes['main-grid'].children[0]),/Low-resolution proportional · advance 6 logical px/);
nodes.search.value='i';nodes.search.events.input({target:nodes.search});
assert.equal(canvas(mappingCell(105)).height,8);
assert.equal(canvas(mappingCell(105)).width,6);

// Missing shared assets are explicitly unknown, not a silent legacy fallback.
const unavailable=boot(false);
assert.match(unavailable.nodes['main-grid'].children[0].title,/Capture unavailable · advance unknown/);

// Every raw graphics byte is visible, including IDs hidden by ASCII mapping.
nodes.search.value='';nodes['font-mode'].value='native-graphics';nodes['font-mode'].events.change();
assert.equal(nodes['glyph-view'].value,'raw');
assert.equal(nodes['main-grid'].children.length,256);
const rawId=mappingCell(0x11);
assert.equal(rawId.children.find(child=>child.className==='id-val').innerText,'0x11');
assert.match(metrics(rawId),/advance 12 physical px/);
assert.match(rawId.children.find(child=>child.className==='char-label').innerText,/✓/);
nodes.search.value='0x11';nodes.search.events.input({target:nodes.search});
assert.equal(nodes['main-grid'].children.length,1);
assert.equal(nodes['main-grid'].children[0].children[0].innerText,0x11);

// All three legacy choices draw the original shared family, not copies of PROP.
nodes.search.value='';
for(const font of ['proportional','fixed','graphics']) {
    nodes['font-mode'].value='legacy-'+font;nodes['font-mode'].events.change();
    nodes['glyph-view'].value='raw';nodes['glyph-view'].events.change();
    const code=49,cell=mappingCell(code);
    const table=vm.runInContext(`FONT_DATA_${font==='proportional'?'PROP':font.toUpperCase()}`,context);
    const expected=[];
    for(let y=0;y<7;y++)for(let x=0;x<table[code][0];x++)
        if(table[code][y+1] & (1<<(5-x)))expected.push([x,y+1,1,1]);
    assert.deepEqual(canvas(cell).getContext().fills.filter(fill=>fill.colour==='#38bdf8').map(fill=>fill.args),expected);
    assert.match(metrics(cell),new RegExp(`Low-resolution ${font}`));
}
nodes['font-mode'].value='native-fixed';nodes['font-mode'].events.change();
assert.match(metrics(mappingCell(49)),/advance 12 physical px/);

// Returning to mapping mode preserves character search/AUDSCII translation.
nodes['font-mode'].value='native-proportional';nodes['font-mode'].events.change();
nodes['glyph-view'].value='ascii';nodes['glyph-view'].events.change();
nodes.search.value='i';nodes.search.events.input({target:nodes.search});
assert.equal(mappingCell(105).children.find(child=>child.className==='id-val').innerText,'0x09');

// Installed-helper integration compares every drawn pixel with an independent
// row-stride decoder of the captured source, rather than mirroring API logic.
if (fs.existsSync(path.join(assetDir,'native_font_data.js'))) {
    const real=boot('real');
    const one=real.nodes['main-grid'].children.find(cell=>cell.children[0].innerText===49);
    const glyph=real.context.NativeFont.getGlyph('proportional',49);
    assert.equal(glyph.advance_px,10);
    assert.match(metrics(one),/Verified glyph · advance 10 physical px/);
    const bytes=Buffer.from(glyph.mask_hex,'hex'),expected=[];
    for(let y=0;y<glyph.size[1];y++)for(let x=0;x<glyph.size[0];x++)
        if(bytes[y*Math.ceil(glyph.size[0]/8)+Math.floor(x/8)] & (128>>(x%8)))expected.push([x,y,1,1]);
    assert.deepEqual(canvas(one).getContext().fills.filter(fill=>fill.colour==='#38bdf8').map(fill=>fill.args),expected);
    for (const raw of [0,0xD7]) assert.equal(real.context.NativeFont.getGlyph('proportional',raw).advance_px,null);
    const fraction=real.nodes['main-grid'].children.find(cell=>cell.children[0].innerText===0xBE);
    assert.ok(fraction,'Captured¾/raw0xBE must appear with its character alias');
    assert.equal(real.context.NativeFont.getGlyph('proportional',0xBE).status,'verified');
    assert.ok(canvas(fraction).getContext().fills.some(fill=>fill.colour==='#38bdf8'));
}

// Shared Unicode aliases are searchable in both views, across all six families.
const specialMappings = [['¼',0xBC],['½',0xBD],['¾',0xBE],['↑',0x18],['↓',0x19],['→',0x1A],['←',0x1B]];
for (const mode of ['native-fixed','native-proportional','native-graphics','legacy-fixed','legacy-proportional','legacy-graphics']) {
    nodes['font-mode'].value=mode;nodes['font-mode'].events.change();
    for (const view of ['raw','ascii']) {
        nodes['glyph-view'].value=view;nodes['glyph-view'].events.change();
        for (const [character,code] of specialMappings) {
            nodes.search.value=character;nodes.search.events.input({target:nodes.search});
            assert.equal(nodes['main-grid'].children.length,1,`${mode}/${view}/${character}`);
            const cell=nodes['main-grid'].children[0];
            assert.equal(cell.children.find(child=>child.className==='id-val').innerText,'0x'+code.toString(16).toUpperCase());
            assert.ok(cell.children.find(child=>child.className==='char-label').innerText.includes(character));
            assert.ok(canvas(cell));
        }
    }
}
// The mapping list includes actual Unicode codepoints, not truncated UTF-16.
nodes['glyph-view'].value='ascii';nodes['glyph-view'].events.change();
nodes.search.value='0x2191';nodes.search.events.input({target:nodes.search});
assert.equal(nodes['main-grid'].children.length,1);
assert.equal(nodes['main-grid'].children[0].children[0].innerText,0x2191);
nodes.search.value='🙂';nodes.search.events.input({target:nodes.search});
assert.equal(nodes['main-grid'].children.length,0,'Unsupported Unicode is not invented as a mapping row');
assert.deepEqual(Array.from(context.AUDSCII_MAPPING.encodeText('¼½¾↑↓→←🙂')),[0xBC,0xBD,0xBE,0x18,0x19,0x1A,0x1B,0x20]);
assert.deepEqual(Array.from(context.AUDSCII_MAPPING.encodeText('iä\0\t\x1c\x1e\x1f')),[9,0x91,0,0x2F,0x1C,0xD7,0x65]);

console.log('AUDSCII helper: six font choices, native pixel geometry, shared legacy tables, all 256 raw graphics codes, mapping and search passed.');
