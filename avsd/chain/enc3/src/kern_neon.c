/* rnv2enc NEON kernels (AArch64 / ARMv8 ASIMD).  Results are bit-identical to kern_scalar.c (make test).
 * On x86 the same source compiles against src/neon_emu.h (-DRNV_NEON_EMU) so the logic can be checked without
 * an ARM machine; the real proof is `make test` on the Pi. */
#include "kern.h"
#ifdef RNV2_HAVE_NEON
#ifdef __ARM_NEON
#include <arm_neon.h>
#else
#include "neon_emu.h"
/* the intrinsics only csc8 uses (real ones on ARM) */
#define E_ static inline
#define LP_(N) for (int i = 0; i < (N); i++)
E_ uint8x16_t vqtbl1q_u8(uint8x16_t t, uint8x16_t x) { uint8x16_t r; LP_(16) r.v[i] = x.v[i] < 16 ? t.v[x.v[i]] : 0; return r; }
E_ uint8x16_t vsriq_n_u8(uint8x16_t a, uint8x16_t b, int n) { uint8x16_t r; LP_(16) r.v[i] = (uint8_t)((a.v[i] & ~(0xFF >> n)) | (b.v[i] >> n)); return r; }
E_ uint16x8_t vaddl_u8(uint8x8_t a, uint8x8_t b) { uint16x8_t r; LP_(8) r.v[i] = (uint16_t)(a.v[i] + b.v[i]); return r; }
E_ uint16x8_t vaddw_u8(uint16x8_t a, uint8x8_t b) { LP_(8) a.v[i] = (uint16_t)(a.v[i] + b.v[i]); return a; }
E_ uint16x8_t vld1q_u16(const uint16_t *p) { uint16x8_t r; memcpy(r.v, p, 16); return r; }
E_ uint32x4_t vshll_n_u16(uint16x4_t a, int n) { uint32x4_t r; LP_(4) r.v[i] = (uint32_t)a.v[i] << n; return r; }
E_ uint32x4_t vsubq_u32(uint32x4_t a, uint32x4_t b) { LP_(4) a.v[i] -= b.v[i]; return a; }
E_ uint32x4_t vsubl_u16(uint16x4_t a, uint16x4_t b) { uint32x4_t r; LP_(4) r.v[i] = (uint32_t)a.v[i] - b.v[i]; return r; }
E_ uint16x4_t vdup4u_(uint16_t x) { uint16x4_t r; LP_(4) r.v[i] = x; return r; }
#define vmull_laneq_u16(a, c, l) vmull_u16((a), vdup4u_((c).v[l]))
#define vmlal_laneq_u16(d, a, c, l) vmlal_u16((d), (a), vdup4u_((c).v[l]))
E_ uint16x8_t vpaddlq_u8(uint8x16_t a) { uint16x8_t r; LP_(8) r.v[i] = (uint16_t)(a.v[2 * i] + a.v[2 * i + 1]); return r; }
E_ uint16x8_t vaddl_high_u8(uint8x16_t a, uint8x16_t b) { uint16x8_t r; LP_(8) r.v[i] = (uint16_t)(a.v[i + 8] + b.v[i + 8]); return r; }
E_ uint16x8_t vaddw_high_u8(uint16x8_t a, uint8x16_t b) { LP_(8) a.v[i] = (uint16_t)(a.v[i] + b.v[i + 8]); return a; }
E_ uint32x4_t vshll_high_n_u16(uint16x8_t a, int n) { uint32x4_t r; LP_(4) r.v[i] = (uint32_t)a.v[i + 4] << n; return r; }
E_ uint32x4_t vsubl_high_u16(uint16x8_t a, uint16x8_t b) { uint32x4_t r; LP_(4) r.v[i] = (uint32_t)a.v[i + 4] - b.v[i + 4]; return r; }
#define vmull_high_laneq_u16(a, c, l) vmull_u16(vget_high_u16(a), vdup4u_((c).v[l]))
#define vmlal_high_laneq_u16(d, a, c, l) vmlal_u16((d), vget_high_u16(a), vdup4u_((c).v[l]))
E_ int32x4_t emu_mull_s16(int16x4_t a, int16_t b) { int32x4_t r; LP_(4) r.v[i] = (int32_t)a.v[i] * b; return r; }
E_ int32x4_t emu_mlal_s16(int32x4_t d, int16x4_t a, int16_t b) { LP_(4) d.v[i] = (int32_t)((uint32_t)d.v[i] + (uint32_t)((int32_t)a.v[i] * b)); return d; }
#define vmull_laneq_s16(a, c, l) emu_mull_s16((a), (c).v[l])
#define vmlal_laneq_s16(d, a, c, l) emu_mlal_s16((d), (a), (c).v[l])
E_ int16x4_t vrshrn_n_s32(int32x4_t a, int n) { int16x4_t r; LP_(4) r.v[i] = (int16_t)(((int64_t)a.v[i] + (1LL << (n - 1))) >> n); return r; }
E_ uint16x4_t vqrshrun_n_s32(int32x4_t a, int n) { uint16x4_t r; LP_(4) { int64_t x = ((int64_t)a.v[i] + (1LL << (n - 1))) >> n; r.v[i] = (uint16_t)(x < 0 ? 0 : x > 65535 ? 65535 : x); } return r; }
E_ int16_t emu_sat16_(int64_t x) { return (int16_t)(x > 32767 ? 32767 : x < -32768 ? -32768 : x); }
E_ int16x8_t emu_qrdmulh_(int16x8_t a, int16_t b) { LP_(8) a.v[i] = emu_sat16_((2 * (int64_t)a.v[i] * b + 32768) >> 16); return a; }
E_ int16x8_t emu_qdmulh_(int16x8_t a, int16_t b) { LP_(8) a.v[i] = emu_sat16_((2 * (int64_t)a.v[i] * b) >> 16); return a; }
#define vqrdmulhq_laneq_s16(a, c, l) emu_qrdmulh_((a), (c).v[l])
#define vqdmulhq_laneq_s16(a, c, l) emu_qdmulh_((a), (c).v[l])
E_ uint16x8_t vqaddq_u16(uint16x8_t a, uint16x8_t b) { LP_(8) { uint32_t s = (uint32_t)a.v[i] + b.v[i]; a.v[i] = (uint16_t)(s > 65535 ? 65535 : s); } return a; }
E_ uint16x8_t vcltq_u16(uint16x8_t a, uint16x8_t b) { uint16x8_t r; LP_(8) r.v[i] = a.v[i] < b.v[i] ? 0xFFFF : 0; return r; }
E_ uint16x8_t veorq_u16(uint16x8_t a, uint16x8_t b) { LP_(8) a.v[i] ^= b.v[i]; return a; }
E_ uint8x16_t vqaddq_u8(uint8x16_t a, uint8x16_t b) { LP_(16) { int s = a.v[i] + b.v[i]; a.v[i] = (uint8_t)(s > 255 ? 255 : s); } return a; }
E_ uint8x16_t vbslq_u8(uint8x16_t m, uint8x16_t a, uint8x16_t b) { LP_(16) a.v[i] = (uint8_t)((m.v[i] & a.v[i]) | (~m.v[i] & b.v[i])); return a; }
E_ uint8x16_t vreinterpretq_u8_u16(uint16x8_t a) { uint8x16_t r; memcpy(&r, &a, sizeof r); return r; }
E_ uint8x16_t vuzp1q_u8(uint8x16_t a, uint8x16_t b) { uint8x16_t r; LP_(8) { r.v[i] = a.v[2 * i]; r.v[i + 8] = b.v[2 * i]; } return r; }
#undef E_
#undef LP_
#endif
#include <string.h>

