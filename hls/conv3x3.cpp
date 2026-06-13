// conv3x3.cpp
// -----------------------------------------------------------------------------
// The same 3x3 convolution, now in C++ for Vitis HLS: the PL reads the image
// straight out of DRAM over an AXI master and writes the result back.
//
// What you see below is the NAIVE version - the loop nest a software developer
// writes first. It is correct, and that is the point: it lets us run C simulation
// and look at the synthesis report honestly. It is also where "HLS is not a free
// lunch" becomes concrete - re-reading the neighbourhood from DRAM for every
// output pixel is bandwidth-bound, and the tool cannot hit one-pixel-per-cycle.
// README.md walks through the line-buffer + window rewrite that fixes this and
// turns on the nine parallel multipliers we want.
// -----------------------------------------------------------------------------
#include "conv3x3.hpp"

void conv3x3_accel(const uint8_t *in, uint8_t *out, const int8_t *coeff,
                   int shift, int mode, int height, int width) {
    // ---- interfaces ----
    // m_axi: the PL becomes a bus master and reads/writes DRAM directly - separate
    // bundles so image reads, result writes, and the tiny kernel fetch do not fight
    // for one port.
#pragma HLS INTERFACE m_axi port=in    offset=slave bundle=gmem0 depth=2073600
#pragma HLS INTERFACE m_axi port=out   offset=slave bundle=gmem1 depth=2073600
#pragma HLS INTERFACE m_axi port=coeff offset=slave bundle=gmem2 depth=9
    // s_axilite: the control registers Python pokes (buffer addresses, the scalar
    // parameters, and start/done). All on the default 'control' bundle.
#pragma HLS INTERFACE s_axilite port=in
#pragma HLS INTERFACE s_axilite port=out
#pragma HLS INTERFACE s_axilite port=coeff
#pragma HLS INTERFACE s_axilite port=shift
#pragma HLS INTERFACE s_axilite port=mode
#pragma HLS INTERFACE s_axilite port=height
#pragma HLS INTERFACE s_axilite port=width
#pragma HLS INTERFACE s_axilite port=return

    // Pull the 9 coefficients on-chip once (cheap, and keeps the hot loop local).
    int8_t k[9];
load_coeff: for (int i = 0; i < 9; i++) {
#pragma HLS PIPELINE II=1
        k[i] = coeff[i];
    }

    // ---- the compute loops ----
    // For every output pixel, a weighted sum over its 3x3 neighbourhood, with
    // out-of-image taps treated as zero (same-size, zero-padded output).
// #region conv-loops
rows: for (int i = 0; i < height; i++) {
    cols: for (int j = 0; j < width; j++) {
#pragma HLS PIPELINE II=1
            int acc = 0;
        wy: for (int dy = -1; dy <= 1; dy++) {
            wx: for (int dx = -1; dx <= 1; dx++) {
                    int yy = i + dy;
                    int xx = j + dx;
                    uint8_t p = 0;  // zero padding outside the image
                    if (yy >= 0 && yy < height && xx >= 0 && xx < width) {
                        p = in[yy * width + xx];   // the bandwidth-hungry DRAM read
                    }
                    acc += (int)k[(dy + 1) * 3 + (dx + 1)] * (int)p;
                }
            }

            int v = acc >> shift;                 // arithmetic shift = divide by 2^shift
            if (mode && v < 0) v = -v;            // magnitude, for edge kernels
            if (v < 0) v = 0; else if (v > 255) v = 255;  // clamp to a byte
            out[i * width + j] = (uint8_t)v;
        }
    }
// #endregion conv-loops
}
