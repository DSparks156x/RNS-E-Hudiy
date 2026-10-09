// Exercise the actual emulator renderer with a physical-pixel canvas model.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const repo = process.argv[2] || path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(repo, 'dis_emulator/templates/index.html'), 'utf8');
for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
    new vm.Script(match[1]); // Parse the whole page, not just extracted helpers.
}
assert.match(html, /backBuffer\.width = 128/);
assert.match(html, /backBuffer\.height = 176/);
const pixels = new Uint8Array(128 * 176);
let transform = [2, 0, 0, 2, 0, 0];
let stack = [], presents = 0;
const context = {
    fillStyle: 'black',
    setTransform(...values) { transform = values; },
    save() { stack.push([transform.slice(), this.fillStyle]); },
    restore() { [transform, this.fillStyle] = stack.pop(); },
    fillRect(x, y, width, height) {
        const [sx, , , sy, dx, dy] = transform;
        const left = x*sx+dx, top = y*sy+dy;
        const right = left+width*sx, bottom = top+height*sy;
        for (let yy = Math.max(0, Math.ceil(top)); yy < Math.min(176, Math.ceil(bottom)); yy++) {
            for (let xx = Math.max(0, Math.ceil(left)); xx < Math.min(128, Math.ceil(right)); xx++) {
                pixels[yy*128+xx] = this.fillStyle === 'black' ? 0 : 1;
            }
        }
    },
};
const sandbox = {
    bCtx: context, ctx: {drawImage() { presents++; }}, backBuffer: {},
    currentDisColor: 'white', REG_Y: 27, currentRegion: 'central',
    lastAction: {}, currentCommandSet: [], fpsCount: 0,
    addCommandLog() {}, addLog() {}, drawDividers() {}, updateLastCommandSet() {},
};
vm.createContext(sandbox);
const handler = html.slice(html.indexOf('function handleCommand(cmd)'), html.indexOf('// App Theme State'));
const line = html.slice(html.indexOf('function drawLine(x,'), html.indexOf('window.onload ='));
vm.runInContext(handler + line, sandbox);

// Native upper-left and lower-right physical pixels, including the bottom row.
const source = Buffer.alloc(1536);
source[0] = 0x80;
source[1535] = 0x01;
sandbox.handleCommand({command: 'draw_native_bitmap', data_hex: source.toString('hex')});
assert.equal(pixels[54*128], 1);
assert.equal(pixels[149*128+127], 1);
assert.equal(pixels.reduce((a,b) => a+b, 0), 2);
assert.deepEqual(transform, [2,0,0,2,0,0]);
assert.equal(presents, 0, 'Back buffer is not presented without commit');
sandbox.handleCommand({command:'commit'});
assert.equal(presents, 1);

// Validation happens before modifying the existing snapshot.
sandbox.handleCommand({command:'draw_native_bitmap', data_hex:'zz'.repeat(1536)});
assert.equal(pixels.reduce((a,b) => a+b, 0), 2);

// Ordinary coordinates still map to logical2x2 cells; clear resets native bits.
sandbox.handleCommand({command:'clear_payload'});
assert.equal(pixels.reduce((a,b) => a+b, 0), 0);
sandbox.handleCommand({command:'draw_line', x:3, y:2, length:2, vertical:true});
assert.equal(pixels.reduce((a,b) => a+b, 0), 4);
assert.equal(pixels[58*128+6], 1);
assert.equal(pixels[58*128+7], 0, 'Vertical line is one physical pixel wide');
sandbox.handleCommand({command:'clear_payload'});
sandbox.handleCommand({command:'draw_line', x:3, y:2, length:2, vertical:false});
assert.equal(pixels.reduce((a,b) => a+b, 0), 4);
assert.equal(pixels[59*128+6], 0, 'Horizontal line is one physical pixel tall');
// Execute the real atomic text handler. The old field is wiped before text
// enters the back buffer, without presenting the intermediate cleared state.
const textCalls = [];
pixels.fill(1);
sandbox.drawText = (text, x, y, flags) => {
    assert.equal(pixels[60*128+4], 0, 'Previous footprint cleared before replacement');
    assert.equal(pixels[60*128+122], 1, 'Adjacent approach bar survives text cleanup');
    textCalls.push({text, x, y, flags});
    context.fillStyle = 'white';
    context.fillRect(x, y, 2, 2);
};
const beforeText = presents;
sandbox.handleCommand({command:'update_text', text:'Hi', x:4, y:3, flags:0x26,
    clear_rect:{x:2,y:3,w:12,h:9}});
assert.deepEqual(textCalls, [{text:'Hi',x:4,y:30,flags:0x26}]);
assert.equal(pixels[60*128+8], 1, 'Replacement drawn into the wiped field');
assert.equal(presents, beforeText, 'Atomic text does not imply a commit');
sandbox.handleCommand({command:'commit'});
assert.equal(presents, beforeText+1);

// Removing a field only clears it. An overwrite with no cleanup skips the wipe.
sandbox.handleCommand({command:'update_text', text:'', clear_rect:{x:2,y:3,w:12,h:9}});
assert.equal(textCalls.length, 1);
assert.equal(pixels[60*128+8], 0);
sandbox.handleCommand({command:'update_text', text:'Next', x:4, y:3});
assert.deepEqual(textCalls[1], {text:'Next',x:4,y:30,flags:6});
assert.equal(presents, beforeText+1, 'Only explicit commit presents text');
console.log('Emulator: native pixels, validation, explicit commit, physical lines and atomic text cleanup PASS');
