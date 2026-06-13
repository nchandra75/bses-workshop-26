# Detailed Workshop Plan

A 2-hour, demo-driven session. The guiding principle: **one operation - a 3x3 image
convolution - made faster and faster, rung by rung**, where each step fixes the
bottleneck the previous one exposed. The projector should always be showing something
run, measured, and dropped onto a single recurring picture: a **roofline** that asks
"how far are we from what the hardware can actually do?"

Audience: mixed EE and data-science undergrads. Assume they can read code and have seen
NumPy, but do not assume any prior digital-logic background.

The series is built as a stack of short Jupyter notebooks
([python/notebooks/](../python/notebooks/)), one per rung, all sharing a single
measurement harness ([python/fpga_conv/bench.py](../python/fpga_conv/bench.py)) and one
combined bitstream (which already carries all four accelerators - each notebook just
activates the backend it discusses). The slide deck ([slides/](../slides/)) mirrors the
same seven sections.

Timing summary:

| # | Rung | Notebook | Target | Hard cap |
|---|------|----------|--------|----------|
| 1 | Motivation + Python loops + measuring | `01_python_loops` | 20 min | 22 min |
| 2 | NumPy | `02_numpy` | 12 min | 15 min |
| 3 | FPGA + hand-written RTL + MMIO wall | `03_rtl_fpga` | 28 min | 32 min |
| 4 | HLS naive + the II wall | `04_hls_naive` | 18 min | 20 min |
| 5 | Line buffers (memory-bound) | `05_line_buffer` | 15 min | 18 min |
| 6 | Streaming + DMA (near the roof) | `06_streaming` | 18 min | 20 min |
| - | Bonus: clock ramp / interactive playground | `07` / `99` | flex | (flex) |

The hard caps matter more than the targets. If a rung overruns, cut depth, not the next
rung. Rungs 1-2 hook the software half of the room and install the measurement
discipline; rung 6 is the payoff. Protect those.

**Why convolution?** Nine multiply-accumulates per pixel: genuinely compute-bound, it
lights up the FPGA's DSP blocks, and it is *exactly one conv layer of a CNN* - the bridge
to the data-science audience. The circuit they watch climb the ladder is the inner loop
of every modern vision model.

**The recurring spine - the roofline.** Two ceilings no design can beat: a flat
**compute ceiling** (the fabric at 100 MHz doing one pixel/clock = 100 Mpix/s) and a
sloped **memory-bandwidth ceiling** (a design that moves more bytes per pixel hits the
DRAM wall sooner). Every rung is one dot under those ceilings; the gap is the performance
still on the table. Keep it simple on the projector - two lines and a moving dot. The
helper is `Scoreboard.roofline()` in `bench.py`; the scoreboard persists across the
notebook series (`notebooks/scoreboard.json`) so the picture grows as you climb.

---

## Rung 1 - The problem, and a slow first answer {#rung-1}

**Goal:** motivate the whole session, and install measurement discipline before any
optimisation. Material: [01_python_loops.ipynb](../python/notebooks/01_python_loops.ipynb),
slides [01-motivation](../slides/pages/01-motivation.md).

**Beat 1 - motivation (6 min).** Modern systems are buried in arithmetic - a CNN
inference is billions of MACs, and it is all the same tiny operation repeated. Our
stand-in is the 3x3 convolution. Then the back-of-the-envelope: a ~1 GHz core does ~1e9
useful ops/s; one output pixel is ~50 instructions; a megapixel image is tens of ms *if
every instruction counts*. It usually doesn't, because of the **memory wall** - a
multiply is ~1 clock, a DRAM miss is hundreds, and the naive loop re-reads each pixel up
to nine times. Plant the flag: **every rung after the first is a data-movement fix.**

**Beat 2 - the slow answer + measuring honestly (10 min).** Run the pure-Python triple
loop (`run_rung('pyloop', ...)`). It is correct and brutally slow. Use it to teach the
measurement method that every later rung reuses:

- **Warm up** - the first run pays one-time costs that are not the computation (imports,
  interpreter warm-up, buffer allocation, cold caches; later, FPGA DMA-buffer allocation).
  Throw the first runs away. `run_rung` prints the cold-vs-warm gap so the cost is visible.
- **Average, show the spread** - one run is noisy; take many, report the best, show the
  stdev. The notebook plots the per-run times with the best line.

**Beat 3 - the first dot (4 min).** `sb.roofline()` - one lonely dot far below both
ceilings. The interpreter is the bottleneck, not the hardware. That gap is what the rest
of the workshop closes.

**Transition:** the biggest, cheapest win - stop interpreting the inner loop.

---

## Rung 2 - NumPy {#rung-2}

