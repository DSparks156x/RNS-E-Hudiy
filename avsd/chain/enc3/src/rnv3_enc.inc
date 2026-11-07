/* RNV3 encoder side: lattice build, soft and tone block candidates, their bitstream walker.  Included by enc.c. */

/* ------------------------------------------------------------------ lattice build: a pure function of the target, so a block's reconstruction never depends on its neighbours' decisions */
#define G8W 101
#define G8H 61
#define G4W 201
#define G4H 121
#define G2W 401
#define G2H 241
static inline int iclamp(int v, int a, int b) { return v < a ? a : v > b ? b : v; }

/* one output row of the tent: 3 source rows, every 2nd column.  Same result as the scalar loop */
static inline void tent_row(const uint8_t *r0, const uint8_t *r1, const uint8_t *r2, int sw, uint8_t *d, int dw) {
    int j = 0;
    { int x = 0, xb = sw > 1 ? 1 : 0; d[0] = (uint8_t)((r0[0] + 2 * r0[x] + r0[xb] + 2 * (r1[0] + 2 * r1[x] + r1[xb]) + r2[0] + 2 * r2[x] + r2[xb] + 8) >> 4); }
    j = 1;
#ifdef __ARM_NEON
    for (; j + 8 <= dw && 2 * (j + 7) + 1 <= sw - 1; j += 8) {
        int x = 2 * j;
        uint16x8_t m0 = vmovl_u8(vget_low_u8(vld2q_u8(r0 + x).val[0])), m1 = vmovl_u8(vget_low_u8(vld2q_u8(r1 + x).val[0])), m2 = vmovl_u8(vget_low_u8(vld2q_u8(r2 + x).val[0]));
        uint16x8_t a0 = vmovl_u8(vget_low_u8(vld2q_u8(r0 + x - 1).val[0])), a1 = vmovl_u8(vget_low_u8(vld2q_u8(r1 + x - 1).val[0])), a2 = vmovl_u8(vget_low_u8(vld2q_u8(r2 + x - 1).val[0]));
        uint16x8_t b0 = vmovl_u8(vget_low_u8(vld2q_u8(r0 + x + 1).val[0])), b1 = vmovl_u8(vget_low_u8(vld2q_u8(r1 + x + 1).val[0])), b2 = vmovl_u8(vget_low_u8(vld2q_u8(r2 + x + 1).val[0]));
        uint16x8_t ca = vaddq_u16(vaddq_u16(a0, a2), vshlq_n_u16(a1, 1)), cm = vaddq_u16(vaddq_u16(m0, m2), vshlq_n_u16(m1, 1)), cb_ = vaddq_u16(vaddq_u16(b0, b2), vshlq_n_u16(b1, 1));
        uint16x8_t v = vaddq_u16(vaddq_u16(ca, cb_), vshlq_n_u16(cm, 1));
        vst1_u8(d + j, vmovn_u16(vshrq_n_u16(vaddq_u16(v, vdupq_n_u16(8)), 4)));
    }
#endif
    for (; j < dw; j++) {
        int x = 2 * j; if (x > sw - 1) x = sw - 1;
        int xa = x > 0 ? x - 1 : 0, xb = x < sw - 1 ? x + 1 : sw - 1;
        d[j] = (uint8_t)((r0[xa] + 2 * r0[x] + r0[xb] + 2 * (r1[xa] + 2 * r1[x] + r1[xb]) + r2[xa] + 2 * r2[x] + r2[xb] + 8) >> 4);
    }
}
/* tent down a lattice by 2 (uint8 grid to uint8 grid), edges clamp */
static void lat_down(const uint8_t *s, int sw, int sh, uint8_t *d, int dw, int dh) {
    int i;
    for (i = 0; i < dh; i++) {
        int y = 2 * i, ya = y > 0 ? y - 1 : 0, yb = y < sh - 1 ? y + 1 : sh - 1;
        tent_row(s + ya * sw, s + y * sw, s + yb * sw, sw, d + i * dw, dw);
    }
}
static inline int q_delta(int f, int pred, int q) { int e = f - pred; return e >= 0 ? (e + q / 2) / q : -((-e + q / 2) / q); }
#ifdef __ARM_NEON
#define Q_NEON(q) ((q) >= 2 && (q) <= 64)
/* q_delta and the range fix of Q1 on 8 lanes.  (t * M) >> 16 with M = ceil(65536 / q) is t / q for every t this can see */
static inline void qlanes(uint8x8_t f8, uint8x8_t p8, int q, int lo, int hi, uint8x8_t *v8, int16x8_t *d8) {
    const uint16_t M = (uint16_t)((65536 + q - 1) / q);
    int16x8_t p = vreinterpretq_s16_u16(vmovl_u8(p8)), e = vsubq_s16(vreinterpretq_s16_u16(vmovl_u8(f8)), p), neg = vshrq_n_s16(e, 15), dd, vv;
    uint16x8_t t = vaddq_u16(vreinterpretq_u16_s16(vabsq_s16(e)), vdupq_n_u16((uint16_t)(q / 2)));
    uint16x8_t dq = vcombine_u16(vshrn_n_u32(vmull_n_u16(vget_low_u16(t), M), 16), vshrn_n_u32(vmull_high_n_u16(t, M), 16));
    const int16x8_t Q_ = vdupq_n_s16((int16_t)q), LO = vdupq_n_s16((int16_t)lo), HI = vdupq_n_s16((int16_t)hi);
    dd = vsubq_s16(veorq_s16(vreinterpretq_s16_u16(dq), neg), neg);
    vv = vmlaq_s16(p, dd, Q_);
    for (;;) {
        uint16x8_t ml = vcltq_s16(vv, LO), mh = vcgtq_s16(vv, HI);
        if (!vmaxvq_u16(vorrq_u16(ml, mh))) break;
        dd = vaddq_s16(vsubq_s16(dd, vreinterpretq_s16_u16(ml)), vreinterpretq_s16_u16(mh));
        vv = vsubq_s16(vaddq_s16(vv, vandq_s16(Q_, vreinterpretq_s16_u16(ml))), vandq_s16(Q_, vreinterpretq_s16_u16(mh)));
    }
    *v8 = vmovn_u16(vreinterpretq_u16_s16(vv)); *d8 = dd;
}
/* n targets at F[0], F[2]..: predictors at offsets oa, ob from each target, round up or down.  Returns how many were done (the rest is for the scalar loop) */
static inline int qrow2(const uint8_t *F, uint8_t *Q, int16_t *D, int oa, int ob, int n, int q, int lo, int hi, int up) {
    int k; const uint16x8_t LB = vdupq_n_u16(0x00FF);
    for (k = 0; k + 8 <= n; k += 8) {
        uint8x8_t f8 = vmovn_u16(vreinterpretq_u16_u8(vld1q_u8(F + 2 * k))), a8 = vmovn_u16(vreinterpretq_u16_u8(vld1q_u8(Q + 2 * k + oa))), b8 = vmovn_u16(vreinterpretq_u16_u8(vld1q_u8(Q + 2 * k + ob))), v8; int16x8_t d8; int16x8x2_t dd;
        qlanes(f8, up ? vrhadd_u8(a8, b8) : vhadd_u8(a8, b8), q, lo, hi, &v8, &d8);
        vst1q_u8(Q + 2 * k, vreinterpretq_u8_u16(vbslq_u16(LB, vmovl_u8(v8), vreinterpretq_u16_u8(vld1q_u8(Q + 2 * k)))));
        dd = vld2q_s16(D + 2 * k); dd.val[0] = d8; vst2q_s16(D + 2 * k, dd);
    }
    return k;
}
/* the same on a contiguous run */
static inline int qrow1(const uint8_t *F, uint8_t *Q, int16_t *D, int oa, int ob, int n, int q, int lo, int hi, int up) {
    int k;
    for (k = 0; k + 8 <= n; k += 8) {
        uint8x8_t a8 = vld1_u8(Q + k + oa), b8 = vld1_u8(Q + k + ob), v8; int16x8_t d8;
        qlanes(vld1_u8(F + k), up ? vrhadd_u8(a8, b8) : vhadd_u8(a8, b8), q, lo, hi, &v8, &d8);
        vst1_u8(Q + k, v8); vst1q_s16(D + k, d8);
    }
    return k;
}
#else
#define Q_NEON(q) 0
#define qrow2(F, Q, D, oa, ob, n, q, lo, hi, up) 0
#define qrow1(F, Q, D, oa, ob, n, q, lo, hi, up) 0
#endif
/* hierarchical quantisation of a 201x121 (coarse 3x3 per block) grid.  corners exact (qc), others predicted by the bilinear rule.  D = coded delta */
static void lat_quant3(const uint8_t *F, int gw, int gh, int qc, int q, int lo, int hi, uint8_t *Q, int16_t *D) {
    int i, j;
    for (i = 0; i < gh; i += 2) for (j = 0; j < gw; j += 2) { int v = iclamp(F[i * gw + j], lo, hi); if (qc > 1) { v = (v + qc / 2) / qc * qc; if (v > hi) v -= qc; } Q[i * gw + j] = (uint8_t)v; D[i * gw + j] = 0; }
#define QT3(STARTJ, OA, OB) do { int t_ = i * gw + (STARTJ); int done_ = Q_NEON(q) ? qrow2(F + t_, Q + t_, D + t_, OA, OB, (gw - (STARTJ) + 1) / 2, q, lo, hi, 1) : 0; \
        for (j = (STARTJ) + 2 * done_; j < gw; j += 2) { int p = lat_rup(Q[i * gw + j + (OA)], Q[i * gw + j + (OB)]), d = q_delta(F[i * gw + j], p, q), v = p + d * q; while (v < lo) { d++; v += q; } while (v > hi) { d--; v -= q; } Q[i * gw + j] = (uint8_t)v; D[i * gw + j] = (int16_t)d; } } while (0)
    for (i = 0; i < gh; i += 2) QT3(1, -1, 1);
    for (i = 1; i < gh; i += 2) QT3(0, -gw, gw);
    for (i = 1; i < gh; i += 2) QT3(1, -1, 1);
