// Actual emulator functions against a physical-pixel canvas, using captured masks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const repo = process.argv[2] || path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(repo, 'dis_emulator/templates/index.html'), 'utf8');
assert.match(html, /src="\/static\/native_font_data\.js/);
assert.match(html, /src="\/static\/audscii_data\.js/);
assert.doesNotMatch(html, /const AUDSCII =|charCodeAt/);
assert.match(html, /src="\/static\/native_font\.js/);
assert.match(html, /<select id="fontResolution"[^>]*onchange="setFontResolution\(this.value\)"/);
assert.match(html, /<option value="native" selected>/);
assert.match(html, /Legacy low-res \(red cluster\)/);
assert.match(html, /Tint changes color only/);
const pixels = new Uint8Array(128 * 176);
const logs = [];
let transform = [2, 0, 0, 2, 0, 0];
const stack = [];
const canvas = {
    fillStyle: 'black',
    setTransform(...value) { transform = value; },
    save() { stack.push([transform.slice(), this.fillStyle]); },
    restore() { [transform, this.fillStyle] = stack.pop(); },
    fillRect(x, y, w, h) {
        const [sx, , , sy, dx, dy] = transform;
        const left=x*sx+dx, top=y*sy+dy;
        for (let yy=Math.max(0, Math.ceil(top)); yy<Math.min(176, Math.ceil(top+h*sy)); yy++) {
            for (let xx=Math.max(0, Math.ceil(left)); xx<Math.min(128, Math.ceil(left+w*sx)); xx++) {
                pixels[yy*128+xx] = this.fillStyle === 'black' ? 0 : 1;
            }
        }
    },
};
const sandbox = {bCtx:canvas, currentDisColor:'white', addLog(text) { logs.push(text); }};
vm.createContext(sandbox);
for (const file of ['audscii_data.js', 'font_data.js', 'native_font_data.js', 'native_font.js']) {
    vm.runInContext(fs.readFileSync(path.join(repo, 'dis_emulator/static', file), 'utf8'), sandbox);
}
vm.runInContext(html.slice(html.indexOf('function getFontTable(flags)'), html.indexOf('function drawBitmap(cmd,')), sandbox);
const data = sandbox.NATIVE_FONT_DATA.fonts.proportional.glyphs;

function expectedGlyph(glyph, x, y, target=new Uint8Array(128*176), inverted=false) {
    const bytes=Buffer.from(glyph.mask_hex || '', 'hex');
    const [w,h]=glyph.size || [0,0];
    const stride=Math.ceil(w/8);
    if (inverted) {
        for (let yy=0; yy<18; yy++) for (let xx=0; xx<glyph.advance_px; xx++) {
            if (x+xx>=0 && x+xx<128 && y+yy>=0 && y+yy<176) target[(y+yy)*128+x+xx]=1;
        }
    }
    for (let yy=0; yy<h; yy++) for (let xx=0; xx<w; xx++) {
        if ((bytes[yy*stride+(xx>>3)] & (0x80>>(xx&7))) && x+xx>=0 && x+xx<128 && y+yy>=0 && y+yy<176) {
            target[(y+yy)*128+x+xx] = inverted ? 0 : 1;
        }
    }
    return target;
}

// Exact renderer output for every captured mask, including non-bytealigned widths.
let verified=0;
const counts={};
for (const [font, flags] of [['fixed',0x02],['proportional',0x06],['graphics',0x0A]]) {
    const captured=sandbox.NATIVE_FONT_DATA.fonts[font];
    if (!captured) continue;
    counts[font]=0;
    for (const glyph of captured.glyphs.filter(g => g.status==='verified')) {
        pixels.fill(0);
        sandbox.drawAudscii([glyph.code], 3, 27, flags, false, false);
        assert.deepEqual(pixels, expectedGlyph(glyph, 6, 54), `${font} captured0x${glyph.code.toString(16)}`);
        assert.deepEqual(transform, [2,0,0,2,0,0]);
        counts[font]++;verified++;
    }
}
assert.equal(counts.proportional, 245);
pixels.fill(0);
sandbox.drawAudscii(Uint8Array.from([65]), 3, 27, 0x06, false, false);
assert.deepEqual(pixels, expectedGlyph(data[65], 6, 54), 'Raw typed bytes use the same native path');

// Unicode lowercase and extended Latin retain existing AUDSCII translation.
pixels.fill(0);
sandbox.drawText('aä', 1, 27, 0x06);
let expected=expectedGlyph(data[1], 2, 54);
expectedGlyph(data[0x91], 2+data[1].advance_px, 54, expected);
assert.deepEqual(pixels, expected);

// Center using physical measured advances, without2x bitmap enlargement.
pixels.fill(0);
sandbox.drawText('A1.', 17, 27, 0x26);
const sequence=[65,49,46];
const width=sequence.reduce((n,c)=>n+data[c].advance_px,0);
let cursor=Math.max(0, Math.floor((128-width)/2));
expected=new Uint8Array(128*176);
for (const code of sequence) { expectedGlyph(data[code], cursor, 54, expected); cursor+=data[code].advance_px; }
assert.deepEqual(pixels, expected);

// Opaque/inverted text and capture-confirmed blank spaces erase prior content.
pixels.fill(0);
sandbox.drawText('A', 2, 27, 0x86);
assert.deepEqual(pixels, expectedGlyph(data[65], 4, 54, undefined, true));
pixels.fill(1);
sandbox.drawAudscii([32], 2, 27, 0x06, false, false);
for (let yy=0; yy<176; yy++) for (let xx=0; xx<128; xx++) {
    assert.equal(pixels[yy*128+xx], yy>=54 && yy<72 && xx>=4 && xx<4+data[32].advance_px ? 0 : 1);
}

// A NULL byte retains the old blank legacy advance; it does not truncate text.
pixels.fill(0);logs.length=0;
sandbox.drawText('A\0B', 0, 27, 0x06);
expected=expectedGlyph(data[65],0,54);
expectedGlyph(data[66],data[65].advance_px+8,54,expected);
assert.deepEqual(pixels,expected);
assert.equal(logs.length,1);
assert.match(logs[0], /0x00.*legacy fallback.*metrics unavailable/);
sandbox.drawText('\0',0,0,0x06);
assert.equal(logs.length,1,'Unknown-code diagnostic is deduplicated');
assert.equal(sandbox.NativeFont.measureCodes('proportional',[0]).advancePx,null);

// Canvas bounds clip physical ink; next ordinary operation retains logical2x scale.
pixels.fill(0);
sandbox.drawAudscii([65], 62, 84, 0x06, false, false);
assert.deepEqual(pixels,expectedGlyph(data[65],124,168));
assert.deepEqual(transform,[2,0,0,2,0,0]);

function expectedLegacy(table, codes, x, y, fixedWidth=false) {
    const target=new Uint8Array(128*176);
    let cursor=x*2;
    for (const code of codes) {
        const rows=table[code];
        const width=fixedWidth ? 6 : rows[0];
        for (let yy=0; yy<7; yy++) for (let xx=0; xx<6; xx++) if ((rows[yy+1]>>(5-xx))&1) {
            for (let sy=0; sy<2; sy++) for (let sx=0; sx<2; sx++) target[(y*2+2+yy*2+sy)*128+cursor+xx*2+sx]=1;
        }
        cursor+=width*2;
    }
    return target;
}

// Explicit legacy selection retains each original low-resolution table.
assert.equal(sandbox.setFontResolution('legacy'),true);
for (const [font,flags] of [['FIXED',0x02],['PROP',0x06],['GRAPHICS',0x0A]]) {
    pixels.fill(0);
    sandbox.drawAudscii([1,3],0,27,flags,false,false);
    const table=vm.runInContext(`FONT_DATA_${font}`,sandbox);
    assert.deepEqual(pixels,expectedLegacy(table,[1,3],0,27),`Selected low-resolution ${font}`);
}
assert.equal(sandbox.setFontResolution('unsupported'),false);
assert.equal(vm.runInContext('fontResolution',sandbox),'legacy');

// Color/tint does not choose font geometry in either direction.
sandbox.currentDisColor='red';
pixels.fill(0);
sandbox.drawText('A',0,27,0x06);
assert.deepEqual(pixels,expectedLegacy(vm.runInContext('FONT_DATA_PROP',sandbox),[65],0,27));
assert.equal(sandbox.setFontResolution('native'),true);
pixels.fill(0);
sandbox.drawText('A',0,27,0x06);
assert.deepEqual(pixels,expectedGlyph(data[65],0,54),'Red tint still permits native font geometry');
sandbox.currentDisColor='white';

// Missing or ambiguous entries are marked per font, not assigned fake metrics.
const missing=sandbox.NATIVE_FONT_DATA.fonts.fixed.glyphs.find(g=>!['verified','observed_blank'].includes(g.status));
if (missing) {
    pixels.fill(0);logs.length=0;
    sandbox.drawAudscii([missing.code],0,27,0x02,false,false);
    assert.deepEqual(pixels,expectedLegacy(vm.runInContext('FONT_DATA_FIXED',sandbox),[missing.code],0,27));
    assert.match(logs[0], /Native fixed.*legacy fallback.*metrics unavailable/);
    assert.equal(sandbox.NativeFont.measureCodes('fixed',[missing.code]).advancePx,null);
}

// Top-service fixed-width proportional bytes still use6 logical-pixel cells.
pixels.fill(0);
sandbox.drawAudscii([65,65],0,3,0x06,true,false);
let legacy=vm.runInContext('FONT_DATA_PROP[65]',sandbox);
expected=new Uint8Array(128*176);
for (let i=0; i<2; i++) for (let yy=0; yy<7; yy++) for (let xx=0; xx<6; xx++) if ((legacy[yy+1]>>(5-xx))&1) {
    for (let sy=0; sy<2; sy++) for (let sx=0; sx<2; sx++) expected[(8+yy*2+sy)*128+i*12+xx*2+sx]=1;
}
assert.deepEqual(pixels,expected,'Fixed-width top text retains the original legacy path');

// Unicode-to-byte conversion must match direct raw rendering in all families.
const specialMappings=[['¼',0xBC],['½',0xBD],['¾',0xBE],['↑',0x18],['↓',0x19],['→',0x1A],['←',0x1B]];
for (const resolution of ['native','legacy']) {
    sandbox.setFontResolution(resolution);
    for (const flags of [0x02,0x06,0x0A]) {
        for (const [character,code] of specialMappings) {
            pixels.fill(0);sandbox.drawAudscii([code],1,27,flags,false,false);
            const rawPixels=pixels.slice();
            pixels.fill(0);sandbox.drawText(character,1,27,flags);
            assert.deepEqual(pixels,rawPixels,`${resolution}/flags${flags.toString(16)} ${character}`);
        }
        // A surrogate pair is one unsupported character and one space advance.
        for (const centered of [0,0x20]) {
            pixels.fill(0);sandbox.drawText('A B',0,27,flags|centered);
            const expectedBlank=pixels.slice();
            pixels.fill(0);sandbox.drawText('A🙂B',0,27,flags|centered);
            assert.deepEqual(pixels,expectedBlank,`${resolution} one Unicode blank / centered${centered}`);
        }
    }
}
assert.deepEqual(Array.from(sandbox.AUDSCII_MAPPING.encodeText('iä\0\t\x1c\x1e\x1f')),[9,0x91,0,0x2F,0x1C,0xD7,0x65]);
assert.deepEqual(Array.from(sandbox.AUDSCII_MAPPING.encodeText('¼½¾↑↓→←🙂')),[0xBC,0xBD,0xBE,0x18,0x19,0x1A,0x1B,0x20]);

console.log(`Native emulator: ${JSON.stringify(counts)} (${verified} exact masks), explicit legacy selection, independent tint, font fallback and geometry PASS`);
