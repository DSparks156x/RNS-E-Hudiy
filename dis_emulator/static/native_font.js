// Shared native-pixel font access for the emulator and standalone AUDSCII helper.
(function(root, factory) {
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = factory(require('./native_font_data.js'));
    } else {
        root.NativeFont = factory(root.NATIVE_FONT_DATA);
    }
})(typeof globalThis !== 'undefined' ? globalThis : this, function(data) {
    'use strict';
    const bitmaps = new WeakMap();

    function getGlyph(font, code) {
        const entries = data && data.fonts && data.fonts[font];
        if (!entries || !Number.isInteger(code) || code < 0 || code > 255) return null;
        return entries.glyphs[code] || null;
    }

    function forEachPixel(glyph, callback) {
        if (!glyph || glyph.status !== 'verified' || !glyph.mask_hex || !glyph.size) return;
        let bytes = bitmaps.get(glyph);
        if (!bytes) {
            bytes = Uint8Array.from(glyph.mask_hex.match(/../g), value => parseInt(value, 16));
            bitmaps.set(glyph, bytes);
        }
        const [width, height] = glyph.size;
        const stride = Math.ceil(width / 8);
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                if (bytes[y * stride + (x >> 3)] & (0x80 >> (x & 7))) callback(x, y);
            }
        }
    }

    function measureCodes(font, codes) {
        let knownAdvancePx = 0;
        const unknownCodes = [];
        for (const code of codes) {
            const glyph = getGlyph(font, code);
            if (glyph && (glyph.status === 'verified' || glyph.status === 'observed_blank') &&
                Number.isFinite(glyph.advance_px) && glyph.advance_px >= 0) {
                knownAdvancePx += glyph.advance_px;
            } else if (!unknownCodes.includes(code)) unknownCodes.push(code);
        }
        return {advancePx: unknownCodes.length ? null : knownAdvancePx, knownAdvancePx, unknownCodes};
    }

    return Object.freeze({getGlyph, forEachPixel, measureCodes});
});
