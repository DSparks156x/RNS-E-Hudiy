/* rnv2enc core: real-time RNV2 encoder.  Algorithm = video/rnv2.py (Encoder2) re-organised per block:
 *   1 change detection (+damage hint) and glass CSC only for changed 8x8 blocks
 *   2 global motion candidates from row/column projections (scroll / pan)
 *   3 block motion search: zero, previous MV, global candidates, small descent; two Jacobi neighbour passes with a
 *     12-point refine (as rnv2.py), half-pel last
 *   4 per-block RD analysis at qp (MC / ZRES / INTRA residual candidates, perceptual distortion, Huffman bit counts,
 *     SH-4A cycle model) - cached, so a cycle-cap retry (mu change) only re-runs step 5
 *   5 per-block mode decision at (lambda, mu); exact frame size and cycles from a cheap serial pass
 *   6 rnv2.py leaky-bucket / cycle-cap control loop over steps 4-5
 *   7 commit: reconstruction (bit-exact with rnv2dec.c) + serial bitstream write, half-pel planes for next frame
 * Every per-block decision depends only on frame-level inputs (Jacobi-style ME, no intra-frame causal state), so the
 * bitstream is identical for any thread count. */
#define _GNU_SOURCE
#include "rnv2enc.h"
#include "kern.h"
#include "rnv2_tables.h"
#include "rnv3_modes.h"
#include "csc_common.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <time.h>
#include <pthread.h>
#include <stdatomic.h>
#ifdef __ARM_NEON
#include <arm_neon.h>
#endif

#define W RNV2_W
#define H RNV2_H
#define CW (W / 2)
#define BW (W / 8)
#define BH (H / 8)
#define NB (BW * BH)
enum { SKIP = 0, MC, MCR, ZRES, INTRA, RAW };
#define RNV3_QC2 2
#define RUNMAX 16
#define LVMAX 13
static const uint8_t ZZ[16] = {0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15};
/* SH-4A decode cost model (rnv.CY + rnv2 add_c4/add_c4dc), cycles */
enum { CY_FRAME = 20000, CY_SKIP = 6, CY_MEM = 306, CY_SKIPCOPY = 100 + 306, CY_HDR = 150, CY_MC_INT = 100, CY_MC_ODD = 398,
       CY_MC_H = 646, CY_MC_V = 318, CY_MC_HV = 924, CY_HALF_MEM = 38, CY_ZRES = 100 + 306, CY_FILL = 54 + 306,
       CY_RAW = 150 + 306 + 77, CY_COEF = 55, CY_IWHT_FULL = 218, CY_IWHT_BASE = 20, CY_IWHT_PER = 16, CY_DC = 30,
       CY_ADD_Y = 184, CY_ADD_YDC = 152, CY_ADD_C4 = 207, CY_ADD_C4DC = 177,
       CY_LAT8 = 784, CY_LAT4 = 1016, CY_LAT2 = 2047, CY_BTC4 = 991, CY_BTC2 = 792, CY_DITH = 70 }; /* LAT / BTC: qemu instruction counts per block (enc3/sh/sim/table_final2.txt) + CY_MEM - CY_HDR */ /* LAT / BTC: estimates, include CY_MEM */
static const int WSB[8] = {20, 20, 20, 20, 44, 44, 33, 33}; /* 1, 2.2, 1.65 (rnv2.WCB/WCR) x20 */
#define DSCALE 320.0                                         /* pd8 is x16, weights x20 */
#define MAXG 8
#define BURST_QP_OCT 5.0 /* qp per halving of the frame size around qp 15-30, measured on fades: 4.8 */

typedef struct { int c[6]; } btcinfo; /* y0 y1 u0 u1 v0 v1 */
typedef struct { uint8_t F2[401 * 241], F4[201 * 121], F8[101 * 61], FU4[201 * 121], FV4[201 * 121], FU8[101 * 61], FV8[101 * 61], QY8[101 * 61], QY4[201 * 121], QY2[401 * 241], QU4[201 * 121], QV4[201 * 121];
                 int16_t DY4[201 * 121], DY2[401 * 241], DU4[201 * 121], DV4[201 * 121]; } latgrid;
typedef struct {
    btcinfo btc[2]; uint8_t m4[16], m2[8];  /* btc[0] = BTC4, btc[1] = BTC2 */
    uint8_t fill[3];
    int16_t L3[3][128];                     /* quantised levels of each residual candidate (commit and the stream writer use these) */
} blkstat;
/* What the mode decision reads, kept apart from blkstat: decide runs several times per frame over every active block, and these two arrays stay near the size of L2.
 * Distortions are WSB * pd8 / DSCALE; infinity = candidate not evaluated. */
#define DCNONE 0xFFFF
typedef struct { float g[8]; uint16_t bits[8], cyc[8]; } dcand; /* one residual candidate: per subblock Doff - Don (< 0: never coded), bits, cycles */
typedef struct {
    float Jds, Jdm, Jdi, ipw, Dlat[3], Dbtc[2];
    uint16_t blat[3], mvbits, mcc, cskip, cand[3];
    uint8_t valid, ry, rc;
} blkdc;
_Static_assert(sizeof(dcand) == 64, "dcand is one cache line");
_Static_assert(sizeof(blkdc) <= 64, "blkdc is one cache line");
typedef struct { uint8_t mode, cbp, cand; int32_t cbits, cyc, ebits; float dist; } blkdec;
typedef struct { uint8_t *buf; size_t cap, n; uint64_t acc; int nb; } bw_t;
typedef void (*job_fn)(rnv2enc *e, int idx);
enum { GNSX = 4, GSW = W / GNSX, GNBAND = 3, GBHT = H / GNBAND, GRNG = 120 };
typedef struct { uint32_t rows[2][H * GNSX], cols[2][GNBAND][W]; int32_t prof[9][2][W]; int res[9][2]; } gme_t;
static uint32_t COEF_CODE[416], CBPL_CODE[16], CBPC_CODE[16];
/* -DRNV_COUNT: kernel work counters for the Pi speed model (single thread only; not thread safe) */
#ifdef RNV_COUNT
long long rnv_cnt[8]; /* csc pairs, sad calls, pd8 calls, fwd8 calls, iwht calls, addclamp calls, halfpel px, proj px */
#define KC(i, n) (rnv_cnt[i] += (n))
#else
#define KC(i, n) ((void)0)
#endif

struct rnv2enc {
    rnv2enc_params p;
    const rnv2_kern *k;
    int kappa16, thr;
    uint8_t *tY, *tU, *tV, *refrgb;
    const uint8_t *cur; int curstride; enum rnv2_fmt fmt;
    uint8_t *R[2][3];          /* recon double buffer */
    uint8_t *HP[3][3];         /* half-pel planes of the reference: [Y,U,V][h,v,hv] */
    int rb, first;
    uint8_t prevmode[NB], changed[NB], forced[NB], damaged[NB], medone[NB], hdirty[BH], mchg[2][NB];
    uint8_t (*rec)[128];
    uint8_t skq[NB]; double skmu[NB]; int qp0; double mu0; /* static-skip validity: (qp, mu, level) of the last evaluated SKIP */
    int16_t prev_mv[NB][2], mv0[NB][2], mv1[NB][2];
    uint32_t mc0[NB], mc1[NB];
    blkstat *bs; blkdec *bd; blkdc *dc; dcand *dcp; uint8_t smp[NB]; uint16_t sact[NB]; int nsact; double lam_est, nu_est, lam_gate, nu_gate, rslope; int burst; /* blocks of the lambda sample; this frame's lambda from it */
    double fill, rate_pf, buf, mu; int qp, fn;
    double pend_dt, dtf; int since_spill; /* rnv2enc_set_elapsed; frames since the last deliberate spill */
    /* headroom-driven quality: operating point ladder lvl 0 (near-exact) .. nlev-1 (= --lamk/--kappa/--thr) */
    int nlev, lvl, alvl, l0cool, since; double lamk; uint8_t skl[NB];
    _Atomic double pend_cap; /* live link capacity request (B/s), 0 = none; applied at the next encode call */
    int ng, g[MAXG][2], prev_g[2], qp_raised;
    gme_t *G;
    struct qtab_s *qt[52][2];
    /* frame-level job parameters */
    int cqp, step, wqp; double lam, cmu; int pass;
    bw_t w0, w1, w2; uint8_t *s3; size_t s3cap, s3n;
    uint8_t *obuf; size_t ocap;
    int n_forced, n_search;
    /* thread pool */
    int nth; pthread_t th[16];
    pthread_mutex_t m; pthread_cond_t cv, cvdone;
    int gen, quit; job_fn jfn; int njobs; _Atomic uint64_t next; atomic_int done; /* next = gen << 32 | next job index */
    /* per-frame work lists / flags */
    uint8_t nxtd[NB], lat_valid, key, tvalid, cscneed[NB]; /* key = coded from black; tvalid: tY/U/V = csc(refrgb) everywhere (not before the first frame) */
    uint16_t act[NB]; int nact, ncoded, nprev_act;
    uint16_t hx0[BH], hx1[BH];        /* x range of the blocks written to each band (half-pel update range) */
    double lastn, bmu;
    uint8_t *drgb, rng[NB], dith[NB]; /* --dither: source with the static pattern, per-block channel range, blocks dithered now */
    int kl0;                          /* last key at level 0: 0 unknown, 1 fitted, 2 did not fit */
    double pbpa, pkey; int pq, pkq;    /* bytes per active block / of the last key at the classic point, at qp pq / pkq: first-qp prediction */
    blkstat *bs2; int bs2_cls, bs2_qp; /* the other analysis class, kept so a failed level-0 probe does not re-run the level-1 analysis */
    latgrid *L; int q4, q2a, q2b, q4c; uint8_t clean[NB]; double lamp, mup, szrat, lamb; int lat_ok; blkdec *bd2, *bd3; void *fillc;
};

/* ------------------------------------------------------------------ utils */
static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec * 1e-6; }
static inline int ue_len(uint32_t v) { return 2 * (31 - __builtin_clz(v + 1)) + 1; }
static inline uint32_t se_map(int v) { return v > 0 ? (uint32_t)(2 * v - 1) : (uint32_t)(-2 * v); }
static void *xmalloc(size_t n) { void *p = NULL; if (posix_memalign(&p, 64, n ? n : 64)) { fprintf(stderr, "rnv2enc: out of memory\n"); exit(1); } return p; }

static void bw_reset(bw_t *w) { w->n = 0; w->acc = 0; w->nb = 0; }
static void bw_grow(bw_t *w) { size_t nc = w->cap ? 2 * w->cap : 1 << 16; uint8_t *nbuf = xmalloc(nc); if (w->n) memcpy(nbuf, w->buf, w->n); free(w->buf); w->buf = nbuf; w->cap = nc; }
static inline void bw_put(bw_t *w, uint32_t v, int n) { /* n <= 32; MSB first; keeps < 32 bits pending */
    if (!n) return;
    w->acc = (w->acc << n) | (n == 32 ? v : (v & ((1u << n) - 1)));
    w->nb += n;
    if (w->nb >= 32) {
        uint32_t x;
        if (w->n + 4 > w->cap) bw_grow(w);
        w->nb -= 32; x = (uint32_t)(w->acc >> w->nb);
        w->buf[w->n] = (uint8_t)(x >> 24); w->buf[w->n + 1] = (uint8_t)(x >> 16); w->buf[w->n + 2] = (uint8_t)(x >> 8); w->buf[w->n + 3] = (uint8_t)x;
        w->n += 4;
    }
}
static inline void bw_ue(bw_t *w, uint32_t v) { uint64_t x = (uint64_t)v + 1; int nb = 0; while ((x >> nb) > 1) nb++; bw_put(w, 0, nb); bw_put(w, (uint32_t)x, nb + 1); }
static void bw_flush(bw_t *w) {
    if (w->n + 5 > w->cap) bw_grow(w);
    while (w->nb >= 8) { w->nb -= 8; w->buf[w->n++] = (uint8_t)(w->acc >> w->nb); }
    if (w->nb) { w->buf[w->n++] = (uint8_t)(w->acc << (8 - w->nb)); w->nb = 0; }
}

/* ------------------------------------------------------------------ thread pool */
/* A job is claimed with a CAS on (generation, index).  run_jobs waits for the jobs, not for the workers: a worker that is still
 * asleep or preempted (the Pi's cores are shared with the compositor) never delays a frame unless it holds a claimed job. */
static inline void claim_loop(rnv2enc *e, int g, job_fn fn, int n) {
    for (;;) {
        uint64_t v = atomic_load(&e->next); int i = (int)(uint32_t)v;
        if ((int)(v >> 32) != g || i >= n) return;
        if (atomic_compare_exchange_weak(&e->next, &v, v + 1)) {
            fn(e, i);
            if (atomic_fetch_add(&e->done, 1) + 1 == n) { pthread_mutex_lock(&e->m); pthread_cond_signal(&e->cvdone); pthread_mutex_unlock(&e->m); }
        }
    }
}
static void *worker(void *arg) {
    rnv2enc *e = arg; int g = 0;
    for (;;) {
        job_fn fn; int n;
        pthread_mutex_lock(&e->m);
        while (e->gen == g && !e->quit) pthread_cond_wait(&e->cv, &e->m);
        if (e->quit) { pthread_mutex_unlock(&e->m); return NULL; }
        g = e->gen; fn = e->jfn; n = e->njobs;
        pthread_mutex_unlock(&e->m);
        claim_loop(e, g, fn, n);
    }
}
static void run_jobs(rnv2enc *e, job_fn fn, int n) {
    int i, g;
    if (e->nth <= 1) { for (i = 0; i < n; i++) fn(e, i); return; }
    pthread_mutex_lock(&e->m);
    g = ++e->gen; e->jfn = fn; e->njobs = n; atomic_store(&e->done, 0); atomic_store(&e->next, (uint64_t)(uint32_t)g << 32);
    pthread_cond_broadcast(&e->cv);
    pthread_mutex_unlock(&e->m);
    claim_loop(e, g, fn, n);
    for (i = 0; i < 200 && atomic_load(&e->done) < n; i++) ; /* the other thread is usually finishing its last row */
    if (atomic_load(&e->done) < n) {
        pthread_mutex_lock(&e->m);
        while (atomic_load(&e->done) < n) pthread_cond_wait(&e->cvdone, &e->m);
        pthread_mutex_unlock(&e->m);
    }
}
/* run in parallel only when the work is worth a thread wake-up (a futex wake and a core out of idle cost ~50 us of CPU) */
static inline void run_w(rnv2enc *e, job_fn fn, int n, int work, int minwork) {
    int i;
    if (work < minwork) { for (i = 0; i < n; i++) fn(e, i); return; }
    run_jobs(e, fn, n);
}

/* ------------------------------------------------------------------ block gather / scatter (SB layout) */
static inline void gather_y(const uint8_t *p, int stride, uint8_t *o) {
#ifdef __ARM_NEON
    int g;
    for (g = 0; g < 2; g++, p += 4 * stride, o += 32) {
        uint32x4_t a = vreinterpretq_u32_u8(vcombine_u8(vld1_u8(p), vld1_u8(p + stride))), c = vreinterpretq_u32_u8(vcombine_u8(vld1_u8(p + 2 * stride), vld1_u8(p + 3 * stride)));
        vst1q_u32((uint32_t *)o, vuzp1q_u32(a, c)); vst1q_u32((uint32_t *)(o + 16), vuzp2q_u32(a, c));
    }
#else
    int r;
    for (r = 0; r < 8; r++, p += stride) { uint8_t *d = o + ((r >> 2) * 2) * 16 + (r & 3) * 4; memcpy(d, p, 4); memcpy(d + 16, p + 4, 4); }
#endif
}
static inline void gather_c(const uint8_t *p, int stride, uint8_t *o) { /* o = start of the component's 2 subblocks */
    int r;
    for (r = 0; r < 8; r++, p += stride) memcpy(o + (r >> 2) * 16 + (r & 3) * 4, p, 4);
}
static inline void gather_blk(const uint8_t *Y, const uint8_t *U, const uint8_t *V, int b, uint8_t *o) {
    int x0 = (b % BW) * 8, y0 = (b / BW) * 8;
    gather_y(Y + y0 * W + x0, W, o); gather_c(U + y0 * CW + x0 / 2, CW, o + 64); gather_c(V + y0 * CW + x0 / 2, CW, o + 96);
}
static inline void scatter_blk(uint8_t *Y, uint8_t *U, uint8_t *V, int b, const uint8_t *s) {
    int x0 = (b % BW) * 8, y0 = (b / BW) * 8, r;
    uint8_t *py = Y + y0 * W + x0, *pu = U + y0 * CW + x0 / 2, *pv = V + y0 * CW + x0 / 2;
    for (r = 0; r < 8; r++, py += W, pu += CW, pv += CW) {
        const uint8_t *d = s + ((r >> 2) * 2) * 16 + (r & 3) * 4;
        memcpy(py, d, 4); memcpy(py + 4, d + 16, 4);
        memcpy(pu, s + 64 + (r >> 2) * 16 + (r & 3) * 4, 4); memcpy(pv, s + 96 + (r >> 2) * 16 + (r & 3) * 4, 4);
    }
}
static inline const uint8_t *yplane(const rnv2enc *e, int f) { return f ? e->HP[0][f - 1] : e->R[e->rb][0]; }
static inline const uint8_t *cplane(const rnv2enc *e, int c, int f) { return f ? e->HP[c][f - 1] : e->R[e->rb][c]; }
/* motion-compensated prediction (rnv.pred_luma / pred_chroma = decoder packed MC), mv valid */
static void mc_pred(const rnv2enc *e, int b, int mx, int my, uint8_t *o) {
    int x0 = (b % BW) * 8, y0 = (b / BW) * 8, ix = mx >> 1, fx = mx & 1, iy = my >> 1, fy = my & 1;
    int fxc = fx & (ix & 1), cx = x0 / 2 + (ix >> 1), y = y0 + iy;
    gather_y(yplane(e, fy * 2 + fx) + y * W + x0 + ix, W, o);
    gather_c(cplane(e, 1, fy * 2 + fxc) + y * CW + cx, CW, o + 64);
    gather_c(cplane(e, 2, fy * 2 + fxc) + y * CW + cx, CW, o + 96);
}
static inline int mv_valid(int b, int mx, int my) {
    int x0 = (b % BW) * 8, y0 = (b / BW) * 8, ix = mx >> 1, fx = mx & 1, iy = my >> 1, fy = my & 1;
    return x0 + ix >= 0 && x0 + ix + 7 + fx <= W - 1 && y0 + iy >= 0 && y0 + iy + 7 + fy <= H - 1;
}
static int mc_cycles(int mx, int my) {
    int fx = mx & 1, fy = my & 1, odd = (mx >> 1) & 1;
    int c = fx && fy ? CY_MC_HV : fx ? CY_MC_H : fy ? CY_MC_V : odd ? CY_MC_ODD : CY_MC_INT;
    return c + CY_MEM + ((fx | fy) ? CY_HALF_MEM : 0);
}