**Goal:** the single biggest jump, and an honest reframing. Material:
[02_numpy.ipynb](../python/notebooks/02_numpy.ipynb), slides
[02-python-numpy](../slides/pages/02-python-numpy.md).

Run `run_rung('software', ...)` on a much bigger image than the loop could stomach. The
speedup is many orders of magnitude for *identical* output (it is the golden reference).
**Lesson: most of the imagined "CPU vs FPGA" gap is really good code vs bad code - beat
the easy wins first.** Then the ceiling: a CPU does a bounded number of ops/clock and
still re-reads neighbours from memory. To go faster you must do all nine multiplies at
once, every clock, and stop re-reading - something you *build*, not run.

**Honesty for the roofline:** on a laptop, NumPy can sit *above* the 100 MHz PL ceiling -
a modern laptop core is faster than our small fabric. The fair fight is **same-system**:
run the software rungs on the board's ARM cores (PS) against the accelerator (PL). When
you assemble the final roofline, do it on the board.

**Transition:** what an FPGA actually is, and our first circuit.

---

## Rung 3 - Onto the FPGA: hand-written RTL {#rung-3}

**Goal:** make "describing hardware" concrete, and expose the data-movement wall.
Material: [rtl/](../rtl/), [03_rtl_fpga.ipynb](../python/notebooks/03_rtl_fpga.ipynb),
slides [03-rtl-fpga](../slides/pages/03-rtl-fpga.md).

**Beat 1 - what's inside an FPGA (6 min).** Not a processor: LUTs (configurable truth
tables), flip-flops, DSP blocks (real multiplier silicon), BRAM. You don't write a
program that runs on it; you *describe a circuit* and the fabric becomes it. For
convolution: nine DSP multipliers into one adder tree, all on the same clock edge - no
loop over the taps, they are nine wires.

**Beat 2 - read the core (8 min).** Open [rtl/conv3x3_core.sv](../rtl/conv3x3_core.sv).
Two ideas: the **MAC tree** (`acc = ...` - nine multiplies, one edge) and the **line
buffers** (`lb0`/`lb1` - a raster *stream* becomes a 3x3 *window*; we reuse this in HLS).
Optionally simulate (`make sim` prints PASS, bit-exact vs the NumPy reference).

**Beat 3 - the data-movement wall (8 min).** Run `run_rung('rtl', ...)` on a small image
(board only). The compute is fully parallel, yet throughput is poor: this first version
is driven the simplest way - the CPU writes each pixel to a register over AXI (**MMIO**),
one transaction per pixel, and reads each result back the same way. Every pixel crosses
the bus twice under CPU control, costing far more than the nine multiplies it feeds. **The
bottleneck moved from compute to data movement.** The roofline dot sits low because we are
trickling data by hand, not because the circuit is slow.

**Beat 4 - side quest, kept minimal (6 min).** Timing: at 100 MHz every result must settle
in 10 ns; the slowest path is the **critical path**; pipelining inserts registers to split
one long hop into four short ones (trades latency for clock, throughput unchanged). Show
the slack table (one-shot -16 ns FAILS vs pipelined +3.3 ns MET, same testbench). The
honest caveat: static timing is worst-case - this board ran correct past ~150 MHz before
the AXI bus hung, so there is no clean correctness "cliff" to demo. The bonus notebook
([07_clock_ramp.ipynb](../python/notebooks/07_clock_ramp.ipynb)) ramps the clock live if
the room is engaged; full detail in [observability.md](observability.md). Do not let this
become the headline - it is a side quest now.

**Transition:** writing every wire by hand is slow. Let a tool compile C++ into the
circuit - and let the accelerator fetch its own data from DRAM.

---

## Rung 4 - HLS naive: C++ into a circuit {#rung-4}

**Goal:** raise the abstraction, and meet the II wall. Material: [hls/](../hls/) (chiefly
[hls/conv3x3.cpp](../hls/conv3x3.cpp)),
[04_hls_naive.ipynb](../python/notebooks/04_hls_naive.ipynb), slides
[04-hls-naive](../slides/pages/04-hls-naive.md).

Open the kernel: recognisably the same algorithm a software person would write, plus
pragmas. `m_axi` makes the PL a bus master reading DRAM itself (no more per-pixel MMIO);
`s_axilite` is the control registers Python pokes; `PIPELINE II=1` is the *goal*.

**The key number is II** - clocks between successive loop iterations. The naive loop
re-reads its 3x3 window from DRAM every output pixel (up to nine reads, one port), so the
tool reports **II=9**: nine clocks per pixel. Run `run_rung('hls_naive', ...)` (board
only): faster than MMIO RTL (it fetches in bulk) but still far from the ceiling, because
it moves 9 bytes read + 1 written per pixel - **low arithmetic intensity**, so the
roofline dot sits left, under the memory slope.