#undef QT3
}
/* 401x241 grid: every 4th point = corner (qc), every 2nd = q2a by rup rule, the rest q2b by rdn rule */
static void lat_quant5(const uint8_t *F, int qc, int qa, int qb, uint8_t *Q, int16_t *D) {
    int i, j, gw = G2W, gh = G2H;
#define Q1(I, J, PR, QQ, RND) do { int p = RND(PR), d = q_delta(F[(I) * gw + (J)], p, QQ), v = p + d * (QQ); while (v < 0) { d++; v += QQ; } while (v > 255) { d--; v -= QQ; } Q[(I) * gw + (J)] = (uint8_t)v; D[(I) * gw + (J)] = (int16_t)d; } while (0)
#define RU(A) lat_rup A
#define RD(A) lat_rdn A
    for (i = 0; i < gh; i += 4) for (j = 0; j < gw; j += 4) { int v = F[i * gw + j]; if (qc > 1) { v = (v + qc / 2) / qc * qc; if (v > 255) v -= qc; } Q[i * gw + j] = (uint8_t)v; D[i * gw + j] = 0; }
    for (i = 0; i < gh; i += 4) for (j = 2; j < gw; j += 4) Q1(i, j, (Q[i * gw + j - 2], Q[i * gw + j + 2]), qa, RU);
    for (i = 2; i < gh; i += 4) for (j = 0; j < gw; j += 4) Q1(i, j, (Q[(i - 2) * gw + j], Q[(i + 2) * gw + j]), qa, RU);
    for (i = 2; i < gh; i += 4) for (j = 2; j < gw; j += 4) Q1(i, j, (Q[i * gw + j - 2], Q[i * gw + j + 2]), qa, RU);
    for (i = 0; i < gh; i += 2) { int t_ = i * gw + 1, done_ = Q_NEON(qb) ? qrow2(F + t_, Q + t_, D + t_, -1, 1, (gw - 1) / 2, qb, 0, 255, 0) : 0; for (j = 1 + 2 * done_; j < gw; j += 2) Q1(i, j, (Q[i * gw + j - 1], Q[i * gw + j + 1]), qb, RD); }
    for (i = 1; i < gh; i += 2) { int t_ = i * gw, done_ = Q_NEON(qb) ? qrow1(F + t_, Q + t_, D + t_, -gw, gw, gw, qb, 0, 255, 0) : 0; for (j = done_; j < gw; j++) Q1(i, j, (Q[(i - 1) * gw + j], Q[(i + 1) * gw + j]), qb, RD); }
#undef Q1
#undef RU
#undef RD
}
/* The grids are built in two rounds of jobs: the filtered ones per plane, then the quantised ones */
static void job_lat_filter(rnv2enc *e, int idx) {
    int i, j; latgrid *L = e->L;
    if (idx) {
        /* chroma base: 4 px grid.  One chroma sample covers 2 px, so grid column j sits on chroma column 2j */
        const uint8_t *P = idx == 2 ? e->tV : e->tU; uint8_t *C4 = idx == 2 ? L->FV4 : L->FU4, *C8 = idx == 2 ? L->FV8 : L->FU8;
        for (i = 0; i < G4H; i++) {
            int y = 4 * i; if (y > H - 1) y = H - 1;
            int ya = y >= 2 ? y - 2 : 0, yb = y + 2 <= H - 1 ? y + 2 : H - 1;
            tent_row(P + ya * CW, P + y * CW, P + yb * CW, CW, C4 + i * G4W, G4W);
        }
        lat_down(C4, G4W, G4H, C8, G8W, G8H);
        return;
    }
    /* base: tent at full resolution onto the 2 px grid */
    for (i = 0; i < G2H; i++) {
        int y = 2 * i; if (y > H - 1) y = H - 1;
        int ya = y > 0 ? y - 1 : 0, yb = y < H - 1 ? y + 1 : H - 1;
        tent_row(e->tY + ya * W, e->tY + y * W, e->tY + yb * W, W, L->F2 + i * G2W, G2W);
    }
    lat_down(L->F2, G2W, G2H, L->F4, G4W, G4H);
    lat_down(L->F4, G4W, G4H, L->F8, G8W, G8H);
    if (e->p.lat_sharp > 0) { /* the tent plus linear interpolation blurs more than it has to: pull each level away from the next coarser one */
        int s = e->p.lat_sharp;
        for (i = 0; i < G2H; i++) for (j = 0; j < G2W; j++) { int c = L->F4[(i / 2) * G4W + j / 2]; if (!(i & 1) && !(j & 1)) { int v = L->F2[i * G2W + j]; L->F2[i * G2W + j] = (uint8_t)iclamp(v + ((v - c) * s >> 4), 0, 255); } }
        for (i = 0; i < G4H; i += 2) for (j = 0; j < G4W; j += 2) { int c = L->F8[(i / 2) * G8W + j / 2], v = L->F4[i * G4W + j]; L->F4[i * G4W + j] = (uint8_t)iclamp(v + ((v - c) * s >> 4), 0, 255); }
    }
}
static void job_lat_quant(rnv2enc *e, int idx) {
    int i, dith = e->p.dither != 0, lo = dith ? LAT_YMIN : 0, hi = dith ? LAT_YMAX : 255; latgrid *L = e->L;
    switch (idx) {
    case 0: for (i = 0; i < G8W * G8H; i++) L->QY8[i] = (uint8_t)iclamp(L->F8[i], lo, hi);
            lat_quant3(L->F4, G4W, G4H, 1, e->q4, lo, hi, L->QY4, L->DY4); break;
    case 1: lat_quant5(L->F2, RNV3_QC2, e->q2a, e->q2b, L->QY2, L->DY2); break;
    case 2: lat_quant3(L->FU4, G4W, G4H, 1, e->q4c, 0, 255, L->QU4, L->DU4); break;
    default: lat_quant3(L->FV4, G4W, G4H, 1, e->q4c, 0, 255, L->QV4, L->DV4); break;
    }
}
/* reconstruction of a LAT block (d: 0 LAT8, 1 LAT4, 2 LAT2) into SB layout */
#if !defined(__ARM_NEON) || defined(RNV_CHECK)
static void words_to_sb(const uint32_t *w, uint8_t *o) {
    int r, x;
    for (r = 0; r < 8; r++) {
        uint8_t *yr = o + ((r >> 2) * 2) * 16 + (r & 3) * 4, *ur = o + 64 + (r >> 2) * 16 + (r & 3) * 4, *vr = o + 96 + (r >> 2) * 16 + (r & 3) * 4;
        for (x = 0; x < 4; x++) {
            uint32_t v = w[4 * r + x]; int ly = 2 * x;
            if (ly < 4) { yr[ly] = (uint8_t)(v >> 24); yr[ly + 1] = (uint8_t)(v >> 8); } else { yr[16 + ly - 4] = (uint8_t)(v >> 24); yr[16 + ly - 3] = (uint8_t)(v >> 8); }
            ur[x] = (uint8_t)(v >> 16); vr[x] = (uint8_t)v;
        }
    }
}
#endif
#ifdef __ARM_NEON
/* The same bytes as lat2_words / lat4_words / lat8_words + words_to_sb.  LV_U and LV_D act on each byte alone, so they are vrhadd and vhadd. */
#define RH8 vrhadd_u8
#define HA8 vhadd_u8
/* rows of 8 luma pixels to two luma subblocks */
static inline void y4rows(uint8x8_t r0, uint8x8_t r1, uint8x8_t r2, uint8x8_t r3, uint8_t *o) {
    uint32x4_t a = vreinterpretq_u32_u8(vcombine_u8(r0, r1)), c = vreinterpretq_u32_u8(vcombine_u8(r2, r3));
    vst1q_u32((uint32_t *)o, vuzp1q_u32(a, c)); vst1q_u32((uint32_t *)(o + 16), vuzp2q_u32(a, c));
}
/* LAT2 chroma: 3x3 to 4x8 */
static inline void c33_sb(const uint8_t *Q, uint8_t *o) {
    uint8x8_t a0 = vld1_u8(Q), a1 = vld1_u8(Q + G4W), a2 = vld1_u8(Q + 2 * G4W);
    uint8x8_t c0 = vzip1_u8(a0, RH8(a0, vext_u8(a0, a0, 1))), c2 = vzip1_u8(a1, RH8(a1, vext_u8(a1, a1, 1))), c4 = vzip1_u8(a2, RH8(a2, vext_u8(a2, a2, 1)));
    uint8x8_t c1 = HA8(c0, c2), c3 = HA8(c2, c4);
#define Z32(x, y) vreinterpret_u8_u32(vzip1_u32(vreinterpret_u32_u8(x), vreinterpret_u32_u8(y)))
    vst1q_u8(o, vcombine_u8(Z32(c0, RH8(c0, c1)), Z32(c1, RH8(c1, c2))));
    vst1q_u8(o + 16, vcombine_u8(Z32(c2, RH8(c2, c3)), Z32(c3, RH8(c3, c4))));
#undef Z32
}
/* four rows of YUY2 words, already planar per row (Y a, Y b, Cb, Cr: 4 bytes each), to their 4 subblocks */
static inline void t4rows(uint8x16_t t0, uint8x16_t t1, uint8x16_t t2, uint8x16_t t3, uint8_t *oy, uint8_t *ou, uint8_t *ov) {
    uint32x4x2_t a = vtrnq_u32(vreinterpretq_u32_u8(t0), vreinterpretq_u32_u8(t1)), c = vtrnq_u32(vreinterpretq_u32_u8(t2), vreinterpretq_u32_u8(t3));
    vst1q_u32((uint32_t *)oy, vcombine_u32(vget_low_u32(a.val[0]), vget_low_u32(c.val[0])));
    vst1q_u32((uint32_t *)(oy + 16), vcombine_u32(vget_low_u32(a.val[1]), vget_low_u32(c.val[1])));
    vst1q_u32((uint32_t *)ou, vcombine_u32(vget_high_u32(a.val[0]), vget_high_u32(c.val[0])));
    vst1q_u32((uint32_t *)ov, vcombine_u32(vget_high_u32(a.val[1]), vget_high_u32(c.val[1])));
}
/* rows 0, 4, 8 of a soft block, as 4 words each: the rest, dither and the subblock layout (lat_finish + words_to_sb) */
static inline void lat_finish_sb(uint8x16_t ra, uint8x16_t rc, uint8x16_t re, int dith, uint8_t *o) {
    static const uint8_t PL[16] = {3, 1, 7, 5, 11, 9, 15, 13, 2, 6, 10, 14, 0, 4, 8, 12};
    static const uint8_t D0[16] = {LAT_DITH[0][0], LAT_DITH[0][1], 0, 2, 0, 2, 0, 2, 0}, D1[16] = {3, 1, 3, 1, 3, 1, 3, 1, 0};
    const uint8x16_t tb = vld1q_u8(PL);
    uint8x16_t a = vqtbl1q_u8(ra, tb), c = vqtbl1q_u8(rc, tb), e_ = vqtbl1q_u8(re, tb), b = vhaddq_u8(a, c), d = vhaddq_u8(c, e_);
    if (dith) {
        const uint8x16_t k0 = vld1q_u8(D0), k1 = vld1q_u8(D1);
        t4rows(vaddq_u8(a, k0), vaddq_u8(a, k1), vaddq_u8(b, k0), vaddq_u8(b, k1), o, o + 64, o + 96);
        t4rows(vaddq_u8(c, k0), vaddq_u8(c, k1), vaddq_u8(d, k0), vaddq_u8(d, k1), o + 32, o + 80, o + 112);
    } else { t4rows(a, a, b, b, o, o + 64, o + 96); t4rows(c, c, d, d, o + 32, o + 80, o + 112); }
}
/* [a, m, e] words: a, U(a,m), m, U(m,e) */
static inline uint8x16_t lat4_row(uint32_t a, uint32_t m, uint32_t e_) {
    uint32x2_t l = vcreate_u32((uint64_t)m << 32 | a), r = vcreate_u32((uint64_t)e_ << 32 | m);
    uint32x2_t u = vreinterpret_u32_u8(RH8(vreinterpret_u8_u32(l), vreinterpret_u8_u32(r)));
    return vreinterpretq_u8_u32(vcombine_u32(vzip1_u32(l, u), vzip2_u32(l, u)));
}
/* [A, E] words: A, U(A,m), m, U(m,E) with m = D(A,E) */
static inline uint8x16_t lat8_row(uint8x8_t v) {
    uint8x8_t m = HA8(v, vreinterpret_u8_u32(vrev64_u32(vreinterpret_u32_u8(v)))), u = RH8(v, m);
    uint32x2_t vv = vreinterpret_u32_u8(v), mm = vreinterpret_u32_u8(m), uu = vreinterpret_u32_u8(u);
    return vreinterpretq_u8_u32(vcombine_u32(vzip1_u32(vv, uu), vzip2_u32(mm, uu)));
}
static void lat_recon_n(const rnv2enc *e, int b, int d, uint8_t *o) {
    const latgrid *L = e->L; int bx = b % BW, by = b / BW, dith = e->p.dither != 0, ofs = dith ? LAT_DITH_BASE : 0;
    if (d == 2) {
        const uint8_t *g = L->QY2 + 4 * by * G2W + 4 * bx; int tc = 2 * by * G4W + 2 * bx; uint8x8_t w[5]; int i;
        for (i = 0; i < 5; i++) { uint8x8_t a = vld1_u8(g + i * G2W); w[i] = vzip1_u8(a, RH8(a, vext_u8(a, a, 1))); }
        y4rows(w[0], RH8(w[0], w[1]), w[1], RH8(w[1], w[2]), o);
        y4rows(w[2], RH8(w[2], w[3]), w[3], RH8(w[3], w[4]), o + 32);
        c33_sb(L->QU4 + tc, o + 64); c33_sb(L->QV4 + tc, o + 96);
    } else {
        int s = by * G8W + bx;
        uint32_t c0 = LAT_CW(L->FU8[s], L->FV8[s]), c1 = LAT_CW(L->FU8[s + 1], L->FV8[s + 1]), c2 = LAT_CW(L->FU8[s + G8W], L->FV8[s + G8W]), c3 = LAT_CW(L->FU8[s + G8W + 1], L->FV8[s + G8W + 1]);
        if (d == 1) {
            const uint8_t *q = L->QY4 + 2 * by * G4W + 2 * bx;
            uint32_t c01 = LV_U(c0, c1), c21 = LV_U(c2, c3), c10 = LV_U(c0, c2), c12 = LV_U(c1, c3), c11 = LV_U(c10, c12);
#define YC(i, j, c) (LAT_YW(q[(i) * G4W + (j)] - ofs) | (c))
            lat_finish_sb(lat4_row(YC(0, 0, c0), YC(0, 1, c01), YC(0, 2, c1)), lat4_row(YC(1, 0, c10), YC(1, 1, c11), YC(1, 2, c12)), lat4_row(YC(2, 0, c2), YC(2, 1, c21), YC(2, 2, c3)), dith, o);
#undef YC
        } else {
            const uint8_t *q = L->QY8 + s;
            uint32_t p0 = LAT_YW(q[0] - ofs) | c0, p1 = LAT_YW(q[1] - ofs) | c1, p2 = LAT_YW(q[G8W] - ofs) | c2, p3 = LAT_YW(q[G8W + 1] - ofs) | c3;
            uint8x8_t v0 = vreinterpret_u8_u64(vcreate_u64((uint64_t)p1 << 32 | p0)), v2 = vreinterpret_u8_u64(vcreate_u64((uint64_t)p3 << 32 | p2)), v1 = RH8(v0, v2);
            lat_finish_sb(lat8_row(v0), lat8_row(v1), lat8_row(v2), dith, o);
        }
    }
}
#undef RH8
#undef HA8
#endif
#if !defined(__ARM_NEON) || defined(RNV_CHECK)
static void lat_recon_s(const rnv2enc *e, int b, int d, uint8_t *o) {
    const latgrid *L = e->L; int bx = b % BW, by = b / BW, i, j; uint32_t w[32];
    if (d == 2) {
        int G[5][5], gu[3][3], gv[3][3];
        for (i = 0; i < 5; i++) for (j = 0; j < 5; j++) G[i][j] = L->QY2[(4 * by + i) * G2W + 4 * bx + j];
        for (i = 0; i < 3; i++) for (j = 0; j < 3; j++) { gu[i][j] = L->QU4[(2 * by + i) * G4W + 2 * bx + j]; gv[i][j] = L->QV4[(2 * by + i) * G4W + 2 * bx + j]; }
        lat2_words(G, gu, gv, w);
    } else {
        int s = by * G8W + bx, cu[4] = {L->FU8[s], L->FU8[s + 1], L->FU8[s + G8W], L->FU8[s + G8W + 1]}, cv[4] = {L->FV8[s], L->FV8[s + 1], L->FV8[s + G8W], L->FV8[s + G8W + 1]};
        if (d == 1) { int g3[3][3]; for (i = 0; i < 3; i++) for (j = 0; j < 3; j++) g3[i][j] = L->QY4[(2 * by + i) * G4W + 2 * bx + j]; lat4_words(g3, cu, cv, e->p.dither != 0, w); }
        else { int c[4] = {L->QY8[s], L->QY8[s + 1], L->QY8[s + G8W], L->QY8[s + G8W + 1]}; lat8_words(c, cu, cv, e->p.dither != 0, w); }
    }
    words_to_sb(w, o);
}
#endif
/* -DRNV_CHECK: the NEON path against the scalar one on every block.  For a test run on the Pi */
#ifdef __ARM_NEON
#ifdef RNV_CHECK
static void lat_recon(const rnv2enc *e, int b, int d, uint8_t *o) {
    uint8_t c[128]; lat_recon_n(e, b, d, o); lat_recon_s(e, b, d, c);
    if (memcmp(o, c, 128)) { int i; fprintf(stderr, "lat_recon mismatch block %d d %d dith %d:", b, d, e->p.dither); for (i = 0; i < 128; i++) if (o[i] != c[i]) fprintf(stderr, " %d:%d/%d", i, o[i], c[i]); fprintf(stderr, "\n"); abort(); }
}
#else
#define lat_recon lat_recon_n
#endif
#else
#define lat_recon lat_recon_s
#endif
/* bits of the points a LAT block adds when its neighbours are LAT of the same density: the estimate the mode decision uses (the frame total is exact) */
static int lat_bits_est(const rnv2enc *e, int b, int d) {
    const latgrid *L = e->L; int bx = b % BW, by = b / BW, bits = 0, i, j;
#define SE(v) ue_len(se_map(v))
    if (d == 0) {
        const uint8_t *Q = L->QY8; int s = by * G8W + bx;
        bits += SE(Q[s + G8W + 1] - (Q[s + G8W] + Q[s + 1] - Q[s]));
        Q = L->FU8; bits += SE(Q[s + G8W + 1] - (Q[s + G8W] + Q[s + 1] - Q[s]));
        Q = L->FV8; bits += SE(Q[s + G8W + 1] - (Q[s + G8W] + Q[s + 1] - Q[s]));
    } else if (d == 1) {
        const uint8_t *Q = L->QY4; int t = 2 * by * G4W + 2 * bx, s = by * G8W + bx;
        bits += SE(Q[t + 2 * G4W + 2] - (Q[t + 2 * G4W] + Q[t + 2] - Q[t]));
        bits += SE(L->DY4[t + G4W + 2]) + SE(L->DY4[t + 2 * G4W + 1]) + SE(L->DY4[t + G4W + 1]);
        Q = L->FU8; bits += SE(Q[s + G8W + 1] - (Q[s + G8W] + Q[s + 1] - Q[s]));
        Q = L->FV8; bits += SE(Q[s + G8W + 1] - (Q[s + G8W] + Q[s + 1] - Q[s]));
    } else {
        const uint8_t *Q = L->QY2; int t = 4 * by * G2W + 4 * bx, tc = 2 * by * G4W + 2 * bx;
        bits += SE((Q[t + 4 * G2W + 4] - (Q[t + 4 * G2W] + Q[t + 4] - Q[t])) / RNV3_QC2);
        for (i = 0; i <= 4; i++) for (j = 1; j <= 4; j++) { if ((i == 0) || (i == 4 && j == 4)) continue; bits += SE(L->DY2[t + i * G2W + j]); }
        for (i = 1; i <= 2; i++) for (j = 1; j <= 2; j++) { if (i == 2 && j == 2) continue; bits += SE(L->DU4[tc + i * G4W + j]) + SE(L->DV4[tc + i * G4W + j]); }
        Q = L->QU4; bits += SE(Q[tc + 2 * G4W + 2] - (Q[tc + 2 * G4W] + Q[tc + 2] - Q[tc]));
        Q = L->QV4; bits += SE(Q[tc + 2 * G4W + 2] - (Q[tc + 2 * G4W] + Q[tc + 2] - Q[tc]));
    }
    return bits;
}
/* Walker shared by the size pass (w == NULL) and the writer.  st: state over the frame in raster order */
typedef struct { int last[3][3]; int btc[6]; } emit_t;
static inline int mode_is(const rnv2enc *e, int b, int m) { return e->bd[b].mode == m; }
#define PUTSE(v) do { int v_ = (v); if (w) bw_ue(w, se_map(v_)); bits += ue_len(se_map(v_)); } while (0)
/* corners of one component.  c[] = TL TR BL BR values; qc their step */
static inline int emit_corners(bw_t *w, int *last, const int c[4], int kTL, int kTR, int kBL, int qc) {
    int bits = 0;
    if (!kTL) { PUTSE((c[0] - *last) / qc); }
    if (!kTR) { PUTSE((c[1] - c[0]) / qc); }
    if (!kBL) { PUTSE((c[2] - c[0]) / qc); }
    PUTSE((c[3] - (c[2] + c[1] - c[0])) / qc);
    *last = c[3];
    return bits;
}
static int lat_emit(const rnv2enc *e, int b, int d, emit_t *st, bw_t *w) {
    const latgrid *L = e->L; int bx = b % BW, by = b / BW, m = M_LAT8 + d, bits = 0, i, j;
    int kL = bx > 0 && mode_is(e, b - 1, m), kT = by > 0 && mode_is(e, b - BW, m), kTL = kL || kT || (bx > 0 && by > 0 && mode_is(e, b - BW - 1, m)), kTR = kT || (by > 0 && bx < BW - 1 && mode_is(e, b - BW + 1, m)), kBL = kL;
    int c[4];
    if (d == 0) {
        int s = by * G8W + bx;
        c[0] = L->QY8[s]; c[1] = L->QY8[s + 1]; c[2] = L->QY8[s + G8W]; c[3] = L->QY8[s + G8W + 1]; bits += emit_corners(w, &st->last[d][0], c, kTL, kTR, kBL, 1);
        c[0] = L->FU8[s]; c[1] = L->FU8[s + 1]; c[2] = L->FU8[s + G8W]; c[3] = L->FU8[s + G8W + 1]; bits += emit_corners(w, &st->last[d][1], c, kTL, kTR, kBL, 1);
        c[0] = L->FV8[s]; c[1] = L->FV8[s + 1]; c[2] = L->FV8[s + G8W]; c[3] = L->FV8[s + G8W + 1]; bits += emit_corners(w, &st->last[d][2], c, kTL, kTR, kBL, 1);
        return bits;
    }
    if (d == 1) {
        int t = 2 * by * G4W + 2 * bx, s = by * G8W + bx; const int16_t *D = L->DY4;
        c[0] = L->QY4[t]; c[1] = L->QY4[t + 2]; c[2] = L->QY4[t + 2 * G4W]; c[3] = L->QY4[t + 2 * G4W + 2]; bits += emit_corners(w, &st->last[d][0], c, kTL, kTR, kBL, 1);
        if (!kT) PUTSE(D[t + 1]);
        if (!kL) PUTSE(D[t + G4W]);
        PUTSE(D[t + G4W + 2]); PUTSE(D[t + 2 * G4W + 1]); PUTSE(D[t + G4W + 1]);
        c[0] = L->FU8[s]; c[1] = L->FU8[s + 1]; c[2] = L->FU8[s + G8W]; c[3] = L->FU8[s + G8W + 1]; bits += emit_corners(w, &st->last[d][1], c, kTL, kTR, kBL, 1);
        c[0] = L->FV8[s]; c[1] = L->FV8[s + 1]; c[2] = L->FV8[s + G8W]; c[3] = L->FV8[s + G8W + 1]; bits += emit_corners(w, &st->last[d][2], c, kTL, kTR, kBL, 1);
        return bits;
    }
    {
        int t = 4 * by * G2W + 4 * bx, tc = 2 * by * G4W + 2 * bx, k; const int16_t *D = L->DY2;
        c[0] = L->QY2[t]; c[1] = L->QY2[t + 4]; c[2] = L->QY2[t + 4 * G2W]; c[3] = L->QY2[t + 4 * G2W + 4]; bits += emit_corners(w, &st->last[d][0], c, kTL, kTR, kBL, RNV3_QC2);
        /* 3x3 level */
        if (!kT) PUTSE(D[t + 2]);
        if (!kL) PUTSE(D[t + 2 * G2W]);
        PUTSE(D[t + 2 * G2W + 4]); PUTSE(D[t + 4 * G2W + 2]); PUTSE(D[t + 2 * G2W + 2]);
        /* 5x5 level: even rows, then odd rows */
        for (i = 0; i <= 4; i += 2) { if (i == 0 && kT) continue; PUTSE(D[t + i * G2W + 1]); PUTSE(D[t + i * G2W + 3]); }
        for (i = 1; i <= 3; i += 2) for (j = 0; j <= 4; j++) { if (j == 0 && kL) continue; PUTSE(D[t + i * G2W + j]); }
        for (k = 0; k < 2; k++) {
            const uint8_t *Q = k ? L->QV4 : L->QU4; const int16_t *DC = k ? L->DV4 : L->DU4;
            c[0] = Q[tc]; c[1] = Q[tc + 2]; c[2] = Q[tc + 2 * G4W]; c[3] = Q[tc + 2 * G4W + 2]; bits += emit_corners(w, &st->last[d][k + 1], c, kTL, kTR, kBL, 1);
            if (!kT) PUTSE(DC[tc + 1]);
            if (!kL) PUTSE(DC[tc + G4W]);
            PUTSE(DC[tc + G4W + 2]); PUTSE(DC[tc + 2 * G4W + 1]); PUTSE(DC[tc + G4W + 1]);
        }
        return bits;
    }
}
static int btc_emit(const btcinfo *t, emit_t *st, bw_t *w) {
    int k, bits = 0;
    for (k = 0; k < 6; k++) { PUTSE(t->c[k] - st->btc[k]); st->btc[k] = t->c[k]; }
    return bits;
}