/* ------------------------------------------------------------------ quantiser tables */
/* quantiser: L = sign(T) * min(2047, floor(|T| / (4 step) + dz)) (rnv.quantise on the orthonormal WHT, T = 4 C).
 * Evaluated as (|T| * A + B) >> S (S = 15 + floor(log2(4 step)), A < 2^16) with (A, B) searched so that it equals the exact table for every |T| <= 4080;
 * that form runs in the SIMD kernel.  If no (A, B) matches, the table path is used (same results, scalar). */
typedef struct qtab_s { int16_t t[4096]; uint32_t A, B; int S, ok; } qtab_t;
static const qtab_t *qtab(rnv2enc *e, int qp, int intra) {
    if (!e->qt[qp][intra]) {
        qtab_t *q = xmalloc(sizeof *q); int i; double st = QSTEP2[qp], dz = intra ? e->p.dz_intra : e->p.dz_inter;
        int S = 15 + (int)floor(log2(4 * st)); uint32_t A0 = (uint32_t)floor(ldexp(1.0, S) / (4 * st)), A, B, B0 = (uint32_t)floor(dz * ldexp(1.0, S));
        for (i = 0; i < 4096; i++) { double L = floor(i / 4.0 / st + dz); q->t[i] = (int16_t)(L > 2047 ? 2047 : L); }
        q->ok = 0; q->A = q->B = 0; q->S = S;
        for (A = A0; A <= A0 + 1 && !q->ok; A++) for (B = B0 > 512 ? B0 - 512 : 0; B <= B0 + 512 && !q->ok; B++) {
            if (A > 65535) continue;
            for (i = 0; i <= 4080; i++) { uint32_t l = (i * A + B) >> S; if ((int)(l > 2047 ? 2047 : l) != q->t[i]) break; }
            if (i > 4080) { q->ok = 1; q->A = A; q->B = B; }
        }
        e->qt[qp][intra] = q;
    }
    return e->qt[qp][intra];
}
/* quantise 8 subblocks; returns nz mask; per-sb bits (Huffman + sign + escape) and SH-4A cycles; L raster order */
static int quant_bits(const rnv2enc *e, const int16_t *T, const qtab_t *q, int16_t *L, uint16_t *bits, uint16_t *cyc) {
    int sb, k, mask = 0;
    if (q->ok) mask = e->k->quant8(T, q->A, q->B, q->S, L);
    else for (sb = 0; sb < 8; sb++) {
        int nz = 0;
        for (k = 0; k < 16; k++) { int v = T[16 * sb + k], a = v < 0 ? -v : v, l = q->t[a]; L[16 * sb + k] = (int16_t)(v < 0 ? -l : l); nz |= l; }
        if (nz) mask |= 1 << sb;
    }
    for (sb = 0; sb < 8; sb++) {
        const int16_t *l = L + 16 * sb; unsigned m = 0; int b = 0, prev = -1, nnz, lastpos;
        if (!(mask & (1 << sb))) { bits[sb] = 0; cyc[sb] = 0; continue; }
#ifdef __ARM_NEON
        { /* zigzag-order nonzero mask */
            static const uint8_t ZZT[16] = {0, 1, 4, 8, 5, 2, 3, 6, 9, 12, 13, 10, 7, 11, 14, 15};
            static const uint8_t BIT[16] = {1, 2, 4, 8, 16, 32, 64, 128, 1, 2, 4, 8, 16, 32, 64, 128};
            int16x8_t a0 = vld1q_s16(l), a1 = vld1q_s16(l + 8);
            uint8x16_t nzv = vcombine_u8(vmovn_u16(vtstq_s16(a0, a0)), vmovn_u16(vtstq_s16(a1, a1)));
            nzv = vandq_u8(vqtbl1q_u8(nzv, vld1q_u8(ZZT)), vld1q_u8(BIT));
            m = (unsigned)vaddv_u8(vget_low_u8(nzv)) | ((unsigned)vaddv_u8(vget_high_u8(nzv)) << 8);
        }
#else
        for (k = 0; k < 16; k++) m |= (unsigned)(l[ZZ[k]] != 0) << k;
#endif
        nnz = __builtin_popcount(m); lastpos = 31 - __builtin_clz(m);
        while (m) {
            int pos = __builtin_ctz(m), v = l[ZZ[pos]], a = v < 0 ? -v : v, sym;
            m &= m - 1;
            sym = (pos == lastpos) * (RUNMAX * LVMAX) + (pos - prev - 1) * LVMAX + (a < LVMAX ? a : LVMAX) - 1; prev = pos;
            b += COEF_LEN[sym] + 1 + (a >= LVMAX ? ue_len((uint32_t)(a - LVMAX)) : 0);
        }
        {
            int chroma = sb >= 4, dco = (nnz == 1 && l[0] != 0);
            int iw = CY_IWHT_BASE + CY_IWHT_PER * nnz; if (iw > CY_IWHT_FULL) iw = CY_IWHT_FULL;
            cyc[sb] = (uint16_t)((dco ? CY_DC + (chroma ? CY_ADD_C4DC : CY_ADD_YDC) : iw + (chroma ? CY_ADD_C4 : CY_ADD_Y)) + CY_COEF * nnz);
        }
        bits[sb] = (uint16_t)b;
    }
    return mask;
}

static void recon_res(rnv2enc *e, const int16_t *L, int mask, int step, const uint8_t *P, uint8_t *rec) {
    int32_t R[128]; int sb, k;
    for (sb = 0; sb < 8; sb++) if (mask & (1 << sb)) { int32_t c[16]; for (k = 0; k < 16; k++) c[k] = L[16 * sb + k] * step; KC(4, 1); e->k->iwht(c, R + 16 * sb); }
    KC(5, 1); e->k->addclamp(P, R, mask, rec);
}

#include "rnv3_enc.inc"

/* ------------------------------------------------------------------ phase 1: change detection + CSC */
/* 8 pixels of the input format -> RGB24 */
static inline void line8_rgb(const uint8_t *s, enum rnv2_fmt f, uint8_t *d) {
#ifdef __ARM_NEON
    if (f == RNV2_BGR24) { uint8x8x3_t v = vld3_u8(s), o; o.val[0] = v.val[2]; o.val[1] = v.val[1]; o.val[2] = v.val[0]; vst3_u8(d, o); }
    else { /* 32 bytes in, 24 out: a shuffle over two registers instead of de-interleaving and re-interleaving every row */
        static const uint8_t T[2][24] = {{2, 1, 0, 6, 5, 4, 10, 9, 8, 14, 13, 12, 18, 17, 16, 22, 21, 20, 26, 25, 24, 30, 29, 28}, {0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14, 16, 17, 18, 20, 21, 22, 24, 25, 26, 28, 29, 30}};
        const uint8_t *t = T[f != RNV2_BGR0]; uint8x16x2_t v; v.val[0] = vld1q_u8(s); v.val[1] = vld1q_u8(s + 16);
        vst1q_u8(d, vqtbl2q_u8(v, vld1q_u8(t))); vst1_u8(d + 16, vqtbl2_u8(v, vld1_u8(t + 16)));
    }
#else
    int x;
    switch (f) {
    case RNV2_BGR24: for (x = 0; x < 8; x++, s += 3, d += 3) { d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; } break;
    case RNV2_BGR0: for (x = 0; x < 8; x++, s += 4, d += 3) { d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; } break;
    default: for (x = 0; x < 8; x++, s += 4, d += 3) { d[0] = s[0]; d[1] = s[1]; d[2] = s[2]; } break;
    }
#endif
}
/* n >= 4 pairs; almost all unequal groups already differ in the first 8 bytes */
static inline int group_eq(const uint8_t *a, const uint8_t *b, size_t n) {
    uint64_t x, y;
    memcpy(&x, a, 8); memcpy(&y, b, 8);
    return x == y && !memcmp(a + 8, b + 8, n - 8);
}
/* CSC of one row segment of refrgb (npairs from pixel x).  The kernel is a pure per-pair function, so a 16-pixel group equal to the same
 * group one row up (already converted: same band, or an unchanged block) or to the group on its left reuses that output.  UI and map
 * content is mostly flat or vertically uniform, and this kernel is the most expensive per-pixel step in the encoder.
 * Groups without a match collect into one kernel call: the kernel is faster per group over a long run than called group by group. */
static void csc_seg(rnv2enc *e, int y, int x, int npairs, int r) {
    const uint8_t *rgb = e->refrgb + ((size_t)y * W + x) * 3;
    uint8_t *Y = e->tY + y * W + x, *U = e->tU + y * CW + x / 2, *V = e->tV + y * CW + x / 2;
    int p = 0, run = 0; /* the pending run ends at p */
#define FLUSH() do { if (run) { KC(0, run); e->k->csc_glass(rgb + 6 * (p - run), run, Y + 2 * (p - run), U + p - run, V + p - run); run = 0; } } while (0)
    while (p < npairs) {
        int n = npairs - p >= 8 ? 8 : npairs - p;
        if (r > 0 && group_eq(rgb + 6 * p, rgb + 6 * p - W * 3, (size_t)6 * n)) { FLUSH(); memcpy(Y + 2 * p, Y + 2 * p - W, (size_t)2 * n); memcpy(U + p, U + p - CW, (size_t)n); memcpy(V + p, V + p - CW, (size_t)n); }
        else if (p >= n && group_eq(rgb + 6 * p, rgb + 6 * (p - n), (size_t)6 * n)) { FLUSH(); memcpy(Y + 2 * p, Y + 2 * (p - n), (size_t)2 * n); memcpy(U + p, U + p - n, (size_t)n); memcpy(V + p, V + p - n, (size_t)n); }
        else run += n;
        p += n;
    }
    FLUSH();
#undef FLUSH
}
/* static-skip rule: unchanged source, SKIP last frame, and last evaluated at a qp / mu / level no finer than now: the decision cannot change */
static void csc_row(rnv2enc *e, int by, int bx0, int bx1) { /* CSC on runs of blocks that need it */
    int r, bx, y0 = by * 8;
    for (r = 0; r < 8; r++) {
        int y = y0 + r;
        for (bx = bx0; bx < bx1;) {
            int b0 = bx;
            if (!e->cscneed[by * BW + bx]) { bx++; continue; }
            while (bx < bx1 && e->cscneed[by * BW + bx]) bx++;
            csc_seg(e, y, b0 * 8, (bx - b0) * 4, r);
        }
    }
}
static inline int can_force(const rnv2enc *e, int b) { return e->clean[b]; }
static inline int it_lt(int a, int b) { return a < b; }
static int fill_cmp(const void *a, const void *b) { float x = *(const float *)a, y = *(const float *)b; return x < y ? 1 : x > y ? -1 : (((const int *)a)[1] - ((const int *)b)[1]); }
/* Block compares of job_csc: a = 8 rows of 24 bytes at stride as, r = the same block of refrgb.  Identical results on both paths. */
#ifdef __ARM_NEON
static inline int blk_maxdiff(const uint8_t *a, size_t as, const uint8_t *r) { /* largest byte difference */
    uint8x16_t m = vdupq_n_u8(0); uint8x8_t m8 = vdup_n_u8(0); int i, x, y;
    for (i = 0; i < 8; i++, a += as, r += W * 3) { m = vmaxq_u8(m, vabdq_u8(vld1q_u8(a), vld1q_u8(r))); m8 = vmax_u8(m8, vabd_u8(vld1_u8(a + 16), vld1_u8(r + 16))); }
    x = vmaxvq_u8(m); y = vmaxv_u8(m8);
    return x > y ? x : y;
}
static inline void blk_sumdiff(const uint8_t *a, size_t as, const uint8_t *r, int sm[3]) { /* sum of a - r per channel */
    int16x8_t s0 = vdupq_n_s16(0), s1 = s0, s2 = s0; int i;
    for (i = 0; i < 8; i++, a += as, r += W * 3) {
        uint8x8x3_t x = vld3_u8(a), y = vld3_u8(r);
        s0 = vaddq_s16(s0, vreinterpretq_s16_u16(vsubl_u8(x.val[0], y.val[0]))); s1 = vaddq_s16(s1, vreinterpretq_s16_u16(vsubl_u8(x.val[1], y.val[1]))); s2 = vaddq_s16(s2, vreinterpretq_s16_u16(vsubl_u8(x.val[2], y.val[2])));
    }
    sm[0] = vaddlvq_s16(s0); sm[1] = vaddlvq_s16(s1); sm[2] = vaddlvq_s16(s2);
}
static inline int blk_range(const uint8_t *r) { /* largest max - min of the three channels */
    uint8x8x3_t v = vld3_u8(r); uint8x8_t n0 = v.val[0], x0 = n0, n1 = v.val[1], x1 = n1, n2 = v.val[2], x2 = n2; int i, a, b, c;
    for (i = 1; i < 8; i++) { r += W * 3; v = vld3_u8(r); n0 = vmin_u8(n0, v.val[0]); x0 = vmax_u8(x0, v.val[0]); n1 = vmin_u8(n1, v.val[1]); x1 = vmax_u8(x1, v.val[1]); n2 = vmin_u8(n2, v.val[2]); x2 = vmax_u8(x2, v.val[2]); }
    a = vmaxv_u8(x0) - vminv_u8(n0); b = vmaxv_u8(x1) - vminv_u8(n1); c = vmaxv_u8(x2) - vminv_u8(n2);
    if (b > a) a = b;
    return c > a ? c : a;
}
#else
static inline int blk_maxdiff(const uint8_t *a, size_t as, const uint8_t *r) {
    int i, x, m = 0;
    for (i = 0; i < 8; i++, a += as, r += W * 3) for (x = 0; x < 24; x++) { int d = abs(a[x] - r[x]); if (d > m) m = d; }
    return m;
}
static inline void blk_sumdiff(const uint8_t *a, size_t as, const uint8_t *r, int sm[3]) {
    int i, x;
    sm[0] = sm[1] = sm[2] = 0;
    for (i = 0; i < 8; i++, a += as, r += W * 3) for (x = 0; x < 24; x += 3) { sm[0] += a[x] - r[x]; sm[1] += a[x + 1] - r[x + 1]; sm[2] += a[x + 2] - r[x + 2]; }
}
static inline int blk_range(const uint8_t *r) {
    int mn[3] = {255, 255, 255}, mx[3] = {0, 0, 0}, i, x, c, m = 0;
    for (i = 0; i < 8; i++, r += W * 3) for (x = 0; x < 8; x++) for (c = 0; c < 3; c++) { int v = r[3 * x + c]; if (v < mn[c]) mn[c] = v; if (v > mx[c]) mx[c] = v; }
    for (c = 0; c < 3; c++) if (mx[c] - mn[c] > m) m = mx[c] - mn[c];
    return m;
}
#endif
static void job_csc(rnv2enc *e, int by) {
    int bx, r, y0 = by * 8, bx0 = 0, bx1 = BW, first = e->first;
    const uint8_t *dmg = e->damaged + by * BW; int bpp = e->fmt == RNV2_RGB24 || e->fmt == RNV2_BGR24 ? 3 : 4;
    if (!first) { /* x range of the damage in this band; none: nothing to convert or compare */
        while (bx0 < BW && !dmg[bx0]) bx0++;
        while (bx1 > bx0 && !dmg[bx1 - 1]) bx1--;
        if (bx0 >= bx1) { memset(e->changed + by * BW, 0, BW); memset(e->cscneed + by * BW, 0, BW); if (e->p.refine_static) { for (bx = 0; bx < BW; bx++) e->forced[by * BW + bx] = (uint8_t)can_force(e, by * BW + bx); } else memset(e->forced + by * BW, 1, BW); return; }
    }
    for (bx = 0; bx < BW; bx++) {
        int b = by * BW + bx, diff = 0, need;
        if (!dmg[bx] && !first) { e->changed[b] = 0; e->forced[b] = e->p.refine_static ? (uint8_t)can_force(e, b) : 1; e->cscneed[b] = 0; continue; }
        { /* compare with the source last taken for this block.  Changes within --srcdead levels do not count: the phone stream wobbles by a level or two in flat areas, and the panel cannot show that anyway */
            uint8_t nb[192]; const uint8_t *np, *rb = e->refrgb + (size_t)y0 * W * 3 + bx * 24; size_t ns; int dead = e->p.src_dead, any = 1;
            if (e->fmt == RNV2_RGB24) { np = e->cur + (size_t)y0 * e->curstride + (size_t)bx * 8 * bpp; ns = e->curstride; } /* the source rows themselves */
            else { for (r = 0; r < 8; r++) line8_rgb(e->cur + (size_t)(y0 + r) * e->curstride + (size_t)bx * 8 * bpp, e->fmt, nb + 24 * r); np = nb; ns = 24; }
            if (e->tvalid) {
                int md = blk_maxdiff(np, ns, rb);
                any = md > 0;
                if (any && dead > 0 && md <= dead) { int sm[3]; blk_sumdiff(np, ns, rb, sm); any = abs(sm[0]) >= e->p.src_mean || abs(sm[1]) >= e->p.src_mean || abs(sm[2]) >= e->p.src_mean; } /* a block whose mean moves is a real change on its way (a fade, a slow gradient), not noise */
            }
            if (any) { for (r = 0; r < 8; r++) memcpy(e->refrgb + (size_t)(y0 + r) * W * 3 + bx * 24, np + ns * r, 24); diff = 1; }
        }
        need = diff;
        if (need && (e->p.dither || e->p.smooth)) e->rng[b] = (uint8_t)blk_range(e->refrgb + (size_t)y0 * W * 3 + bx * 24); /* max-min per channel of this block */
        e->cscneed[b] = (uint8_t)need; /* a key frame recodes every block, but the target of an unchanged source block is still valid */
        if (first) diff = 1;
        e->changed[b] = (uint8_t)diff;
        /* unchanged source, SKIP last frame, and the block was last evaluated at a qp / mu no lower than now (a lower
           qp or mu could make rnv2.py refine it): the decision cannot change -> SKIP without evaluation */
        e->forced[b] = (uint8_t)(!diff && can_force(e, b));
    }
    csc_row(e, by, bx0, bx1);
}
/* Smooth blocks: the plain conversion instead of the glass fit.  The fit nudges luma pixel by pixel towards 6-bit levels, which on a gradient is noise: expensive to code, and it does not survive any loss anyway.
 * With --dither the screen-locked pattern goes on top, the same one the decoder adds to soft blocks.  Near black stays undithered: pure black must stay exactly black. */
