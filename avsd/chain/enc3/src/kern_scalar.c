/* rnv2enc scalar reference kernels.  Every NEON kernel in kern_neon.c must match these bit for bit
 * (checked by `make test` -> test_kernels). */
#include "kern.h"
#include "csc_common.h"
#include <string.h>
#include <stdlib.h>

int32_t RNV2_LSU[6], RNV2_LSV[6];

void rnv2_csc_init(void) {
    /* least squares [y0 y1 u v] from [rgb0 rgb1] for the BT.601 full-range YCbCr->RGB matrix (as rnv2.py _P) */
    static const double M[3][3] = {{1, 0, 1.402}, {1, -0.344136, -0.714136}, {1, 1.772, 0}};
    double A[6][4] = {{0}}, N[4][8], P[4][6];
    int i, j, k;
    for (i = 0; i < 3; i++) {
        A[i][0] = 1; A[3 + i][1] = 1;
        A[i][2] = A[3 + i][2] = M[i][1]; A[i][3] = A[3 + i][3] = M[i][2];
    }
    for (i = 0; i < 4; i++) for (j = 0; j < 8; j++) {
        if (j < 4) { double s = 0; for (k = 0; k < 6; k++) s += A[k][i] * A[k][j]; N[i][j] = s; }
        else N[i][j] = (j - 4 == i);
    }
    for (i = 0; i < 4; i++) { /* Gauss-Jordan (A^T A is SPD, no pivoting needed) */
        double d = N[i][i];
        for (j = 0; j < 8; j++) N[i][j] /= d;
        for (k = 0; k < 4; k++) if (k != i) { double f = N[k][i]; for (j = 0; j < 8; j++) N[k][j] -= f * N[i][j]; }
    }
    for (i = 0; i < 4; i++) for (j = 0; j < 6; j++) { double s = 0; for (k = 0; k < 4; k++) s += N[i][4 + k] * A[j][k]; P[i][j] = s; }
    for (j = 0; j < 6; j++) {
        RNV2_LSU[j] = (int32_t)(P[2][j] * 65536.0 + (P[2][j] >= 0 ? 0.5 : -0.5));
        RNV2_LSV[j] = (int32_t)(P[3][j] * 65536.0 + (P[3][j] >= 0 ? 0.5 : -0.5));
    }
}

/* ------------------------------------------------------------------ glass CSC */
static inline int perr(int y, int oR, int oG, int oB, int tR, int tG, int tB) {
    int r = Q6(CL255(y + oR)) - tR, g = Q6(CL255(y + oG)) - tG, b = Q6(CL255(y + oB)) - tB;
    return r * r + g * g + b * b;
}

