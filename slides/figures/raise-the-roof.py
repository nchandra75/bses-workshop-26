#!/usr/bin/env python3
"""Generate raise-the-roof.svg - the one-off closing roofline figure.

This is deliberately NOT the live `Roofline` component or `bench.roofline()`: it is a
single teaching plot for the wrap-up slide that tells the "two ways to go faster" story
the per-rung rooflines only hint at:

  - move RIGHT  : a better memory schedule (read once, burst) walks a rung up the
                  sloped memory ceiling until it reaches the flat compute roof.
  - move UP     : raising the roof itself - more compute (more DSPs, several pixels
                  per clock). The catch, drawn here so it stays honest: the memory
                  ceiling has to rise with it, or the wider datapath just starves.

The numbers are illustrative (a concept slide), not the board's pinned figures - but the
palette and styling match `python/fpga_conv/bench.py:roofline` so it reads as a sibling
of the live plots. Regenerate:  python slides/figures/raise-the-roof.py
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

MACS_PER_PIXEL = 9

# Illustrative ceilings (Mpix/s) and the bandwidths that put each ridge where we want it.
ROOF_NOW = 100.0     # 1 pixel / clock at 100 MHz - the datapath we built
ROOF_HI = 800.0      # ~8 pixels / clock - a wide, parallel datapath
BW_NOW = 300e6       # bytes/s, sets the current ridge near intensity 3
BW_HI = 1.6e9        # the raised memory ceiling that makes ROOF_HI actually reachable

BLUE, BLUE_D = "#3b7dd8", "#23538f"
ORANGE, ORANGE_D = "#e08a1e", "#9c5a00"

fs = 12
fig, ax = plt.subplots(figsize=(8.5, 5.5))

x_lo, x_hi = 0.3, 30.0
xs = np.logspace(np.log10(x_lo), np.log10(x_hi), 400)


def mem_ceiling(bw):
    return (bw * xs) / MACS_PER_PIXEL / 1e6


ridge_now = ROOF_NOW * 1e6 * MACS_PER_PIXEL / BW_NOW   # ~3.0

# regime shading, as in the live roofline
ax.axvspan(x_lo, ridge_now, color=BLUE, alpha=0.06, zorder=0)
ax.axvspan(ridge_now, x_hi, color=ORANGE, alpha=0.07, zorder=0)

# raised ceilings (drawn faint, behind the current roofline)
ax.plot(xs, np.minimum(mem_ceiling(BW_HI), ROOF_HI), color=ORANGE_D, lw=2.0,
        alpha=0.8, label="raised roofline (more compute + bandwidth)")
ax.plot(xs, np.full_like(xs, ROOF_HI), color=ORANGE, ls="--", lw=1.1, alpha=0.6)
ax.plot(xs, mem_ceiling(BW_HI), color=ORANGE, ls=":", lw=1.1, alpha=0.5)

# current ceilings + roofline (the solid black one, as in the live plot)
ax.plot(xs, np.minimum(mem_ceiling(BW_NOW), ROOF_NOW), color="black", lw=2.5,
        label="roofline today (1 pixel / clock)")
ax.plot(xs, np.full_like(xs, ROOF_NOW), color="gray", ls="--", lw=1.1, alpha=0.7)
ax.plot(xs, mem_ceiling(BW_NOW), color="gray", ls=":", lw=1.1, alpha=0.7)

# the three rungs / dots
naive = (0.9, BW_NOW * 0.9 / MACS_PER_PIXEL / 1e6)     # on the slope, memory-bound
stream = (4.5, ROOF_NOW)                               # on the current roof
wide = (4.5, ROOF_HI)                                  # on the raised roof
for (x, y), c in [(naive, BLUE_D), (stream, "black"), (wide, ORANGE_D)]:
    ax.plot(x, y, "o", ms=11, color=c, zorder=6)

ax.annotate("naive\n(memory-bound)", naive, textcoords="offset points",
            xytext=(8, -28), fontsize=fs - 3, color=BLUE_D, weight="bold")
ax.annotate("streaming\n(on the roof)", stream, textcoords="offset points",
            xytext=(10, -4), fontsize=fs - 3, color="black", weight="bold")
ax.annotate("wide datapath", wide, textcoords="offset points",
            xytext=(10, -2), fontsize=fs - 3, color=ORANGE_D, weight="bold")

# the two motions - the whole point of the slide
ax.annotate("", xy=(stream[0] * 0.96, stream[1] * 0.96), xytext=naive,
            arrowprops=dict(arrowstyle="-|>", lw=2.2, color=BLUE_D,
                            connectionstyle="arc3,rad=-0.15"))
ax.text(1.9, 42, "move right:\nread once, burst", fontsize=fs - 2, color=BLUE_D,
        weight="bold", ha="center")

ax.annotate("", xy=(wide[0], wide[1] * 0.94), xytext=(stream[0], stream[1] * 1.06),
            arrowprops=dict(arrowstyle="-|>", lw=2.2, color=ORANGE_D))
ax.text(5.4, 290, "move up:\nraise the roof\n(more DSPs)", fontsize=fs - 2,
        color=ORANGE_D, weight="bold", ha="left", va="center")

ax.axvline(ridge_now, color="gray", ls="-", lw=0.8, alpha=0.5)
ax.text(ridge_now, ROOF_NOW * 1.12, "ridge", ha="center", fontsize=fs - 2, color="gray")

ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlim(x_lo, x_hi)
ax.set_ylim(15, ROOF_HI * 2.2)
ax.set_xlabel("arithmetic intensity (MACs per byte of DRAM traffic)", fontsize=fs)
ax.set_ylabel("throughput (Mpix/s)", fontsize=fs)
ax.set_title("Two ways to go faster: move right, or raise the roof", fontsize=fs + 2)
ax.tick_params(labelsize=fs - 1)
ax.grid(alpha=0.3, which="both")
ax.legend(fontsize=fs - 2, loc="lower right", framealpha=0.9)
fig.tight_layout()

out = __file__.replace(".py", ".svg")
fig.savefig(out)
print("wrote", out)