/* ------------------------------------------------------------------ SAD / distortion */
static uint32_t sad8x8_n(const uint8_t *a, int as, const uint8_t *b, int bs) {
    uint16x8_t acc = vabdl_u8(vld1_u8(a), vld1_u8(b));
    int r;
    for (r = 1; r < 8; r++) acc = vabal_u8(acc, vld1_u8(a + r * as), vld1_u8(b + r * bs));
    return vaddlvq_u16(acc);
}

static void pd8_n(const uint8_t *s, const uint8_t *r, int kappa16, int thr, uint32_t out[8]) {
    const uint8x16_t T = vdupq_n_u8((uint8_t)thr);
    int sb;
    for (sb = 0; sb < 8; sb++) {
        uint8x16_t a = vabdq_u8(vld1q_u8(s + 16 * sb), vld1q_u8(r + 16 * sb)), m = vqsubq_u8(a, T);
#ifdef __ARM_FEATURE_DOTPROD
        uint32x4_t aa = vdotq_u32(vdupq_n_u32(0), a, a), mm = vdotq_u32(vdupq_n_u32(0), m, m);
#else
        uint32x4_t aa = vaddq_u32(vpaddlq_u16(vmull_u8(vget_low_u8(a), vget_low_u8(a))), vpaddlq_u16(vmull_high_u8(a, a)));
        uint32x4_t mm = vaddq_u32(vpaddlq_u16(vmull_u8(vget_low_u8(m), vget_low_u8(m))), vpaddlq_u16(vmull_high_u8(m, m)));
#endif
        out[sb] = vaddvq_u32(vaddq_u32(vshlq_n_u32(aa, 4), vmulq_n_u32(mm, (uint32_t)kappa16)));
    }
}