static void csc_glass_c(const uint8_t *rgb, int npairs, uint8_t *Y, uint8_t *U, uint8_t *V) {
    int p;
    for (p = 0; p < npairs; p++, rgb += 6) {
        int r0 = rgb[0], g0 = rgb[1], b0 = rgb[2], r1 = rgb[3], g1 = rgb[4], b1 = rgb[5];
        int t0r = Q6(r0), t0g = Q6(g0), t0b = Q6(b0), t1r = Q6(r1), t1g = Q6(g1), t1b = Q6(b1);
        int S0 = r0 + g0 + b0, S1 = r1 + g1 + b1;
        int32_t cb0 = CBF(r0, g0, b0), cb1 = CBF(r1, g1, b1), cr0 = CRF(r0, g0, b0), cr1 = CRF(r1, g1, b1);
        int cu[4], cv[4], c, bu = 0, bv = 0, by0 = 0, by1 = 0, be = 0x7FFFFFFF, d;
        int32_t lu = RNV2_LSU[0] * r0 + RNV2_LSU[1] * g0 + RNV2_LSU[2] * b0 + RNV2_LSU[3] * r1 + RNV2_LSU[4] * g1 + RNV2_LSU[5] * b1;
        int32_t lv = RNV2_LSV[0] * r0 + RNV2_LSV[1] * g0 + RNV2_LSV[2] * b0 + RNV2_LSV[3] * r1 + RNV2_LSV[4] * g1 + RNV2_LSV[5] * b1;
        cu[0] = CL255((lu + (128 << 16) + 32768) >> 16); cv[0] = CL255((lv + (128 << 16) + 32768) >> 16);
        cu[1] = CL255((cb0 + cb1 + (256 << 16) + 65536) >> 17); cv[1] = CL255((cr0 + cr1 + (256 << 16) + 65536) >> 17);
        cu[2] = CL255((cb0 + (128 << 16) + 32768) >> 16); cv[2] = CL255((cr0 + (128 << 16) + 32768) >> 16);
        cu[3] = CL255((cb1 + (128 << 16) + 32768) >> 16); cv[3] = CL255((cr1 + (128 << 16) + 32768) >> 16);
        for (c = 0; c < 4; c++) {
            int uu = cu[c] - 128, vv = cv[c] - 128;
            int oR = OR_(vv), oG = OG_(uu, vv), oB = OB_(uu);
            int32_t so = SOFF(uu, vv);
            int y0 = YFROM(S0, so), y1 = YFROM(S1, so);
            int e = perr(y0, oR, oG, oB, t0r, t0g, t0b) + perr(y1, oR, oG, oB, t1r, t1g, t1b);
            if (e < be) { be = e; bu = cu[c]; bv = cv[c]; by0 = y0; by1 = y1; }
        }
        {
            int uu = bu - 128, vv = bv - 128, oR = OR_(vv), oG = OG_(uu, vv), oB = OB_(uu);
            int e0 = perr(by0, oR, oG, oB, t0r, t0g, t0b), e1 = perr(by1, oR, oG, oB, t1r, t1g, t1b);
            int n0 = by0, n1 = by1;
            for (d = -4; d <= 4; d += 2) {
                int y, e;
                if (!d) continue;
                y = CL255(by0 + d); e = perr(y, oR, oG, oB, t0r, t0g, t0b); if (e < e0) { e0 = e; n0 = y; }
                y = CL255(by1 + d); e = perr(y, oR, oG, oB, t1r, t1g, t1b); if (e < e1) { e1 = e; n1 = y; }
            }
            Y[2 * p] = (uint8_t)n0; Y[2 * p + 1] = (uint8_t)n1; U[p] = (uint8_t)bu; V[p] = (uint8_t)bv;
        }
    }
}

/* ------------------------------------------------------------------ SAD / distortion */
static uint32_t sad8x8_c(const uint8_t *a, int as, const uint8_t *b, int bs) {
    uint32_t s = 0; int y, x;
    for (y = 0; y < 8; y++, a += as, b += bs) for (x = 0; x < 8; x++) s += (uint32_t)abs(a[x] - b[x]);
    return s;
}

static void pd8_c(const uint8_t *s, const uint8_t *r, int kappa16, int thr, uint32_t out[8]) {
    int sb, k;
    for (sb = 0; sb < 8; sb++) {
        uint32_t acc = 0;
        for (k = 0; k < 16; k++) {
            int a = abs(s[16 * sb + k] - r[16 * sb + k]), m = a > thr ? a - thr : 0;
            acc += (uint32_t)(16 * a * a) + (uint32_t)(kappa16 * m * m);
        }
        out[sb] = acc;
    }
}

/* ------------------------------------------------------------------ WHT */
static void fwd8_c(const uint8_t *s, const uint8_t *p, int16_t *T) {
    int sb, i;
    for (sb = 0; sb < 8; sb++, s += 16, p += 16, T += 16) {
        int t[16];
        for (i = 0; i < 4; i++) { /* columns: H @ X */
            int c0 = s[i] - p[i], c1 = s[4 + i] - p[4 + i], c2 = s[8 + i] - p[8 + i], c3 = s[12 + i] - p[12 + i];
            int s0 = c0 + c1, s1 = c0 - c1, t0 = c2 + c3, t1 = c2 - c3;
            t[i] = s0 + t0; t[4 + i] = s0 - t0; t[8 + i] = s1 - t1; t[12 + i] = s1 + t1;
        }
        for (i = 0; i < 4; i++) { /* rows: (.) @ H */
            int *q = t + 4 * i;
            int s0 = q[0] + q[1], s1 = q[0] - q[1], t0 = q[2] + q[3], t1 = q[2] - q[3];
            T[4 * i + 0] = (int16_t)(s0 + t0); T[4 * i + 1] = (int16_t)(s0 - t0);
            T[4 * i + 2] = (int16_t)(s1 - t1); T[4 * i + 3] = (int16_t)(s1 + t1);
        }
    }
}

