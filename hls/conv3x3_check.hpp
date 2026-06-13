// conv3x3_check.hpp
// -----------------------------------------------------------------------------
// Shared C testbench harness for both HLS tops (naive conv3x3_accel and
// line-buffer conv3x3_accel_fast). It holds the plain-C golden reference - the
// same zero-padded, same-size convolution the RTL testbench and the Python
// conv_reference compute - and runs a handful of kernels through whichever top is
// passed in. Each top's tb is then a one-liner (see conv3x3_tb.cpp /
// conv3x3_fast_tb.cpp). run_all() returns 0 on success so Vitis HLS marks csim PASS.
// -----------------------------------------------------------------------------
#ifndef CONV3X3_CHECK_HPP
#define CONV3X3_CHECK_HPP

#include "conv3x3.hpp"
#include <cstdio>
#include <vector>

// pointer to either top - they share the exact same signature
typedef void (*conv_fn)(const uint8_t *, uint8_t *, const int8_t *,
                        int, int, int, int);

// plain-C reference for one kernel over the whole image
static void conv_reference(const std::vector<uint8_t> &img, std::vector<uint8_t> &ref,
                           const int8_t k[9], int shift, int mode, int H, int W) {
    for (int i = 0; i < H; i++) {
        for (int j = 0; j < W; j++) {
            int acc = 0;
            for (int dy = -1; dy <= 1; dy++) {
                for (int dx = -1; dx <= 1; dx++) {
                    int yy = i + dy, xx = j + dx;
                    int p = (yy >= 0 && yy < H && xx >= 0 && xx < W) ? img[yy * W + xx] : 0;
                    acc += (int)k[(dy + 1) * 3 + (dx + 1)] * p;
                }
            }
            int v = acc >> shift;
            if (mode && v < 0) v = -v;
            if (v < 0) v = 0; else if (v > 255) v = 255;
            ref[i * W + j] = (uint8_t)v;
        }
    }
}

static int run_kernel(conv_fn fn, const char *name, const std::vector<uint8_t> &img,
                      int H, int W, const int8_t k[9], int shift, int mode) {
    std::vector<uint8_t> out(H * W, 0), ref(H * W, 0);

    fn(img.data(), out.data(), k, shift, mode, H, W);
    conv_reference(img, ref, k, shift, mode, H, W);

    int errors = 0;
    for (int n = 0; n < H * W; n++) {
        if (out[n] != ref[n]) {
            if (errors < 10)
                printf("  [%s] pixel %d (row %d col %d): got %u expected %u\n",
                       name, n, n / W, n % W, out[n], ref[n]);
            errors++;
        }
    }
    if (errors == 0)
        printf("  [%s] PASS: all %d output pixels match the reference\n", name, H * W);
    else
        printf("  [%s] FAIL: %d mismatches\n", name, errors);
    return errors;
}

// Run the standard kernel set through `fn` and report. Used by both tbs.
static int run_all(conv_fn fn) {
    const int H = 32, W = 24;

    // deterministic pseudo-random image
    std::vector<uint8_t> img(H * W);
    unsigned seed = 12345;
    for (int i = 0; i < H * W; i++) {
        seed = seed * 1103515245u + 12345u;       // simple LCG, reproducible
        img[i] = (uint8_t)((seed >> 16) & 0xFF);
    }

    const int8_t identity[9] = {0, 0, 0, 0, 1, 0, 0, 0, 0};
    const int8_t sharpen[9]  = {0, -1, 0, -1, 5, -1, 0, -1, 0};
    const int8_t blur[9]     = {1, 2, 1, 2, 4, 2, 1, 2, 1};
    const int8_t edges[9]    = {-1, -1, -1, -1, 8, -1, -1, -1, -1};

    int errors = 0;
    errors += run_kernel(fn, "identity", img, H, W, identity, 0, 0);
    errors += run_kernel(fn, "sharpen",  img, H, W, sharpen,  0, 0);
    errors += run_kernel(fn, "blur",     img, H, W, blur,     4, 0);
    errors += run_kernel(fn, "edges",    img, H, W, edges,    0, 1);

    if (errors == 0) {
        printf("==== CSIM PASSED: all kernels match the reference ====\n");
        return 0;
    }
    printf("==== CSIM FAILED: %d total mismatches ====\n", errors);
    return 1;
}

#endif // CONV3X3_CHECK_HPP