/* ------------------------------------------------------------------ WHT */
/* 4x4 transpose of two blocks at once: lanes 0-3 block A, lanes 4-7 block B */
static inline void tr4x2(int16x8_t *a0, int16x8_t *a1, int16x8_t *a2, int16x8_t *a3) {
    int16x8x2_t t01 = vtrnq_s16(*a0, *a1), t23 = vtrnq_s16(*a2, *a3);
    int32x4x2_t u02 = vtrnq_s32(vreinterpretq_s32_s16(t01.val[0]), vreinterpretq_s32_s16(t23.val[0]));
    int32x4x2_t u13 = vtrnq_s32(vreinterpretq_s32_s16(t01.val[1]), vreinterpretq_s32_s16(t23.val[1]));
    *a0 = vreinterpretq_s16_s32(u02.val[0]); *a2 = vreinterpretq_s16_s32(u02.val[1]);
    *a1 = vreinterpretq_s16_s32(u13.val[0]); *a3 = vreinterpretq_s16_s32(u13.val[1]);
}
static inline void bfly16(int16x8_t *a0, int16x8_t *a1, int16x8_t *a2, int16x8_t *a3) {
    int16x8_t s0 = vaddq_s16(*a0, *a1), s1 = vsubq_s16(*a0, *a1), t0 = vaddq_s16(*a2, *a3), t1 = vsubq_s16(*a2, *a3);
    *a0 = vaddq_s16(s0, t0); *a1 = vsubq_s16(s0, t0); *a2 = vsubq_s16(s1, t1); *a3 = vaddq_s16(s1, t1);
}
static void fwd8_n(const uint8_t *s, const uint8_t *p, int16_t *T) {
    int pr;
    for (pr = 0; pr < 4; pr++) {
        const uint8_t *sa = s + 32 * pr, *pa = p + 32 * pr;
        uint8x16_t SA = vld1q_u8(sa), SB = vld1q_u8(sa + 16), PA = vld1q_u8(pa), PB = vld1q_u8(pa + 16);
        int16x8_t A01 = vreinterpretq_s16_u16(vsubl_u8(vget_low_u8(SA), vget_low_u8(PA)));   /* A rows 0,1 */
        int16x8_t A23 = vreinterpretq_s16_u16(vsubl_u8(vget_high_u8(SA), vget_high_u8(PA))); /* A rows 2,3 */
        int16x8_t B01 = vreinterpretq_s16_u16(vsubl_u8(vget_low_u8(SB), vget_low_u8(PB)));
        int16x8_t B23 = vreinterpretq_s16_u16(vsubl_u8(vget_high_u8(SB), vget_high_u8(PB)));
        int16x8_t r0 = vcombine_s16(vget_low_s16(A01), vget_low_s16(B01));
        int16x8_t r1 = vcombine_s16(vget_high_s16(A01), vget_high_s16(B01));
        int16x8_t r2 = vcombine_s16(vget_low_s16(A23), vget_low_s16(B23));
        int16x8_t r3 = vcombine_s16(vget_high_s16(A23), vget_high_s16(B23));
        int16_t *ta = T + 32 * pr, *tb = ta + 16;
        bfly16(&r0, &r1, &r2, &r3);      /* H @ X  (rows) */
        tr4x2(&r0, &r1, &r2, &r3);
        bfly16(&r0, &r1, &r2, &r3);      /* (.) @ H -> columns of T */
        tr4x2(&r0, &r1, &r2, &r3);       /* back to raster rows */
        vst1_s16(ta, vget_low_s16(r0)); vst1_s16(ta + 4, vget_low_s16(r1)); vst1_s16(ta + 8, vget_low_s16(r2)); vst1_s16(ta + 12, vget_low_s16(r3));
        vst1_s16(tb, vget_high_s16(r0)); vst1_s16(tb + 4, vget_high_s16(r1)); vst1_s16(tb + 8, vget_high_s16(r2)); vst1_s16(tb + 12, vget_high_s16(r3));
    }
}

