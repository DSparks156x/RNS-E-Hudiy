/* Fixed-point constants of the glass-aware CSC (shared by the scalar and NEON paths; 16 fractional bits).
 * Model: the decoder side (DU) converts YUY2 -> RGB with BT.601 full range, nearest chroma, then the panel keeps
 * 6 bits per channel (q666 = bit-replicated 6-bit).  Same model as rnv2.py rgb_to_yuy2_glass. */
#ifndef RNV2_CSC_COMMON_H
#define RNV2_CSC_COMMON_H
#define CL255(x) ((x) < 0 ? 0 : (x) > 255 ? 255 : (x))
#define Q6(x) (((x) & 0xFC) | ((x) >> 6))
/* Cb/Cr of one pixel minus 128, scaled 2^16 (coefficient sums are exactly 0 so grey -> 0) */
#define CBF(r, g, b) (-11058 * (r) - 21710 * (g) + 32768 * (b))
#define CRF(r, g, b) (32768 * (r) - 27439 * (g) - 5329 * (b))
/* rounded channel offsets of the YCbCr->RGB matrix for integer chroma uu, vv (= u-128, v-128) */
#define OR_(vv) ((91881 * (vv) + 32768) >> 16)
#define OG_(uu, vv) ((-22554 * (uu) - 46802 * (vv) + 32768) >> 16)
#define OB_(uu) ((116130 * (uu) + 32768) >> 16)
/* sum of the three (unrounded) offsets, 2^16: (1.402-0.714136) vv + (1.772-0.344136) uu */
#define SOFF(uu, vv) (45080 * (vv) + 93576 * (uu))
/* y = clip(round((S - soff) / 3)), S = r+g+b; exact floor division by 3 via multiply (valid for the range used) */
#define YFROM(S, so) CL255((((((((S) << 16) - (so) + 98304) >> 16) + 384) * 21846) >> 16) - 128)
#endif
