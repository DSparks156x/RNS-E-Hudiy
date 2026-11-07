/* rnv2enc hot kernels: one scalar reference set and one NEON set with IDENTICAL results.
 *
 * Block layout used everywhere inside the encoder ("SB layout", 128 bytes per 8x8 block):
 *   8 subblocks x 16 bytes, subblock s at offset 16*s, raster 4x4 inside:
 *   s0 Y rows0-3 cols0-3, s1 Y rows0-3 cols4-7, s2 Y rows4-7 cols0-3, s3 Y rows4-7 cols4-7,
 *   s4 Cb rows0-3, s5 Cb rows4-7, s6 Cr rows0-3, s7 Cr rows4-7   (chroma blocks are 4 wide x 8 tall).
 * This is exactly the RNV2 residual subblock order (cbp bit s).
 */
#ifndef RNV2_KERN_H
#define RNV2_KERN_H
#include <stdint.h>
#include <stddef.h>

typedef struct {
    const char *name;
    /* glass-aware RGB->YUY2 for npairs pixel pairs. rgb = packed RGB24 (6 bytes per pair). */
    void (*csc_glass)(const uint8_t *rgb, int npairs, uint8_t *Y, uint8_t *U, uint8_t *V);
    /* 8x8 SAD on u8 planes */
    uint32_t (*sad8x8)(const uint8_t *a, int as, const uint8_t *b, int bs);
    /* perceptual distortion per subblock, unweighted: sum 16*e^2 + kappa16*max(0,|e|-thr)^2 */
    void (*pd8)(const uint8_t *s, const uint8_t *r, int kappa16, int thr, uint32_t out[8]);
    /* forward 4x4 WHT (unscaled H X H) of residual s-p for all 8 subblocks; T[s*16+k] */
    void (*fwd8)(const uint8_t *s, const uint8_t *p, int16_t *T);
    /* quantise 8x16 WHT coefs: L = sign(T) * min(2047, (|T| * A + B) >> S), |T| <= 4080, A <= 65535, no u32 overflow; returns the
       mask of subblocks with any nonzero level */
    int (*quant8)(const int16_t *T, uint32_t A, uint32_t B, int S, int16_t *L);
    /* inverse WHT of dequantised coefs c[16] (int32): r = (H C H + 2) >> 2 */
    void (*iwht)(const int32_t *c, int32_t *r);
    /* rec = clamp(p + R) for the subblocks set in mask, rec = p elsewhere (R: 8x16 int32) */
    void (*addclamp)(const uint8_t *p, const int32_t *R, int mask, uint8_t *rec);
    /* half-pel row: h[x]=avg(a[x],a[x+1]) (h[w-1]=a[w-1]); v[x]=avg(a[x],b[x]); hv[x]=avg(h_a[x],h_b[x]).
       b = next row (or a itself for the last row). avg = (x+y+1)>>1 */
    void (*halfpel_row)(const uint8_t *a, const uint8_t *b, int w, uint8_t *h, uint8_t *v, uint8_t *hv);
    /* projections: rows[y*nsx+k] += sum of row y over strip k (strip width sw, nsx strips); cols[x] += column sum */
    void (*proj_rows)(const uint8_t *p, int stride, int w, int h, int sw, uint32_t *rows, uint32_t *cols);
} rnv2_kern;

extern const rnv2_kern rnv2_kern_scalar;
#if defined(__ARM_NEON) || defined(RNV_NEON_EMU)
#define RNV2_HAVE_NEON 1
extern const rnv2_kern rnv2_kern_neon;
#endif

/* shared constants for the glass CSC (fixed point, 16 fractional bits) */
void rnv2_csc_init(void);
extern int32_t RNV2_LSU[6], RNV2_LSV[6];   /* least-squares rows for u and v from (r0 g0 b0 r1 g1 b1) */

#endif