static int quant8_n(const int16_t *T, uint32_t A, uint32_t B, int S, int16_t *L) {
    const uint32x4_t vB = vdupq_n_u32(B); const uint16x8_t vmax = vdupq_n_u16(2047); const int32x4_t vS = vdupq_n_s32(-S);
    int sb, mask = 0;
    if (!(A & (A - 1))) { /* A = 2^m (power-of-two steps, incl. qp 0): (a*2^m + B) >> S == (a + (B >> m)) >> (S - m), 16-bit */
        int m = 0; uint16x8_t vK; int16x8_t vsh;
        while ((1u << m) < A) m++;
        vK = vdupq_n_u16((uint16_t)(B >> m)); vsh = vdupq_n_s16((int16_t)-(S - m));
        for (sb = 0; sb < 8; sb++) {
            int16x8_t t0 = vld1q_s16(T + 16 * sb), t1 = vld1q_s16(T + 16 * sb + 8);
            uint16x8_t l0 = vminq_u16(vshlq_u16(vaddq_u16(vreinterpretq_u16_s16(vabsq_s16(t0)), vK), vsh), vmax);
            uint16x8_t l1 = vminq_u16(vshlq_u16(vaddq_u16(vreinterpretq_u16_s16(vabsq_s16(t1)), vK), vsh), vmax);
            int16x8_t s0 = vreinterpretq_s16_u16(l0), s1 = vreinterpretq_s16_u16(l1);
            s0 = vbslq_s16(vcltq_s16(t0, vdupq_n_s16(0)), vnegq_s16(s0), s0);
            s1 = vbslq_s16(vcltq_s16(t1, vdupq_n_s16(0)), vnegq_s16(s1), s1);
            vst1q_s16(L + 16 * sb, s0); vst1q_s16(L + 16 * sb + 8, s1);
            if (vmaxvq_u16(vorrq_u16(l0, l1))) mask |= 1 << sb;
        }
        return mask;
    }
    for (sb = 0; sb < 8; sb++) {
        int16x8_t t0 = vld1q_s16(T + 16 * sb), t1 = vld1q_s16(T + 16 * sb + 8);
        uint16x8_t a0 = vreinterpretq_u16_s16(vabsq_s16(t0)), a1 = vreinterpretq_u16_s16(vabsq_s16(t1));
        uint32x4_t p0 = vmlal_n_u16(vB, vget_low_u16(a0), (uint16_t)A), p1 = vmlal_n_u16(vB, vget_high_u16(a0), (uint16_t)A);
        uint32x4_t p2 = vmlal_n_u16(vB, vget_low_u16(a1), (uint16_t)A), p3 = vmlal_n_u16(vB, vget_high_u16(a1), (uint16_t)A);
        uint16x8_t l0 = vminq_u16(vcombine_u16(vmovn_u32(vshlq_u32(p0, vS)), vmovn_u32(vshlq_u32(p1, vS))), vmax);
        uint16x8_t l1 = vminq_u16(vcombine_u16(vmovn_u32(vshlq_u32(p2, vS)), vmovn_u32(vshlq_u32(p3, vS))), vmax);
        int16x8_t s0 = vreinterpretq_s16_u16(l0), s1 = vreinterpretq_s16_u16(l1);
        s0 = vbslq_s16(vcltq_s16(t0, vdupq_n_s16(0)), vnegq_s16(s0), s0);
        s1 = vbslq_s16(vcltq_s16(t1, vdupq_n_s16(0)), vnegq_s16(s1), s1);
        vst1q_s16(L + 16 * sb, s0); vst1q_s16(L + 16 * sb + 8, s1);
        if (vmaxvq_u16(vorrq_u16(l0, l1))) mask |= 1 << sb;
    }
    return mask;
}

static inline void tr4_32(int32x4_t *a0, int32x4_t *a1, int32x4_t *a2, int32x4_t *a3) {
    int32x4x2_t t01 = vtrnq_s32(*a0, *a1), t23 = vtrnq_s32(*a2, *a3);
    *a0 = vcombine_s32(vget_low_s32(t01.val[0]), vget_low_s32(t23.val[0]));
    *a2 = vcombine_s32(vget_high_s32(t01.val[0]), vget_high_s32(t23.val[0]));
    *a1 = vcombine_s32(vget_low_s32(t01.val[1]), vget_low_s32(t23.val[1]));
    *a3 = vcombine_s32(vget_high_s32(t01.val[1]), vget_high_s32(t23.val[1]));
}
static inline void bfly32(int32x4_t *a0, int32x4_t *a1, int32x4_t *a2, int32x4_t *a3) {
    int32x4_t s0 = vaddq_s32(*a0, *a1), s1 = vsubq_s32(*a0, *a1), t0 = vaddq_s32(*a2, *a3), t1 = vsubq_s32(*a2, *a3);
    *a0 = vaddq_s32(s0, t0); *a1 = vsubq_s32(s0, t0); *a2 = vsubq_s32(s1, t1); *a3 = vaddq_s32(s1, t1);
}
static void iwht_n(const int32_t *c, int32_t *o) {
    int32x4_t r0 = vld1q_s32(c), r1 = vld1q_s32(c + 4), r2 = vld1q_s32(c + 8), r3 = vld1q_s32(c + 12);
    bfly32(&r0, &r1, &r2, &r3);
    tr4_32(&r0, &r1, &r2, &r3);
    bfly32(&r0, &r1, &r2, &r3);
    r0 = vrshrq_n_s32(r0, 2); r1 = vrshrq_n_s32(r1, 2); r2 = vrshrq_n_s32(r2, 2); r3 = vrshrq_n_s32(r3, 2);
    tr4_32(&r0, &r1, &r2, &r3);
    vst1q_s32(o, r0); vst1q_s32(o + 4, r1); vst1q_s32(o + 8, r2); vst1q_s32(o + 12, r3);
}

static void addclamp_n(const uint8_t *p, const int32_t *R, int mask, uint8_t *rec) {
    int sb;
    for (sb = 0; sb < 8; sb++, p += 16, R += 16, rec += 16) {
        uint8x16_t pv = vld1q_u8(p);
        if (mask & (1 << sb)) {
            int16x8_t r0 = vcombine_s16(vqmovn_s32(vld1q_s32(R)), vqmovn_s32(vld1q_s32(R + 4)));
            int16x8_t r1 = vcombine_s16(vqmovn_s32(vld1q_s32(R + 8)), vqmovn_s32(vld1q_s32(R + 12)));
            int16x8_t s0 = vqaddq_s16(vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(pv))), r0);
            int16x8_t s1 = vqaddq_s16(vreinterpretq_s16_u16(vmovl_u8(vget_high_u8(pv))), r1);
            vst1q_u8(rec, vcombine_u8(vqmovun_s16(s0), vqmovun_s16(s1)));
        } else vst1q_u8(rec, pv);
    }
}

