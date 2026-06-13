// conv3x3.hpp
// -----------------------------------------------------------------------------
// Interface for the Vitis HLS 3x3 convolution accelerator.
// Same contract as the RTL and Python versions: grayscale 8-bit pixels in,
// grayscale 8-bit pixels out, same-size with zero-padded borders.
//   out(i,j) = clip( (mode ? |S| : S) >> shift , 0, 255),  S = sum coeff[k]*pix[k]
// -----------------------------------------------------------------------------
#ifndef CONV3X3_HPP
#define CONV3X3_HPP

#include <cstdint>

// Largest frame we size the AXI-master depth for (1080p). Only matters for
// cosim / IP packaging; csim ignores it.
constexpr int MAX_PIXELS = 1920 * 1080;

// Largest image width the line-buffer accelerator sizes its on-chip row buffers
// for. conv3x3_accel_fast keeps two rows of this many pixels in BRAM, so it only
// handles images up to this wide (height is unbounded). 2048 covers up to 2K video.
constexpr int CONV3X3_MAX_WIDTH = 2048;

// Top-level accelerator (NAIVE version - conv3x3.cpp).
//   in     : height*width bytes of grayscale pixels in DRAM (read over AXI)
//   out    : height*width bytes for the result in DRAM (written over AXI)
//   coeff  : 9 signed kernel coefficients, row-major (c0 = top-left)
//   shift  : right-shift applied to the weighted sum (the kernel divisor)
//   mode   : 0 = signed clamp to [0,255]; 1 = abs then clamp (edge kernels)
//   height : image height in pixels
//   width  : image width in pixels
void conv3x3_accel(const uint8_t *in, uint8_t *out, const int8_t *coeff,
                   int shift, int mode, int height, int width);

// Top-level accelerator (LINE-BUFFER version - conv3x3_fast.cpp). Identical
// contract and bit-exact output, but streams each input pixel from DRAM exactly
// once into two on-chip line buffers + a 3x3 sliding window, so the inner loop
// reaches II=1 (one output pixel per clock) instead of the naive kernel's II=9.
// Same argument list => same s_axilite register layout, so Python drives it with
// the same offsets, only a different IP cell name.
void conv3x3_accel_fast(const uint8_t *in, uint8_t *out, const int8_t *coeff,
                        int shift, int mode, int height, int width);

// Top-level accelerator (STREAMING version - conv3x3_stream.cpp). Same contract
// and bit-exact output again, but wraps the line-buffer compute in a DATAFLOW
// pipeline (read -> compute -> write over FIFOs) so the byte-wide DRAM traffic
// bursts and hides behind the II=1 compute. This is the kernel that actually
// SUSTAINS ~1 pixel/clock end to end, where conv3x3_accel_fast was memory-bound at
// ~10 Mpix/s. Same argument list => same s_axilite register layout, so Python
// drives it with the same offsets, only a different IP cell name.
void conv3x3_accel_stream(const uint8_t *in, uint8_t *out, const int8_t *coeff,
                          int shift, int mode, int height, int width);

#endif // CONV3X3_HPP
