# Rungs 4-6 - HLS: the same convolution in C++

The 3x3 convolution written for Vitis HLS. Same contract as the RTL and Python
versions (grayscale in, grayscale out, same-size with zero-padded borders), but now
we describe *what* to compute and let the tool build the circuit - then fix what the
tool cannot do for us. Three kernels, one per rung 4-6:

## Files

| File | What it is |
|------|------------|
| `conv3x3.hpp` | The interface and the shared contract (declares all three tops). |
| `conv3x3.cpp` | **Rung 4 - naive:** an AXI master re-reads the neighbourhood from DRAM per pixel. Bandwidth-bound on purpose (inner-loop II=9). |
| `conv3x3_fast.cpp` | **Rung 5 - line buffer:** each pixel read from DRAM once into on-chip line buffers + a sliding window. II=1, but byte-wide `m_axi` makes it memory-bound. |
| `conv3x3_stream.cpp` | **Rung 6 - streaming:** the same line-buffer compute wrapped in a Vitis `DATAFLOW` read/compute/write pipeline over FIFOs, so DRAM bursts hide behind compute. |
| `conv3x3_check.hpp` | Shared C testbench harness: the golden reference + kernel set, run through whichever top is passed in. |
| `conv3x3_tb.cpp` / `conv3x3_fast_tb.cpp` / `conv3x3_stream_tb.cpp` | Thin mains that run the harness against each top. |
| `run_hls.tcl` | csynth + export all three IPs (native); csim/cosim gated behind `-tclargs`. |
| `Makefile` | `make` (all three IPs), `make csim` (quick g++ check), `make hls-csim` (Docker). |
| `Dockerfile` / `run-in-docker.sh` | compatible userland for csim/cosim on this box. |

## Run it

```bash
cd hls
make                              # csynth + export all three IPs (what build.tcl needs)
# or: vitis_hls -f run_hls.tcl
make csim                         # quick g++ bit-exactness check, no Vitis
```

You get three synthesis reports under `build/`:

- `conv3x3_hls/sol1/syn/report/conv3x3_accel_csynth.rpt` (naive)
- `conv3x3_fast_hls/sol1/syn/report/conv3x3_accel_fast_csynth.rpt` (line buffer)
- `conv3x3_stream_hls/sol1/syn/report/conv3x3_accel_stream_csynth.rpt` (streaming)

Find the latency, the inner-loop initiation interval (II), and the LUT/FF/BRAM/DSP
usage in each. The naive `cols` loop comes out at **II=9** (memory-bound); the line
buffer and streaming loops at **II=1**. That before/after is the lesson.

### csim / cosim need Docker on this box

csynth/export run natively, but csim and cosim link a host binary, and the 2021.1
toolchain's bundled binutils can't read this machine's modern glibc. Run those in a
container with a compatible (ubuntu 20.04) userland - the toolchain is bind-mounted:

```bash
cd hls
./run-in-docker.sh                # csim + cosim + csynth + export
```

For a quick functional check without any of this, each kernel also builds with the
system compiler: `g++ -std=c++14 conv3x3.cpp conv3x3_tb.cpp && ./a.out`.

## Rung 4 -> 5: HLS is not a free lunch

The naive compute loop is the obvious thing a software developer writes - for each
output pixel, loop over the 3x3 neighbourhood and accumulate, with `PIPELINE II=1`
requested. But it re-reads up to nine pixels from DRAM for *every* output pixel
through one `m_axi` port; the tool cannot serve that in one cycle, so it stretches
the II to 9 and the design becomes memory-bandwidth bound. **The pragma is a
request, not a guarantee.**

The fix (`conv3x3_fast.cpp`) is the idea the RTL already used: stream the image
through on-chip line buffers so every pixel is read from DRAM exactly once, build
the 3x3 window from fast local memory, and `ARRAY_PARTITION` the window so all nine
taps are readable the same cycle. The csynth report shows the II drop from 9 to 1.
You spent a couple of BRAMs (the line buffers) to turn a memory-bound loop into a
one-pixel-per-cycle compute pipeline.

## Rung 5 -> 6: burst and overlap

The line-buffer kernel is II=1 in compute but still memory-bound: its byte-wide
`m_axi` ports trickle one byte per clock. `conv3x3_stream.cpp` keeps the identical
compute but wraps it in a Vitis `DATAFLOW` pipeline of three concurrent processes
over `hls::stream` FIFOs - `read_pixels` (burst read) -> `compute` (the line buffer,
touching only FIFOs) -> `write_pixels` (burst write). The image ports set
`max_read/write_burst_length=256` so the masters get close to one beat/clock from
DRAM, and the bursts hide behind compute. csynth shows all three loops II=1 with
inferred bursts, sustaining ~1 pixel/clock end to end.

## From IP to bitstream

`run_hls.tcl` exports each IP under `build/<name>/sol1/impl/ip`. You do not wire
them in by hand: [../rtl/build.tcl](../rtl) picks up all three and drops them into a
single block design alongside the hand-written RTL core, connecting the `m_axi`
ports to PS HP ports and each `s_axilite` to a PS GP port:

```bash
cd ../hls && vitis_hls -f run_hls.tcl   # export the three IPs (this step)
cd ../rtl && vivado -mode batch -source build.tcl   # combined conv3x3.bit + .hwh
```

That one bitstream carries the RTL core `conv0` plus `conv3x3_accel_0` (naive),
`conv3x3_accel_fast_0` (line buffer), and `conv3x3_accel_stream_0` (streaming). The
Python overlay finds them by those cell names. Full steps in
[../docs/instructor-setup.md](../docs/instructor-setup.md).