/* ------------------------------------------------------------------ half-pel planes, projections */
static void halfpel_row_n(const uint8_t *a, const uint8_t *b, int w, uint8_t *h, uint8_t *v, uint8_t *hv) {
    int x = 0;
    for (; x + 16 <= w - 1; x += 16) {
        uint8x16_t a0 = vld1q_u8(a + x), a1 = vld1q_u8(a + x + 1), b0 = vld1q_u8(b + x), b1 = vld1q_u8(b + x + 1);
        uint8x16_t ha = vrhaddq_u8(a0, a1), hb = vrhaddq_u8(b0, b1);
        vst1q_u8(h + x, ha); vst1q_u8(v + x, vrhaddq_u8(a0, b0)); vst1q_u8(hv + x, vrhaddq_u8(ha, hb));
    }
    for (; x < w; x++) {
        int ha = x < w - 1 ? (a[x] + a[x + 1] + 1) >> 1 : a[x];
        int hb = x < w - 1 ? (b[x] + b[x + 1] + 1) >> 1 : b[x];
        h[x] = (uint8_t)ha; v[x] = (uint8_t)((a[x] + b[x] + 1) >> 1); hv[x] = (uint8_t)((ha + hb + 1) >> 1);
    }
}

static void proj_rows_n(const uint8_t *p, int stride, int w, int h, int sw, uint32_t *rows, uint32_t *cols) {
    int y, x, nsx = w / sw;
    for (y = 0; y < h; y++, p += stride) {
        int k;
        for (k = 0; k < nsx; k++) {
            uint16x8_t acc = vdupq_n_u16(0); uint32_t s;
            for (x = k * sw; x + 16 <= (k + 1) * sw; x += 16) acc = vpadalq_u8(acc, vld1q_u8(p + x));
            s = vaddlvq_u16(acc);
            for (; x < (k + 1) * sw; x++) s += p[x];
            rows[y * nsx + k] += s;
        }
        for (x = 0; x + 16 <= w; x += 16) {
            uint8x16_t v = vld1q_u8(p + x);
            uint16x8_t lo = vmovl_u8(vget_low_u8(v)), hi = vmovl_u8(vget_high_u8(v));
            vst1q_u32(cols + x, vaddw_u16(vld1q_u32(cols + x), vget_low_u16(lo)));
            vst1q_u32(cols + x + 4, vaddw_u16(vld1q_u32(cols + x + 4), vget_high_u16(lo)));
            vst1q_u32(cols + x + 8, vaddw_u16(vld1q_u32(cols + x + 8), vget_low_u16(hi)));
            vst1q_u32(cols + x + 12, vaddw_u16(vld1q_u32(cols + x + 12), vget_high_u16(hi)));
        }
        for (; x < w; x++) cols[x] += p[x];
    }
}

/* ------------------------------------------------------------------ glass CSC, 8 pixel pairs per step
 * Same result as csc_glass_c, computed differently:
 *  - 16-bit lanes wherever the value allows it.  Errors saturate at 65535.  The comparisons stay exact as long as the winning pair error
 *    is below 65535; if a lane's is not, the whole group goes through the scalar kernel (a pair needs a colour error of about 100 levels
 *    per channel for that).
 *  - cu[0] is always cu[1]: RNV2_LSU is exactly CBF / 2.  cv[0] is (crs + bs - gs) / 2 against cv[1] = crs / 2, because RNV2_LSV is CRF / 2
 *    rounded the other way on g and b, so the two chromas differ only when that small term crosses a rounding boundary.  Candidate 1 runs
 *    only then.  A candidate equal to an earlier one can never win (strict <).  test_kernels pins all of this against the scalar.
 *  - The offsets come from exhaustively checked 16-bit forms: (91881 v + 32768) >> 16 = v + sqrdmulh(v, 13172) for all v in -128..127,
 *    (116130 u + 32768) >> 16 = u + sqrdmulh(u, 25297), and YFROM's multiply by 21846 is sqdmulh by 10923. */
