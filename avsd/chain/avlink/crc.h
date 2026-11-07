/* crc.h -- zlib CRC-32 (container CRCs, SPEC 3.2) and SD CRC16-CCITT tables (wire images, SPEC 1.5). */
#ifndef AVL_CRC_H
#define AVL_CRC_H
#include <stdint.h>
#include <stddef.h>

void crc_init(void);                                         /* builds all tables; call once */
uint32_t crc32z(uint32_t c, const void *p, size_t n);        /* zlib crc32(); start with c = 0, chainable */
extern uint16_t crc16_tab[256];                              /* poly 0x1021, init 0, MSB first, per byte */
static inline uint16_t crc16_byte(uint16_t c, uint8_t x) { return (uint16_t)((c << 8) ^ crc16_tab[((c >> 8) ^ x) & 0xFF]); }
uint16_t crc16_sd(const uint8_t *p, size_t n);

#endif
