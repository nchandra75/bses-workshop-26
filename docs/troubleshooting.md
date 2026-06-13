# Troubleshooting and Debugging

A reference for when something breaks during prep, and a reminder that hardware work
is mostly debugging - and that the bug is usually at a boundary.

## The five classics

### 1. Wrong AXI address

Symptom: reads return 0 or garbage, writes seem to do nothing.

Cause: the offset you poke from Python does not match the register map in the RTL,
or the base address PYNQ assigned differs from what you assumed.

Fix: cross-check the raw offsets. For the RTL core, against the register map in
[../rtl/README.md](../rtl/README.md); for the HLS IPs, against the
`s_axi_control` map in the generated `.hwh` (or `xconv3x3_accel_hw.h`). Note: the
backends deliberately use **raw MMIO**, not pynq's `register_map`, because for these
HLS IPs `register_map` recurses to a stack overflow on the board.

### 2. Off-by-one or sign error in the window / kernel

Symptom: the output is shifted by a pixel, mirrored, or a sharpen looks like a blur.

Cause: the 3x3 window taps mapped to the wrong coefficients (a transpose or flip),
or a coefficient's sign got lost (treating the signed `int8` as unsigned).

Fix: the golden reference is `conv_reference` in
[../python/fpga_conv/core.py](../python/fpga_conv/core.py). Compare any
implementation against it element-by-element on a small image; the RTL testbench and
the HLS C-sim both do this. If they pass and the hardware disagrees, the bug is in
the plumbing (cache flush, address, shift/border convention), not the arithmetic.

### 3. Reading before done

Symptom: the output image is partial - the last rows are stale or zero.

Cause: reading the result before the accelerator has finished (not waiting on the
done/idle bit), or in HLS a pipeline whose final iterations have not drained.

Fix: always poll the done bit before reading the result (the
`while not (mmio.read(CTRL) & AP_DONE): pass` style wait the backends use).

### 4. Forgetting to flush the DRAM cache

Symptom: the FPGA reads stale image data, or Python reads a stale result - the
output is "one run behind" or random.

Cause: the ARM cores cache DRAM. If Python writes the image/kernel and the cache is
not flushed, the PL (reading DRAM directly) sees old bytes. Same in reverse for the
result the PL writes.

Fix: use `pynq.allocate` buffers; call `.flush()` after writing the input and
coefficients, and `.invalidate()` before reading the output. The FPGA backend in
[../python/fpga_conv/backends.py](../python/fpga_conv/backends.py) does this; the
comments mark where and why.

### 5. The .hwh does not match the .bit

Symptom: `Overlay(...)` loads but the IP is missing, has the wrong name, or the
register map is wrong.

Cause: the `.bit` and `.hwh` came from different builds.

Fix: always copy the two files as a pair, generated from the same Vivado run.

## A convolution-specific gotcha: borders and the shift

Symptom: the interior of the image is correct but a one-pixel frame around the edge
is wrong, or every value is half/double what you expect.

Cause: the implementations must agree on two conventions - zero-padded borders
(same-size output) and an *arithmetic* right-shift by `shift` (the divisor), with
the optional magnitude (`mode`) applied after the shift. Mix a floor-shift with a
truncating divide, or pad differently, and only the borders or the scale disagree.

Fix: all follow `conv_reference`'s exact arithmetic. The RTL streams a pre-padded
frame; HLS and Python pad by index checks. Verify on a constant image (a flat region
has a zero Laplacian in the interior but a non-zero border - that is correct).

## A debugging mindset to hand the students

The bug is almost always at a boundary, not in the arithmetic:

- algorithm vs. golden reference (the simulator / C-sim catches this),
- RTL vs. AXI plumbing (the RTL backend's OUT_DATA/OUT_COUNT read-back catches this),
- PS software vs. PL hardware (cache flush, addresses, done bit).

So bisect by boundary: does it pass in simulation? in C-sim? on hardware (read the
RTL core's registers back from Python)? from the HLS path? The first boundary that
fails is where the bug lives. That transferable skill is worth more than any single
fix above.
