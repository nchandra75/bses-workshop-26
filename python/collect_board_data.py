#!/usr/bin/env python3
"""Collect the roofline data on the board, in one shot.

Run this ON THE PYNQ-Z2 (it needs pynq + the bitstream). It times every rung,
checks each is bit-exact against the golden NumPy reference, and writes two files:

  board_data.json   - the rich record (per-rung throughput, bytes/pixel, the
                      achieved DRAM bandwidth, the clock). This is what gets handed
                      back to regenerate the roofline figure - it carries enough to
                      set BOTH ceilings, not just the dots.
  scoreboard.json   - the same throughput tally the notebooks' roofline reads, so
                      the live demo can open already populated (or be re-run live).

Typical use on the board:

    sudo CONV3X3_BIT=/home/xilinx/conv3x3.bit \
        python3 collect_board_data.py --out board_data.json

then copy board_data.json back to the dev box. Everything is size-independent
throughput, so the per-backend image sizes below only trade run time for noise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# allow running from anywhere (the package is the parent dir of this file)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from fpga_conv import bench
from fpga_conv.backends import BACKEND_LABELS, available_backends, get_backend
from fpga_conv.core import conv_reference, get_kernel


# Bytes of DRAM traffic per output pixel, per rung. This is the arithmetic-intensity
# denominator and the multiplier that turns a throughput (Mpix/s) into an achieved
# bandwidth (bytes/s). pyloop/software run on the ARM core with no PL DRAM port, so
# "DRAM bytes/pixel" is not meaningful for them (None).
BYTES_PER_PIXEL = {
    "pyloop": None,
    "software": None,
    "rtl": 2,          # one pixel streamed in, one out, over MMIO
    "hls_naive": 10,   # 9 window reads + 1 write per output pixel
    "hls_opt": 2,      # read each pixel once + write once
    "hls_stream": 2,   # same traffic as hls_opt, but bursted
}

# Per-rung image size (pixels per side). The slow rungs get a smaller frame so the
# sweep finishes quickly; throughput is steady-state so this does not bias it.
#   pyloop  - pure Python triple loop, genuinely slow -> tiny
#   rtl     - one MMIO write per pixel -> small
#   others  - big enough to reach steady state on the DMA path
SIDE = {
    "pyloop": 64,
    "software": 512,
    "rtl": 128,
    "hls_naive": 720,
    "hls_opt": 720,
    "hls_stream": 720,
}
REPEATS = {"pyloop": 3, "rtl": 5}   # default elsewhere is --repeats


def measure(name: str, kernel, repeats: int, side_override: int | None) -> dict:
    side = side_override or SIDE.get(name, 256)
    img = bench.sample_gray(side)
    backend = get_backend(name)
    t = bench.time_backend(backend, img, kernel,
                           repeats=REPEATS.get(name, repeats), warmup=2)

    out = backend.run(img, kernel)[0]
    ref = conv_reference(img, get_kernel(kernel))
    exact = bool(np.array_equal(out, ref))

    bpp = BYTES_PER_PIXEL.get(name)
    mpix = t.throughput_mpix
    achieved_bw = (mpix * 1e6 * bpp) if bpp else None
    return {
        "name": name,
        "label": BACKEND_LABELS.get(name, name),
        "side": side,
        "mpix": mpix,
        "best_ms": t.best_ms,
        "first_ms": t.first_ms,
        "bytes_per_pixel": bpp,
        "achieved_bw_bytes": achieved_bw,
        "bit_exact": exact,
    }


def read_fclk_mhz() -> float | None:
    try:
        from pynq import Clocks  # type: ignore
        return float(Clocks.fclk0_mhz)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kernel", default="edges", help="kernel name (default: edges)")
    ap.add_argument("--repeats", type=int, default=10,
                    help="timed repeats per rung (default: 10)")
    ap.add_argument("--side", type=int, default=None,
                    help="override the per-rung image side (pixels)")
    ap.add_argument("--out", default="board_data.json",
                    help="rich output JSON (default: board_data.json)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="restrict to these backends (default: all available)")
    args = ap.parse_args()

    kernel = get_kernel(args.kernel)
    names = args.only or available_backends()

    print(f"# collecting roofline data  kernel={args.kernel}  rungs={names}\n")
    rows: list[dict] = []
    for name in names:
        try:
            r = measure(name, kernel, args.repeats, args.side)
        except Exception as exc:        # one bad rung should not lose the rest
            print(f"  {name:11s}  SKIPPED ({type(exc).__name__}: {exc})")
            continue
        rows.append(r)
        flag = "ok " if r["bit_exact"] else "BAD"
        bw = f"{r['achieved_bw_bytes']/1e6:7.1f} MB/s" if r["achieved_bw_bytes"] else "      -    "
        print(f"  {name:11s}  {r['mpix']:9.3f} Mpix/s   {bw}   bit-exact:{flag}"
              f"   ({r['side']}x{r['side']})")

    # The compute ceiling is one output pixel per PL clock; the memory ceiling's slope
    # is set by the best DRAM bandwidth the fabric actually delivered - the streaming
    # (bursting) kernel, in practice. Record both so the figure needs no guessing.
    fclk = read_fclk_mhz()
    bws = [r["achieved_bw_bytes"] for r in rows if r["achieved_bw_bytes"]]
    effective_bw = max(bws) if bws else None
    peak_mpix = fclk if fclk else 100.0     # 1 pixel/clock at the PL clock

    data = {
        "kernel": args.kernel,
        "fclk0_mhz": fclk,
        "peak_mpix": peak_mpix,
        "effective_dram_bw_bytes": effective_bw,
        "effective_dram_bw_source": (
            max(rows, key=lambda r: r["achieved_bw_bytes"] or 0)["name"]
            if effective_bw else None),
        "rungs": rows,
    }

    with open(args.out, "w") as f:
        json.dump(data, f, indent=2)

    # also write the scoreboard the notebooks' roofline reads, in ladder order
    sb = bench.Scoreboard()
    sb.reset()
    for r in rows:
        sb.record(r["name"], mpix=r["mpix"],
                  intensity=bench.intensity_of(r["name"]), label=r["label"])

    print(f"\n# wrote {args.out}")
    print(f"# wrote {sb.path}")
    if effective_bw:
        ridge = peak_mpix * 1e6 * bench.MACS_PER_PIXEL / effective_bw
        print(f"# peak compute ceiling : {peak_mpix:.0f} Mpix/s"
              f"  (fclk0 = {fclk} MHz)" if fclk else
              f"# peak compute ceiling : {peak_mpix:.0f} Mpix/s")
        print(f"# effective DRAM BW    : {effective_bw/1e6:.0f} MB/s"
              f"  (from {data['effective_dram_bw_source']})")
        print(f"# roofline ridge point : {ridge:.2f} MAC/byte"
              f"   -> the flat roof starts here")
    any_bad = [r["name"] for r in rows if not r["bit_exact"]]
    if any_bad:
        print(f"\n!! NOT bit-exact: {any_bad} - investigate before trusting numbers")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
