/* RNV3 block modes shared by the encoder and the reference decoder (bit-exact).
 *
 * LAT: soft block.  Luma comes from a lattice of points shared with neighbouring blocks, bilinear in between: no block edges, and what an
 * overloaded frame loses is sharpness instead of turning into a mosaic.  Three densities: LAT8 (corners), LAT4 (3x3), LAT2 (5x5).
 * Chroma: LAT8 and LAT4 use corners, LAT2 uses 3x3.
 * LAT8 and LAT4 add a screen-locked 2x2 ordered dither to luma when the frame header asks for it, so a gradient on the 6-bit panel costs no bits.
 *
 * BTC: tone block for text and icons.  BTC2: 2 colours, 1 bit per pixel.  BTC4: 4 colours on a line, 2 bits per pixel.
 * Chroma of a pixel pair follows the pair's indices.  Sharp, no ringing, and cheaper to decode than RAW.
 */
#ifndef RNV3_MODES_H
#define RNV3_MODES_H
#include <stdint.h>

enum { M_SKIP = 0, M_MC, M_MCR, M_ZRES, M_INTRA, M_RAW, M_LAT8, M_LAT4, M_LAT2, M_BTC4, M_BTC2, M_COUNT };

static inline int lat_rup(int a, int b) { return (a + b + 1) >> 1; }
static inline int lat_rdn(int a, int b) { return (a + b) >> 1; }
static const uint8_t LAT_DITH[2][2] = {{0, 2}, {3, 1}};
#define LAT_DITH_BASE 2   /* subtracted before the pattern; lattice luma is kept in LAT_YMIN..LAT_YMAX on dithering frames */
#define LAT_YMIN 2
#define LAT_YMAX 252

/* Reconstruction, defined on YUY2 words (Y0<<24 | Cb<<16 | Y1<<8 | Cr), so the decoder's cost is a few word averages per row.  All of it is bit-exact with the SH-4A code.
 *   LV_U rounds up, LV_D rounds down.  LAT8 and LAT4: rows 0, 4, 8 are built, rows 2, 6 are averages of those, each odd row repeats the row above; luma flat over a pixel pair.  Cost measured on the SH: that is what makes them cheap.
 *   LAT8: 4 corner words.  LAT4: 3x3 lattice words.  LAT2: 5x5 luma on every even row, chroma 3x3, odd rows averaged. */