static int quant8_c(const int16_t *T, uint32_t A, uint32_t B, int S, int16_t *L) {
    int sb, k, mask = 0;
    for (sb = 0; sb < 8; sb++) {
        int nz = 0;
        for (k = 0; k < 16; k++) {
            int v = T[16 * sb + k]; uint32_t a = (uint32_t)(v < 0 ? -v : v), l = (a * A + B) >> S;
            if (l > 2047) l = 2047;
            L[16 * sb + k] = (int16_t)(v < 0 ? -(int)l : (int)l); nz |= (int)l;
        }
        if (nz) mask |= 1 << sb;
    }
    return mask;
}

static void iwht_c(const int32_t *c, int32_t *o) { /* identical to rnv2dec.c iwht4 */
    int32_t t[16]; int i;
    for (i = 0; i < 4; i++) {
        int32_t s0 = c[i] + c[4 + i], s1 = c[i] - c[4 + i], t0 = c[8 + i] + c[12 + i], t1 = c[8 + i] - c[12 + i];
        t[i] = s0 + t0; t[4 + i] = s0 - t0; t[8 + i] = s1 - t1; t[12 + i] = s1 + t1;
    }
    for (i = 0; i < 4; i++) {
        int32_t *q = t + 4 * i;
        int32_t s0 = q[0] + q[1], s1 = q[0] - q[1], t0 = q[2] + q[3], t1 = q[2] - q[3];
        o[4 * i + 0] = (s0 + t0 + 2) >> 2; o[4 * i + 1] = (s0 - t0 + 2) >> 2;
        o[4 * i + 2] = (s1 - t1 + 2) >> 2; o[4 * i + 3] = (s1 + t1 + 2) >> 2;
    }
}

static void addclamp_c(const uint8_t *p, const int32_t *R, int mask, uint8_t *rec) {
    int sb, k;
    for (sb = 0; sb < 8; sb++, p += 16, R += 16, rec += 16) {
        if (mask & (1 << sb)) for (k = 0; k < 16; k++) { int v = p[k] + R[k]; rec[k] = (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v); }
        else memcpy(rec, p, 16);
    }
}

/* ------------------------------------------------------------------ half-pel planes, projections */
static void halfpel_row_c(const uint8_t *a, const uint8_t *b, int w, uint8_t *h, uint8_t *v, uint8_t *hv) {
    int x;
    for (x = 0; x < w; x++) {
        int ha = x < w - 1 ? (a[x] + a[x + 1] + 1) >> 1 : a[x];
        int hb = x < w - 1 ? (b[x] + b[x + 1] + 1) >> 1 : b[x];
        h[x] = (uint8_t)ha; v[x] = (uint8_t)((a[x] + b[x] + 1) >> 1); hv[x] = (uint8_t)((ha + hb + 1) >> 1);
    }
}

static void proj_rows_c(const uint8_t *p, int stride, int w, int h, int sw, uint32_t *rows, uint32_t *cols) {
    int y, x, nsx = w / sw;
    for (y = 0; y < h; y++, p += stride) {
        int k;
        for (k = 0; k < nsx; k++) {
            uint32_t s = 0;
            for (x = k * sw; x < (k + 1) * sw; x++) s += p[x];
            rows[y * nsx + k] += s;
        }
        for (x = 0; x < w; x++) cols[x] += p[x];
    }
}

const rnv2_kern rnv2_kern_scalar = {"scalar", csc_glass_c, sad8x8_c, pd8_c, fwd8_c, quant8_c, iwht_c, addclamp_c, halfpel_row_c, proj_rows_c};
