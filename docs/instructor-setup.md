# Instructor Setup Guide

What to prepare before the workshop. Budget half a day the first time, mostly
waiting on synthesis.

## Hardware and software

- Board: PYNQ-Z2 (Xilinx Zynq-7020, part `xc7z020clg400-1`).
- Board image: the official PYNQ SD image (v3.0+), which ships Python, Jupyter, and
  the `pynq` package.
- Authoring machine: Vivado and Vitis HLS 2021.1. The tcl scripts target this
  version; on a different one, re-check the part name, the HLS IP VLNV, and the
  bd-automation property names.
- Network: the board on a network you (and optionally the students) can reach.

## One bitstream, four accelerators

A single block design holds everything the workshop runs, so one `.bit`/`.hwh` pair
drives every rung:

- `conv0` - the hand-written RTL core (`conv3x3_axi_lite`), AXI-Lite only, fed one
  pixel per MMIO write. The legible path students read and drive (rung 3).
- `conv3x3_accel_0` - the naive Vitis HLS accelerator (rung 4).
- `conv3x3_accel_fast_0` - the line-buffer HLS accelerator (rung 5).
- `conv3x3_accel_stream_0` - the streaming (dataflow+burst) HLS accelerator (rung 6).

Which one runs is chosen from Python; all four are always present. Build it in two
steps ahead of the session (or just run `make` at the repo root, which does both).

### Step 1 - export the HLS IPs

```bash
cd hls
vitis_hls -f run_hls.tcl
```

This runs C synthesis (producing the reports you show in rungs 4-6) and exports the
three IPs under `hls/build/*/sol1/impl/ip`, where `build.tcl` reads them from.

C simulation and cosim are skipped here because the 2021.1 toolchain can't link a
testbench against this box's modern glibc. If you want them, run `./run-in-docker.sh`
(a compatible ubuntu-20.04 userland with the toolchain bind-mounted). The exported
IP is identical either way, so the native run is enough to build the bitstream.

### Step 2 - build the combined bitstream

```bash
cd rtl
vivado -mode batch -source build.tcl                 # -> build/conv3x3.{bit,hwh}
```

`build.tcl` creates the project, adds the RTL sources and the three exported HLS
IPs, wires the four AXI-Lite control ports to a GP master and the nine HLS `m_axi`
masters through one SmartConnect to an HP slave, assigns addresses, and runs
synthesis and implementation. The PS is configured part-only (no board preset) -
PYNQ sets up the PS at boot. PYNQ needs the matching `.hwh` next to the `.bit` to
auto-generate the driver.

There is no embedded ILA - the hardware demo is the live clock ramp
(`Clocks.fclk0_mhz` from Python), which needs no JTAG or Vivado GUI, so it works on
remote IP-only boards.

> Timing note: at 100 MHz the four-accelerator build is marginally over timing
> (WNS ~ -0.3 ns), so the board's 62.5 MHz boot clock is the safe, bit-exact
> operating point. Raise it live with the clock-ramp notebook to find the
> correctness cliff.

## Copy to the board

Bitstreams are git-ignored (large, board-specific). Copy the pair and the Python
layer over:

```bash
scp rtl/build/conv3x3.bit rtl/build/conv3x3.hwh xilinx@<board-ip>:~/workshop/
scp -r python xilinx@<board-ip>:~/workshop/
```

Default PYNQ credentials are `xilinx` / `xilinx`; change them on a shared network.
On the board, add the plotting/widget deps once and point the notebooks at the
bitstream:

```bash
ssh xilinx@<board-ip>
sudo pip3 install matplotlib ipywidgets
# the notebooks set BIT_PATH in a config cell; CONV3X3_BIT is a fallback for overlay_demo.py
```

Open the `python/notebooks/` series in the board's JupyterLab and run each rung top
to bottom, or run `python3 overlay_demo.py cat.jpg edges` for the bare-API script.

## Remote access for the live demos

The clock ramp and all the rungs run entirely in the notebook on the board, so
there is nothing extra to set up. To let students reach it from their own devices,
put the board on the same LAN and share its JupyterLab IP:port (or a Tailscale
address). Bound the clock sweep - a too-high `fclk0` can corrupt a DMA and need an
overlay reload (worst case, reboot).

## Day-before smoke test

- Restart the Jupyter kernel after copying new Python/bitstream - a live kernel
  keeps the old module and overlay.
- Run each notebook top to bottom; confirm the hardware rungs return bit-exact
  output and the scoreboard/roofline assembles.
- The two things most likely to bite: a `.hwh` that does not match its `.bit`
  (regenerate together), and forgetting to flush the allocated buffer before the PL
  reads it (the FPGA backend handles this; see the code comments). More in
  [troubleshooting.md](troubleshooting.md).
