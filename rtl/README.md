# Rung 3 - RTL: the convolution as a circuit

Hand-written SystemVerilog for the 3x3 convolution, plus simulation and bitstream
scripts. This is the "what does hardware description actually look like" rung - and
the compute story: nine multipliers, all firing on the same clock edge.

## Files

| File | What it is |
|------|------------|
| `conv3x3_core.sv` | The datapath: line buffers + a sliding 3x3 window + the 9-multiply MAC tree, with the output arithmetic pipelined into four stages so it meets the 100 MHz clock. |
| `conv3x3_core_unpipelined.sv` | The same core with the MAC + format done in one combinational shot. Bit-identical in simulation but misses timing by ~16 ns - the deliberate "before" for the pipelining demo. Same module name; not in any build. |
| `conv3x3_axi_lite.sv` | AXI4-Lite wrapper so the PS (Python) can load the kernel and stream pixels. |
| `tb_conv3x3_core.sv` | Self-checking testbench: streams a padded image, compares every output pixel to the software reference (sharpen, blur, edges). |
| `conv3x3.xdc` | Clock constraint (the AXI interface is internal to the block design). |
| `sim.tcl` | Run the testbench in batch (`xsim`). Optional arg picks the core file (defaults to `conv3x3_core.sv`). |
| `synth_timing.tcl` / `synth_timing.sh` | Push ONE block through out-of-context synth and report its slack. |
| `build.tcl` | Build the single combined PYNQ-Z2 bitstream (`.bit` + `.hwh`). |

## What the core computes

For every output pixel, a weighted sum of its 3x3 neighbourhood:

```
out(i,j) = clip( S >> shift , 0, 255)          # mode 0 (blur, sharpen)
out(i,j) = clip( |S >> shift| , 0, 255)        # mode 1 (edges)
where    S = sum over the 3x3 window of  coeff[k] * pixel[k]
```

This is exactly one convolutional layer's kernel - the inner loop of a CNN, in
silicon. In software the nine multiply-accumulates happen one after another; here
the nine multipliers are separate DSP blocks that all fire on the same clock edge,
producing one finished pixel per cycle.

Two ideas to look at:

1. **The MAC tree** (the `acc = ...` line): nine multiplies and an adder tree,
   combinational, all at once.
2. **The line buffers** (`lb0`, `lb1`): pixels arrive one per cycle in raster
   order, but a 3x3 window needs three rows at once, so we keep the previous two
   rows on-chip. This sliding-window-over-a-stream pattern is how almost all FPGA
   image processing works.

### Borders / padding

The datapath only ever computes *full* 3x3 windows. We get same-size, zero-padded
output by streaming a frame already padded by one pixel on every side: an HxW image
goes in as a (H+2)x(W+2) frame, and `line_width` is that padded width. Padding in
the feeder, not the datapath, keeps the hardware simple - the same way you would do
it with a DMA. The Python and HLS versions pad identically, so all match the same
golden reference.

## Register map (AXI-Lite, byte offsets)

| Offset | Name | Access | Meaning |
|--------|------|--------|---------|
| 0x00 | CTRL | W | write bit1=1 to clear the window + counters |
| 0x04 | STATUS | R | bit0 = ready (always 1 here) |
| 0x08 | LINE_WIDTH | RW | width of the padded frame being streamed (= W + 2) |
| 0x0C | SHIFT | RW | right-shift applied to the sum (the kernel divisor) |
| 0x10 | MODE | RW | bit0: 0 = signed clamp, 1 = abs then clamp (edges) |
| 0x14 | PIX_IN | W | write a pixel in data[7:0]; the write pulses `pix_valid` |
| 0x18 | OUT_DATA | R | the most recent output pixel produced |
| 0x1C | OUT_COUNT | R | number of output pixels produced since the last clear |
| 0x20..0x40 | COEF0..COEF8 | RW | kernel coefficients c0 (top-left) .. c8 (bottom-right), signed |

## Run the simulation (no board needed)

```bash
cd rtl
vivado -mode batch -source sim.tcl
```

Expect, after the per-kernel lines, `==== TEST PASSED: all kernels match the reference ====`.

## The pipelining demo: does one block meet the clock?

`synth_timing.sh` takes a single module out-of-context (no board, no AXI, no block
design), synthesises it for the PYNQ-Z2 against a 100 MHz clock, and prints the
worst slack and the slow path. The two core variants are *bit-identical in
simulation* yet land on opposite sides of the timing line:

```bash
cd rtl
vivado -mode batch -source sim.tcl -tclargs conv3x3_core_unpipelined.sv  # PASS
./synth_timing.sh conv3x3_core_unpipelined.sv     # WNS ~ -15.5 ns  VIOLATED
./synth_timing.sh conv3x3_core.sv                 # WNS ~ +3.3 ns   MET
./synth_timing.sh conv3x3_core.sv conv3x3_core 8.0   # push it: 125 MHz
```

Same function, same simulation result; only the pipelined version meets the clock.
The full report lands in `timing_<top>.<src>.rpt`. (Out-of-context synth estimates
routing, so the number is an indicator; `build.tcl` is the real sign-off.)

## Build the bitstream

`build.tcl` produces a single bitstream containing the RTL core (`conv0`) **and**
the three HLS accelerators from [../hls](../hls). Export the HLS IPs first, then
build:

```bash
cd ../hls && vitis_hls -f run_hls.tcl             # export the HLS IPs (prerequisite)
cd ../rtl
vivado -mode batch -source build.tcl              # -> build/conv3x3.bit + .hwh
```

`build.tcl` stops with a clear message if the exported HLS IPs are missing. The
resulting block design wires a GP master to the four AXI-Lite control ports
(`conv0`, `conv3x3_accel_0`, `conv3x3_accel_fast_0`, `conv3x3_accel_stream_0`) and
the nine HLS `m_axi` masters through one SmartConnect to an HP slave. No ILA is
inserted - the hardware demo is the live clock ramp from Python
(`Clocks.fclk0_mhz`). Copy the `.bit` and `.hwh` to the board as a pair (see
[../docs/instructor-setup.md](../docs/instructor-setup.md)).

## The deliberate simplification

This design feeds pixels one AXI-Lite write at a time. That is perfect for reading
the datapath back register by register, and it is honest about not being fast -
pushing a megapixel image one MMIO write at a time would crawl. The throughput
story is the HLS kernels in [../hls](../hls), which read the image straight from
DRAM over an AXI master.