static inline uint8x16_t q6q(uint8x16_t x) { return vsriq_n_u8(x, x, 6); }
typedef struct { int16x8_t y0, y1, oR, oG, oB; uint16x8_t e0, e1, u, v; } csc_cand;
#define CSC_INL static inline __attribute__((always_inline))
/* |glass - target| of one channel for both pixels: pixel 0 in the low half, pixel 1 in the high half */
CSC_INL uint8x16_t ch_d(int16x8_t y0, int16x8_t y1, int16x8_t o, uint8x16_t t) {
    return vabdq_u8(q6q(vcombine_u8(vqmovun_s16(vaddq_s16(y0, o)), vqmovun_s16(vaddq_s16(y1, o)))), t);
}
CSC_INL uint16x8_t sq3_lo(uint8x16_t a, uint8x16_t b, uint8x16_t c) {
    uint8x8_t x = vget_low_u8(a), y = vget_low_u8(b), z = vget_low_u8(c);
    return vqaddq_u16(vqaddq_u16(vmull_u8(x, x), vmull_u8(y, y)), vmull_u8(z, z));
}
CSC_INL uint16x8_t sq3_hi(uint8x16_t a, uint8x16_t b, uint8x16_t c) {
    uint8x8_t x = vget_high_u8(a), y = vget_high_u8(b), z = vget_high_u8(c);
    return vqaddq_u16(vqaddq_u16(vmull_u8(x, x), vmull_u8(y, y)), vmull_u8(z, z));
}
CSC_INL csc_cand cand8(uint16x8_t u, uint16x8_t v, int16x8_t S0, int16x8_t S1, uint8x16_t tR, uint8x16_t tG, uint8x16_t tB, int16x8_t C) {
    csc_cand c;
    const int16x8_t K128 = vdupq_n_s16(128);
    int16x8_t uu = vsubq_s16(vreinterpretq_s16_u16(u), K128), vv = vsubq_s16(vreinterpretq_s16_u16(v), K128), sr;
    int16x4_t ul = vget_low_s16(uu), uh = vget_high_s16(uu), vl = vget_low_s16(vv), vh = vget_high_s16(vv);
    uint8x16_t dR, dG, dB;
    c.u = u; c.v = v;
    c.oR = vaddq_s16(vv, vqrdmulhq_laneq_s16(vv, C, 4));
    c.oB = vaddq_s16(uu, vqrdmulhq_laneq_s16(uu, C, 5));
    /* -22554 u - 46802 v, with the whole -v taken out so that the coefficient fits 16 bits */
    c.oG = vsubq_s16(vcombine_s16(vrshrn_n_s32(vmlal_laneq_s16(vmull_laneq_s16(ul, C, 0), vl, C, 1), 16), vrshrn_n_s32(vmlal_laneq_s16(vmull_laneq_s16(uh, C, 0), vh, C, 1), 16)), vv);
    /* (32768 - SOFF) >> 16, same trick */
    sr = vsubq_s16(vcombine_s16(vrshrn_n_s32(vmlal_laneq_s16(vmull_laneq_s16(ul, C, 2), vl, C, 3), 16), vrshrn_n_s32(vmlal_laneq_s16(vmull_laneq_s16(uh, C, 2), vh, C, 3), 16)), vaddq_s16(uu, vv));
    sr = vaddq_s16(sr, vdupq_n_s16(385));
    /* the quotient is at least 38 and at most 473 */
    c.y0 = vreinterpretq_s16_u16(vminq_u16(vqsubq_u16(vreinterpretq_u16_s16(vqdmulhq_laneq_s16(vaddq_s16(S0, sr), C, 6)), vreinterpretq_u16_s16(K128)), vdupq_n_u16(255)));
    c.y1 = vreinterpretq_s16_u16(vminq_u16(vqsubq_u16(vreinterpretq_u16_s16(vqdmulhq_laneq_s16(vaddq_s16(S1, sr), C, 6)), vreinterpretq_u16_s16(K128)), vdupq_n_u16(255)));
    dR = ch_d(c.y0, c.y1, c.oR, tR); dG = ch_d(c.y0, c.y1, c.oG, tG); dB = ch_d(c.y0, c.y1, c.oB, tB);
    c.e0 = sq3_lo(dR, dG, dB); c.e1 = sq3_hi(dR, dG, dB);
    return c;
}
#define CAND_TAKE(U, V) do { csc_cand n_ = cand8(U, V, S0, S1, tR, tG, tB, C); uint16x8_t e_ = vqaddq_u16(n_.e0, n_.e1), m_ = vcltq_u16(e_, be); be = vbslq_u16(m_, e_, be); \
    b.y0 = vbslq_s16(m_, n_.y0, b.y0); b.y1 = vbslq_s16(m_, n_.y1, b.y1); b.oR = vbslq_s16(m_, n_.oR, b.oR); b.oG = vbslq_s16(m_, n_.oG, b.oG); b.oB = vbslq_s16(m_, n_.oB, b.oB); \
    b.e0 = vbslq_u16(m_, n_.e0, b.e0); b.e1 = vbslq_u16(m_, n_.e1, b.e1); b.u = vbslq_u16(m_, n_.u, b.u); b.v = vbslq_u16(m_, n_.v, b.v); } while (0)
/* clip255(y + p - n) where one of p and n is 0 */
CSC_INL uint8x16_t ch_dn(uint8x16_t y, uint8x16_t p, uint8x16_t n, uint8x16_t t) { return vabdq_u8(q6q(vqsubq_u8(vqaddq_u8(y, p), n)), t); }