#define LV_U(a, b) (((a) | (b)) - ((((a) ^ (b)) >> 1) & 0x7F7F7F7Fu))
#define LV_D(a, b) (((a) & (b)) + (((a) ^ (b)) >> 1 & 0x7F7F7F7Fu))
#define LAT_CW(cb, cr) (((uint32_t)(cb) << 16) | (uint32_t)(cr))
#define LAT_YW(y) (((uint32_t)(y) << 24) | ((uint32_t)(y) << 8))
static inline void lat_finish(uint32_t r[3][4], int dith, uint32_t *w) {
    int i;
    for (i = 0; i < 4; i++) {
        uint32_t a = r[0][i], c = r[1][i], e = r[2][i], b = LV_D(a, c), d = LV_D(c, e);
        w[i] = a; w[4 + i] = a; w[8 + i] = b; w[12 + i] = b; w[16 + i] = c; w[20 + i] = c; w[24 + i] = d; w[28 + i] = d; (void)e;
    }
    if (dith) { for (i = 0; i < 32; i += 8) { int k; for (k = 0; k < 4; k++) { w[i + k] += (uint32_t)LAT_DITH[0][0] << 24 | (uint32_t)LAT_DITH[0][1] << 8; w[i + 4 + k] += (uint32_t)LAT_DITH[1][0] << 24 | (uint32_t)LAT_DITH[1][1] << 8; } } }
}
/* y[]: corners TL TR BL BR, cb / cr the same */
static inline void lat8_words(const int y[4], const int cb[4], const int cr[4], int dith, uint32_t *w) {
    int b = dith ? LAT_DITH_BASE : 0, i; uint32_t P[4], r[3][4], ae[3][2];
    for (i = 0; i < 4; i++) P[i] = LAT_YW(y[i] - b) | LAT_CW(cb[i], cr[i]);
    ae[0][0] = P[0]; ae[0][1] = P[1]; ae[2][0] = P[2]; ae[2][1] = P[3]; ae[1][0] = LV_U(P[0], P[2]); ae[1][1] = LV_U(P[1], P[3]);
    for (i = 0; i < 3; i++) { uint32_t A = ae[i][0], E = ae[i][1], m = LV_D(A, E); r[i][0] = A; r[i][1] = LV_U(A, m); r[i][2] = m; r[i][3] = LV_U(m, E); }
    lat_finish(r, dith, w);
}
/* y: 3x3 lattice, cb / cr: corners */
static inline void lat4_words(const int y[3][3], const int cb[4], const int cr[4], int dith, uint32_t *w) {
    int b = dith ? LAT_DITH_BASE : 0, i, j; uint32_t C[3][3], L[3][3], r[3][4];
    C[0][0] = LAT_CW(cb[0], cr[0]); C[0][2] = LAT_CW(cb[1], cr[1]); C[2][0] = LAT_CW(cb[2], cr[2]); C[2][2] = LAT_CW(cb[3], cr[3]);
    C[0][1] = LV_U(C[0][0], C[0][2]); C[2][1] = LV_U(C[2][0], C[2][2]); C[1][0] = LV_U(C[0][0], C[2][0]); C[1][2] = LV_U(C[0][2], C[2][2]); C[1][1] = LV_U(C[1][0], C[1][2]);
    for (i = 0; i < 3; i++) for (j = 0; j < 3; j++) L[i][j] = LAT_YW(y[i][j] - b) | C[i][j];
    for (i = 0; i < 3; i++) {
        uint32_t a = L[i][0], m = L[i][1], e = L[i][2];
        r[i][0] = a; r[i][1] = LV_U(a, m); r[i][2] = m; r[i][3] = LV_U(m, e);
    }
    lat_finish(r, dith, w);
}
/* G: 5x5 luma (2 px spacing), cb / cr: 3x3 */
static inline void lat2_words(const int G[5][5], const int cb[3][3], const int cr[3][3], uint32_t *w) {
    int i, k; uint32_t C[3][3], cw[5][4], rw[5][4];
    for (i = 0; i < 3; i++) for (k = 0; k < 3; k++) C[i][k] = LAT_CW(cb[i][k], cr[i][k]);
    for (i = 0; i < 3; i++) { cw[2 * i][0] = C[i][0]; cw[2 * i][1] = LV_U(C[i][0], C[i][1]); cw[2 * i][2] = C[i][1]; cw[2 * i][3] = LV_U(C[i][1], C[i][2]); }
    for (k = 0; k < 4; k++) { cw[1][k] = LV_D(cw[0][k], cw[2][k]); cw[3][k] = LV_D(cw[2][k], cw[4][k]); }
    for (i = 0; i < 5; i++) for (k = 0; k < 4; k++) rw[i][k] = ((uint32_t)G[i][k] << 24) | ((uint32_t)lat_rup(G[i][k], G[i][k + 1]) << 8) | cw[i][k];
    for (i = 0; i < 4; i++) for (k = 0; k < 4; k++) { w[8 * i + k] = rw[i][k]; w[8 * i + 4 + k] = LV_U(rw[i][k], rw[i + 1][k]); }
}
/* BTC palettes.  BTC4 luma levels i = 0..3 and chroma for i0 + i1 = 0..6 */
static inline void btc4_y(int y0, int y3, int Y[4]) { Y[0] = y0; Y[3] = y3; Y[1] = (5 * y0 + 3 * y3 + 4) >> 3; Y[2] = (3 * y0 + 5 * y3 + 4) >> 3; }
static inline void btc4_c(int c0, int c3, int C[7]) {
    /* s = i0 + i1: weights in eighths so the decoder needs only shifts and adds */
    static const uint8_t W3[7] = {0, 1, 3, 4, 5, 7, 8};
    int s; for (s = 0; s < 7; s++) C[s] = ((8 - W3[s]) * c0 + W3[s] * c3 + 4) >> 3;
}
/* BTC2: a mixed pair takes the rounded mean chroma */
static inline int btc2_c(int a, int b, int s) { return s == 0 ? a : s == 2 ? b : (a + b + 1) >> 1; }
#endif