static void plain_block(rnv2enc *e, int b, int dith) {
    int bx = b % BW, by = b / BW, r, x;
    for (r = 0; r < 8; r++) {
        const uint8_t *p = e->refrgb + (size_t)(by * 8 + r) * W * 3 + bx * 24; uint8_t *Y = e->tY + (by * 8 + r) * W + bx * 8, *U = e->tU + (by * 8 + r) * CW + bx * 4, *V = e->tV + (by * 8 + r) * CW + bx * 4;
        for (x = 0; x < 4; x++, p += 6) {
            int r0 = p[0], g0 = p[1], b0 = p[2], r1 = p[3], g1 = p[4], b1 = p[5];
            int y0 = (19595 * r0 + 38470 * g0 + 7471 * b0 + 32768) >> 16, y1 = (19595 * r1 + 38470 * g1 + 7471 * b1 + 32768) >> 16;
            int u = ((CBF(r0, g0, b0) + CBF(r1, g1, b1) + 65536) >> 17) + 128, v = ((CRF(r0, g0, b0) + CRF(r1, g1, b1) + 65536) >> 17) + 128;
            if (dith) { y0 += LAT_DITH[r & 1][0] - LAT_DITH_BASE; y1 += LAT_DITH[r & 1][1] - LAT_DITH_BASE; }
            Y[2 * x] = (uint8_t)CL255(y0); Y[2 * x + 1] = (uint8_t)CL255(y1); U[x] = (uint8_t)CL255(u); V[x] = (uint8_t)CL255(v);
        }
    }
}
static void smooth_classify(rnv2enc *e) {
    int b, R = e->p.dither_range;
    for (b = 0; b < NB; b++) {
        int bx = b % BW, by = b / BW, m = e->rng[b], a = m, d;
        if (bx > 0) { int v = e->rng[b - 1]; if (v > m) m = v; a |= v; }
        if (bx < BW - 1) { int v = e->rng[b + 1]; if (v > m) m = v; a |= v; }
        if (by > 0) { int v = e->rng[b - BW]; if (v > m) m = v; a |= v; }
        if (by < BH - 1) { int v = e->rng[b + BW]; if (v > m) m = v; a |= v; }
        d = m <= R && a > 0;
        if (d && e->p.dither) { const uint8_t *p = e->refrgb + (size_t)(by * 8 + 4) * W * 3 + bx * 24 + 12; if (p[0] + p[1] + p[2] < 48) d = 2; } /* dark: smooth, no pattern */
        else if (d && !e->p.dither) d = 2;
        if (d != e->dith[b]) { e->cscneed[b] = e->first ? e->cscneed[b] : 2; if (!e->first) { e->changed[b] = 1; e->forced[b] = 0; e->clean[b] = 0; } } /* the target of this block changes though its source did not */
        e->nxtd[b] = (uint8_t)d;
    }
}
static void job_smooth(rnv2enc *e, int by) {
    int b;
    for (b = by * BW; b < (by + 1) * BW; b++) {
        int d = e->nxtd[b];
        if (e->cscneed[b]) {
            if (d) plain_block(e, b, d == 1);
            else if (e->cscneed[b] == 2) { int r; for (r = 0; r < 8; r++) csc_seg(e, by * 8 + r, (b % BW) * 8, 4, 0); }
        }
        e->dith[b] = (uint8_t)d;
    }
}

/* ------------------------------------------------------------------ phase 2: global motion from projections */
/* Row profiles per vertical strip (4 x 200 px) and column profiles per horizontal band (3 x 160 rows) of the current
 * target and the reference.  A 1-D SAD search over shifts finds scroll (dy) and pan (dx) per strip / band and for the
 * whole frame; static chrome cancels out of the profile difference, so a list scrolling inside a static frame is found.
 * Candidates (full-pel, converted to half-pel units) are handed to every block's motion search. */
#define GCOARSE_TOP 3 /* shifts of the coarse 1-D search that get the full search around them */
static int64_t cost1d(const int32_t *c, const int32_t *r, int n, int d) { /* mean absolute difference of the profiles at shift d, Q12 */
    int i0 = d < 0 ? -d : 0, i1 = d > 0 ? n - d : n, i; int32_t s = 0; const int32_t *rr = r + d;
    for (i = i0; i < i1; i++) { int32_t x = c[i] - rr[i]; s += x < 0 ? -x : x; }
    return ((int64_t)s << 12) / (i1 - i0);
}
/* Coarse: profiles at half resolution, even shifts only.  Fine: search1d then costs only d = 0 and the best coarse shifts +-1. */
static void coarse1d(const int32_t *c, const int32_t *r, int n, int R, uint8_t *want) {
    int32_t c2[W / 2], r2[W / 2]; int m = n / 2, i, q, top[GCOARSE_TOP] = {0}; int64_t tc[GCOARSE_TOP];
    for (i = 0; i < GCOARSE_TOP; i++) tc[i] = INT64_MAX;
    for (i = 0; i < m; i++) { c2[i] = c[2 * i] + c[2 * i + 1]; r2[i] = r[2 * i] + r[2 * i + 1]; }
    for (q = -R / 2; q <= R / 2; q++) {
        int64_t sc = cost1d(c2, r2, m, q);
        if (sc < tc[GCOARSE_TOP - 1]) { for (i = GCOARSE_TOP - 1; i > 0 && sc < tc[i - 1]; i--) { tc[i] = tc[i - 1]; top[i] = top[i - 1]; } tc[i] = sc; top[i] = q; }
    }
    memset(want, 0, 2 * R + 3); want[R + 1] = 1;
    for (i = 0; i < GCOARSE_TOP; i++) if (tc[i] != INT64_MAX) { int d = 2 * top[i]; want[d + R] = want[d + R + 1] = want[d + R + 2] = 1; }
}
static void search1d(const int32_t *c, const int32_t *r, int n, int R, const uint8_t *want, int *best, int *second, int64_t *bcost, int64_t *zcost) {
    int d, d1 = 0, d2 = 0; int64_t b1 = INT64_MAX, b2 = INT64_MAX;
    for (d = -R; d <= R; d++) {
        int i0 = d < 0 ? -d : 0, i1 = d > 0 ? n - d : n; int64_t sc;
        if (i1 - i0 < n / 2 || (want && !want[d + R + 1])) continue;
        sc = cost1d(c, r, n, d);
        if (d == 0) *zcost = sc;
        if (sc < b1) { if (abs(d - d1) > 2) { b2 = b1; d2 = d1; } b1 = sc; d1 = d; }
        else if (sc < b2 && abs(d - d1) > 2) { b2 = sc; d2 = d; }
    }
    *best = d1; *second = d2; *bcost = b1;
}
static void add_g(rnv2enc *e, int dx, int dy) {
    int i;
    if (!dx && !dy) return;
    if (e->ng >= MAXG) return;
    for (i = 0; i < e->ng; i++) if (e->g[i][0] == 2 * dx && e->g[i][1] == 2 * dy) return;
    e->g[e->ng][0] = 2 * dx; e->g[e->ng][1] = 2 * dy; e->ng++;
}
static void job_proj(rnv2enc *e, int idx) { /* idx: image (0 cur, 1 ref) x band */
    int img = idx / GNBAND, k = idx % GNBAND;
    memset(e->G->rows[img] + k * GBHT * GNSX, 0, sizeof(uint32_t) * GBHT * GNSX); memset(e->G->cols[img][k], 0, sizeof(uint32_t) * W);
    KC(7, W * GBHT); e->k->proj_rows((img ? e->R[e->rb][0] : e->tY) + k * GBHT * W, W, W, GBHT, GSW, e->G->rows[img] + k * GBHT * GNSX, e->G->cols[img][k]);
}
static void job_gsearch(rnv2enc *e, int j) { /* 0 full rows, 1 full cols, 2-5 strips (rows), 6-8 bands (cols) */
    int n = (j == 0 || (j >= 2 && j <= 5)) ? H : W, t, fast = e->p.me_level == 2; int64_t bc, zc = 0; uint8_t want[2 * GRNG + 3];
    if (fast) coarse1d(e->G->prof[j][0], e->G->prof[j][1], n, GRNG, want);
    search1d(e->G->prof[j][0], e->G->prof[j][1], n, GRNG, fast ? want : NULL, &e->G->res[j][0], &e->G->res[j][1], &bc, &zc);
    if (bc >= zc) e->G->res[j][0] = 0;
    (void)t;
}
static void global_motion(rnv2enc *e, int nchanged) {
    int k, y, x, img, j;
    e->ng = 0;
    if (nchanged < 24) { e->prev_g[0] = e->prev_g[1] = 0; return; } /* nothing moves: no global candidates */
    run_jobs(e, job_proj, 2 * GNBAND);
    for (img = 0; img < 2; img++) {
        for (y = 0; y < H; y++) {
            int32_t f = 0;
            for (k = 0; k < GNSX; k++) { int32_t v = (int32_t)e->G->rows[img][y * GNSX + k]; e->G->prof[2 + k][img][y] = v; f += v; }
            e->G->prof[0][img][y] = f;
        }
        for (x = 0; x < W; x++) {
            int32_t f = 0;
            for (k = 0; k < GNBAND; k++) { e->G->prof[6 + k][img][x] = (int32_t)e->G->cols[img][k][x]; f += (int32_t)e->G->cols[img][k][x]; }
            e->G->prof[1][img][x] = f;
        }
    }
    run_jobs(e, job_gsearch, 9);
    {
        int dyF = e->G->res[0][0], dyF2 = e->G->res[0][1], dxF = e->G->res[1][0], dxF2 = e->G->res[1][1];
        add_g(e, dxF, dyF);
        for (j = 2; j <= 5; j++) add_g(e, 0, e->G->res[j][0]);
        for (j = 6; j <= 8; j++) add_g(e, e->G->res[j][0], 0);
        add_g(e, e->prev_g[0], e->prev_g[1]);
        add_g(e, dxF, 0); add_g(e, 0, dyF);
        add_g(e, dxF2, dyF); add_g(e, dxF, dyF2);
        e->prev_g[0] = dxF; e->prev_g[1] = dyF;
    }
}

/* ------------------------------------------------------------------ phase 3: block motion search (luma SAD) */
#define LAM_MV 4
/* --me 2 (the default) has no wide window, no 12-point refinement and one neighbour pass: on the test clips those moved the picture
 * by under 0.01 dB.  The half-pel step of the last pass is what still earns its cost.  --me 3 keeps the exhaustive search. */
#define ME_G_GOOD 128 /* cost at which the zero / previous mv is good enough to skip the global candidates (2 per pixel) */
#define ME_HP_GOOD 32 /* cost below which half-pel has nothing visible left to gain */
#define PRUNE_NACT 2500 /* active blocks from which the analysis prunes candidates (--prune); lighter frames always analyse everything */
/* cost of (mx, my), or any value >= lim once it is certain the candidate cannot beat lim (rows 4-7 are not read then) */
static inline uint32_t me_cost(const rnv2enc *e, int x0, int y0, const uint8_t *src, int mx, int my, uint32_t lim) {
    int ix = mx >> 1, fx = mx & 1, iy = my >> 1, fy = my & 1; const uint8_t *ref; uint32_t mc;
    if (!(x0 + ix >= 0 && x0 + ix + 7 + fx <= W - 1 && y0 + iy >= 0 && y0 + iy + 7 + fy <= H - 1)) return 0xFFFFFFFFu;
    KC(1, 1);
    mc = LAM_MV * ((mx != 0) + (my != 0));
#ifdef __ARM_NEON
    if (e->p.simd) {
        uint16x8_t acc; uint32_t h; int r;
        ref = e->R[e->rb][0] + (y0 + iy) * W + x0 + ix;
        if (fx | fy) { /* half-pel from the integer plane, equal to the half-pel planes: those would be three more planes to pull through the cache */
            uint8x8_t a = fx ? vrhadd_u8(vld1_u8(ref), vld1_u8(ref + 1)) : vld1_u8(ref), n;
            if (!fy) {
                acc = vabdl_u8(vld1_u8(src), a);
                for (r = 1; r < 8; r++) { if (r == 4 && (h = vaddlvq_u16(acc) + mc) >= lim) return h; acc = vabal_u8(acc, vld1_u8(src + r * W), vrhadd_u8(vld1_u8(ref + r * W), vld1_u8(ref + r * W + 1))); }
                return vaddlvq_u16(acc) + mc;
            }
            acc = vdupq_n_u16(0);
            for (r = 0; r < 8; r++, a = n) {
                n = fx ? vrhadd_u8(vld1_u8(ref + (r + 1) * W), vld1_u8(ref + (r + 1) * W + 1)) : vld1_u8(ref + (r + 1) * W);
                if (r == 4 && (h = vaddlvq_u16(acc) + mc) >= lim) return h;
                acc = vabal_u8(acc, vld1_u8(src + r * W), vrhadd_u8(a, n));
            }
            return vaddlvq_u16(acc) + mc;
        }
        acc = vabdl_u8(vld1_u8(src), vld1_u8(ref));
        acc = vabal_u8(acc, vld1_u8(src + W), vld1_u8(ref + W)); acc = vabal_u8(acc, vld1_u8(src + 2 * W), vld1_u8(ref + 2 * W)); acc = vabal_u8(acc, vld1_u8(src + 3 * W), vld1_u8(ref + 3 * W));
        h = vaddlvq_u16(acc) + mc;
        if (h >= lim) return h;
        for (r = 4; r < 8; r++) acc = vabal_u8(acc, vld1_u8(src + r * W), vld1_u8(ref + r * W));
        return vaddlvq_u16(acc) + mc;
    }
#endif
    ref = yplane(e, fy * 2 + fx) + (y0 + iy) * W + x0 + ix;
    return e->k->sad8x8(src, W, ref, W) + mc;
}
/* Full-pel candidates already costed for this block in this stage, as an 8x8 grid (-4..+3 px) around an anchor.  bc never rises,
 * so costing one again cannot change the result: dropping repeats is exact.  Other candidates are simply not tracked. */
static inline int vis_new(uint64_t *v, int dx, int dy) {
    unsigned ux = (unsigned)(dx + 8), uy = (unsigned)(dy + 8); uint64_t m;
    if ((ux | uy) & ~14u) return 1;
    m = 1ull << (uy * 4 + (ux >> 1));
    if (*v & m) return 0;
    *v |= m; return 1;
}
#define TRY(MX, MY) do { int mx_ = (MX), my_ = (MY); if ((mx_ != bx_ || my_ != by_) && vis_new(&vis_, mx_ - ox_, my_ - oy_)) { uint32_t c_ = me_cost(e, x0_, y0_, src, mx_, my_, bc); if (c_ < bc) { bc = c_; bx_ = mx_; by_ = my_; } } } while (0)