CSC_INL void csc8(const uint8_t *rgb, uint8_t *Y, uint8_t *U, uint8_t *V) {
    static const uint8_t EO[16] = {0, 2, 4, 6, 8, 10, 12, 14, 1, 3, 5, 7, 9, 11, 13, 15};
    static const uint16_t CC_[8] = {11058, 21710, 27439, 5329, 0, 0, 0, 0};
    static const int16_t CO_[8] = {-22554, 18734, -28040, 20456, 13172, 25297, 10923, 0};
    const uint8x16x3_t px = vld3q_u8(rgb); /* 16 pixels */
    const uint8x16_t eo = vld1q_u8(EO);
    const uint16x8_t CC = vld1q_u16(CC_);
    const int16x8_t C = vld1q_s16(CO_);
    /* planar, pixel 0 of each pair in the low half and pixel 1 in the high half */
    const uint8x16_t R = vqtbl1q_u8(px.val[0], eo), G = vqtbl1q_u8(px.val[1], eo), B = vqtbl1q_u8(px.val[2], eo);
    const uint8x16_t tR = q6q(R), tG = q6q(G), tB = q6q(B);
    const uint8x8_t r0 = vget_low_u8(R), g0 = vget_low_u8(G), b0 = vget_low_u8(B);
    const int16x8_t S0 = vreinterpretq_s16_u16(vaddw_u8(vaddl_u8(r0, g0), b0)), S1 = vreinterpretq_s16_u16(vaddw_high_u8(vaddl_high_u8(R, G), B));
    uint16x8_t u0, v0, v1, u2, v2, u3, v3;
    {
        const uint16x8_t R0 = vmovl_u8(r0), G0 = vmovl_u8(g0), B0 = vmovl_u8(b0), RS = vpaddlq_u8(px.val[0]), GS = vpaddlq_u8(px.val[1]), BS = vpaddlq_u8(px.val[2]);
        const int32x4_t K128 = vdupq_n_s32(128 << 16);
        const uint16x8_t K255 = vdupq_n_u16(255);
        int32x4_t cb0l, cb0h, cr0l, cr0h, cbsl, cbsh, crsl, crsh;
#define CBC_L(rr, gg, bb, cbo, cro) do { \
            cbo = vreinterpretq_s32_u32(vsubq_u32(vshll_n_u16(vget_low_u16(bb), 15), vmlal_laneq_u16(vmull_laneq_u16(vget_low_u16(rr), CC, 0), vget_low_u16(gg), CC, 1))); \
            cro = vreinterpretq_s32_u32(vsubq_u32(vshll_n_u16(vget_low_u16(rr), 15), vmlal_laneq_u16(vmull_laneq_u16(vget_low_u16(gg), CC, 2), vget_low_u16(bb), CC, 3))); } while (0)
#define CBC_H(rr, gg, bb, cbo, cro) do { \
            cbo = vreinterpretq_s32_u32(vsubq_u32(vshll_high_n_u16(bb, 15), vmlal_high_laneq_u16(vmull_high_laneq_u16(rr, CC, 0), gg, CC, 1))); \
            cro = vreinterpretq_s32_u32(vsubq_u32(vshll_high_n_u16(rr, 15), vmlal_high_laneq_u16(vmull_high_laneq_u16(gg, CC, 2), bb, CC, 3))); } while (0)
        CBC_L(R0, G0, B0, cb0l, cr0l);
        CBC_H(R0, G0, B0, cb0h, cr0h);
        CBC_L(RS, GS, BS, cbsl, crsl);
        CBC_H(RS, GS, BS, cbsh, crsh);
#undef CBC_L
#undef CBC_H
#define CH(l, h) vminq_u16(vcombine_u16(vqrshrun_n_s32(vaddq_s32(l, K128), 16), vqrshrun_n_s32(vaddq_s32(h, K128), 16)), K255)
#define H1(x) vshrq_n_s32(x, 1) /* floor(floor(x / 2) + n) / m) = floor((x / 2 + n) / m), so halving first keeps the >> 17 of the scalar exact */
        u0 = CH(H1(cbsl), H1(cbsh)); v1 = CH(H1(crsl), H1(crsh));
        v0 = CH(H1(vaddq_s32(crsl, vreinterpretq_s32_u32(vsubl_u16(vget_low_u16(BS), vget_low_u16(GS))))), H1(vaddq_s32(crsh, vreinterpretq_s32_u32(vsubl_high_u16(BS, GS)))));
        u2 = CH(cb0l, cb0h); v2 = CH(cr0l, cr0h);
        u3 = CH(vsubq_s32(cbsl, cb0l), vsubq_s32(cbsh, cb0h)); v3 = CH(vsubq_s32(crsl, cr0l), vsubq_s32(crsh, cr0h));
