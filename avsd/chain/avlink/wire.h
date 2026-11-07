/* wire.h -- SD DAT wire images (SPEC 1.5), bit-identical to link/sd_wire.py wire4()/wire1().
 * 4-bit image: 132 LE words = 528 B. 1-bit image: 130 words = 520 B. No trailing pad word (the Teensy adds it). */
#ifndef AVL_WIRE_H
#define AVL_WIRE_H
#include <stdint.h>

#define WIRE4_WORDS 132
#define WIRE1_WORDS 130
#define WIRE4_BYTES (WIRE4_WORDS * 4)
#define WIRE1_BYTES (WIRE1_WORDS * 4)

void wire_init(void);                               /* after crc_init() */
void wire4_sector(const uint8_t *blk, uint32_t *w);   /* blk: 512 B, w: WIRE4_WORDS */
void wire1_sector(const uint8_t *blk, uint32_t *w);   /* w: WIRE1_WORDS */

#endif