static void job_me_init(rnv2enc *e, int row) {
    int i, b, fast = e->p.me_level == 2;
    for (b = row * BW; b < (row + 1) * BW; b++) {
        int x0_ = (b - row * BW) * 8, y0_ = row * 8;
        const uint8_t *src = e->tY + y0_ * W + x0_;
        int bx_ = 0, by_ = 0, ox_ = 1 << 14, oy_ = 0; uint32_t bc; uint64_t vis_ = 0;
        e->medone[b] = 1;
        if (!(x0_ & 31)) { /* the next lines of the target and of the reference at mv 0: much of the time here is waiting on them */
            int r; const uint8_t *q = e->R[e->rb][0] + y0_ * W + x0_ + 64;
            for (r = 0; r < 8; r++) { __builtin_prefetch(src + 64 + r * W); __builtin_prefetch(q + r * W); }
        }
        if (e->forced[b] || (e->p.refine_static && !e->changed[b])) { e->mv0[b][0] = e->mv0[b][1] = 0; e->mc0[b] = 0; continue; } /* unchanged source: refinement in place, nothing to search */
        bc = me_cost(e, x0_, y0_, src, 0, 0, 0xFFFFFFFFu);
        if (bc) {
            int it;
            e->medone[b] = 0;
            TRY(e->prev_mv[b][0], e->prev_mv[b][1]);
            if (!fast || bc >= ME_G_GOOD) for (i = 0; i < e->ng; i++) TRY(e->g[i][0], e->g[i][1]);
            ox_ = bx_; oy_ = by_; (void)vis_new(&vis_, 0, 0); (void)vis_new(&vis_, -ox_, -oy_); (void)vis_new(&vis_, e->prev_mv[b][0] - ox_, e->prev_mv[b][1] - oy_);
            for (it = 0; it < (e->p.me_level >= 2 ? 8 : 4) && bc; it++) { /* small full-pel descent */
                int cx = bx_, cy = by_; uint32_t c0 = bc;
                TRY(cx + 2, cy); TRY(cx - 2, cy); TRY(cx, cy + 2); TRY(cx, cy - 2);
                if (bc == c0) break;
            }
            if (e->p.me_level >= 3 && bc > (uint32_t)e->p.me_win_thr && bc < (uint32_t)e->p.me_win_max) { /* +-3 full-pel window around the best start (rnv2.py searches +-3 around its global peaks) */
                int cx = bx_, cy = by_, dx, dy;
                for (dy = -6; dy <= 6; dy += 2) for (dx = -6; dx <= 6; dx += 2) TRY(cx + dx, cy + dy);
            }
        }
        e->mv0[b][0] = (int16_t)bx_; e->mv0[b][1] = (int16_t)by_; e->mc0[b] = bc;
    }
}
static void job_me_pass(rnv2enc *e, int row) { /* Jacobi: reads pass input (mv0/mc0 or mv1/mc1), writes the other */
    static const int8_t P12[12][2] = {{2, 0}, {-2, 0}, {0, 2}, {0, -2}, {2, 2}, {-2, -2}, {2, -2}, {-2, 2}, {4, 0}, {-4, 0}, {0, 4}, {0, -4}};
    static const int8_t P8[8][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {-1, -1}, {1, -1}, {-1, 1}};
    int16_t (*mi)[2] = (e->pass & 1) ? e->mv1 : e->mv0, (*mo)[2] = (e->pass & 1) ? e->mv0 : e->mv1;
    uint32_t *ci = (e->pass & 1) ? e->mc1 : e->mc0, *co = (e->pass & 1) ? e->mc0 : e->mc1;
    int last = e->pass == (e->p.me_level >= 1 ? 1 : 0), b, i;
    const uint8_t *pc = e->mchg[e->pass & 1]; uint8_t *oc = e->mchg[(e->pass & 1) ^ 1]; int fast = e->p.me_level == 2;
    if (fast && e->pass == 0) { b = row * BW; memcpy(mo[b], mi[b], BW * sizeof mo[0]); memcpy(co + b, ci + b, BW * sizeof co[0]); memset(oc + b, 1, BW); return; } /* one neighbour pass, the last */
    for (b = row * BW; b < (row + 1) * BW; b++) {
        int x0_ = (b - row * BW) * 8, y0_ = row * 8;
        const uint8_t *src = e->tY + y0_ * W + x0_;
        int bx_ = mi[b][0], by_ = mi[b][1], bxr = b - row * BW, byr = row; uint32_t bc = ci[b];
        if (!e->medone[b] && bc) {
            int ox_ = bx_, oy_ = by_; uint64_t vis_ = 1ull << 36; /* the block mv itself is already costed */
            /* Jacobi fixed point: if neither this block nor a neighbour changed in the previous pass, the
               neighbour + 12-point step would reproduce the previous result exactly -> skip it */
            int same = e->pass > 0 && !pc[b] && (bxr == 0 || !pc[b - 1]) && (bxr == BW - 1 || !pc[b + 1]) &&
                       (byr == 0 || !pc[b - BW]) && (byr == BH - 1 || !pc[b + BW]);
            if (!same) {
                if (bxr > 0) TRY(mi[b - 1][0], mi[b - 1][1]);
                if (bxr < BW - 1) TRY(mi[b + 1][0], mi[b + 1][1]);
                if (byr > 0) TRY(mi[b - BW][0], mi[b - BW][1]);
                if (byr < BH - 1) TRY(mi[b + BW][0], mi[b + BW][1]);
                /* no usable match nearby (cut / new content): skip the local refinements */
                if (!fast && bc < (uint32_t)e->p.me_win_max) { int cx = bx_, cy = by_; for (i = 0; i < 12 && bc; i++) TRY(cx + P12[i][0], cy + P12[i][1]); }
            }
            if (last && bc && bc < (uint32_t)e->p.me_win_max && (!fast || bc >= ME_HP_GOOD)) {
                int cx = bx_, cy = by_;
                if (fast) { /* the sides, then the two diagonals next to the side that won, if one did */
                    int hx = 0, hy = 0; uint32_t c1 = bc;
                    TRY(cx + 1, cy); if (bc < c1) { hx = 1; c1 = bc; }
                    TRY(cx - 1, cy); if (bc < c1) { hx = -1; c1 = bc; }
                    TRY(cx, cy + 1); if (bc < c1) { hy = 1; hx = 0; c1 = bc; }
                    TRY(cx, cy - 1); if (bc < c1) { hy = -1; hx = 0; c1 = bc; }
                    if (hx) { TRY(cx + hx, cy + 1); TRY(cx + hx, cy - 1); }
                    else if (hy) { TRY(cx + 1, cy + hy); TRY(cx - 1, cy + hy); }
                } else for (i = 0; i < 8; i++) TRY(cx + P8[i][0], cy + P8[i][1]);
            }
        }
        oc[b] = (uint8_t)(bx_ != mi[b][0] || by_ != mi[b][1]);
        mo[b][0] = (int16_t)bx_; mo[b][1] = (int16_t)by_; co[b] = bc;
    }
}

/* ------------------------------------------------------------------ phase 4: per-block RD analysis at qp */
static inline int64_t wsum(const uint32_t d[8]) { return 20 * ((int64_t)d[0] + d[1] + d[2] + d[3]) + 44 * ((int64_t)d[4] + d[5]) + 33 * ((int64_t)d[6] + d[7]); } /* WSB */
/* Which subblocks of a residual candidate pay at (lp, np), and their sums.  The sum order is the same in both paths: the float result must not depend on the build */
static inline unsigned dcand_eval(const dcand *c, float lp, float np, int *B, int *cy, float *gain) {
#ifdef __ARM_NEON
    static const uint32_t M0[4] = {1, 2, 4, 8}, M1[4] = {16, 32, 64, 128};
    uint16x8_t bb = vld1q_u16(c->bits), cc = vld1q_u16(c->cyc);
    float32x4_t g0 = vld1q_f32(c->g), g1 = vld1q_f32(c->g + 4);
    float32x4_t t0 = vaddq_f32(vmulq_n_f32(vcvtq_f32_u32(vmovl_u16(vget_low_u16(bb))), lp), vmulq_n_f32(vcvtq_f32_u32(vmovl_u16(vget_low_u16(cc))), np));
    float32x4_t t1 = vaddq_f32(vmulq_n_f32(vcvtq_f32_u32(vmovl_high_u16(bb)), lp), vmulq_n_f32(vcvtq_f32_u32(vmovl_high_u16(cc)), np));
    uint32x4_t m0 = vcgtq_f32(g0, t0), m1 = vcgtq_f32(g1, t1);
    uint16x8_t m16 = vcombine_u16(vmovn_u32(m0), vmovn_u32(m1));
    float32x4_t v = vaddq_f32(vreinterpretq_f32_u32(vandq_u32(vreinterpretq_u32_f32(g0), m0)), vreinterpretq_f32_u32(vandq_u32(vreinterpretq_u32_f32(g1), m1)));
    *B = vaddvq_u16(vandq_u16(bb, m16)); *cy = vaddvq_u16(vandq_u16(cc, m16));
    *gain = (vgetq_lane_f32(v, 0) + vgetq_lane_f32(v, 1)) + (vgetq_lane_f32(v, 2) + vgetq_lane_f32(v, 3));
    return vaddvq_u32(vandq_u32(m0, vld1q_u32(M0))) | vaddvq_u32(vandq_u32(m1, vld1q_u32(M1)));
#else
    unsigned cbp = 0; int k, b_ = 0, c_ = 0; float v[4] = {0, 0, 0, 0};
    for (k = 0; k < 8; k++) if (c->g[k] > (float)c->bits[k] * lp + (float)c->cyc[k] * np) { cbp |= 1u << k; b_ += c->bits[k]; c_ += c->cyc[k]; v[k & 3] += c->g[k]; }
    *B = b_; *cy = c_; *gain = (v[0] + v[1]) + (v[2] + v[3]);
    return cbp;
#endif
}
#define CBPB(x) (CBPL_LEN[(x) & 15] + CBPC_LEN[(x) >> 4])
static inline void blk_stats(const uint8_t *S, int *sy, int *su, int *sv, int *ry, int *rc) {
#ifdef __ARM_NEON
    uint8x16_t q0 = vld1q_u8(S), q1 = vld1q_u8(S + 16), q2 = vld1q_u8(S + 32), q3 = vld1q_u8(S + 48), q4 = vld1q_u8(S + 64), q5 = vld1q_u8(S + 80), q6 = vld1q_u8(S + 96), q7 = vld1q_u8(S + 112);
    int ru, rv;
    *sy = vaddlvq_u8(q0) + vaddlvq_u8(q1) + vaddlvq_u8(q2) + vaddlvq_u8(q3); *su = vaddlvq_u8(q4) + vaddlvq_u8(q5); *sv = vaddlvq_u8(q6) + vaddlvq_u8(q7);
    *ry = vmaxvq_u8(vmaxq_u8(vmaxq_u8(q0, q1), vmaxq_u8(q2, q3))) - vminvq_u8(vminq_u8(vminq_u8(q0, q1), vminq_u8(q2, q3)));
    ru = vmaxvq_u8(vmaxq_u8(q4, q5)) - vminvq_u8(vminq_u8(q4, q5)); rv = vmaxvq_u8(vmaxq_u8(q6, q7)) - vminvq_u8(vminq_u8(q6, q7));
    *rc = ru > rv ? ru : rv;
#else
    int k, a = 0, n = 255, x = 0, ru, rv;
    for (k = 0; k < 64; k++) { int v = S[k]; a += v; if (v < n) n = v; if (v > x) x = v; }
    *sy = a; *ry = x - n; a = 0; n = 255; x = 0;
    for (k = 64; k < 96; k++) { int v = S[k]; a += v; if (v < n) n = v; if (v > x) x = v; }
    *su = a; ru = x - n; a = 0; n = 255; x = 0;
    for (k = 96; k < 128; k++) { int v = S[k]; a += v; if (v < n) n = v; if (v > x) x = v; }
    *sv = a; rv = x - n; *rc = ru > rv ? ru : rv;
#endif
}
#define RES_GATE_LAM 0.5
#define RES_SB_BITS 3     /* the cheapest coded subblock: one coefficient */
#define RES_SB_CYC 237    /* CY_DC + CY_ADD_YDC + CY_COEF */
#define RES_MINBITS 10
/* phase 4a: what any block needs: the predictions and the residual candidates */
static void analyse_block(rnv2enc *e, int b, int *ncand) {
    blkstat *s = &e->bs[b]; blkdc *h = &e->dc[b]; dcand *dcn = e->dcp + (b / BW) * BW * 3 + *ncand;
    uint8_t S[128], Z[128], P[128], I[128], rec[128]; int16_t T[128]; uint32_t ds[8], dm[8], di[8], don[8]; uint16_t cbits[8], ccyc[8];
    const qtab_t *qi, *qa;
    const int16_t (*mv)[2] = e->mv0; /* final mv field */
    int c, mx = mv[b][0], my = mv[b][1], sy, su, sv, ry, rc, has_mc; int64_t Sds = 0, Sdm = 0, Sdi = 0; unsigned skipc = 0;
    h->valid = 0;
    if (e->forced[b]) return;
    h->valid = 1; h->cskip = e->prevmode[b] != SKIP ? CY_SKIPCOPY : CY_SKIP;
    qi = e->qt[e->cqp][0]; qa = e->qt[e->cqp][1]; /* built at create */
    gather_blk(e->tY, e->tU, e->tV, b, S);
    gather_blk(e->R[e->rb][0], e->R[e->rb][1], e->R[e->rb][2], b, Z);
    KC(2, 1), e->k->pd8(S, Z, e->kappa16, e->thr, ds);
    if (!e->key && (!(ds[0] | ds[1] | ds[2] | ds[3] | ds[4] | ds[5] | ds[6] | ds[7]) || (e->p.glass_dead && (uint64_t)ds[0] + ds[1] + ds[2] + ds[3] + ds[4] + ds[5] + ds[6] + ds[7] < 32768 && glass_equal(S, Z)))) {
        /* reference == target at the panel: SKIP has nothing to fix */
        h->valid = 2; return;
    }
    blk_stats(S, &sy, &su, &sv, &ry, &rc);
    h->ry = (uint8_t)ry; h->rc = (uint8_t)rc;
    s->fill[0] = (uint8_t)((sy + 32) >> 6); s->fill[1] = (uint8_t)((su + 16) >> 5); s->fill[2] = (uint8_t)((sv + 16) >> 5);
    memset(I, s->fill[0], 64); memset(I + 64, s->fill[1], 32); memset(I + 96, s->fill[2], 32);
    KC(2, 1), e->k->pd8(S, I, e->kappa16, e->thr, di);
    has_mc = (mx || my);
    if (has_mc) { mc_pred(e, b, mx, my, P); KC(2, 1), e->k->pd8(S, P, e->kappa16, e->thr, dm); }
    {
        int lx = b > 0 ? mv[b - 1][0] : 0, ly = b > 0 ? mv[b - 1][1] : 0;
        h->mvbits = (uint16_t)(ue_len(se_map(mx - lx)) + ue_len(se_map(my - ly)));
        h->mcc = (uint16_t)mc_cycles(mx, my);
    }
    Sds = wsum(ds); if (has_mc) Sdm = wsum(dm); Sdi = wsum(di);
    h->Jds = (float)(Sds / DSCALE); h->Jdm = has_mc ? (float)(Sdm / DSCALE) : INFINITY; h->Jdi = (float)(Sdi / DSCALE);
    if (e->p.prune && e->nact >= e->p.prune_nact) { /* heavy frame: residual candidates whose prediction is worse than another candidate's rarely win, don't transform them */
        int64_t Smin = has_mc && Sdm < Sds ? Sdm : Sds; double pr = e->p.prune_r;
        if (has_mc && Sds > pr * Sdm) skipc |= 2;  /* ZRES: MC predicts better */
        if (has_mc && Sdm > pr * Sds) skipc |= 1;  /* MCR: the reference in place predicts better */
        if (Sdi > pr * Smin) skipc |= 4;              /* INTRA: an inter prediction is better than the flat fill */
    }
    /* the same error shows more on a smooth block than in texture: steer bits there.  pw 1 from a range of 48 up, pw_max at 6 and below */
    { int ra = ry > rc ? ry : rc; double pw = ra >= 48 ? 1.0 : ra <= 6 ? e->p.pw_max : 1.0 + (e->p.pw_max - 1.0) * (48 - ra) / 42.0; h->ipw = (float)(1.0 / pw); }
    if (!e->key && !e->burst && e->p.force_mode <= 0) {
        /* Last frame's lambda and nu, with room for them to fall.  A subblock whose whole error is less than one coefficient costs cannot be worth coding, whatever its residual looks like: skip the candidate if none is.
         * And a candidate cannot win if the plain prediction beats its bits and cycles alone */
        const float lg = (float)(RES_GATE_LAM * e->lamp) * h->ipw, ng = (float)(RES_GATE_LAM * e->mup) * h->ipw, jp = h->Jdm + lg * (3 + h->mvbits) + ng * (CY_HDR + h->mcc), js = h->Jds + lg + ng * h->cskip, j0 = jp < js ? jp : js;
        const double sbmin = (double)(lg * RES_SB_BITS + ng * RES_SB_CYC) * DSCALE;
        const uint32_t *dv[3]; dv[0] = dm; dv[1] = ds; dv[2] = di;
        for (c = 0; c < 3; c++) if (!(c == 0 && !has_mc)) {
            const uint32_t *d = dv[c]; uint32_t my_ = d[0] > d[1] ? d[0] : d[1], m2_; int64_t ms;
            if (d[2] > my_) my_ = d[2]; if (d[3] > my_) my_ = d[3];
            ms = 20 * (int64_t)my_; m2_ = d[4] > d[5] ? d[4] : d[5]; if (44 * (int64_t)m2_ > ms) ms = 44 * (int64_t)m2_; m2_ = d[6] > d[7] ? d[6] : d[7]; if (33 * (int64_t)m2_ > ms) ms = 33 * (int64_t)m2_;
            if ((double)ms <= sbmin) skipc |= 1u << c;
            else if (j0 < lg * (RES_MINBITS + (c == 0 ? 3 + h->mvbits : c == 1 ? 3 : 18)) + ng * (CY_HDR + RES_SB_CYC + (c == 0 ? h->mcc : c == 1 ? CY_ZRES : CY_FILL))) skipc |= 1u << c;
        }
    }
    for (c = 0; c < 3; c++) {
        const uint8_t *pr = c == 0 ? P : c == 1 ? Z : I; const uint32_t *doff = c == 0 ? dm : c == 1 ? ds : di; int sb, nz, pos = 0;
        h->cand[c] = DCNONE;
        if ((c == 0 && !has_mc) || (c == 1 && e->key) || (skipc >> c & 1)) continue; /* key: a residual on black is a worse INTRA */
        KC(3, 1), e->k->fwd8(S, pr, T);
        nz = quant_bits(e, T, c == 2 ? qa : qi, s->L3[c], cbits, ccyc);
        if (nz) {
            recon_res(e, s->L3[c], nz, e->step, pr, rec); KC(2, 1), e->k->pd8(S, rec, e->kappa16, e->thr, don);
            for (sb = 0; sb < 8; sb++) { float g = -1; if (nz & (1 << sb)) { g = (float)(WSB[sb] * ((double)doff[sb] - (double)don[sb]) / DSCALE); pos |= g > 0; } dcn->g[sb] = g; dcn->bits[sb] = cbits[sb]; dcn->cyc[sb] = ccyc[sb]; }
            if (pos) { h->cand[c] = (uint16_t)(dcn - e->dcp); dcn++; ++*ncand; } /* no subblock gains at any lambda: the candidate does not exist */
        }
    }
    h->Dlat[0] = h->Dlat[1] = h->Dlat[2] = h->Dbtc[0] = h->Dbtc[1] = INFINITY;
}
static void job_analyse(rnv2enc *e, int row) { int b, nc = 0; for (b = row * BW; b < (row + 1) * BW; b++) analyse_block(e, b, &nc); }
#define ANA_ALL 800   /* fewer active blocks than this: all of them are the sample */
#define ANA_STEP 5    /* one block in this many */
#define GATE_LAM 0.5  /* the gates use this fraction of the sample's lambda: the fill pass goes below the frame's lambda */
#define KEY_QPMAX 20  /* a key frame leans on fills and tone blocks, residuals above this cost it more than they save */
#define GATE_REDO 1.5 /* the frame's lambda off the sample's by more than this: run the gates again */
/* the block's best J without soft and tone candidates */
static inline float jb_cheap(const rnv2enc *e, const blkdc *h, float lg, float ng) {
    float j = h->Jdm + lg * (3 + h->mvbits) + ng * (CY_HDR + h->mcc), t; int c;
    if (!e->key) { t = h->Jds + lg + ng * h->cskip; if (t < j) j = t; }
    t = h->Jdi * (float)e->p.fill_pen + lg * (3 + 15 + CBPB(0)) + ng * (CY_HDR + CY_FILL); if (t < j) j = t;
    if (e->p.use_raw) { t = lg * (3 + 1024) + ng * (CY_HDR + CY_RAW); if (t < j) j = t; }
    for (c = 0; c < 3; c++) if (h->cand[c] != DCNONE) {
        int B, cy; float g; unsigned cbp = dcand_eval(&e->dcp[h->cand[c]], lg, ng, &B, &cy, &g);
        if (cbp) { t = (c == 0 ? h->Jdm : c == 1 ? h->Jds : h->Jdi) - g + lg * (3 + (c == 0 ? h->mvbits : c == 2 ? 15 : 0) + B + CBPB(cbp)) + ng * (CY_HDR + (c == 0 ? h->mcc : c == 1 ? CY_ZRES : CY_FILL) + cy); if (t < j) j = t; }
    }
    return j;
}
/* Luma flat over 2x2 cells of the block itself, chroma exact: what LAT8 and LAT4 cannot beat, because their luma is flat over those cells */
static inline float cell_energy(const rnv2enc *e, const uint8_t *S) {
#if defined(__ARM_NEON) && defined(__ARM_FEATURE_DOTPROD)
    const uint8x16_t T = vdupq_n_u8((uint8_t)e->thr); uint32x4_t aa = vdupq_n_u32(0), mm = aa; int sb;
    for (sb = 0; sb < 4; sb++) {
        uint8x16_t q = vld1q_u8(S + 16 * sb), v = vrhaddq_u8(q, vreinterpretq_u8_u32(vrev64q_u32(vreinterpretq_u32_u8(q)))), a = vabdq_u8(q, vrhaddq_u8(v, vrev16q_u8(v))), m = vqsubq_u8(a, T);
        aa = vdotq_u32(aa, a, a); mm = vdotq_u32(mm, m, m);
    }
    return (float)(20 * ((int64_t)16 * vaddvq_u32(aa) + (int64_t)e->kappa16 * vaddvq_u32(mm)) / DSCALE);
#else
    uint8_t M[128]; uint32_t d[8]; int sb;
    memcpy(M + 64, S + 64, 64);
    for (sb = 0; sb < 4; sb++) {
        const uint8_t *p = S + 16 * sb; uint8_t *m = M + 16 * sb; int k;
        for (k = 0; k < 16; k += 2) { int k2 = k ^ 4, v0 = (p[k] + p[k2] + 1) >> 1, v1 = (p[k + 1] + p[k2 + 1] + 1) >> 1; m[k] = m[k + 1] = (uint8_t)((v0 + v1 + 1) >> 1); }
    }
    e->k->pd8(S, M, e->kappa16, e->thr, d);
    return (float)(wsum(d) / DSCALE);
#endif
}
/* sum of squared differences of n 16-byte groups */
static inline int ssd16(const uint8_t *a, const uint8_t *b, int n) {
#if defined(__ARM_NEON) && defined(__ARM_FEATURE_DOTPROD)
    uint32x4_t s = vdupq_n_u32(0); int i;
    for (i = 0; i < n; i++) { uint8x16_t d = vabdq_u8(vld1q_u8(a + 16 * i), vld1q_u8(b + 16 * i)); s = vdotq_u32(s, d, d); }
    return (int)vaddvq_u32(s);
#else
    int k, s = 0; for (k = 0; k < 16 * n; k++) { int t = a[k] - b[k]; s += t * t; } return s;
#endif
}
/* phase 4b: soft and tone blocks, which take most of the analysis and win rarely.  gated: this frame's lambda is known (lam_gate), so skip what cannot beat the block's best J at that lambda.
 * The constants come from a per-block study: nearly nothing is lost at these values (GATE_* below) */
