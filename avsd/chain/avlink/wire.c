/* wire.c -- see wire.h. Per-line CRC16 by table: for 4 data bytes, line k gets one byte made of the
 * (bit 4+k, bit k) pairs of each byte, first byte in the top bits; that byte goes through the normal
 * MSB-first CRC16 byte table. ~1 table lookup per data byte and line: ~10k sectors/s is a few % of one A76. */
#include "wire.h"
#include "crc.h"

static uint32_t spread[256];    /* byte b -> line k pair (bit 4+k << 1 | bit k) in byte lane k */
static uint8_t bitrev[256];

void wire_init(void)
{
    for (int b = 0; b < 256; b++) {
        uint32_t s = 0;
        for (int k = 0; k < 4; k++) s |= (uint32_t)((((b >> (4 + k)) & 1) << 1) | ((b >> k) & 1)) << (8 * k);
        spread[b] = s;
        uint8_t r = 0;
        for (int i = 0; i < 8; i++) if (b & (1 << i)) r |= (uint8_t)(0x80 >> i);
        bitrev[b] = r;
    }
}

static inline uint32_t nibswap8(uint32_t b) { return ((b & 0x0F) << 4) | (b >> 4); }

void wire4_sector(const uint8_t *blk, uint32_t *w)
{
    uint16_t c0 = 0, c1 = 0, c2 = 0, c3 = 0;
    w[0] = 0x0FFFFFFFu;                                   /* 7 idle nibbles, then the start nibble 0 */
    for (int i = 0; i < 512; i += 4) {
        uint32_t b0 = blk[i], b1 = blk[i + 1], b2 = blk[i + 2], b3 = blk[i + 3];
        w[1 + i / 4] = nibswap8(b0) | (nibswap8(b1) << 8) | (nibswap8(b2) << 16) | (nibswap8(b3) << 24);
        uint32_t L = (spread[b0] << 6) | (spread[b1] << 4) | (spread[b2] << 2) | spread[b3];
        c0 = crc16_byte(c0, (uint8_t)L);
        c1 = crc16_byte(c1, (uint8_t)(L >> 8));
        c2 = crc16_byte(c2, (uint8_t)(L >> 16));
        c3 = crc16_byte(c3, (uint8_t)(L >> 24));
    }
    uint32_t a = 0, b = 0;
    for (int j = 0; j < 16; j++) {                        /* CRC MSB first on all four lines at once */
        int bit = 15 - j;
        uint32_t nib = ((c0 >> bit) & 1u) | (((c1 >> bit) & 1u) << 1) | (((c2 >> bit) & 1u) << 2) | (((c3 >> bit) & 1u) << 3);
        if (j < 8) a |= nib << (4 * j); else b |= nib << (4 * (j - 8));
    }
    w[129] = a; w[130] = b;
    w[131] = 0xFFFFFFFFu;                                 /* end nibble F, then idle */
}

void wire1_sector(const uint8_t *blk, uint32_t *w)
{
    w[0] = 0x7FFFFFFFu;                                   /* 31 idle bits, then the start bit */
    for (int i = 0; i < 512; i += 4)
        w[1 + i / 4] = (uint32_t)bitrev[blk[i]] | ((uint32_t)bitrev[blk[i + 1]] << 8) |
                       ((uint32_t)bitrev[blk[i + 2]] << 16) | ((uint32_t)bitrev[blk[i + 3]] << 24);
    uint16_t c = crc16_sd(blk, 512);
    uint32_t r = ((uint32_t)bitrev[c & 0xFF] << 8) | bitrev[c >> 8];   /* bitrev16 */
    w[129] = r | 0xFFFF0000u;                             /* CRC16 MSB first, end bit, idle */
}