**Transition:** the fix is the idea the RTL already used - don't re-read.

---

## Rung 5 - Line buffers: read each pixel once {#rung-5}

**Goal:** reach II=1 in compute, and watch the bottleneck move to memory bandwidth.
Material: [hls/conv3x3_fast.cpp](../hls/conv3x3_fast.cpp),
[05_line_buffer.ipynb](../python/notebooks/05_line_buffer.ipynb), slides
[05-line-buffer](../slides/pages/05-line-buffer.md).

Keep the previous two rows in on-chip BRAM, so each new streamed pixel completes a
vertical column and every pixel is read from DRAM exactly once; with the window in
registers (nine taps, nine DSPs, same cycle), the compute loop hits **II=1**. Run
`run_rung('hls_opt', ...)`. Better - and on the roofline the dot moves right (2 bytes/pixel
instead of 10). But it is not 9x faster: the memory port is byte-wide, so even reading each
pixel once it pulls one byte per clock and must write one out - the datapath now **waits on
memory** (~10 Mpix/s). **Memory-bandwidth bound.** The bottleneck moved again; the roofline
names which wall you are against.

**Transition:** stop trickling bytes - burst, and overlap read/compute/write.

---

## Rung 6 - Streaming with DMA: near the roof {#rung-6}

**Goal:** the payoff - change *how* it talks to memory, not *what* it computes. Material:
[hls/conv3x3_stream.cpp](../hls/conv3x3_stream.cpp),
[06_streaming.ipynb](../python/notebooks/06_streaming.ipynb), slides
[06-streaming](../slides/pages/06-streaming.md).

Same line-buffer compute, wrapped in a Vitis `DATAFLOW` read/compute/write pipeline over
FIFOs: **burst** transfers (DRAM is fast in bulk, slow per byte) and **overlap** the three
stages so memory traffic hides behind compute. csynth shows all three loops II=1 with
inferred bursts. Run `run_rung('hls_stream', ...)`: **~40 Mpix/s** on the board (counting
read and write) - near what one byte-wide port and a 100 MHz fabric can sustain. The dot
sits up near the **ridge point** where the ceilings meet. To go further you would widen the
datapath (several pixels/clock) or use a wider/parallel memory interface - a different
design.

**The whole climb (5 min).** `sb.roofline()` and `sb.progress()` with every rung. The
takeaways: beat the easy wins first; hardware wins on parallelism *only if you can feed
it*; every rung after the first was a data-movement fix; the bottleneck moves, and the
roofline tells you which wall you are against.

**Close the loop to the CNN:** the `edges` kernel is a fixed filter; a CNN *learns* its
kernels, but the hardware operation is identical - this accelerator is one conv layer.

---

## Bonus / playground {#bonus}

Use if time and energy allow.

- **[07_clock_ramp.ipynb](../python/notebooks/07_clock_ramp.ipynb)** - the clock-is-the-
  speed side quest (latency falls as ~1/f; correctness edge is fuzzy on warm silicon).
- **[99_interactive.ipynb](../python/notebooks/99_interactive.ipynb)** - upload your own
  photo, pick a kernel and a backend, watch the latency change. If Jupyter is hosted on a
  public URL, students run it on their own machines. This single interaction does more for
  engagement than any slide.

Debugging reference (what goes wrong, and why) is in
[troubleshooting.md](troubleshooting.md): wrong AXI address, off-by-one window indexing, a
coefficient sign error, the wrong shift/border convention, forgetting to flush the DRAM
cache before the PL reads.

---

## Pre-flight checklist (do this the day before)

- [ ] Single combined bitstream (`.bit` + `.hwh`) built and copied to the board - it
      carries the RTL core and all three HLS accelerators. See
      [instructor-setup.md](instructor-setup.md).
- [ ] Board reachable over the network; reservation/queue system tested.
- [ ] Each notebook runs on the board top-to-bottom; the hardware rungs return bit-exact
      output and the scoreboard/roofline assembles. Capture the real numbers (especially
      the ~40 Mpix/s streaming point) to pin the roofline ceiling constants.
- [ ] `make test` passes (31 tests) and `make sim` prints PASS on your machine.
- [ ] HLS synthesis reports open and you know where II and resource numbers are
      (naive II=9 vs line-buffer/streaming II=1).
- [ ] Backup plots/screenshots: the assembled roofline, the per-run timing plot, a working
      notebook run - in case a board wedges.
- [ ] One large test image and a couple of fun ones (a cat, a high-contrast scene) ready
      to upload in the playground.
- [ ] The roofline on a slide you can jump back to from any rung.