#define GATE_L84 1.3f   /* LAT8, LAT4 distortion against cell_energy */
#define GATE_L2 0.35f   /* LAT2 distortion against cell_energy: it has detail, this is not a bound but rarely passes when it should not */
#define GATE_B2 0.8f    /* BTC2 distortion against the energy of the two-tone fit */
#define GATE_B4 0.15f   /* BTC4 the same */
#define LAT2_MINBITS 25
static void analyse_soft(rnv2enc *e, int b, int gated) {
    static const int CL_[3] = {CY_LAT8, CY_LAT4, CY_LAT2};
    blkstat *s = &e->bs[b]; blkdc *h = &e->dc[b]; uint8_t S[128], rec[128]; uint32_t dd[8]; int d, k, ry = h->ry, rc = h->rc, skip84 = 0;
    double Dl[3] = {-1, -1, -1}; float ip = h->ipw, lg = (float)e->lam_gate * ip, ng = (float)e->nu_gate * ip, jb = 0, E22 = 0;
    if (!e->p.r3) return;
    if (e->p.force_mode > 0 || e->p.stale_w > 0) gated = 0;
    h->Dlat[0] = h->Dlat[1] = h->Dlat[2] = h->Dbtc[0] = h->Dbtc[1] = INFINITY;
    if (gated) {
        jb = jb_cheap(e, h, lg, ng);
        if (jb < lg * 8 + ng * (CY_HDR + CY_LAT8)) return; /* within what the cheapest soft block costs in bits and cycles alone, and every other candidate costs more */
    }
    gather_blk(e->tY, e->tU, e->tV, b, S);
    if (gated && !e->p.dither) { E22 = cell_energy(e, S); skip84 = jb < GATE_L84 * E22 + lg * 8 + ng * (CY_HDR + CY_LAT8); }
    if (e->lat_ok) for (d = 0; d < 3; d++) {
        if (d < 2 && skip84) continue;
        if (d > 0 && Dl[d - 1] >= 0 && Dl[d - 1] < 16) break; /* a coarser lattice is already nearly exact */
        if (d == 2 && gated && jb < GATE_L2 * E22 + lg * LAT2_MINBITS + ng * (CY_HDR + CY_LAT2)) break;
        h->blat[d] = (uint16_t)lat_bits_est(e, b, d);
        if (gated && d > 0 && Dl[d - 1] >= 0 && (lg * (h->blat[d] - h->blat[d - 1]) + ng * (CL_[d] - CL_[d - 1])) > 1.5 * Dl[d - 1]) break; /* even an exact block would not pay for the extra bits and cycles */
        lat_recon(e, b, d, rec); e->k->pd8(S, rec, e->kappa16, e->thr, dd);
        Dl[d] = wsum(dd) / DSCALE; h->Dlat[d] = (float)Dl[d];
        if (gated) { float t = (float)Dl[d] + lg * (5 + h->blat[d]) + ng * (CY_HDR + CL_[d]); if (t < jb) jb = t; }
    }
    { int tone = ry >= 10 || rc >= 10;
      if (gated) { /* a block already within what the tone bits would cost cannot gain; at a very low lambda RAW beats it anyway */
          if (jb < lg * 84 + ng * (CY_HDR + CY_BTC2) || e->lam_est * ip < e->p.btc_lmin) tone = 0;
      }
      if (tone && ry >= rc) { /* most pixels in the middle of the range: texture or a gradient, not two tones */
          int n_mid = 0, ymn = 255; for (k = 0; k < 64; k++) if (S[k] < ymn) ymn = S[k]; { int q_ = ry / 4, m0 = ymn + q_, m1 = ymn + ry - q_; for (k = 0; k < 64; k++) n_mid += S[k] > m0 && S[k] < m1; if (n_mid > 26) tone = 0; } }
      if (tone) { /* tone blocks are for real edges */
        int E, E2; btcctx bc; uint8_t Fl[128];
        memset(Fl, s->fill[0], 64); memset(Fl + 64, s->fill[1], 32); memset(Fl + 96, s->fill[2], 32);
        E = ssd16(S, Fl, 4) + 2 * ssd16(S + 64, Fl + 64, 4);
        btc_load(e, b, &bc); btc_first(&bc, &s->btc[1], s->m2, &s->btc[0]);
        btc2_rec(&s->btc[1], s->m2, rec);
        E2 = ssd16(S, rec, 4) + 2 * ssd16(S + 64, rec + 64, 4);
        if (E2 * e->p.btc_gate <= E) {
            if (!gated || jb >= GATE_B2 * (float)E2 + lg * (4 + 64 + 16) + ng * (CY_HDR + CY_BTC2)) { e->k->pd8(S, rec, e->kappa16, e->thr, dd); h->Dbtc[1] = (float)(wsum(dd) / DSCALE); }
            if (!gated || jb >= GATE_B4 * (float)E2 + lg * (3 + 128 + 16) + ng * (CY_HDR + CY_BTC4)) { btc_full(&bc, &s->btc[0], s->m4); btc4_rec(&s->btc[0], s->m4, rec); e->k->pd8(S, rec, e->kappa16, e->thr, dd); h->Dbtc[0] = (float)(wsum(dd) / DSCALE); }
        }
      } }
}
static void job_soft0(rnv2enc *e, int row) { int b; for (b = row * BW; b < (row + 1) * BW; b++) if (e->dc[b].valid == 1 && e->smp[b]) analyse_soft(e, b, 0); }
static void job_soft1(rnv2enc *e, int row) { int b; for (b = row * BW; b < (row + 1) * BW; b++) if (e->dc[b].valid == 1 && !e->smp[b]) analyse_soft(e, b, !e->key && !e->burst); }

/* ------------------------------------------------------------------ phase 5: mode decision at (lambda, mu) */
typedef struct { float lam, nu, K[M_COUNT]; } decpar; /* K: the part of lambda bits + nu cycles that is the same for every block */
static inline void decide_block(const rnv2enc *e, int b, const decpar *q) {
    const blkdc *h = &e->dc[b]; blkdec *d = &e->bd[b];
    float J[M_COUNT], Dc[3], ip, lp, np, bj; int cbp[3] = {0, 0, 0}, B[3] = {0, 0, 0}, cy[3] = {0, 0, 0}, c, m, best;
    if (h->valid != 1) { d->mode = SKIP; d->cbp = 0; d->cbits = 0; d->cyc = h->cskip; d->ebits = 0; d->dist = 0; return; }
    ip = h->ipw; lp = q->lam * ip; np = q->nu * ip;
    Dc[0] = h->Jdm; Dc[1] = h->Jds; Dc[2] = h->Jdi;
    for (c = 0; c < 3; c++) if (h->cand[c] != DCNONE) { float g; cbp[c] = (int)dcand_eval(&e->dcp[h->cand[c]], lp, np, &B[c], &cy[c], &g); if (cbp[c]) Dc[c] -= g; }
    J[SKIP] = h->Jds + lp + np * h->cskip;
    J[MC] = h->Jdm + lp * (3 + h->mvbits) + np * (CY_HDR + h->mcc);
    J[MCR] = cbp[0] ? Dc[0] + lp * (3 + h->mvbits + B[0] + CBPB(cbp[0])) + np * (CY_HDR + h->mcc + cy[0]) : INFINITY;
    J[ZRES] = cbp[1] ? Dc[1] + lp * (3 + B[1] + CBPB(cbp[1])) + np * (CY_HDR + CY_ZRES + cy[1]) : INFINITY;
    J[INTRA] = (cbp[2] ? Dc[2] : Dc[2] * (float)e->p.fill_pen) + lp * (3 + 15 + B[2] + CBPB(cbp[2])) + np * (CY_HDR + CY_FILL + cy[2]);
    J[RAW] = ip * q->K[RAW];
    J[M_LAT8] = h->Dlat[0] + lp * h->blat[0] + ip * q->K[M_LAT8];
    J[M_LAT4] = h->Dlat[1] + lp * h->blat[1] + ip * q->K[M_LAT4];
    J[M_LAT2] = h->Dlat[2] + lp * h->blat[2] + ip * q->K[M_LAT2];
    J[M_BTC4] = h->Dbtc[0] + ip * q->K[M_BTC4];
    J[M_BTC2] = h->Dbtc[1] + ip * q->K[M_BTC2];
    if (e->key) J[SKIP] = INFINITY;
    if (e->p.stale_w > 0) { /* picture that stays visibly wrong costs extra: a coarse replacement beats a cheap stale block */
        float sd = (float)e->p.stale_d, w = (float)e->p.stale_w;
        if (h->Jds > sd) J[SKIP] += w * (h->Jds - sd);
        if (h->Jdm < INFINITY && h->Jdm > sd) J[MC] += w * (h->Jdm - sd);
        if (J[MCR] < INFINITY && Dc[0] > sd) J[MCR] += w * (Dc[0] - sd);
        if (J[ZRES] < INFINITY && Dc[1] > sd) J[ZRES] += w * (Dc[1] - sd);
        if (Dc[2] > sd) J[INTRA] += w * (Dc[2] - sd);
    }
    best = 0; bj = J[0];
    for (m = 1; m < M_COUNT; m++) { int lt = J[m] < bj; bj = lt ? J[m] : bj; best = lt ? m : best; }
    if (e->p.force_mode > 0 && J[e->p.force_mode] < INFINITY) best = e->p.force_mode; /* test streams: one mode everywhere */
    d->mode = (uint8_t)best; d->cbp = 0; d->cbits = 0;
    switch (best) {
    case SKIP: d->cyc = h->cskip; d->dist = h->Jds; d->ebits = 0; break;
    case MC: d->cyc = CY_HDR + h->mcc; d->dist = h->Jdm; d->ebits = 4 + h->mvbits; break;
    case MCR: d->cand = 0; d->cbp = (uint8_t)cbp[0]; d->cbits = B[0]; d->cyc = CY_HDR + h->mcc + cy[0]; d->dist = Dc[0]; d->ebits = 6 + h->mvbits + B[0] + CBPB(cbp[0]); break;
    case ZRES: d->cand = 1; d->cbp = (uint8_t)cbp[1]; d->cbits = B[1]; d->cyc = CY_HDR + CY_ZRES + cy[1]; d->dist = Dc[1]; d->ebits = 6 + B[1] + CBPB(cbp[1]); break;
    case INTRA: d->cand = 2; d->cbp = (uint8_t)cbp[2]; d->cbits = B[2]; d->cyc = CY_HDR + CY_FILL + cy[2]; d->dist = Dc[2]; d->ebits = 6 + 15 + B[2] + CBPB(cbp[2]); break;
    case M_LAT8: d->cyc = CY_HDR + CY_LAT8 + (e->p.dither ? CY_DITH : 0); d->dist = h->Dlat[0]; d->ebits = 8 + h->blat[0]; break;
    case M_LAT4: d->cyc = CY_HDR + CY_LAT4 + (e->p.dither ? CY_DITH : 0); d->dist = h->Dlat[1]; d->ebits = 8 + h->blat[1]; break;
    case M_LAT2: d->cyc = CY_HDR + CY_LAT2; d->dist = h->Dlat[2]; d->ebits = 8 + h->blat[2]; break;
    case M_BTC4: d->cyc = CY_HDR + CY_BTC4; d->dist = h->Dbtc[0]; d->ebits = 6 + 128 + 16; break;
    case M_BTC2: d->cyc = CY_HDR + CY_BTC2; d->dist = h->Dbtc[1]; d->ebits = 7 + 64 + 16; break;
    default: d->cyc = CY_HDR + CY_RAW; d->dist = 0; d->ebits = 7 + 1024; break;
    }
}
/* only the active blocks: the decision of a forced block is fixed for the whole frame */
#define DSLICE 128
#define DECIDE() run_w(e, job_decide, (e->nact + DSLICE - 1) / DSLICE, e->nact, 256)
static inline void decide_list(rnv2enc *e, const uint16_t *list, int cnt, int j) {
    int i, n = (j + 1) * DSLICE, dc_ = e->p.dither ? CY_DITH : 0; double l = e->lam, nu = e->lam * e->cmu; decpar q;
    q.lam = (float)l; q.nu = (float)nu;
    q.K[RAW] = e->p.use_raw ? (float)(l * (3 + 1024) + nu * (CY_HDR + CY_RAW)) : INFINITY;
    q.K[M_LAT8] = (float)(l * 5 + nu * (CY_HDR + CY_LAT8 + dc_)); q.K[M_LAT4] = (float)(l * 5 + nu * (CY_HDR + CY_LAT4 + dc_)); q.K[M_LAT2] = (float)(l * 5 + nu * (CY_HDR + CY_LAT2));
    q.K[M_BTC4] = (float)(l * (3 + 128 + 16) + nu * (CY_HDR + CY_BTC4)); q.K[M_BTC2] = (float)(l * (4 + 64 + 16) + nu * (CY_HDR + CY_BTC2));
    if (n > cnt) n = cnt;
    for (i = j * DSLICE; i < n; i++) decide_block(e, list[i], &q);
}
static void job_decide(rnv2enc *e, int j) { decide_list(e, e->act, e->nact, j); }
static void job_decide_s(rnv2enc *e, int j) { decide_list(e, e->sact, e->nsact, j); }
/* This frame's lambda and nu from a sample of the blocks (all their candidates are in), before the rest of the analysis.  The search below starts from them, and the rest of the analysis gates against them */
static void sample_eval(rnv2enc *e, double l, double nu, double scale, double cyfix, double rat, double *bits, double *cyc) {
    int64_t sb = 0, sc = 0; int i;
    e->lam = l; e->cmu = nu / l; run_w(e, job_decide_s, (e->nsact + DSLICE - 1) / DSLICE, e->nsact, 256);
    for (i = 0; i < e->nsact; i++) { const blkdec *d = &e->bd[e->sact[i]]; sb += d->ebits; sc += d->cyc; }
    *bits = (double)sb * scale * rat; *cyc = cyfix + (double)sc * scale;
}
static void lam_presearch(rnv2enc *e, double lam, double nu, double Tb, double cb, double rat, double LMIN, double LMAX, int n1) {
    const int cold = e->key || e->burst; const double tol = cold ? 1.0 : 1.03; /* a sample cannot tell 1.00 from 1.02, and nu is slow: the search below has the last word */
    double scale = (double)n1 / e->nsact, cyfix = CY_FRAME, l = lam, n = nu, lo = 0, hi = 0, lp_ = 0, bp = 0, b0, c0, slope = e->rslope; int b, it;
    for (b = 0; b < NB; b++) { const blkdc *h = &e->dc[b]; if (e->forced[b]) cyfix += e->bd[b].cyc; else if (h->valid != 1) cyfix += h->cskip; }
    for (it = 0; it < (cold ? 10 : 6); it++) {
        double eb, ec, next;
        sample_eval(e, l, n, scale, cyfix, rat, &b0, &c0); eb = b0 / Tb; ec = c0 / cb;
        if (lp_ > 0 && b0 > 0 && bp > 0 && l != lp_) { double sl = log(b0 / bp) / log(l / lp_); if (sl < -0.1 && sl > -8) slope = sl; }
        if (eb <= tol && (eb >= 0.9 || l <= LMIN)) { /* the bytes are right: now the cycles, by their price */
            double r = ec / 0.98;
            if (ec <= tol) break;
            r *= r; if (n <= 0) n = l * 0.002; n *= cold && r < 1.2 ? 1.2 : r; lo = hi = lp_ = 0;
            continue;
        }
        if (eb > tol) lo = l; else hi = l;
        if (lo > 0 && hi > 0 && hi / lo < 1.04) break; /* a cliff in the size: the search below deals with it */
        next = l * pow((eb > 1e-3 ? eb : 1e-3) / 0.97, -1 / slope);
        if (next < LMIN) next = LMIN; if (next > LMAX) next = LMAX; if (next > l * 64) next = l * 64; if (next < l / 64) next = l / 64;
        if (lo > 0 && hi > 0 && (next <= lo || next >= hi)) next = sqrt(lo * hi);
        lp_ = l; bp = b0; l = next;
    }
    e->rslope = slope; e->lam_est = l; e->nu_est = n;
}
/* what the search uses: the decisions' own bit estimates and cycles, summed.  The exact walker corrects it through a ratio */
static void fast_size(const rnv2enc *e, double *bits, double *cyc) {
    int64_t bb = 0; int64_t cy = CY_FRAME; int b;
    for (b = 0; b < NB; b++) { const blkdec *d = &e->bd[b]; bb += d->ebits; cy += d->cyc; }
    *bits = (double)bb; *cyc = (double)cy;
}