/* ------------------------------------------------------------------ tone blocks */
/* c[]: y0 y1 u0 u1 v0 v1 */
static inline void btc_put_row(uint8_t *o, int r, int x, const uint8_t *e4) { /* e4: y of the pair, cb, cr */
    uint8_t *yr = o + ((r >> 2) * 2) * 16 + (r & 3) * 4 + (x < 2 ? 2 * x : 16 + 2 * (x - 2));
    int c = (r >> 2) * 16 + (r & 3) * 4 + x;
    yr[0] = e4[0]; yr[1] = e4[1]; o[64 + c] = e4[2]; o[96 + c] = e4[3];
}
#ifdef __ARM_NEON
/* p: palette index of the 16 pairs of 4 rows.  T0..T3: palette as y of the pair (first, second), cb, cr */
static inline void btc_group(uint8x16_t p, uint8x16_t T0, uint8x16_t T1, uint8x16_t T2, uint8x16_t T3, uint8_t *oy, uint8_t *ou, uint8_t *ov) {
    uint8x16_t ya = vqtbl1q_u8(T0, p), yb = vqtbl1q_u8(T1, p);
    uint32x4_t r01 = vreinterpretq_u32_u8(vzip1q_u8(ya, yb)), r23 = vreinterpretq_u32_u8(vzip2q_u8(ya, yb));
    vst1q_u32((uint32_t *)oy, vuzp1q_u32(r01, r23)); vst1q_u32((uint32_t *)(oy + 16), vuzp2q_u32(r01, r23));
    vst1q_u8(ou, vqtbl1q_u8(T2, p)); vst1q_u8(ov, vqtbl1q_u8(T3, p));
}
static void btc2_rec(const btcinfo *t, const uint8_t *m, uint8_t *o) {
    static const int8_t SH[16] = {-6, -4, -2, 0, -6, -4, -2, 0, -6, -4, -2, 0, -6, -4, -2, 0};
    static const uint8_t AI[16] = {0, 0, 1, 1}, BI[16] = {0, 1, 0, 1};
    const int8x16_t sh = vld1q_s8(SH); const uint8x16_t k3 = vdupq_n_u8(3); int g, c2m = (t->c[2] + t->c[3] + 1) >> 1, c4m = (t->c[4] + t->c[5] + 1) >> 1;
    uint8_t Yc[16] = {(uint8_t)t->c[0], (uint8_t)t->c[1]}, Uc[16] = {(uint8_t)t->c[2], (uint8_t)c2m, (uint8_t)c2m, (uint8_t)t->c[3]}, Vc[16] = {(uint8_t)t->c[4], (uint8_t)c4m, (uint8_t)c4m, (uint8_t)t->c[5]};
    const uint8x16_t Yv = vld1q_u8(Yc), T0 = vqtbl1q_u8(Yv, vld1q_u8(AI)), T1 = vqtbl1q_u8(Yv, vld1q_u8(BI)), T2 = vld1q_u8(Uc), T3 = vld1q_u8(Vc);
    for (g = 0; g < 2; g++) {
        uint8x16_t mm = vcombine_u8(vcreate_u8((uint64_t)m[4 * g] * 0x01010101ULL + ((uint64_t)m[4 * g + 1] * 0x01010101ULL << 32)), vcreate_u8((uint64_t)m[4 * g + 2] * 0x01010101ULL + ((uint64_t)m[4 * g + 3] * 0x01010101ULL << 32)));
        btc_group(vandq_u8(vshlq_u8(mm, sh), k3), T0, T1, T2, T3, o + 32 * g, o + 64 + 16 * g, o + 96 + 16 * g);
    }
}
static void btc4_rec(const btcinfo *t, const uint8_t *m, uint8_t *o) {
    static const uint8_t AI[16] = {0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3}, BI[16] = {0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3}, SI[16] = {0, 1, 2, 3, 1, 2, 3, 4, 2, 3, 4, 5, 3, 4, 5, 6};
    static const uint8_t HI_[16] = {0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7}; static const int8_t SH[16] = {-4, 0, -4, 0, -4, 0, -4, 0, -4, 0, -4, 0, -4, 0, -4, 0};
    int Y[4], U[7], V[7], g, i; uint8_t Yc[16] = {0}, Uc[16] = {0}, Vc[16] = {0}; uint8x16_t Yv, Uv, Vv, T0, T1, T2, T3; const uint8x16_t k15 = vdupq_n_u8(15);
    btc4_y(t->c[0], t->c[1], Y); btc4_c(t->c[2], t->c[3], U); btc4_c(t->c[4], t->c[5], V);
    for (i = 0; i < 4; i++) Yc[i] = (uint8_t)Y[i];
    for (i = 0; i < 7; i++) { Uc[i] = (uint8_t)U[i]; Vc[i] = (uint8_t)V[i]; }
    Yv = vld1q_u8(Yc); Uv = vld1q_u8(Uc); Vv = vld1q_u8(Vc); T0 = vqtbl1q_u8(Yv, vld1q_u8(AI)); T1 = vqtbl1q_u8(Yv, vld1q_u8(BI)); T2 = vqtbl1q_u8(Uv, vld1q_u8(SI)); T3 = vqtbl1q_u8(Vv, vld1q_u8(SI));
    for (g = 0; g < 2; g++) { /* 8 bytes of m4, 2 per row, 2 pairs per byte */
        uint8x16_t bytes = vqtbl1q_u8(vcombine_u8(vld1_u8(m + 8 * g), vdup_n_u8(0)), vld1q_u8(HI_));
        btc_group(vandq_u8(vshlq_u8(bytes, vld1q_s8(SH)), k15), T0, T1, T2, T3, o + 32 * g, o + 64 + 16 * g, o + 96 + 16 * g);
    }
}
#define btc2_rec btc2_rec_s
#define btc4_rec btc4_rec_s
#define BTC_REC_NEON
#endif
#if !defined(__ARM_NEON) || defined(RNV_CHECK)
static void btc2_rec(const btcinfo *t, const uint8_t *m, uint8_t *o) {
    uint8_t T[4][4]; int r, x, p;
    for (p = 0; p < 4; p++) { int a = p >> 1, bb = p & 1, s = a + bb; T[p][0] = (uint8_t)t->c[a]; T[p][1] = (uint8_t)t->c[bb]; T[p][2] = (uint8_t)btc2_c(t->c[2], t->c[3], s); T[p][3] = (uint8_t)btc2_c(t->c[4], t->c[5], s); }
    for (r = 0; r < 8; r++) for (x = 0; x < 4; x++) btc_put_row(o, r, x, T[(m[r] >> (6 - 2 * x)) & 3]);
}
static void btc4_rec(const btcinfo *t, const uint8_t *m, uint8_t *o) {
    uint8_t T[16][4]; int r, x, p, Y[4], U[7], V[7];
    btc4_y(t->c[0], t->c[1], Y); btc4_c(t->c[2], t->c[3], U); btc4_c(t->c[4], t->c[5], V);
    for (p = 0; p < 16; p++) { int a = p >> 2, bb = p & 3; T[p][0] = (uint8_t)Y[a]; T[p][1] = (uint8_t)Y[bb]; T[p][2] = (uint8_t)U[a + bb]; T[p][3] = (uint8_t)V[a + bb]; }
    for (r = 0; r < 8; r++) { unsigned bits = (unsigned)m[2 * r] << 8 | m[2 * r + 1]; for (x = 0; x < 4; x++) btc_put_row(o, r, x, T[(bits >> (12 - 4 * x)) & 15]); }
}
#endif
#ifdef BTC_REC_NEON
#undef btc2_rec
#undef btc4_rec
#ifdef RNV_CHECK
static void btc2_rec_c(const btcinfo *t, const uint8_t *m, uint8_t *o) { uint8_t c[128]; btc2_rec(t, m, o); btc2_rec_s(t, m, c); if (memcmp(o, c, 128)) { fprintf(stderr, "btc2_rec mismatch\n"); abort(); } }
static void btc4_rec_c(const btcinfo *t, const uint8_t *m, uint8_t *o) { uint8_t c[128]; btc4_rec(t, m, o); btc4_rec_s(t, m, c); if (memcmp(o, c, 128)) { fprintf(stderr, "btc4_rec mismatch\n"); abort(); } }
#define btc2_rec btc2_rec_c
#define btc4_rec btc4_rec_c
#endif
#endif
/* Tone search on 32 pixel pairs at a time.  GCC vector extensions: the one path on x86 and on the Pi (plain integer arithmetic, so the result is the same).
 * Pair i = 4 r + x: luma Y0[i] Y1[i], chroma U[i] V[i] */
