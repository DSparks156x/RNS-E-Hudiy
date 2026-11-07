/* crc.c -- see crc.h. No zlib dependency (Pi OS Lite has no zlib1g-dev by default). */
#include "crc.h"
#if defined(__aarch64__)
#include <arm_acle.h>
#include <string.h>
#endif

static uint32_t crc32_tab[256];
uint16_t crc16_tab[256];

void crc_init(void)
{
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t v = i;
        for (int k = 0; k < 8; k++) v = (v >> 1) ^ (0xEDB88320u & (0u - (v & 1u)));
        crc32_tab[i] = v;
        uint32_t c = i << 8;
        for (int k = 0; k < 8; k++) c = (c & 0x8000u) ? ((c << 1) ^ 0x1021u) : (c << 1);
        crc16_tab[i] = (uint16_t)c;
    }
}

#if defined(__aarch64__)
/* ARMv8 CRC32 instructions use this same polynomial. Every Pi 5 has them (/proc/cpuinfo: crc32). */
__attribute__((target("+crc")))
uint32_t crc32z(uint32_t c, const void *vp, size_t n)
{
    const uint8_t *p = (const uint8_t *)vp;
    c = ~c;
    for (; n >= 8; n -= 8, p += 8) { uint64_t v; memcpy(&v, p, 8); c = __crc32d(c, v); }
    while (n--) c = __crc32b(c, *p++);
    return ~c;
}
#else
uint32_t crc32z(uint32_t c, const void *vp, size_t n)
{
    const uint8_t *p = (const uint8_t *)vp;
    c = ~c;
    while (n--) c = (c >> 8) ^ crc32_tab[(c ^ *p++) & 0xFF];
    return ~c;
}
#endif

uint16_t crc16_sd(const uint8_t *p, size_t n)
{
    uint16_t c = 0;
    while (n--) c = crc16_byte(c, *p++);
    return c;
}