/* exact frame size (bytes incl. 24-byte header) and modelled decode cycles of the current decisions */
static void frame_size(rnv2enc *e, size_t *bytes, double *cyc) {
    int64_t b0 = 0, b1 = 0, b2 = 0, nraw = 0, ns3 = 0; int run = 0, pmx = 0, pmy = 0, pf[3] = {128, 128, 128}, b, nc = 0; double cy = CY_FRAME; emit_t st;
    static const uint8_t ML[M_COUNT] = {0, 2, 3, 3, 3, 4, 5, 5, 5, 3, 4}; int r3 = e->p.r3;
    memset(&st, 0, sizeof st); { int i_, j_; for (i_ = 0; i_ < 3; i_++) for (j_ = 0; j_ < 3; j_++) st.last[i_][j_] = 128; for (i_ = 0; i_ < 6; i_++) st.btc[i_] = 128; }
    for (b = 0; b < NB; b++) {
        const blkdec *d = &e->bd[b]; int m = d->mode;
        cy += d->cyc;
        if (m == SKIP) { run++; continue; }
        b0 += ue_len((uint32_t)run) + (r3 ? ML[m] : (m >= INTRA ? 3 : 2)); run = 0; nc++;
        if (m >= M_LAT8 && m <= M_LAT2) { b1 += lat_emit(e, b, m - M_LAT8, &st, NULL); continue; }
        if (m == M_BTC4) { b1 += btc_emit(&e->bs[b].btc[0], &st, NULL); ns3 += 16; continue; }
        if (m == M_BTC2) { b1 += btc_emit(&e->bs[b].btc[1], &st, NULL); ns3 += 8; continue; }
        if (m == MCR || m == ZRES || m == INTRA) b0 += CBPB(d->cbp);
        if (m == MC || m == MCR) { int mx = e->mv0[b][0], my = e->mv0[b][1]; b1 += ue_len(se_map(mx - pmx)) + ue_len(se_map(my - pmy)); pmx = mx; pmy = my; }
        if (m == INTRA) { int k; for (k = 0; k < 3; k++) { b1 += ue_len(se_map(e->bs[b].fill[k] - pf[k])); pf[k] = e->bs[b].fill[k]; } }
        if (m == RAW) nraw++;
        b2 += d->cbits;
    }
    if (run) b0 += ue_len((uint32_t)run);
    { size_t h = (size_t)(24 + (b0 + 7) / 8 + (b1 + 7) / 8 + (b2 + 7) / 8); if (r3) h = (h + 3) & ~(size_t)3; *bytes = h + (size_t)(128 * nraw + ns3); }
    *cyc = cy; e->ncoded = nc;
}

/* ------------------------------------------------------------------ phase 7: commit (recon + levels) */
static void commit_block(rnv2enc *e, int b) {
    const blkdec *d = &e->bd[b];
    uint8_t P[128], *rec = e->rec[b]; int mx = e->mv0[b][0], my = e->mv0[b][1];
    switch (d->mode) {
    case SKIP: return; /* reference unchanged */
    case MC: mc_pred(e, b, mx, my, rec); break;
    case RAW: gather_blk(e->tY, e->tU, e->tV, b, rec); break;
    case M_LAT8: case M_LAT4: case M_LAT2: lat_recon(e, b, d->mode - M_LAT8, rec); break;
    case M_BTC4: btc4_rec(&e->bs[b].btc[0], e->bs[b].m4, rec); break;
    case M_BTC2: btc2_rec(&e->bs[b].btc[1], e->bs[b].m2, rec); break;
    default: {
        const blkstat *s = &e->bs[b];
        if (d->mode == MCR) mc_pred(e, b, mx, my, P);
        else if (d->mode == ZRES) gather_blk(e->R[e->rb][0], e->R[e->rb][1], e->R[e->rb][2], b, P);
        else { memset(P, s->fill[0], 64); memset(P + 64, s->fill[1], 32); memset(P + 96, s->fill[2], 32); }
        recon_res(e, s->L3[d->cand], d->cbp, e->step, P, rec);
    } }
    { uint8_t S_[128]; gather_blk(e->tY, e->tU, e->tV, b, S_); e->clean[b] = d->mode == RAW ? 1 : (uint8_t)glass_equal(S_, rec); }
}
static void job_commit(rnv2enc *e, int row) { int b; for (b = row * BW; b < (row + 1) * BW; b++) commit_block(e, b); }
/* after all blocks are committed (MC reads the old reference), write the coded blocks into the single reference */
static void job_scatter(rnv2enc *e, int row) {
    int b, dirty = 0, x0 = W, x1 = 0;
    for (b = row * BW; b < (row + 1) * BW; b++) if (e->bd[b].mode != SKIP) {
        int x = (b - row * BW) * 8;
        scatter_blk(e->R[0][0], e->R[0][1], e->R[0][2], b, e->rec[b]); dirty = 1;
        if (x < x0) x0 = x;
        x1 = x + 8;
    }
    e->hdirty[row] = (uint8_t)dirty; e->hx0[row] = (uint16_t)x0; e->hx1[row] = (uint16_t)x1;
}

static void job_halfpel(rnv2enc *e, int idx) { /* idx = 3 components x BH row bands */
    int c = idx / BH, band = idx % BH, w = c ? CW : W, y;
    const uint8_t *P = e->R[e->rb][c]; int xa = W, xb = 0, n;
    if (e->hdirty[band]) { xa = e->hx0[band]; xb = e->hx1[band]; }
    if (band + 1 < BH && e->hdirty[band + 1]) { if (e->hx0[band + 1] < xa) xa = e->hx0[band + 1]; if (e->hx1[band + 1] > xb) xb = e->hx1[band + 1]; }
    if (xa >= xb) return; /* rows 8b..8b+8 unchanged */
    if (c) { xa /= 2; xb /= 2; }
    if (xa > 0) xa--;     /* h[x] also depends on x + 1 */
    n = xb - xa;
    for (y = band * 8; y < band * 8 + 8; y++) {
        const uint8_t *a = P + y * w + xa, *bb = y < H - 1 ? a + w : a; uint8_t *ph = e->HP[c][0] + y * w + xa, *phv = e->HP[c][2] + y * w + xa;
        KC(6, n);
        if (xb < w) { /* the kernel treats its last pixel as the end of the row: run one pixel long, keep that pixel's old values */
            uint8_t sh = ph[n], shv = phv[n];
            e->k->halfpel_row(a, bb, n + 1, ph, e->HP[c][1] + y * w + xa, phv);
            ph[n] = sh; phv[n] = shv;
        } else e->k->halfpel_row(a, bb, n, ph, e->HP[c][1] + y * w + xa, phv);
    }
}

/* serial bitstream writer */
static void write_stream(rnv2enc *e, int qp) {
    int b, run = 0, pmx = 0, pmy = 0, pf[3] = {128, 128, 128}, r3 = e->p.r3; emit_t st;
    static const uint8_t MCODE2[6][2] = {{0, 0}, {0, 2}, {1, 2}, {2, 2}, {6, 3}, {7, 3}};
    static const uint8_t MCODE3[M_COUNT][2] = {{0, 0}, {0, 2}, {2, 3}, {3, 3}, {4, 3}, {15, 4}, {20, 5}, {21, 5}, {22, 5}, {6, 3}, {14, 4}}; /* MC 00, MCR 010, ZRES 011, INTRA 100, LAT 101dd, BTC4 110, BTC2 1110, RAW 1111 */
    memset(&st, 0, sizeof st); { int i_, j_; for (i_ = 0; i_ < 3; i_++) for (j_ = 0; j_ < 3; j_++) st.last[i_][j_] = 128; for (i_ = 0; i_ < 6; i_++) st.btc[i_] = 128; }
    bw_reset(&e->w0); bw_reset(&e->w1); bw_reset(&e->w2); e->s3n = 0;
    for (b = 0; b < NB; b++) {
        const blkdec *d = &e->bd[b]; int m = d->mode;
        if (m == SKIP) { run++; continue; }
        bw_ue(&e->w0, (uint32_t)run); run = 0;
        if (r3) bw_put(&e->w0, MCODE3[m][0], MCODE3[m][1]); else bw_put(&e->w0, MCODE2[m][0], MCODE2[m][1]);
        if (m >= M_LAT8 && m <= M_LAT2) { lat_emit(e, b, m - M_LAT8, &st, &e->w1); continue; }
        if (m == M_BTC4 || m == M_BTC2) {
            int nb = m == M_BTC4 ? 16 : 8;
            btc_emit(&e->bs[b].btc[m == M_BTC4 ? 0 : 1], &st, &e->w1);
            if (e->s3n + nb > e->s3cap) { size_t nc = e->s3cap * 2; uint8_t *nbuf = xmalloc(nc); memcpy(nbuf, e->s3, e->s3n); free(e->s3); e->s3 = nbuf; e->s3cap = nc; }
            memcpy(e->s3 + e->s3n, m == M_BTC4 ? e->bs[b].m4 : e->bs[b].m2, (size_t)nb); e->s3n += nb;
            continue;
        }
        if (m == MCR || m == ZRES || m == INTRA) {
            bw_put(&e->w0, (uint32_t)CBPL_CODE[d->cbp & 15], CBPL_LEN[d->cbp & 15]);
            bw_put(&e->w0, (uint32_t)CBPC_CODE[d->cbp >> 4], CBPC_LEN[d->cbp >> 4]);
        }
        if (m == MC || m == MCR) {
            int mx = e->mv0[b][0], my = e->mv0[b][1];
            bw_ue(&e->w1, se_map(mx - pmx)); bw_ue(&e->w1, se_map(my - pmy)); pmx = mx; pmy = my;
        }
        if (m == INTRA) { int k; for (k = 0; k < 3; k++) { bw_ue(&e->w1, se_map(e->bs[b].fill[k] - pf[k])); pf[k] = e->bs[b].fill[k]; } }
        if (m == RAW) {
            uint8_t S[128]; int r, x;
            if (e->s3n + 128 > e->s3cap) { size_t nc = e->s3cap * 2; uint8_t *nb = xmalloc(nc); memcpy(nb, e->s3, e->s3n); free(e->s3); e->s3 = nb; e->s3cap = nc; }
            gather_blk(e->tY, e->tU, e->tV, b, S);
            for (r = 0; r < 8; r++) {
                const uint8_t *yr = S + ((r >> 2) * 2) * 16 + (r & 3) * 4, *ur = S + 64 + (r >> 2) * 16 + (r & 3) * 4, *vr = S + 96 + (r >> 2) * 16 + (r & 3) * 4;
                uint8_t *o = e->s3 + e->s3n + 16 * r;
                for (x = 0; x < 4; x++) {
                    int ly = 2 * x; /* luma column 2x, 2x+1 */
                    o[4 * x + 0] = ly < 4 ? yr[ly] : yr[16 + ly - 4];
                    o[4 * x + 1] = ur[x];
                    o[4 * x + 2] = ly + 1 < 4 ? yr[ly + 1] : yr[16 + ly + 1 - 4];
                    o[4 * x + 3] = vr[x];
                }
            }
            e->s3n += 128;
        }
        if (d->cbp) {
            int sb, pos;
            for (sb = 0; sb < 8; sb++) if (d->cbp & (1 << sb)) {
                const int16_t *l = e->bs[b].L3[d->cand] + 16 * sb; int lastpos = -1, prev = -1;
                for (pos = 0; pos < 16; pos++) if (l[ZZ[pos]]) lastpos = pos;
                for (pos = 0; pos <= lastpos; pos++) {
                    int v = l[ZZ[pos]], a, sym;
                    if (!v) continue;
                    a = v < 0 ? -v : v;
                    sym = (pos == lastpos) * (RUNMAX * LVMAX) + (pos - prev - 1) * LVMAX + (a < LVMAX ? a : LVMAX) - 1; prev = pos;
                    bw_put(&e->w2, (uint32_t)COEF_CODE[sym], COEF_LEN[sym]);
                    if (a >= LVMAX) bw_ue(&e->w2, (uint32_t)(a - LVMAX));
                    bw_put(&e->w2, v < 0, 1);
                }
            }
        }
    }
    if (run) bw_ue(&e->w0, (uint32_t)run);
    bw_flush(&e->w0); bw_flush(&e->w1); bw_flush(&e->w2);
    if (r3) while ((24 + e->w0.n + e->w1.n + e->w2.n) & 3) { if (e->w2.n + 1 > e->w2.cap) bw_grow(&e->w2); e->w2.buf[e->w2.n++] = 0; } /* stream 3 starts word aligned: the masks are read as words */
    {
        size_t n = 24 + e->w0.n + e->w1.n + e->w2.n + e->s3n; uint8_t *o; size_t l[4]; int i;
        if (n > e->ocap) { free(e->obuf); e->ocap = n * 2; e->obuf = xmalloc(e->ocap); }
        o = e->obuf; l[0] = e->w0.n; l[1] = e->w1.n; l[2] = e->w2.n; l[3] = e->s3n;
        o[0] = 'R'; o[1] = r3 ? '3' : '2'; o[2] = (uint8_t)((e->fn >> 8) & 0xFF); o[3] = (uint8_t)(e->fn & 0xFF); o[4] = (uint8_t)qp; o[5] = r3 ? (uint8_t)(e->p.dither ? 1 : 0) : 1; o[6] = r3 ? (uint8_t)(e->q4 | e->q2a << 4) : 0; o[7] = r3 ? (uint8_t)(e->q2b | e->q4c << 4) : 0;
        for (i = 0; i < 4; i++) { o[8 + 4 * i] = (uint8_t)(l[i] >> 24); o[9 + 4 * i] = (uint8_t)(l[i] >> 16); o[10 + 4 * i] = (uint8_t)(l[i] >> 8); o[11 + 4 * i] = (uint8_t)l[i]; }
        o += 24;
        memcpy(o, e->w0.buf, l[0]); o += l[0]; memcpy(o, e->w1.buf, l[1]); o += l[1]; memcpy(o, e->w2.buf, l[2]); o += l[2]; memcpy(o, e->s3, l[3]);
    }
}

