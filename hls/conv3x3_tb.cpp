// conv3x3_tb.cpp
// -----------------------------------------------------------------------------
// C testbench for the NAIVE HLS convolution (conv3x3_accel). The reference and
// the kernel set live in conv3x3_check.hpp, shared with the line-buffer tb so the
// two tops are checked against the identical golden model.
// -----------------------------------------------------------------------------
#include "conv3x3_check.hpp"

int main() {
    return run_all(conv3x3_accel);
}
