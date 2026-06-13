# Python: driving the convolution

The data-science half of the workshop, and the glue that ties the rungs together.
Everything here runs on a laptop with the software backends; the hardware backends
switch to the real board with no code change.

## Files

| File | What it is |
|------|------------|
| `fpga_conv/core.py` | The golden reference (`conv_reference`), the `Kernel` type, the built-in `KERNELS`, and the image helpers. |
| `fpga_conv/backends.py` | The `Backend` interface and the backend ladder (see below). |
| `fpga_conv/bench.py` | The shared measurement + roofline harness: `time_backend` (warmup/averaging), `Scoreboard`, `roofline`, `run_rung`. Every notebook imports this. |
| `notebooks/` | The `01..06` rung series + `07_clock_ramp` (bonus) + `99_interactive` (playground). |
| `overlay_demo.py` | The bare PYNQ overlay API, board only, read top to bottom. |
| `collect_board_data.py` | One command on the board -> `board_data.json` + scoreboard (pins the roofline numbers). |
| `make_roofline.py` | Regenerate the roofline figure from a board-data JSON. |
| `test_conv.py` | Tests for the software layer; run anywhere. |
| `reference_data/` | Real board measurements, checked in so the roofline regenerates without a board. |

## The backend ladder

One interface, the same convolution made faster rung by rung:

| name | what it is |
|------|------------|
| `pyloop` | pure-Python triple loop - correct, brutally slow (rung 1) |
| `software` | NumPy - the golden reference (rung 2) |
| `rtl` | the hand-written RTL core (conv0) over AXI-Lite, one pixel per MMIO write (rung 3) |
| `hls_naive` | the naive HLS accelerator, DMA but II=9 (rung 4) |
| `hls_opt` | the line-buffer HLS accelerator, II=1, memory-bound (rung 5) |
| `hls_stream` | the streaming HLS accelerator, dataflow+burst, near the roof (rung 6) |

`pyloop` and `software` run anywhere; the four hardware backends are board only and
raise a clear `BackendUnavailable` (not an `ImportError`) off-board.

## On a laptop (rehearsal)

```bash
# from the repo root, after: uv pip install -r requirements.txt
.venv/bin/python -m pytest python/ -q          # all software, no board

# launch Jupyter and open the rung series
.venv/bin/jupyter lab python/notebooks/
```

Off-board, the notebooks run the `pyloop` and `software` rungs; the hardware rungs
report "hardware not available" cleanly instead of crashing.

## On the PYNQ-Z2 board

PYNQ boards boot into JupyterLab, so the notebooks are the native way to run this:

```bash
# pynq ships in the board image; add the plotting/widget deps once if needed:
sudo pip3 install matplotlib ipywidgets
```

Copy `python/` to the board, open the notebooks in the board's Jupyter, and run
them top to bottom - the hardware backends appear and the clock-ramp cell becomes
live. For the bare-API script:

```bash
cd ~/workshop/python
CONV3X3_BIT=/home/xilinx/workshop/conv3x3.bit python3 overlay_demo.py cat.jpg edges
```

## How the abstraction keeps it portable

The notebooks, `overlay_demo.py`, and the tests only ever talk to the `Backend`
interface:

```python
from fpga_conv import get_backend, KERNELS
backend = get_backend("software")              # or "rtl"/"hls_stream"/... on the board
out_image, latency_ms = backend.run(image, KERNELS["edges"])   # color=True for RGB
```

The board backends lazily import `pynq` and share one Overlay, so none of this
breaks on a laptop.

## The kernel as data (loaded over AXI)

A `Kernel` is nine signed coefficients, a `shift` (divisor), and a `mode` (0 =
signed clamp, 1 = abs then clamp, for edges). The built-ins:

| name | what it does |
|------|--------------|
| `identity` | passes the image through (sanity check) |
| `blur` | Gaussian blur (`>> 4`) |
| `sharpen` | unsharp / local-contrast boost |
| `edges` | Laplacian edge detector (magnitude) |

Python writes the nine coefficients (and shift/mode) into the PL over AXI before
streaming the image. Same-size output with zero-padded borders, bit-exact across the
NumPy reference, the RTL, and the HLS kernels.

## Register / IP names

Both hardware backends talk **raw AXI-Lite MMIO** at fixed byte offsets - they do
*not* use pynq's `register_map`, because for the HLS accelerators `register_map`
recurses to a stack overflow on the board (a known pynq quirk with some HLS register
layouts). `RtlBackend` uses the offsets in `rtl/conv3x3_axi_lite.sv`; `FpgaBackend`
uses the standard Vitis HLS `s_axi_control` map (confirmed against the `.hwh`). The
three HLS backends share `FpgaBackend` and the same offsets (identical argument
signature) - only the IP cell name differs.

The only thing that varies by how the block design was assembled is the **cell
name**. If yours differ, pass `ip_name=...` (the notebooks' `BACKEND_KWARGS`, or the
`FpgaBackend(...)` / `RtlBackend(...)` constructor). A notebook inspection cell
prints `ol.ip_dict` so you can read the real names.
