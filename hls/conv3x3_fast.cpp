// conv3x3_fast.cpp
// -----------------------------------------------------------------------------
// The 3x3 convolution again - same contract, same bit-exact output as the naive
// conv3x3.cpp and the RTL core - but written the way an FPGA wants it. Where the
// naive kernel re-reads each pixel's neighbourhood from
// DRAM nine times (II=9, bandwidth-bound), this one streams every input pixel out
// of DRAM EXACTLY ONCE, keeps the two rows it still needs in on-chip line buffers,
// and slides a 3x3 window across them. The inner loop then pipelines at II=1: one
// finished output pixel per clock, with the nine multiplies running in parallel.
//
// The trick is "read one row ahead": to emit output row (i-1) we need input rows
// i-2, i-1, i, so we keep rows i-2 and i-1 in lb0/lb1 and read row i live. The
// loop runs one extra row and column (i in [0,height], j in [0,width]); those
// flush iterations feed zeros and emit the trailing row/column. Zero-padded
// borders fall out of the index guards, so the result matches conv_reference to
// the bit. See README.md for the before/after.
// -----------------------------------------------------------------------------
#include "conv3x3.hpp"

void conv3x3_accel_fast(const uint8_t *in, uint8_t *out, const int8_t *coeff,
                        int shift, int mode, int height, int width) {
    // ---- interfaces ----
    // Identical to the naive kernel so the two IPs are drop-in interchangeable from
    // Python: same AXI masters, same s_axilite control layout (same arg order).
#pragma HLS INTERFACE m_axi port=in    offset=slave bundle=gmem0 depth=2073600
#pragma HLS INTERFACE m_axi port=out   offset=slave bundle=gmem1 depth=2073600
#pragma HLS INTERFACE m_axi port=coeff offset=slave bundle=gmem2 depth=9
#pragma HLS INTERFACE s_axilite port=in
#pragma HLS INTERFACE s_axilite port=out
#pragma HLS INTERFACE s_axilite port=coeff
#pragma HLS INTERFACE s_axilite port=shift
#pragma HLS INTERFACE s_axilite port=mode
#pragma HLS INTERFACE s_axilite port=height
#pragma HLS INTERFACE s_axilite port=width
#pragma HLS INTERFACE s_axilite port=return

    // 9 coefficients on-chip once, fully partitioned so the 9 multiplies are parallel.
    int8_t k[9];
#pragma HLS ARRAY_PARTITION variable=k complete dim=1
load_coeff: for (int i = 0; i < 9; i++) {
#pragma HLS PIPELINE II=1
        k[i] = coeff[i];
    }

    // Two line buffers: lb0 holds row (i-2), lb1 holds row (i-1) for the current
    // read row i. One read + one write port each, so HLS maps them to BRAM on its
    // own (csynth reports the line buffers in BRAM18K) - which is exactly what we
    // want. We deliberately do NOT pin them with BIND_STORAGE impl=bram: forcing it
    // hoists the RAM module out to the top of the IP, and Vitis HLS 2021.1's
    // export_design then drops that hoisted RAM (and every other submodule) from
    // the packaged component.xml, so the Vivado synth of the IP fails with
    // "module conv3x3_accel_fast_lb0 not found". Letting HLS bind the storage keeps
    // the RAM inside the pipelined-loop submodule, which packages correctly.
    uint8_t lb0[CONV3X3_MAX_WIDTH];
    uint8_t lb1[CONV3X3_MAX_WIDTH];

    // 3x3 window of pixel values; column 2 is the freshest (current j). Fully
    // partitioned so every tap is read in the same cycle.
    uint8_t win[3][3];
#pragma HLS ARRAY_PARTITION variable=win complete dim=0

rows: for (int i = 0; i <= height; i++) {
        // clear the horizontal window history at the start of each row so the two
        // columns to the left of j=0 read as zero (left-edge zero padding).
        win[0][0] = win[0][1] = win[0][2] = 0;
        win[1][0] = win[1][1] = win[1][2] = 0;
        win[2][0] = win[2][1] = win[2][2] = 0;

    cols: for (int j = 0; j <= width; j++) {
#pragma HLS PIPELINE II=1
            // New pixel at (row i, col j). Zero outside the image: column j==width
            // is the right flush, row i==height is the bottom flush.
            uint8_t newpix = 0;
            if (i < height && j < width) newpix = in[i * width + j];

            // Build the window column for col j: top=row i-2, mid=row i-1, bot=row i.
            // Guards give top/bottom zero padding without depending on buffer init
            // (so repeated ap_start calls stay correct): row i-2 only exists at i>=2,
            // and the j==width flush column contributes zero.
            uint8_t top = (i >= 2 && j < width) ? lb0[j] : (uint8_t)0;
            uint8_t mid = (i >= 1 && j < width) ? lb1[j] : (uint8_t)0;
            uint8_t bot = newpix;

            // slide the window left, append the new column on the right
            win[0][0] = win[0][1]; win[0][1] = win[0][2]; win[0][2] = top;
            win[1][0] = win[1][1]; win[1][1] = win[1][2]; win[1][2] = mid;
            win[2][0] = win[2][1]; win[2][1] = win[2][2]; win[2][2] = bot;

            // push row i down the line buffers for this column: lb0<=lb1, lb1<=new.
            // Reuse the value already in `mid` (= old lb1[j], or 0 at i==0) instead
            // of reading lb1[j] a second time, so each buffer needs only one read
            // port and the loop keeps II=1.
            if (j < width) {
                lb0[j] = mid;
                lb1[j] = newpix;
            }

            // Emit the center pixel (i-1, j-1) once it is a real output location.
            // win[1][1] is exactly (row i-1, col j-1); off-image taps are already
            // zero in the window, so this is the zero-padded same-size convolution.
            if (i >= 1 && j >= 1) {
                int acc = 0;
            mac: for (int t = 0; t < 9; t++) {
#pragma HLS UNROLL
                    acc += (int)k[t] * (int)win[t / 3][t % 3];
                }
                int v = acc >> shift;                 // arithmetic (floor) shift
                if (mode && v < 0) v = -v;             // magnitude for edge kernels
                if (v < 0) v = 0; else if (v > 255) v = 255;  // clamp to a byte
                out[(i - 1) * width + (j - 1)] = (uint8_t)v;
            }
        }
    }
}