static void job_post(rnv2enc *e, int idx) { if (idx == 0) write_stream(e, e->wqp); else job_halfpel(e, idx - 1); }

/* ------------------------------------------------------------------ canonical codes (rnv.canon_codes) */
static void canon(const unsigned char *L, int n, uint32_t *code) {
    int order[416], i, j; uint32_t c = 0; int prev = 0;
    for (i = 0; i < n; i++) order[i] = i;
    for (i = 1; i < n; i++) { int v = order[i]; j = i - 1; while (j >= 0 && (L[order[j]] > L[v] || (L[order[j]] == L[v] && order[j] > v))) { order[j + 1] = order[j]; j--; } order[j + 1] = v; }
    for (i = 0; i < n; i++) { int s = order[i]; if (i) { c = (c + 1) << (L[s] - prev); } prev = L[s]; code[s] = c; }
}

/* ------------------------------------------------------------------ public API */
void rnv2enc_default_params(rnv2enc_params *p) {
    memset(p, 0, sizeof *p);
    p->qp_min = 0; p->qp_max = 51; p->rate = 8e6; p->buf_frames = 4; p->fps = 60; p->cyc_budget = 4.49e6; p->lam_k = 0.04;
    p->kappa = 4; p->thr = 3; p->dz_inter = 0.22; p->dz_intra = 0.33; p->mu_min = 0.002; p->mu_max = 2.0; p->use_raw = 1;
    p->link_cap = 0; p->adapt = 1; p->nlevels = 12; p->lam_lo = 0.0025; p->lam_x = 0.01; p->kappa_lo = 16; p->thr_lo = 0; p->fill_target = 0.25; p->hyst = 0.85; p->dwell = 4; p->pin_level = -1;
    p->max_tries = 12; p->threads = 1; p->static_skip = 1; p->simd = 1; p->me_level = 2; p->me_win_thr = 0; p->me_win_max = 1024; p->rt_rc = 1; p->prune = 3; p->qp_pred = 1;
    p->lag_target = 0.5; p->refine_static = 1; p->max_frame = 1.5; p->stale_d = 6000; p->stale_w = 0; p->burst_probe = 1; p->mu_relax = 1; p->qp_drop = 4; p->fast_refine = 1; p->dither = 0; p->dither_range = 24;
    p->rc_tol = 0.88; p->btc_lmin = 0.02; p->fill_gap = 1; p->prune_nact = 1200; p->prune_r = 1.5; p->smooth = 0; p->src_mean = 48; p->pw_max = 3; p->btc_gate = 5; p->fill_pen = 2.0; p->r3 = 1; p->src_dead = 3; p->glass_dead = 1; p->lat_q4 = 2; p->lat_q2a = 2; p->lat_q2b = 3; p->lat_q4c = 3; p->lat_sharp = 0; p->rc_gamma = 1.0; p->sf_budget = 0; p->trim_ratio = 1.35; p->spill_qp = 18; p->spill_sf = 2; p->spill_gap = 30; p->spill_carry = 1; p->trim_max = 3; p->spill_cyc = 1;
}

static void set_level(rnv2enc *e, int L);
/* Next frame is a key: coded from black, exactly like frame 0, so a decoder that lost frames can rejoin. */
void rnv2enc_force_key(rnv2enc *e) {
    int i;
    memset(e->R[0][0], 0, W * H); memset(e->R[0][1], 128, CW * H); memset(e->R[0][2], 128, CW * H);
    for (i = 0; i < 3; i++) { memset(e->HP[0][i], 0, W * H); memset(e->HP[1][i], 128, CW * H); memset(e->HP[2][i], 128, CW * H); } /* half-pel planes of black: the old ones must not survive the key */
    e->rb = 0; e->first = 1; memset(e->prevmode, INTRA, NB); memset(e->prev_mv, 0, sizeof e->prev_mv); memset(e->clean, 0, NB);
}

rnv2enc *rnv2enc_create(const rnv2enc_params *p) {
    rnv2enc *e = calloc(1, sizeof *e); int i, c;
    static int inited;
    if (!e) return NULL;
    if (!inited) { rnv2_csc_init(); canon(COEF_LEN, 416, COEF_CODE); canon(CBPL_LEN, 16, CBPL_CODE); canon(CBPC_LEN, 16, CBPC_CODE); inited = 1; }
    e->p = *p;
    e->k = &rnv2_kern_scalar;
#ifdef RNV2_HAVE_NEON
    if (p->simd) e->k = &rnv2_kern_neon;
#endif
    e->nlev = p->adapt && p->nlevels > 1 ? (p->nlevels > 64 ? 64 : p->nlevels) : 1;
    if (p->link_cap > 0) e->p.rate = p->link_cap;
    e->lvl = e->alvl = p->pin_level >= 0 && p->pin_level < e->nlev ? p->pin_level : e->nlev - 1;
    { double kmax = p->kappa > p->kappa_lo ? p->kappa : p->kappa_lo, tmin = p->thr < p->thr_lo ? p->thr : p->thr_lo; int tmax = (int)lrint(p->thr > p->thr_lo ? p->thr : p->thr_lo);
      if (e->nlev == 1) { kmax = p->kappa; tmin = p->thr; tmax = (int)lrint(p->thr); }
      if (lrint(kmax * 16) > 256 || lrint(kmax * 16) < 0 || lrint(tmin) < 0 || tmax > 255) e->k = &rnv2_kern_scalar; } /* NEON pd8 range limit */
    set_level(e, e->lvl);
    atomic_init(&e->pend_cap, 0.0);
    e->tY = xmalloc(W * H); e->tU = xmalloc(CW * H); e->tV = xmalloc(CW * H);
    e->refrgb = xmalloc(W * H * 3); e->drgb = xmalloc(W * H * 3);
    for (i = 0; i < 2; i++) { e->R[i][0] = xmalloc(W * H); e->R[i][1] = xmalloc(CW * H); e->R[i][2] = xmalloc(CW * H); }
    for (c = 0; c < 3; c++) for (i = 0; i < 3; i++) e->HP[c][i] = xmalloc(c ? CW * H : W * H);
    memset(e->R[0][0], 0, W * H); memset(e->R[0][1], 128, CW * H); memset(e->R[0][2], 128, CW * H);
    e->rb = 0; e->first = 1; memset(e->hdirty, 1, BH);
    for (i = 0; i < BH; i++) { e->hx0[i] = 0; e->hx1[i] = W; }
    e->G = xmalloc(sizeof(gme_t));
    for (i = 0; i < 52; i++) { qtab(e, i, 0); qtab(e, i, 1); } /* build all quantiser tables up front (no first-use stalls) */
    e->rec = xmalloc(128 * NB); e->L = xmalloc(sizeof(latgrid)); e->q4 = p->lat_q4; e->q2a = p->lat_q2a; e->q2b = p->lat_q2b; e->q4c = p->lat_q4c; e->lamp = 1.0; e->mup = 0; e->rslope = -0.6;
    e->dc = xmalloc(sizeof(blkdc) * NB); e->dcp = xmalloc(sizeof(dcand) * NB * 3);
    e->bs = xmalloc(sizeof(blkstat) * NB); e->bs2 = xmalloc(sizeof(blkstat) * NB); e->bs2_cls = -1; e->bd = xmalloc(sizeof(blkdec) * NB); e->bd2 = xmalloc(sizeof(blkdec) * NB); e->bd3 = xmalloc(sizeof(blkdec) * NB);
    memset(e->prevmode, INTRA, NB); memset(e->prev_mv, 0, sizeof e->prev_mv);
    e->rate_pf = e->p.rate / p->fps; e->buf = p->buf_frames * e->p.rate / p->fps; e->fill = 0; e->qp = p->qp_min; e->mu = p->mu_min; e->pend_dt = -1; e->dtf = 1; e->since_spill = 1 << 20;
    e->w2.cap = 0; e->s3cap = 1 << 20; e->s3 = xmalloc(e->s3cap); e->ocap = 1 << 21; e->obuf = xmalloc(e->ocap);
    run_jobs(e, job_halfpel, 3 * BH);
    e->nth = p->threads < 1 ? 1 : p->threads > 16 ? 16 : p->threads;
    pthread_mutex_init(&e->m, NULL); pthread_cond_init(&e->cv, NULL); pthread_cond_init(&e->cvdone, NULL);
    for (i = 1; i < e->nth; i++) pthread_create(&e->th[i], NULL, worker, e);
    return e;
}

void rnv2enc_destroy(rnv2enc *e) {
    int i, c;
    if (!e) return;
    pthread_mutex_lock(&e->m); e->quit = 1; pthread_cond_broadcast(&e->cv); pthread_mutex_unlock(&e->m);
    for (i = 1; i < e->nth; i++) pthread_join(e->th[i], NULL);
    free(e->tY); free(e->tU); free(e->tV); free(e->refrgb); free(e->drgb);
    for (i = 0; i < 2; i++) for (c = 0; c < 3; c++) free(e->R[i][c]);
    for (c = 0; c < 3; c++) for (i = 0; i < 3; i++) free(e->HP[c][i]);
    for (i = 0; i < 52; i++) { free(e->qt[i][0]); free(e->qt[i][1]); }
    free(e->L); free(e->G); free(e->rec); free(e->bs); free(e->dc); free(e->dcp); free(e->bs2); free(e->bd); free(e->w0.buf); free(e->w1.buf); free(e->w2.buf); free(e->s3); free(e->obuf);
    free(e);
}

/* operating point of ladder level L.  nlev-1 = (lam_k, kappa, thr) = the classic point.  Levels 1..nlev-2 keep that kappa / thr and
 * lower only lambda, geometrically down to lam_lo (measured on the night map: 2.4 -> 7.6 MB/s, glass-vs-target error 3.2% -> 0.2%, a
 * smooth ladder; thr is a cliff, thr 3 -> 0 doubles the rate).  Level 0 = (lam_x, kappa_lo, thr_lo): thr 0 near-exact. */
static void set_level(rnv2enc *e, int L) {
    const rnv2enc_params *p = &e->p; int N = e->nlev;
    double lo = p->lam_lo > 0 && p->lam_lo < p->lam_k ? p->lam_lo : p->lam_k;
    if (L >= N - 1 || (N < 3 && L > 0)) { e->lamk = p->lam_k; e->kappa16 = (int)lrint(p->kappa * 16); e->thr = (int)lrint(p->thr); return; }
    if (L == 0) {
        e->lamk = p->lam_x < p->lam_k ? p->lam_x : p->lam_k;
        e->kappa16 = (int)lrint((p->kappa_lo > p->kappa ? p->kappa_lo : p->kappa) * 16); e->thr = (int)lrint(p->thr_lo < p->thr ? p->thr_lo : p->thr); return;
    }
    e->lamk = lo * pow(p->lam_k / lo, (double)(L - 1) / (N - 2));
    e->kappa16 = (int)lrint(p->kappa * 16); e->thr = (int)lrint(p->thr);
}
/* lambda of ladder level L >= 1 (levels >= 1 share kappa / thr, hence the cached block analysis: only the decision is redone) */
static void set_lam(rnv2enc *e, int L) {
    double st = QSTEP2[e->cqp];
    set_level(e, L);
    e->lam = e->lamk * (st > 2 ? st : 2) * (st > 2 ? st : 2);
}
static void set_cap(rnv2enc *e, double cap) {
    e->p.rate = cap; e->rate_pf = cap / e->p.fps; e->buf = e->p.buf_frames * cap / e->p.fps;
    if (e->fill > e->buf) e->fill = e->buf; /* the streamer owns whatever was already queued beyond the new bucket */
}
void rnv2enc_set_linkcap(rnv2enc *e, double bytes_per_s) { if (bytes_per_s > 0) atomic_store(&e->pend_cap, bytes_per_s); }
void rnv2enc_set_elapsed(rnv2enc *e, double seconds) { e->pend_dt = seconds; }
static void set_qp(rnv2enc *e, int qp) {
    double st = QSTEP2[qp];
    e->cqp = qp; e->step = QSTEP2[qp]; e->lam = e->lamk * (st > 2 ? st : 2) * (st > 2 ? st : 2);
    qtab(e, qp, 0); qtab(e, qp, 1);
}

