// conv3x3_fast_tb.cpp
// -----------------------------------------------------------------------------
// C testbench for the LINE-BUFFER HLS convolution (conv3x3_accel_fast). Uses the
// same golden reference and kernel set as the naive tb (conv3x3_check.hpp), so a
// PASS here means the fast kernel is bit-exact with the naive one, the RTL core,
// and the Python reference.
// -----------------------------------------------------------------------------
#include "conv3x3_check.hpp"

int main() {
    return run_all(conv3x3_accel_fast);
}