typedef int16_t v8s __attribute__((vector_size(16), may_alias));
typedef int32_t v4i __attribute__((vector_size(16), may_alias));
typedef struct { int16_t Y0[32], Y1[32], U[32], V[32]; int ymn, ymx, umn, umx, vmn, vmx, axis, sy, su, sv; } __attribute__((aligned(16))) btcctx;
static inline int hs8(v8s v) {
#ifdef __ARM_NEON
    return vaddvq_s16(vreinterpretq_s16_u8(vreinterpretq_u8_s16((int16x8_t)v)));
#else
    int k, s = 0; for (k = 0; k < 8; k++) s += v[k]; return (int16_t)s;
#endif
}
static inline int hs4(v4i v) {
#ifdef __ARM_NEON
    return vaddvq_s32((int32x4_t)v);
#else
    return v[0] + v[1] + v[2] + v[3];
#endif
}
static void btc_load(const rnv2enc *e, int b, btcctx *c) {
    const int x0 = (b % BW) * 8, y0_ = (b / BW) * 8; int r, x, i, ymn = 255, ymx = 0, umn = 255, umx = 0, vmn = 255, vmx = 0, sy = 0, su = 0, sv = 0;
#ifdef __ARM_NEON
    uint8x16_t yn = vdupq_n_u8(255), yx = vdupq_n_u8(0), un = yn, ux = yx, vn = yn, vx = yx; uint16x8_t ays = vdupq_n_u16(0), aus = ays, avs = ays;
    for (r = 0; r < 8; r += 2) {
        const uint8_t *py = e->tY + (y0_ + r) * W + x0, *pu = e->tU + (y0_ + r) * CW + x0 / 2, *pv = e->tV + (y0_ + r) * CW + x0 / 2;
        uint8x16_t yy = vcombine_u8(vld1_u8(py), vld1_u8(py + W)); uint8x16x2_t dd = vuzpq_u8(yy, yy);
        uint32x4_t ul = vdupq_n_u32(0), vl = ul; uint8x8_t uu, vv;
        ul = vld1q_lane_u32((const uint32_t *)(const void *)pu, ul, 0); ul = vld1q_lane_u32((const uint32_t *)(const void *)(pu + CW), ul, 1); vl = vld1q_lane_u32((const uint32_t *)(const void *)pv, vl, 0); vl = vld1q_lane_u32((const uint32_t *)(const void *)(pv + CW), vl, 1);
        uu = vreinterpret_u8_u32(vget_low_u32(ul)); vv = vreinterpret_u8_u32(vget_low_u32(vl));
        vst1q_s16(c->Y0 + 4 * r, vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(dd.val[0])))); vst1q_s16(c->Y1 + 4 * r, vreinterpretq_s16_u16(vmovl_u8(vget_low_u8(dd.val[1]))));
        vst1q_s16(c->U + 4 * r, vreinterpretq_s16_u16(vmovl_u8(uu))); vst1q_s16(c->V + 4 * r, vreinterpretq_s16_u16(vmovl_u8(vv)));
        yn = vminq_u8(yn, yy); yx = vmaxq_u8(yx, yy); un = vminq_u8(un, vcombine_u8(uu, uu)); ux = vmaxq_u8(ux, vcombine_u8(uu, uu)); vn = vminq_u8(vn, vcombine_u8(vv, vv)); vx = vmaxq_u8(vx, vcombine_u8(vv, vv));
        ays = vpadalq_u8(ays, yy); aus = vaddw_u8(aus, uu); avs = vaddw_u8(avs, vv);
    }
    ymn = vminvq_u8(yn); ymx = vmaxvq_u8(yx); umn = vminvq_u8(un); umx = vmaxvq_u8(ux); vmn = vminvq_u8(vn); vmx = vmaxvq_u8(vx); sy = vaddlvq_u16(ays); su = vaddlvq_u16(aus); sv = vaddlvq_u16(avs); (void)x; (void)i;
