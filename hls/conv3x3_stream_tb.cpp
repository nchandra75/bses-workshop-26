// conv3x3_stream_tb.cpp
// -----------------------------------------------------------------------------
// C testbench for the STREAMING HLS convolution (conv3x3_accel_stream). Uses the
// same golden reference and kernel set as the other two HLS tops
// (conv3x3_check.hpp), so a PASS here means the streaming kernel is bit-exact with
// the naive kernel, the line-buffer kernel, the RTL core and the Python reference.
// -----------------------------------------------------------------------------
#include "conv3x3_check.hpp"

int main() {
    return run_all(conv3x3_accel_stream);
}