int rnv2enc_encode(rnv2enc *e, const uint8_t *pix, int stride, enum rnv2_fmt fmt, const rnv2_rect *dmg, int ndmg,
                   const uint8_t **out, size_t *outlen, rnv2enc_info *info) {
    double t0 = now_ms(), t1, t2, t3, ta = 0, td = 0, t5, t6, cap, soft, mu, cyc = 0; size_t n = 0; int qp, tries = 0, aqp = -1, b, i, nana = 0, rtok = 0, ad, Lprev, acls = -1, want0;
    int Lprev0 = e->lvl; double alw = 0, hard0 = 0; int hint = -1, evs = 0, keytry0 = 0;
    int bm = 0, spill = 0, trims = 0, resoft = 0, nact1 = 0; double C = 0, cb = e->p.cyc_budget, n_pre = 0, alim = 1e18;
    e->bs2_cls = -1;
    if (info) memset(info, 0, sizeof *info);
    { double c = atomic_exchange(&e->pend_cap, 0.0); if (c > 0 && c != e->p.rate) set_cap(e, c); }
    if (e->pend_dt >= 0) { /* the fill already drained one 1/fps after the last frame: correct it to the time that really passed.  The bucket bounds both ways: idle time is not banked below empty */
        e->fill -= (e->pend_dt - 1.0 / e->p.fps) * e->p.rate; if (e->fill < 0) e->fill = 0; if (e->fill > e->buf) e->fill = e->buf;
        /* the share of the link one frame may plan on follows the source: at 30 fps a frame has two ticks of link.  Smoothed over about 10 frames; never under one tick, never over the bucket */
        { double tk = e->pend_dt * e->p.fps; if (tk < 1) tk = 1; if (tk > e->p.buf_frames) tk = e->p.buf_frames; e->dtf += 0.1 * (tk - e->dtf); }
        e->pend_dt = -1;
    }
    e->cur = pix; e->curstride = stride; e->fmt = fmt;
    if (ndmg < 0) memset(e->damaged, 1, NB);
    else {
        memset(e->damaged, 0, NB);
        for (i = 0; i < ndmg; i++) {
            int x0 = dmg[i].x < 0 ? 0 : dmg[i].x, y0 = dmg[i].y < 0 ? 0 : dmg[i].y, x1 = dmg[i].x + dmg[i].w, y1 = dmg[i].y + dmg[i].h, bx, by;
            if (x1 > W) x1 = W; if (y1 > H) y1 = H;
            for (by = y0 / 8; by * 8 < y1; by++) for (bx = x0 / 8; bx * 8 < x1; bx++) e->damaged[by * BW + bx] = 1;
        }
    }
    e->qp0 = (e->p.rt_rc && e->qp_raised) ? e->qp : e->qp - e->p.qp_drop; /* rt_rc: hold qp after a frame that had to raise it */
    if (e->qp0 < e->p.qp_min) e->qp0 = e->p.qp_min;
    e->mu0 = e->mu * 0.6 > e->p.mu_min ? e->mu * 0.6 : e->p.mu_min;
#ifdef RNV_EXACT_TEST /* test build: no key-frame shortcuts (they are the only intended bitstream change on a stream without forced keys) */
    e->key = 0;
#else
    e->key = (uint8_t)e->first;
#endif
    { int nd = NB; if (ndmg >= 0 && !e->first) { nd = 0; for (b = 0; b < NB; b++) nd += e->damaged[b]; } run_w(e, job_csc, BH, nd, 128); }
    if (e->p.dither || e->p.smooth) { smooth_classify(e); run_w(e, job_smooth, BH, NB, 256); }
    e->first = 0; e->tvalid = 1;
    /* blocks that need any work this frame; the decision of the others is SKIP for the whole frame */
    e->nprev_act = e->nact; e->nact = 0;
    for (b = 0; b < NB; b++) {
        if (!e->forced[b]) e->act[e->nact++] = (uint16_t)b;
        else { blkdec *d = &e->bd[b]; d->mode = SKIP; d->cbp = 0; d->cbits = 0; d->ebits = 0; d->cyc = e->prevmode[b] != SKIP ? CY_SKIPCOPY : CY_SKIP; }
    }
    t1 = now_ms();
    if (e->key) { /* the reference is black: nothing to search */
        e->ng = 0; e->prev_g[0] = e->prev_g[1] = 0; t2 = now_ms();
        memset(e->mv0, 0, sizeof e->mv0); memset(e->mc0, 0, sizeof e->mc0); memset(e->medone, 1, NB);
    } else {
        { int nch = 0; for (b = 0; b < NB; b++) nch += e->changed[b]; global_motion(e, nch); }
        t2 = now_ms();
        run_w(e, job_me_init, BH, e->nact, 64);
        for (e->pass = 0; e->pass <= (e->p.me_level >= 1 ? 1 : 0); e->pass++) run_w(e, job_me_pass, BH, e->nact, 64);
        if (e->pass & 1) memcpy(e->mv0, e->mv1, sizeof e->mv0); /* final field in mv0 */
    }
    t3 = now_ms();
    e->n_forced = NB - e->nact; e->n_search = 0;
    for (b = 0; b < NB; b++) e->n_search += !e->medone[b];
    /* Rate control.  Every frame fits one superframe, keys included: no spills, no 300 KB frames.  Lambda is searched so the frame fills what the link has; the block decisions do the rest.
     * A cold burst falls back to soft blocks and sharpens over the next frames as lambda comes down.  The cycle cap is a second multiplier (mu). */
    {
        double T, rp = e->rate_pf, lam; int it; const double LMIN = e->p.rc_lmin > 0 ? e->p.rc_lmin : 0.001, LMAX = 20000;
        cb = e->p.cyc_budget;
        C = e->p.sf_budget > 0 ? e->p.sf_budget - 64 : 1e12;
        T = rp + (e->p.lag_target * e->buf - e->fill) * 0.35; if (T < 0.7 * rp) T = 0.7 * rp; if (T > C) T = C;
        e->burst = e->nact > 2 * e->nprev_act + 512; lam = e->lamp; if (e->burst && e->lamb > lam) lam = e->lamb; /* a sudden burst is like the last one, not like the quiet frame before it */
        e->lamp = lam; /* the analysis prunes against this */
        /* qp of the residual candidates follows lambda (RD slope of a uniform quantiser), one analysis per frame */
        { double st_ = sqrt(lam / (e->p.lam_k > 0 ? e->p.lam_k : 0.04)); qp = 0; while (qp < e->p.qp_max && QSTEP2[qp] < st_) qp++; if (qp < e->qp - e->p.qp_drop) qp = e->qp - e->p.qp_drop; if (qp < e->p.qp_min) qp = e->p.qp_min; }
        e->lvl = e->nlev - 1; set_level(e, e->lvl); set_qp(e, qp);
        e->lat_ok = 0;
        if (e->p.r3) { int any = e->key; for (b = 0; b < NB && !any; b++) any = e->changed[b]; if (any || !e->lat_valid) { run_w(e, job_lat_filter, 3, e->nact, 256); run_w(e, job_lat_quant, 4, e->nact, 256); e->lat_valid = 1; } e->lat_ok = 1; }
        { /* the block analysis has two steps: the sample decides this frame's lambda, and the expensive candidates of all other blocks are gated against it */
            double t_ = now_ms(), rat_ = e->szrat > 0 ? e->szrat : 1.05;
            run_w(e, job_analyse, BH, e->nact, 64); nana++;
            int n1 = 0;
            resoft = 0; e->nsact = 0;
            for (i = 0; i < e->nact; i++) { int b_ = e->act[i]; if (e->dc[b_].valid == 1) { n1++; e->smp[b_] = e->nact < ANA_ALL || ((b_ % BW) + 2 * (b_ / BW)) % ANA_STEP == 0; if (e->smp[b_]) e->sact[e->nsact++] = (uint16_t)b_; } }
            run_w(e, job_soft0, BH, e->nsact, 64);
            e->lam_est = lam; e->nu_est = e->mup;
            if (e->nsact > 0) {
                lam_presearch(e, lam, e->mup, (T - 24) * 8, cb, rat_, LMIN, LMAX, n1); lam = e->lam_est;
                if (e->key || e->burst) { /* a cold start: qp above came from a lambda that has nothing to do with this frame, and residual candidates at the wrong qp cost quality on just the frame that needs it */
                    int q_; double st_ = sqrt(lam / (e->p.lam_k > 0 ? e->p.lam_k : 0.04)); q_ = 0; while (q_ < e->p.qp_max && QSTEP2[q_] < st_) q_++; if (q_ < e->p.qp_min) q_ = e->p.qp_min; if (e->key && q_ > KEY_QPMAX) q_ = KEY_QPMAX;
                    if (q_ > qp + 2 || q_ < qp - 2) {
                        qp = q_; set_qp(e, qp); run_w(e, job_analyse, BH, e->nact, 64); nana++; run_w(e, job_soft0, BH, e->nsact, 64);
                        lam_presearch(e, lam, e->nu_est, (T - 24) * 8, cb, rat_, LMIN, LMAX, n1); lam = e->lam_est;
                    }
                }
            }
            e->lam_gate = GATE_LAM * lam; e->nu_gate = GATE_LAM * e->nu_est;
            if (n1 > e->nsact) run_w(e, job_soft1, BH, n1 - e->nsact, 64);
            nact1 = n1;
            ta += now_ms() - t_;
        }
        { double tt = now_ms(), rat = e->szrat > 0 ? e->szrat : 1.05, Tb = (T - 24) * 8, fb = 0, fc = 0, nu = e->nu_est; int round_;
          /* J = D + lambda R + nu C.  lambda holds the bytes, nu the decode cycles; they are solved in turn */
#define FEVAL(L) do { e->lam = (L); e->cmu = nu / e->lam; DECIDE(); fast_size(e, &fb, &fc); evs++; } while (0)
          research:
          FEVAL(lam);
          for (round_ = 0; round_ < 2; round_++) {
              { /* lambda for the bytes.  Secant on log size vs log lambda inside a bracket: size has cliffs (many similar blocks turn RAW at once), so a plain secant can stop far under the target */
                  double l0 = lam, b0 = fb * rat, slope = e->rslope, lo = 0, hi = 0; int its;
                  for (its = 0; its < 6 && evs < 10 + 3 * round_; its++) {
                      double err = b0 / Tb, next;
                      if (err <= 1) { hi = l0; if (err >= e->p.rc_tol || lam <= LMIN) break; } else lo = l0;
                      if (lo > 0 && hi > 0 && hi / lo < 1.04) break;
                      next = l0 * pow(err * (err > 1 ? 1.02 : 1.01), -1 / slope);
                      if (next < LMIN) next = LMIN; if (next > LMAX) next = LMAX; if (next > l0 * 64) next = l0 * 64; if (next < l0 / 64) next = l0 / 64;
                      if (lo > 0 && hi > 0 && (next <= lo || next >= hi || its >= 3)) next = sqrt(lo * hi);
                      else if (lo > 0 && next <= lo) next = lo * 1.15;
                      else if (hi > 0 && next >= hi) next = hi / 1.15;
                      if (next == l0) break;
                      FEVAL(next);
                      { double b1 = fb * rat; if (b1 > 0 && b0 > 0 && next != l0) { double sl = log(b1 / b0) / log(next / l0); if (sl < -0.1 && sl > -8) { slope = sl; e->rslope = sl; } } l0 = next; b0 = b1; lam = next; }
                  }
                  if (b0 > Tb && hi > 0) { lam = hi; FEVAL(lam); }
                  for (its = 0; its < 8 && fb * rat > Tb && lam < LMAX; its++) { lam *= 1.2; FEVAL(lam); }
              }
              if (fc <= cb) break;
              { /* nu for the cycles: only as far as this frame needs, the controller below carries it to the next frame */
                  int its;
                  if (nu <= 0) nu = lam * 0.002;
                  for (its = 0; its < 5 && fc > cb; its++) { double r = fc / cb; r = r * r; nu *= r > 1.2 ? r : 1.2; FEVAL(lam); }
              }
          }
          if (!resoft && !e->key && !e->burst && e->nsact < nact1 && (lam > GATE_REDO * e->lam_est || lam < e->lam_est / GATE_REDO)) { /* the sample was wrong by a lot, and the gates with it */
              double t_ = now_ms(); resoft = 1; e->lam_gate = GATE_LAM * lam; e->nu_gate = GATE_LAM * nu; e->lam_est = lam;
              run_w(e, job_soft1, BH, nact1 - e->nsact, 64); ta += now_ms() - t_;
              goto research;
          }
          frame_size(e, &n, &cyc);
          if (fb > 1000) { double nr = ((double)n - 24) * 8 / fb; if (nr > 0.5 && nr < 3) e->szrat = 0.6 * rat + 0.4 * nr; }
          /* exact correction, up or down.  Down is only taken if it still fits */
          if ((double)n < 0.75 * T && lam > LMIN && cyc < 0.97 * cb) {
              double keep = lam, f = pow((double)n / (0.9 * T), 1.6); if (f < 1 / 16.0) f = 1 / 16.0;
              lam *= f; if (lam < LMIN) lam = LMIN; FEVAL(lam); frame_size(e, &n, &cyc);
              if ((double)n > T || cyc > cb) { lam = keep; FEVAL(lam); frame_size(e, &n, &cyc); }
          }
          for (it = 0; it < 6 && (double)n > T; it++) { double f = (double)n / T; lam *= pow(f, 1.5) * 1.03; FEVAL(lam); frame_size(e, &n, &cyc); }
          for (it = 0; it < 12 && cyc > cb; it++) { nu *= 1.3; FEVAL(lam); frame_size(e, &n, &cyc); }
          for (it = 0; it < 24 && (cyc > cb || (double)n > C); it++) { nu *= 1.3; lam *= 1.3; FEVAL(lam); frame_size(e, &n, &cyc); }
          /* Fill.  Frame size has cliffs in lambda: many similar blocks change mode at once, so the search can end well under the target with bytes the picture could use.
           * Take the decisions at a lower lambda, and move blocks over to them one by one, best distortion gain per bit first, until the frame is full */
          if (e->p.fill_gap && (double)n < 0.97 * T && lam > LMIN && cyc < cb) {
              static __thread struct fillc { float g; int b, dr, dc; } *fc_ = NULL; struct fillc *L_; int nf_ = 0, nap = 0, i_; double room, croom = cb - cyc, lo_ = lam * 0.35, nrat = fb > 1000 ? ((double)n - 24) * 8 / fb : rat; size_t n0 = n; double cyc0 = cyc;
              if (!e->fillc) e->fillc = xmalloc(sizeof(struct fillc) * NB);
              L_ = e->fillc; (void)fc_;
              if (lo_ < LMIN) lo_ = LMIN;
              memcpy(e->bd2, e->bd, sizeof(blkdec) * NB);
              e->lam = lo_; e->cmu = nu / e->lam; DECIDE(); evs++;
              memcpy(e->bd3, e->bd, sizeof(blkdec) * NB);
              memcpy(e->bd, e->bd2, sizeof(blkdec) * NB);
              for (i_ = 0; i_ < e->nact; i_++) {
                  int b_ = e->act[i_]; const blkdec *A = &e->bd2[b_], *Z = &e->bd3[b_]; double dD; int dR;
                  if (A->mode == Z->mode && A->cbp == Z->cbp) continue;
                  dD = (double)(A->dist - Z->dist) / e->dc[b_].ipw; dR = Z->ebits - A->ebits;
                  if (dD <= 0) continue;
                  L_[nf_].g = (float)(dD / (dR > 8 ? dR : 8)); L_[nf_].b = b_; L_[nf_].dr = dR; L_[nf_].dc = Z->cyc - A->cyc; nf_++;
              }
              qsort(L_, (size_t)nf_, sizeof(struct fillc), fill_cmp);
              room = (0.985 * T - (double)n) * 8 / (nrat > 0.5 ? nrat : 1.0);
              for (i_ = 0; i_ < nf_ && room > 0; i_++) {
                  if (L_[i_].dr > room || L_[i_].dc > croom) continue;
                  e->bd[L_[i_].b] = e->bd3[L_[i_].b]; room -= L_[i_].dr; croom -= L_[i_].dc; L_[nap++] = L_[i_];
              }
              frame_size(e, &n, &cyc);
              /* the walker has the last word: neighbours sharing lattice points change the true size a little */
              for (it = 0; it < 6 && ((double)n > T || cyc > cb) && nap > 0; it++) { int un = nap / 8 + 1; while (un-- > 0 && nap > 0) { nap--; e->bd[L_[nap].b] = e->bd2[L_[nap].b]; } frame_size(e, &n, &cyc); }
              if ((double)n > T || cyc > cb) { memcpy(e->bd, e->bd2, sizeof(blkdec) * NB); n = n0; cyc = cyc0; }
              e->cmu = nu / lam; e->lam = lam;
          }
          if (cyc > cb) fprintf(stderr, "rnv3enc: frame %d over the cycle cap (%.0f > %.0f)\n", e->fn, cyc, cb);
          if ((double)n > C) fprintf(stderr, "rnv3enc: frame %d over the superframe (%zu)\n", e->fn, n);
          { double r = cyc / (0.97 * cb); r = r * r; nu *= r < 0.7 ? 0.7 : r > 1.3 ? 1.3 : r; if (nu < lam * 1e-4) nu = 0; }
          if (getenv("RCDBG")) fprintf(stderr, "F %d T %.0f n %zu fbr %.0f rat %.3f szrat %.3f lam %.3f est %.3f nu %.4f est %.4f cyc %.0f ev %d qp %d nact %d ns %d\n", e->fn, T, n, fb * rat / 8, rat, e->szrat, lam, e->lam_est, nu, e->nu_est, cyc, evs, qp, e->nact, e->nsact);
          e->mup = nu; e->lamp = lam; mu = e->cmu; if (e->nact >= 3000 && (double)n > 0.7 * T) e->lamb = lam; /* an active frame that did not fill says nothing about the next burst */
          td += now_ms() - tt; }
        tries = evs;
        e->fill = e->fill + (double)n - rp; if (e->fill < 0) e->fill = 0; if (e->fill > e->buf) e->fill = e->buf;
        e->lastn = (double)n; e->qp = qp; e->alvl = e->lvl;
    }
    t5 = now_ms();
    run_w(e, job_commit, BH, e->ncoded, 64);
    run_w(e, job_scatter, BH, e->ncoded, 256);
    e->wqp = qp;
    run_w(e, job_post, 1 + 3 * BH, e->ncoded, 128); /* serial bitstream write overlapped with the half-pel planes of the new reference */
    t6 = now_ms();
    for (b = 0; b < NB; b++) {
        int m = e->bd[b].mode;
        e->prevmode[b] = (uint8_t)m;
        /* clean: the reference equals the target at the panel, so only a source change wakes this block */
        if (m == SKIP) e->clean[b] = e->forced[b] ? e->clean[b] : (uint8_t)(e->dc[b].valid == 2);
        if (m == SKIP) e->prev_mv[b][0] = e->prev_mv[b][1] = 0; else { e->prev_mv[b][0] = e->mv0[b][0]; e->prev_mv[b][1] = e->mv0[b][1]; }
        if (info) info->modes[m]++;
    }
    *out = e->obuf; *outlen = 24 + e->w0.n + e->w1.n + e->w2.n + e->s3n;
    if (*outlen != n) fprintf(stderr, "rnv2enc: internal size mismatch %zu vs %zu\n", *outlen, n);
    if (info) {
        info->bytes = (int)*outlen; info->qp = qp; info->level = e->alvl; info->link_cap = e->p.rate; info->lamk = e->lamp; info->tries = tries; info->cycles = cyc; info->mu = mu; info->fill = e->fill;
        info->n_skip_forced = e->n_forced; info->n_searched = e->n_search; info->trims = trims; info->spill = !e->p.sf_budget || (double)n <= C ? 0 : (spill || e->key) ? 1 : 2;
        info->sizes[0] = (int)e->w0.n; info->sizes[1] = (int)e->w1.n; info->sizes[2] = (int)e->w2.n; info->sizes[3] = (int)e->s3n;
        info->gmv_n = e->ng; for (i = 0; i < e->ng; i++) { info->gmv[i][0] = e->g[i][0]; info->gmv[i][1] = e->g[i][1]; }
        info->t_ms[0] = t1 - t0; info->t_ms[1] = t2 - t1; info->t_ms[2] = t3 - t2; info->t_ms[3] = ta; info->t_ms[4] = td;
        info->t_ms[5] = evs + 100 * nana; info->t_ms[6] = t6 - t5; info->t_ms[7] = now_ms() - t0;
    }
    e->fn++;
    return 0;
}

static void pack_yuy2(const uint8_t *Y, const uint8_t *U, const uint8_t *V, uint8_t *d) {
    int i;
    for (i = 0; i < W * H / 2; i++) { d[4 * i] = Y[2 * i]; d[4 * i + 1] = U[i]; d[4 * i + 2] = Y[2 * i + 1]; d[4 * i + 3] = V[i]; }
}
void rnv2enc_recon_yuy2(const rnv2enc *e, uint8_t *dst) { pack_yuy2(e->R[e->rb][0], e->R[e->rb][1], e->R[e->rb][2], dst); }
void rnv2enc_target_yuy2(const rnv2enc *e, uint8_t *dst) { pack_yuy2(e->tY, e->tU, e->tV, dst); }
void rnv2enc_planes(const rnv2enc *e, const uint8_t **rY, const uint8_t **rU, const uint8_t **rV,
                    const uint8_t **tY, const uint8_t **tU, const uint8_t **tV) {
    *rY = e->R[e->rb][0]; *rU = e->R[e->rb][1]; *rV = e->R[e->rb][2]; *tY = e->tY; *tU = e->tU; *tV = e->tV;
}
const char *rnv2enc_kernel_name(const rnv2enc *e) { return e->k->name; }
