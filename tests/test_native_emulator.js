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
console.log('Emulator: page syntax, native pixels, validation, commit, logical restore and physical line geometry PASS');
