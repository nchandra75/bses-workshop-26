#!/usr/bin/env python3
"""Regenerate slides/figures/roofline.svg from collected board data.

Runs on the DEV BOX (just needs numpy + matplotlib). Reads board_data.json - the
file collect_board_data.py produced on the board - and redraws the roofline with the
real ceilings: the compute ceiling from the PL clock, the memory ceiling's slope from
the best DRAM bandwidth the fabric actually delivered. Each rung is a dot.

    python3 make_roofline.py board_data.json
    python3 make_roofline.py            # no data yet: draws the *expected* picture

With no argument (or a missing file) it falls back to the modelled numbers so the
figure is never a placeholder - it just gets sharper once real data lands.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fpga_conv import bench

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_SVG = os.path.normpath(os.path.join(HERE, os.pardir, "slides", "figures",
                                        "roofline.svg"))

# When no fresh board_data.json is given, fall back to the checked-in baseline - real
# numbers captured on the board (see reference_data/README.md), not a guess. This lets
# the deck regenerate offline / without a board.
BASELINE = os.path.join(HERE, "reference_data", "board_data_pynqz2_62mhz.json")


def load(path: str | None) -> tuple[dict, bool]:
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f), True
    with open(BASELINE) as f:           # checked-in real baseline
        return json.load(f), False


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "board_data.json"
    data, real = load(path)

    sb = bench.Scoreboard(path=os.path.join(HERE, ".roofline_tmp.json"))
    sb.reset()
    from fpga_conv.backends import BACKEND_LABELS
    for r in data["rungs"]:
        sb.record(r["name"], mpix=r["mpix"],
                  intensity=bench.intensity_of(r["name"]),
                  label=r.get("label", BACKEND_LABELS.get(r["name"], r["name"])))

    peak = data.get("peak_mpix") or bench.PEAK_MPIX
    dram_bw = data.get("effective_dram_bw_bytes") or bench.DRAM_BW_BYTES

    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    bench.roofline(sb, ax=ax, peak_mpix=peak, dram_bw_bytes=dram_bw)
    fclk = data.get("fclk0_mhz")
    src = f"PYNQ-Z2 @ {fclk:g} MHz" if fclk else "PYNQ-Z2 baseline"
    ax.set_title(f"Roofline:  [{src}]")
    # fig.savefig(OUT_SVG, bbox_inches='tight')
    fig.savefig(OUT_SVG)
    sb.reset()   # remove the temp store

    print(f"wrote {OUT_SVG}")
    print(f"  source        : {path if real else 'checked-in baseline ' + BASELINE}")
    print(f"  compute ceiling: {peak:.0f} Mpix/s")
    print(f"  DRAM bandwidth : {dram_bw/1e6:.0f} MB/s")
    ridge = peak * 1e6 * bench.MACS_PER_PIXEL / dram_bw
    print(f"  ridge point    : {ridge:.2f} MAC/byte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