#undef H1
#undef CH
    }
    {
        csc_cand b = cand8(u0, v0, S0, S1, tR, tG, tB, C);
        uint16x8_t be = vqaddq_u16(b.e0, b.e1);
        const uint16x8_t d20 = vorrq_u16(veorq_u16(u2, u0), veorq_u16(v2, v0)), d30 = vorrq_u16(veorq_u16(u3, u0), veorq_u16(v3, v0)), d10 = veorq_u16(v0, v1);
        int bm;
        /* video from a 4:2:0 source: both pixels of a pair round to the same chroma, and in nearly every group all lanes do */
        if (vmaxvq_u16(vorrq_u16(vorrq_u16(d10, d20), d30))) {
            if (vmaxvq_u16(d10)) CAND_TAKE(u0, v1);
            if (vmaxvq_u16(d20)) CAND_TAKE(u2, v2);
            if (vmaxvq_u16(vminq_u16(d30, vorrq_u16(veorq_u16(u3, u2), veorq_u16(v3, v2))))) CAND_TAKE(u3, v3); /* min: nonzero only where both differ */
        }
        bm = vmaxvq_u16(be);
        if (bm == 0xFFFF) { rnv2_kern_scalar.csc_glass(rgb, 8, Y, U, V); return; }
        if (!bm) { /* every pair is already exact: no nudge can win */
            uint8x8x2_t yy; yy.val[0] = vmovn_u16(vreinterpretq_u16_s16(b.y0)); yy.val[1] = vmovn_u16(vreinterpretq_u16_s16(b.y1));
            vst2_u8(Y, yy); vst1_u8(U, vmovn_u16(b.u)); vst1_u8(V, vmovn_u16(b.v));
            return;
        }
        { /* Y nudge onto a better 6-bit level.  The offsets as saturating add + subtract on 8-bit lanes: |o| is at most 227 */
            const uint8x8_t pr = vqmovun_s16(b.oR), pg = vqmovun_s16(b.oG), pb = vqmovun_s16(b.oB), nr = vqmovun_s16(vnegq_s16(b.oR)), ng = vqmovun_s16(vnegq_s16(b.oG)), nb = vqmovun_s16(vnegq_s16(b.oB));
            const uint8x16_t PR = vcombine_u8(pr, pr), PG = vcombine_u8(pg, pg), PB = vcombine_u8(pb, pb), NR = vcombine_u8(nr, nr), NG = vcombine_u8(ng, ng), NB = vcombine_u8(nb, nb);
            const uint8x16_t Y0 = vcombine_u8(vmovn_u16(vreinterpretq_u16_s16(b.y0)), vmovn_u16(vreinterpretq_u16_s16(b.y1)));
            const uint8x16_t K2 = vdupq_n_u8(2), K4 = vdupq_n_u8(4);
            uint8x16_t N = Y0;
            uint16x8_t e0 = b.e0, e1 = b.e1;
#define TRY(EXPR) do { uint8x16_t yc = EXPR, dR = ch_dn(yc, PR, NR, tR), dG = ch_dn(yc, PG, NG, tG), dB = ch_dn(yc, PB, NB, tB); \
                uint16x8_t a0 = sq3_lo(dR, dG, dB), a1 = sq3_hi(dR, dG, dB), m0 = vcltq_u16(a0, e0), m1 = vcltq_u16(a1, e1); \
                e0 = vminq_u16(a0, e0); e1 = vminq_u16(a1, e1); \
                N = vbslq_u8(vuzp1q_u8(vreinterpretq_u8_u16(m0), vreinterpretq_u8_u16(m1)), yc, N); } while (0)
            TRY(vqsubq_u8(Y0, K4));
            TRY(vqsubq_u8(Y0, K2));
            TRY(vqaddq_u8(Y0, K2));
            TRY(vqaddq_u8(Y0, K4));
#undef TRY
            {
                uint8x8x2_t yy; yy.val[0] = vget_low_u8(N); yy.val[1] = vget_high_u8(N);
                vst2_u8(Y, yy); vst1_u8(U, vmovn_u16(b.u)); vst1_u8(V, vmovn_u16(b.v));
            }
        }
    }
}
#undef CAND_TAKE
#undef CSC_INL

static void csc_glass_n(const uint8_t *rgb, int npairs, uint8_t *Y, uint8_t *U, uint8_t *V) {
    int p = 0;
    for (; p + 8 <= npairs; p += 8) csc8(rgb + 6 * p, Y + 2 * p, U + p, V + p);
    if (p < npairs) { /* tail through a padded buffer (same kernel => same results) */
        uint8_t tr[48] = {0}, ty[16], tu[8], tv[8]; int n = npairs - p;
        memcpy(tr, rgb + 6 * p, (size_t)6 * n);
        csc8(tr, ty, tu, tv);
        memcpy(Y + 2 * p, ty, (size_t)2 * n); memcpy(U + p, tu, (size_t)n); memcpy(V + p, tv, (size_t)n);
    }
}

const rnv2_kern rnv2_kern_neon = {"neon", csc_glass_n, sad8x8_n, pd8_n, fwd8_n, quant8_n, iwht_n, addclamp_n, halfpel_row_n, proj_rows_n};
#else
typedef int rnv2_kern_neon_unused;
#endif
