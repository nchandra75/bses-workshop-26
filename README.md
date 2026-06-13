# Digital Design Workshop: An FPGA Image Convolution Accelerator

These are notes, slides, and code for a 2-hour, demo-driven introduction to digital design on FPGAs for undergraduate students, spanning both electrical engineering and data science audiences. This workshop 
is part of Paradox 2026.

> **IMPORTANT**: This work was planned with extensive use of Claude Opus, including RTL and HLS sources,
Python code, and slides.  I have made every effort to review the code examples in detail, 
and am fairly confident that they do what is advertised.  On occasion, you may come
across inconsistencies due to changes in the planning process midway through, but I expect 
the final version to be reasonably coherent.

> Needless to say, any errors of omission or commission that still persist in the code or slides
are my responsibility as author.  I would appreciate it if you let me know of any issues
you find so I can fix them and leave the notes here for future reference.

> -- Nitin Chandrachoodan, IIT Madras, June 2026

The whole workshop is anchored to a single design that grows in complexity: a
**3x3 image convolution accelerator** on the PYNQ-Z2 (Xilinx Zynq-7020). A 3x3
convolution is the operation at the heart of every convolutional neural network -
a weighted sum over each pixel's neighbourhood - so it is both genuinely
compute-intensive (nine multiply-accumulates per pixel) and immediately meaningful
to the data-science half of the room: *this is one conv layer, in silicon.* We take
that one operation and **make it faster and faster, rung by rung**, each step fixing
the bottleneck the last one exposed - and keep a single **roofline** picture showing
how far each rung is from what the hardware can actually do.

## The narrative arc (2 hours)

A ladder of implementations of the same convolution, built as a series of short
Jupyter notebooks ([python/notebooks/](python/notebooks/)) that build on each other.
All share one measurement harness and one combined bitstream; each notebook activates
only the backend it discusses.

| # | Rung | Notebook | Lesson |
|---|------|----------|--------|
| 1 | Python loops | `01_python_loops` | the problem; the memory wall; measuring honestly (warmup, averaging) |
| 2 | NumPy | `02_numpy` | vectorise; most "CPU vs FPGA" gaps are good vs bad code |
| 3 | RTL on the FPGA | `03_rtl_fpga` | LUTs/DSPs; nine multipliers at once, but starved by per-pixel MMIO |
| 4 | HLS naive | `04_hls_naive` | C++ to a circuit; the II wall (re-reads from DRAM) |
| 5 | Line buffers | `05_line_buffer` | read each pixel once; now memory-bandwidth bound |
| 6 | Streaming + DMA | `06_streaming` | burst + dataflow; ~40 Mpix/s, near the roof |

## Repository map

```
README.md                 This file
requirements.txt          Laptop-side Python dependencies
docs/
  instructor-setup.md     Board prep, the combined bitstream, remote access
  troubleshooting.md      Common bugs and how to debug them live
rtl/                      Rung 3 - SystemVerilog conv3x3 core + AXI-Lite wrapper + testbench
hls/                      Rungs 4-6 - Vitis HLS C++ kernels (naive, line-buffer, streaming)
python/                   The notebook series, the backend ladder, the shared bench harness
  fpga_conv/              Backends (pyloop..hls_stream), golden reference, bench.py harness
  notebooks/              01..06 ladder + 07_clock_ramp (bonus) + 99_interactive (playground)
slides/                   Slidev deck (one section per rung)
```

Each subdirectory has its own README with exact commands.

## The design contract (shared by every rung)

Everything agrees on one simple specification so the rungs line up:

- Input: a grayscale image, one byte per pixel (values 0-255).
- Kernel: nine signed coefficients, a right-`shift` (divisor), and a `mode` bit
  (0 = signed clamp, 1 = abs then clamp, for edge kernels).
- Output: a grayscale image of the **same size**, with zero-padded borders.
- Reference behaviour, bit-exact across RTL / HLS / FPGA:

  ```
  S        = sum over the 3x3 window of  coeff[k] * pixel[k]   (zero padding at edges)
  v        = S >> shift                  (arithmetic / floor shift)
  out(i,j) = clip( |v| if mode else v , 0, 255)
  ```

This means the Python software backend in [python/](python/) (`conv_reference`) is
the golden reference for both the RTL testbench and the HLS C simulation. Colour
images are handled in the Python layer by filtering each RGB channel; the hardware
stays a single grayscale datapath.

## Quick start (laptop, no board needed)

Most of the workshop can be rehearsed on a laptop. The RTL/HLS need Xilinx tools
(Vivado / Vitis HLS), but the Python layer runs anywhere - the FPGA backend
degrades gracefully to a clear "hardware not available" message.

```bash
uv venv --python 3.13
uv pip install -r requirements.txt

# Run the tests for the software convolution (the golden reference)
.venv/bin/python -m pytest python/ -q

# Launch the rung series (the software backends work on the laptop)
.venv/bin/jupyter lab python/notebooks/
```

See [python/README.md](python/README.md) for the on-board commands.

## What runs where

| Component | Authoring laptop | PYNQ-Z2 board |
|-----------|------------------|---------------|
| RTL simulation (`xsim`) | Yes (needs Vivado) | - |
| Bitstream build | Yes (needs Vivado) | - |
| HLS C-sim / synthesis | Yes (needs Vitis HLS) | - |
| Python software backends (`pyloop`, `software`) | Yes | Yes |
| Python RTL + HLS backends (pynq) | No (stub) | Yes |
| Jupyter notebooks | Yes (software rungs) | Yes (all six backends) |

The recommended deployment is to build the bitstream on the authoring machine (one
block design carries the RTL core and all three HLS accelerators), copy it to the
board, and run the notebooks on the board so students can upload images (cats work
well) and see hardware-accelerated results. Details in
[docs/instructor-setup.md](docs/instructor-setup.md).