#else
    for (r = 0; r < 8; r++) { const uint8_t *py = e->tY + (y0_ + r) * W + x0, *pu = e->tU + (y0_ + r) * CW + x0 / 2, *pv = e->tV + (y0_ + r) * CW + x0 / 2;
        for (x = 0; x < 4; x++) { i = 4 * r + x; c->Y0[i] = py[2 * x]; c->Y1[i] = py[2 * x + 1]; c->U[i] = pu[x]; c->V[i] = pv[x]; } }
    for (i = 0; i < 32; i++) { int a = c->Y0[i], d = c->Y1[i], u = c->U[i], v = c->V[i]; sy += a + d; su += u; sv += v;
        if (a < ymn) ymn = a; if (a > ymx) ymx = a; if (d < ymn) ymn = d; if (d > ymx) ymx = d; if (u < umn) umn = u; if (u > umx) umx = u; if (v < vmn) vmn = v; if (v > vmx) vmx = v; }
#endif
    c->ymn = ymn; c->ymx = ymx; c->umn = umn; c->umx = umx; c->vmn = vmn; c->vmx = vmx; c->sy = sy; c->su = su; c->sv = sv;
    c->axis = (ymx - ymn) * 2 >= 3 * (umx - umn) && (ymx - ymn) * 2 >= 3 * (vmx - vmn) ? 0 : (umx - umn) >= (vmx - vmn) ? 1 : 2;
}
/* first split by the axis value of the pixel (chroma axes: the pair), then BTC2: two-means, pixels by threshold on the axis.  t4 keeps the first split, BTC4 starts from it.  Endpoints along the strongest axis */
static void btc_first(const btcctx *c, btcinfo *t2, uint8_t *m2, btcinfo *t4) {
    const int axis = c->axis; const int16_t *a0 = axis == 0 ? c->Y0 : axis == 1 ? c->U : c->V, *a1 = axis == 0 ? c->Y1 : a0; int i, it;
    {
        const int16_t lo = (int16_t)(axis == 0 ? c->ymn : axis == 1 ? c->umn : c->vmn), hi = (int16_t)(axis == 0 ? c->ymx : axis == 1 ? c->umx : c->vmx), rng = hi - lo > 0 ? hi - lo : 1;
        const int16_t r2 = (int16_t)(2 * rng), r4 = (int16_t)(4 * rng);
        v8s sy0 = {0}, sy1 = {0}, su0 = {0}, su1 = {0}, sv0 = {0}, sv1 = {0}, ny0 = {0}, ny1 = {0}, nc0 = {0}, nc1 = {0};
        int ny[2], nc[2];
        for (i = 0; i < 32; i += 8) {
            v8s y0 = *(const v8s *)(c->Y0 + i), y1 = *(const v8s *)(c->Y1 + i), u = *(const v8s *)(c->U + i), v = *(const v8s *)(c->V + i), p0 = *(const v8s *)(a0 + i), p1 = *(const v8s *)(a1 + i);
            v8s d0 = (p0 - lo) * 3, d1 = (p1 - lo) * 3, dp = d0 + d1;
            v8s z0 = d0 < rng, z1 = d1 < rng, t0 = d0 >= r2, t1 = d1 >= r2, zp = dp < r2, tp = dp >= r4;
            sy0 += (y0 & z0) + (y1 & z1); ny0 -= z0 + z1; sy1 += (y0 & t0) + (y1 & t1); ny1 -= t0 + t1;
            su0 += u & zp; sv0 += v & zp; nc0 -= zp; su1 += u & tp; sv1 += v & tp; nc1 -= tp;
        }
        ny[0] = hs8(ny0); ny[1] = hs8(ny1); nc[0] = hs8(nc0); nc[1] = hs8(nc1);
        t4->c[0] = ny[0] ? (hs8(sy0) + ny[0] / 2) / ny[0] : c->ymn; t4->c[1] = ny[1] ? (hs8(sy1) + ny[1] / 2) / ny[1] : c->ymx;
        t4->c[2] = nc[0] ? (hs8(su0) + nc[0] / 2) / nc[0] : c->umn; t4->c[3] = nc[1] ? (hs8(su1) + nc[1] / 2) / nc[1] : c->umx;
        t4->c[4] = nc[0] ? (hs8(sv0) + nc[0] / 2) / nc[0] : c->vmn; t4->c[5] = nc[1] ? (hs8(sv1) + nc[1] / 2) / nc[1] : c->vmx;
    }
    *t2 = *t4;
    for (it = 0; it < 3; it++) {
        static const int16_t W0[8] = {128, 32, 8, 2, 128, 32, 8, 2}, W1[8] = {64, 16, 4, 1, 64, 16, 4, 1};
        int ax0 = axis == 0 ? t2->c[0] : axis == 1 ? t2->c[2] : t2->c[4], ax1 = axis == 0 ? t2->c[1] : axis == 1 ? t2->c[3] : t2->c[5], ny1_, nc0_, nc1_;
        const int16_t thr2 = (int16_t)(ax0 + ax1), flip = ax0 > ax1 ? -1 : 0;
        v8s sy1 = {0}, ny1 = {0}, su0 = {0}, sv0 = {0}, nc0 = {0}, su1 = {0}, sv1 = {0}, nc1 = {0};
        for (i = 0; i < 32; i += 8) {
            v8s y0 = *(const v8s *)(c->Y0 + i), y1 = *(const v8s *)(c->Y1 + i), u = *(const v8s *)(c->U + i), v = *(const v8s *)(c->V + i), p0 = *(const v8s *)(a0 + i), p1 = *(const v8s *)(a1 + i);
            v8s m0 = ((p0 + p0) > thr2) ^ flip, m1 = ((p1 + p1) > thr2) ^ flip, both1 = m0 & m1, both0 = ~(m0 | m1);
            sy1 += (y0 & m0) + (y1 & m1); ny1 -= m0 + m1;
            su1 += u & both1; sv1 += v & both1; nc1 -= both1; su0 += u & both0; sv0 += v & both0; nc0 -= both0;
            if (it == 2) { v8s w = (m0 & *(const v8s *)W0) | (m1 & *(const v8s *)W1); m2[i >> 2] = (uint8_t)(w[0] | w[1] | w[2] | w[3]); m2[(i >> 2) + 1] = (uint8_t)(w[4] | w[5] | w[6] | w[7]); }
        }
        if (it == 2) break;
        ny1_ = hs8(ny1); nc0_ = hs8(nc0); nc1_ = hs8(nc1);
        { int ny0_ = 64 - ny1_, s1 = hs8(sy1), s0 = c->sy - s1;
          if (ny0_) t2->c[0] = (s0 + ny0_ / 2) / ny0_;
          if (ny1_) t2->c[1] = (s1 + ny1_ / 2) / ny1_; }
        if (nc0_) { t2->c[2] = (hs8(su0) + nc0_ / 2) / nc0_; t2->c[4] = (hs8(sv0) + nc0_ / 2) / nc0_; }
        if (nc1_) { t2->c[3] = (hs8(su1) + nc1_ / 2) / nc1_; t2->c[5] = (hs8(sv1) + nc1_ / 2) / nc1_; }
    }
}
/* BTC4: for each pixel of a pair only the two luma levels around it are tried, then least-squares endpoints */
static void btc_full(const btcctx *c, btcinfo *t4, uint8_t *m4) {
    int32_t Ya[32] __attribute__((aligned(16))), Yb[32] __attribute__((aligned(16))), Ua[32] __attribute__((aligned(16))), Va[32] __attribute__((aligned(16))); int i, it, r;
    static const v4i WY = {0, 3, 5, 8}, WC0 = {0, 1, 3, 4}, WC1 = {5, 7, 8, 0};
    for (i = 0; i < 32; i++) { Ya[i] = c->Y0[i]; Yb[i] = c->Y1[i]; Ua[i] = c->U[i]; Va[i] = c->V[i]; }
    for (it = 0; it < 3; it++) {
        int Y[4], U[7], V[7], up = t4->c[1] >= t4->c[0]; v4i aw = {0}, aw2 = {0}, awy = {0}, ac = {0}, ac2 = {0}, acu = {0}, acv = {0}, Yv, U0, U1, V0, V1;
        btc4_y(t4->c[0], t4->c[1], Y); btc4_c(t4->c[2], t4->c[3], U); btc4_c(t4->c[4], t4->c[5], V);
        Yv = (v4i){Y[0], Y[1], Y[2], Y[3]}; U0 = (v4i){U[0], U[1], U[2], U[3]}; U1 = (v4i){U[4], U[5], U[6], 0}; V0 = (v4i){V[0], V[1], V[2], V[3]}; V1 = (v4i){V[4], V[5], V[6], 0};
        for (r = 0; r < 8; r++) {
            const v4i ya = *(const v4i *)(Ya + 4 * r), yb = *(const v4i *)(Yb + 4 * r), ua = *(const v4i *)(Ua + 4 * r), va = *(const v4i *)(Va + 4 * r);
            /* levels around ya, yb.  Y is monotonic in the index, either way up */
            v4i ka = up ? -((ya > Y[1]) + (ya > Y[2])) : -((ya < Y[1]) + (ya < Y[2])), kb = up ? -((yb > Y[1]) + (yb > Y[2])) : -((yb < Y[1]) + (yb < Y[2]));
            v4i ka1 = ka + 1, kb1 = kb + 1, s0 = ka + kb, s1 = s0 + 1, s2 = s0 + 2;
            v4i da0 = ya - __builtin_shuffle(Yv, ka), da1 = ya - __builtin_shuffle(Yv, ka1), db0 = yb - __builtin_shuffle(Yv, kb), db1 = yb - __builtin_shuffle(Yv, kb1);
            v4i ea0 = da0 * da0, ea1 = da1 * da1, eb0 = db0 * db0, eb1 = db1 * db1;
            v4i du0 = ua - __builtin_shuffle(U0, U1, s0), dv0 = va - __builtin_shuffle(V0, V1, s0), du1 = ua - __builtin_shuffle(U0, U1, s1), dv1 = va - __builtin_shuffle(V0, V1, s1), du2 = ua - __builtin_shuffle(U0, U1, s2), dv2 = va - __builtin_shuffle(V0, V1, s2);
            v4i c0 = (du0 * du0 + dv0 * dv0) * 2, c1 = (du1 * du1 + dv1 * dv1) * 2, c2 = (du2 * du2 + dv2 * dv2) * 2;
            v4i best = ea0 + eb0 + c0, q0 = ka, q1 = kb, d_, m;
            d_ = ea0 + eb1 + c1; m = d_ < best; best = (d_ & m) | (best & ~m); q1 = (kb1 & m) | (q1 & ~m);
            d_ = ea1 + eb0 + c1; m = d_ < best; best = (d_ & m) | (best & ~m); q0 = (ka1 & m) | (q0 & ~m); q1 = (kb & m) | (q1 & ~m);
            d_ = ea1 + eb1 + c2; m = d_ < best; q0 = (ka1 & m) | (q0 & ~m); q1 = (kb1 & m) | (q1 & ~m);
            if (it == 2) { v4i bi = (q0 << 2) | q1; m4[2 * r] = (uint8_t)(bi[0] << 4 | bi[1]); m4[2 * r + 1] = (uint8_t)(bi[2] << 4 | bi[3]); }
            else {
                v4i w0 = __builtin_shuffle(WY, q0), w1 = __builtin_shuffle(WY, q1), wc = __builtin_shuffle(WC0, WC1, q0 + q1);
                aw += w0 + w1; aw2 += w0 * w0 + w1 * w1; awy += w0 * ya + w1 * yb;
                ac += wc; ac2 += wc * wc; acu += wc * ua; acv += wc * va;
            }
        }
        if (it == 2) break;
        { long sw = hs4(aw), n22 = hs4(aw2), S1 = hs4(awy), n12 = 8 * sw - n22, n11 = 64 * 64 - 16 * sw + n22, S0 = 8 * (long)c->sy - S1, det = n11 * n22 - n12 * n12;
          if (det) { double a = 8.0 * (double)(S0 * n22 - S1 * n12) / det, bb = 8.0 * (double)(S1 * n11 - S0 * n12) / det; t4->c[0] = iclamp((int)lrint(a), 0, 255); t4->c[1] = iclamp((int)lrint(bb), 0, 255); } }
        { long sw = hs4(ac), c22 = hs4(ac2), c12 = 8 * sw - c22, c11 = 32 * 64 - 16 * sw + c22, U1_ = hs4(acu), U0_ = 8 * (long)c->su - U1_, V1_ = hs4(acv), V0_ = 8 * (long)c->sv - V1_, det = c11 * c22 - c12 * c12;
          if (det) { t4->c[2] = iclamp((int)lrint(8.0 * (double)(U0_ * c22 - U1_ * c12) / det), 0, 255); t4->c[3] = iclamp((int)lrint(8.0 * (double)(U1_ * c11 - U0_ * c12) / det), 0, 255);
                     t4->c[4] = iclamp((int)lrint(8.0 * (double)(V0_ * c22 - V1_ * c12) / det), 0, 255); t4->c[5] = iclamp((int)lrint(8.0 * (double)(V1_ * c11 - V0_ * c12) / det), 0, 255); } }
    }
}
/* the two pixel blocks look the same on the panel (q666): nothing visible to fix */
static int glass_equal(const uint8_t *A, const uint8_t *B) {
    /* SB layout: luma at 0..63, Cb 64..95, Cr 96..127.  Chroma sample i (4x8) maps to luma pixels through the same subblock order */
    int r, x;
    for (r = 0; r < 8; r++) for (x = 0; x < 4; x++) {
        int ci = (r >> 2) * 16 + (r & 3) * 4 + x, ua = A[64 + ci] - 128, va = A[96 + ci] - 128, ub = B[64 + ci] - 128, vb = B[96 + ci] - 128;
        int sb = (r >> 2) * 2 + (x >> 1), ly = (r & 3) * 4 + (x & 1) * 2, k;
        int roa = OR_(va), goa = OG_(ua, va), boa = OB_(ua), rob = OR_(vb), gob = OG_(ub, vb), bob = OB_(ub);
        for (k = 0; k < 2; k++) {
            int ya = A[sb * 16 + ly + k], yb = B[sb * 16 + ly + k];
            if ((CL255(ya + roa) ^ CL255(yb + rob)) & 0xFC) return 0;
            if ((CL255(ya + goa) ^ CL255(yb + gob)) & 0xFC) return 0;
            if ((CL255(ya + boa) ^ CL255(yb + bob)) & 0xFC) return 0;
        }
    }
    return 1;
}
