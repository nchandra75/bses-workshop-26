// conv3x3_stream.cpp
// -----------------------------------------------------------------------------
// The 3x3 convolution a THIRD time - same contract, same bit-exact output as the
// naive conv3x3.cpp, the line-buffer conv3x3_fast.cpp and the RTL core - but now
// fixing the bottleneck the line-buffer kernel left behind. conv3x3_accel_fast
// reaches II=1 in COMPUTE (one output pixel per clock), yet on the board it only
// sustains ~10 Mpix/s, an order of magnitude under that 100 Mpix/s ceiling. The
// reason is memory, not maths: its `in[]`/`out[]` are byte-wide AXI masters poked
// one element at a time, so every pixel pays the full DRAM round-trip latency with
// no burst, and the II=1 pipeline starves waiting for DRAM.
//
// This version keeps the exact same line-buffer compute (so the result is bit-
// identical) but wraps it in a classic Vitis DATAFLOW pipeline of three concurrent
// processes connected by FIFOs:
//
//     read_pixels  --pix-->  compute (line buffer, II=1)  --res-->  write_pixels
//
//   * read_pixels  streams the input from DRAM in raster order. A plain sequential
//     m_axi read in a pipelined loop, which Vitis turns into long INCR bursts, so
//     the latency is paid once per burst instead of once per pixel.
//   * compute      is conv3x3_accel_fast's inner loop verbatim, but it gets its
//     pixels from the `pix` FIFO and pushes results to the `res` FIFO instead of
//     touching DRAM - so it never stalls on memory.
//   * write_pixels drains `res` back to DRAM, again as bursts.
//
// Because the three run concurrently (DATAFLOW), the memory traffic hides behind
// the compute, and the whole thing sustains ~1 pixel/clock end to end - the
// throughput the line-buffer kernel promised. Same s_axilite layout as the other
// two IPs (same arg order), so Python drives it with the same register offsets,
// only a different IP cell name. See README.md / docs for the before/after.
// -----------------------------------------------------------------------------
#include "conv3x3.hpp"
#include <hls_stream.h>

// ---- stage 1: stream the input image out of DRAM in raster order ----
// Sequential m_axi reads in a II=1 pipeline; Vitis HLS infers a burst, so DRAM
// latency is amortised across the whole row instead of paid per pixel.
static void read_pixels(const uint8_t *in, hls::stream<uint8_t> &pix,
                        int height, int width) {
    int n = height * width;
read: for (int i = 0; i < n; i++) {
#pragma HLS PIPELINE II=1
        pix.write(in[i]);
    }
}

// ---- stage 3: drain the result FIFO back to DRAM, again as bursts ----
static void write_pixels(uint8_t *out, hls::stream<uint8_t> &res,
                         int height, int width) {
    int n = height * width;
write: for (int i = 0; i < n; i++) {
#pragma HLS PIPELINE II=1
        out[i] = res.read();
    }
}

// ---- stage 2: the line-buffer convolution, fed by FIFOs (no DRAM here) ----
// This is conv3x3_accel_fast's body unchanged except that `newpix` comes from the
// `pix` stream and each finished pixel is written to the `res` stream, so the
// arithmetic - and therefore the output - is bit-identical to all the other paths.
static void compute(hls::stream<uint8_t> &pix, hls::stream<uint8_t> &res,
                    const int8_t *coeff, int shift, int mode,
                    int height, int width) {
    int8_t k[9];
#pragma HLS ARRAY_PARTITION variable=k complete dim=1
load_coeff: for (int i = 0; i < 9; i++) {
#pragma HLS PIPELINE II=1
        k[i] = coeff[i];
    }

    uint8_t lb0[CONV3X3_MAX_WIDTH];   // row i-2
    uint8_t lb1[CONV3X3_MAX_WIDTH];   // row i-1
    uint8_t win[3][3];
#pragma HLS ARRAY_PARTITION variable=win complete dim=0

rows: for (int i = 0; i <= height; i++) {
        win[0][0] = win[0][1] = win[0][2] = 0;
        win[1][0] = win[1][1] = win[1][2] = 0;
        win[2][0] = win[2][1] = win[2][2] = 0;

    cols: for (int j = 0; j <= width; j++) {
#pragma HLS PIPELINE II=1
            // pull the next input pixel from the FIFO (zero outside the image: the
            // j==width / i==height flush iterations contribute nothing to consume)
            uint8_t newpix = 0;
            if (i < height && j < width) newpix = pix.read();

            uint8_t top = (i >= 2 && j < width) ? lb0[j] : (uint8_t)0;
            uint8_t mid = (i >= 1 && j < width) ? lb1[j] : (uint8_t)0;
            uint8_t bot = newpix;

            win[0][0] = win[0][1]; win[0][1] = win[0][2]; win[0][2] = top;
            win[1][0] = win[1][1]; win[1][1] = win[1][2]; win[1][2] = mid;
            win[2][0] = win[2][1]; win[2][1] = win[2][2]; win[2][2] = bot;

            if (j < width) {
                lb0[j] = mid;
                lb1[j] = newpix;
            }

            if (i >= 1 && j >= 1) {
                int acc = 0;
            mac: for (int t = 0; t < 9; t++) {
#pragma HLS UNROLL
                    acc += (int)k[t] * (int)win[t / 3][t % 3];
                }
                int v = acc >> shift;                 // arithmetic (floor) shift
                if (mode && v < 0) v = -v;             // magnitude for edge kernels
                if (v < 0) v = 0; else if (v > 255) v = 255;  // clamp to a byte
                res.write((uint8_t)v);
            }
        }
    }
}

void conv3x3_accel_stream(const uint8_t *in, uint8_t *out, const int8_t *coeff,
                          int shift, int mode, int height, int width) {
    // ---- interfaces ----
    // Identical to the naive and line-buffer kernels so the three IPs are drop-in
    // interchangeable from Python: same AXI masters, same s_axilite control layout.
// max_read/write_burst_length=256 (the default is only 16): longer AXI bursts mean
// far fewer address phases, so the byte-wide image ports get close to one beat per
// clock from DRAM - which is what lets the dataflow pipeline actually sustain II=1.
#pragma HLS INTERFACE m_axi port=in    offset=slave bundle=gmem0 depth=2073600 \
        max_read_burst_length=256  num_read_outstanding=32
#pragma HLS INTERFACE m_axi port=out   offset=slave bundle=gmem1 depth=2073600 \
        max_write_burst_length=256 num_write_outstanding=32
#pragma HLS INTERFACE m_axi port=coeff offset=slave bundle=gmem2 depth=9
#pragma HLS INTERFACE s_axilite port=in
#pragma HLS INTERFACE s_axilite port=out
#pragma HLS INTERFACE s_axilite port=coeff
#pragma HLS INTERFACE s_axilite port=shift
#pragma HLS INTERFACE s_axilite port=mode
#pragma HLS INTERFACE s_axilite port=height
#pragma HLS INTERFACE s_axilite port=width
#pragma HLS INTERFACE s_axilite port=return

#pragma HLS DATAFLOW
    hls::stream<uint8_t> pix("pix");
    hls::stream<uint8_t> res("res");
#pragma HLS STREAM variable=pix depth=64
#pragma HLS STREAM variable=res depth=64

    read_pixels(in, pix, height, width);
    compute(pix, res, coeff, shift, mode, height, width);
    write_pixels(out, res, height, width);
}
