"""Shared measurement + display harness for the workshop notebook series.

Every rung of the ladder (Python loops -> NumPy -> RTL -> naive HLS -> line-buffer
HLS -> streaming HLS) is measured the *same way* and plotted on the *same* picture,
so the story is a single climb rather than six unrelated demos. That consistency is
the point, so it lives here, imported by every notebook, instead of being copy-pasted.

Three things:

  - timing      : time_backend() - warm up, then best/median over repeats, plus the
                  spread, so notebook 01 can show why warmup + averaging matter.
  - scoreboard  : Scoreboard - a tiny JSON-backed accumulator. Each notebook appends
                  its rung's throughput; the roofline grows across the series.
  - roofline    : roofline() - the recurring "how far from the hardware's limit are
                  we?" plot, kept deliberately simple (one compute ceiling, one
                  memory-bandwidth ceiling, one dot per rung).

The roofline ceilings are the PL fabric's (100 MHz, 9 MACs/clock, one HP DRAM port).
For an honest same-system comparison the software rungs (pyloop, NumPy) should be
measured on the board's ARM cores too - the laptop runs them for development, but the
numbers that go on the final roofline come from the board.
"""

from __future__ import annotations

import io
import json
import os
import statistics
import time
from dataclasses import dataclass, field

import numpy as np

from .core import KERNEL_SIZE, Kernel, conv_reference, get_kernel, to_grayscale_u8

# ----------------------------------------------------------------------------------
# Images
# ----------------------------------------------------------------------------------

def make_sample_image(n: int = 256) -> np.ndarray:
    """A synthetic colour image with gradients and shapes - something to filter if
    you do not have a photo handy. Upload a real image in the playground notebook."""
    yy, xx = np.mgrid[0:n, 0:n]
    r = (xx * 255 // n).astype(np.uint8)
    g = np.where((xx - n // 2) ** 2 + (yy - n // 2) ** 2 < (n // 4) ** 2, 230, 30).astype(np.uint8)
    b = np.zeros((n, n), np.uint8)
    b[n // 6:n // 3, n // 6:5 * n // 6] = 200
    return np.dstack([r, g, b])


def sample_gray(n: int = 128) -> np.ndarray:
    """A grayscale sample image of side n - the honest apples-to-apples input (the
    hardware datapath is grayscale)."""
    return to_grayscale_u8(make_sample_image(n))


def image_from_bytes(data) -> np.ndarray:
    """Decode uploaded image bytes to an HxWx3 uint8 array (needs Pillow)."""
    from PIL import Image
    return np.array(Image.open(io.BytesIO(bytes(data))).convert('RGB'))


# ----------------------------------------------------------------------------------
# Timing - the measurement methodology, in one place
# ----------------------------------------------------------------------------------

@dataclass
class Timing:
    """The result of timing a backend: latency in ms and the throughput it implies."""
    label: str
    npix: int
    best_ms: float
    median_ms: float
    stdev_ms: float
    first_ms: float          # the un-warmed first run - the cost of NOT warming up
    samples_ms: list[float] = field(default_factory=list)

    @property
    def throughput_mpix(self) -> float:
        """Megapixels per second at the best (steady-state) latency."""
        return (self.npix / (self.best_ms / 1e3)) / 1e6 if self.best_ms > 0 else float('inf')


def time_backend(backend, image, kernel, repeats: int = 10, warmup: int = 1,
                 color: bool = False) -> Timing:
    """Measure a backend honestly: a few warmup runs, then best/median of `repeats`.

    Why this shape, and why it is the same for every rung:

      - WARMUP. The first call pays one-time costs that are not the computation:
        Python imports, JIT-less interpreter warm-up, NumPy allocating scratch, the
        FPGA backend allocating its DMA buffers, cold caches. We run `warmup` calls
        first and throw them away. `first_ms` keeps the un-warmed number so you can
        SEE how big that one-time cost is.
      - AVERAGING / BEST-OF. A single timed run is noisy (the OS scheduler, other
        processes). We take `repeats` runs and report the BEST - the cleanest view of
        what the path sustains - alongside the median and the spread (stdev), so the
        noise is visible rather than hidden.

    Returns a Timing. `image` and `kernel` are passed straight to backend.run().
    """
    kernel = get_kernel(kernel)
    npix = to_grayscale_u8(image).size if not color else np.asarray(image)[..., 0].size

    first_ms = backend.run(image, kernel, color=color)[1]      # the cold run
    for _ in range(max(0, warmup - 1)):
        backend.run(image, kernel, color=color)

    samples = [backend.run(image, kernel, color=color)[1] for _ in range(repeats)]
    return Timing(
        label=getattr(backend, 'name', str(backend)),
        npix=npix,
        best_ms=min(samples),
        median_ms=statistics.median(samples),
        stdev_ms=statistics.pstdev(samples) if len(samples) > 1 else 0.0,
        first_ms=first_ms,
        samples_ms=samples,
    )


# ----------------------------------------------------------------------------------
# Roofline model - kept deliberately simple
# ----------------------------------------------------------------------------------

# The PL fabric's limits at the rated clock. These set the two ceilings.
PL_CLOCK_HZ = 100e6          # fclk0, the design's rated clock
MACS_PER_PIXEL = KERNEL_SIZE * KERNEL_SIZE          # 9 multiply-accumulates / pixel
PEAK_MACS = MACS_PER_PIXEL * PL_CLOCK_HZ            # 9 DSPs firing every clock
PEAK_MPIX = PL_CLOCK_HZ / 1e6                        # 1 output pixel / clock = 100 Mpix/s

# Effective DRAM bandwidth reachable over the single HP AXI port the accelerators
# share, in bytes/s. The HLS m_axi ports here are byte-wide, so the *usable* figure is
# modest; bursting (the streaming kernel) is what gets close to it. Pinned from board
# measurement - adjust once you have the real streaming number.
DRAM_BW_BYTES = 60e6        # ~60 MB/s usable, byte-wide port; refine from the board

# Arithmetic intensity (MACs per byte of DRAM traffic) per implementation. The naive
# kernel re-reads the 9-pixel window from DRAM every output pixel (9 reads + 1 write =
# 10 bytes); the line-buffer and streaming kernels read each pixel once (1 read + 1
# write = 2 bytes). Same compute, very different memory traffic - that is the story.
INTENSITY_MAC_PER_BYTE: dict[str, float] = {
    'pyloop':     MACS_PER_PIXEL / 10.0,
    'software':   MACS_PER_PIXEL / 10.0,
    'rtl':        MACS_PER_PIXEL / 2.0,    # streams each pixel once over MMIO
    'hls_naive':  MACS_PER_PIXEL / 10.0,   # 9 DRAM reads + 1 write per pixel
    'fpga':       MACS_PER_PIXEL / 10.0,   # back-compat alias
    'hls_opt':    MACS_PER_PIXEL / 2.0,    # 1 read + 1 write per pixel
    'hls_stream': MACS_PER_PIXEL / 2.0,    # same traffic, but bursted
}


def intensity_of(name: str) -> float:
    return INTENSITY_MAC_PER_BYTE.get(name, MACS_PER_PIXEL / 10.0)


# ----------------------------------------------------------------------------------
# Scoreboard - the running tally the roofline reads
# ----------------------------------------------------------------------------------

DEFAULT_STORE = os.path.join(os.path.dirname(__file__), os.pardir, 'notebooks',
                             'scoreboard.json')


class Scoreboard:
    """A tiny JSON-backed tally of each rung's throughput, so the roofline grows as
    you work through the notebook series. Each notebook does:

        sb = Scoreboard()
        sb.record('hls_naive', timing)      # or sb.record(name, mpix=..., intensity=...)
        sb.roofline()                       # draw where we are

    The store is a JSON file beside the notebooks; delete it to start the climb over.
    """

    def __init__(self, path: str | None = None):
        self.path = os.path.abspath(path or DEFAULT_STORE)
        self.points: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path) as f:
                self.points = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.points = {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w') as f:
            json.dump(self.points, f, indent=2)

    def record(self, name, timing: Timing | None = None, *, mpix: float | None = None,
               intensity: float | None = None, label: str | None = None) -> None:
        """Add or update a rung. Pass either a Timing or an explicit mpix throughput."""
        from .backends import BACKEND_LABELS
        if timing is not None:
            mpix = timing.throughput_mpix
        if mpix is None:
            raise ValueError('record() needs either a Timing or mpix=')
        self.points[name] = {
            'label': label or BACKEND_LABELS.get(name, name),
            'mpix': float(mpix),
            'intensity': float(intensity if intensity is not None else intensity_of(name)),
            'order': self.points.get(name, {}).get('order', len(self.points)),
        }
        self._save()

    def reset(self) -> None:
        self.points = {}
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass

    def ordered(self) -> list[tuple[str, dict]]:
        return sorted(self.points.items(), key=lambda kv: kv[1]['order'])

    # -- the two views -------------------------------------------------------------

    def progress(self, ax=None):
        """The recurring scoreboard: a horizontal bar of throughput per rung so far
        (log scale - the rungs span several orders of magnitude)."""
        import matplotlib.pyplot as plt
        items = self.ordered()
        if not items:
            print('scoreboard is empty - record a rung first.')
            return None
        labels = [v['label'] for _, v in items]
        mpix = [v['mpix'] for _, v in items]
        if ax is None:
            _, ax = plt.subplots(figsize=(7, 0.6 * len(items) + 1))
        ax.barh(range(len(items)), mpix, color='steelblue')
        ax.set_yticks(range(len(items)))
        ax.set_yticklabels(labels)
        ax.invert_yaxis()
        ax.set_xscale('log')
        ax.set_xlabel('throughput (Mpix/s, log scale)')
        ax.axvline(PEAK_MPIX, color='red', ls='--', alpha=0.6)
        ax.text(PEAK_MPIX, -0.4, ' PL compute ceiling', color='red', fontsize=8)
        for i, m in enumerate(mpix):
            ax.text(m, i, f' {m:.2f}', va='center', fontsize=8)
        ax.set_title('Where are we? throughput per rung')
        ax.figure.tight_layout()
        return ax

    def roofline(self, ax=None):
        """The roofline: arithmetic intensity (x) vs throughput (y), with the PL's
        compute ceiling and DRAM-bandwidth ceiling. Each rung is a dot; the gap to
        the ceilings is how much performance is still on the table."""
        return roofline(self, ax=ax)


def _place_rung_labels(ax, points, x_lo, x_hi, fs):
    """Annotate each rung dot without labels stomping each other.

    The general problem: several rungs can share an arithmetic intensity (same x),
    so their labels pile up. The fix here is intensity-cluster-aware: group points by
    x, fan each group's labels apart vertically (in log space, with a leader line back
    to the dot), colour each label to match its dot, and put labels on whichever side
    keeps them in frame (left for points in the right third, right otherwise). No
    external deps - good enough for the handful of rungs we ever plot.
    """
    import numpy as np
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for x, y, lab, color in points:
        # short tag only: the detail in "(DMA, II=1, mem-bound)" belongs in the
        # legend / the presenter's mouth, not crammed onto the dot.
        groups[round(np.log10(x), 2)].append((x, y, lab.split(' (')[0], color))

    min_gap = 0.30            # minimum vertical label separation, in decades
    x_mid = 10 ** (0.66 * np.log10(x_hi) + 0.34 * np.log10(x_lo))
    for _, grp in groups.items():
        grp.sort(key=lambda p: p[1])               # by throughput
        logs = np.array([np.log10(y) for _, y, _, _ in grp], float)
        spread = logs.copy()                       # push apart greedily, then recentre
        for i in range(1, len(spread)):
            if spread[i] - spread[i - 1] < min_gap:
                spread[i] = spread[i - 1] + min_gap
        spread += np.mean(logs) - np.mean(spread)
        for (x, y, lab, color), ly in zip(grp, spread):
            right = x < x_mid                      # label side keeps text on-canvas
            label_x = x * (1.18 if right else 0.85)
            ax.annotate(lab, xy=(x, y), xytext=(label_x, 10 ** ly),
                        textcoords='data', ha='left' if right else 'right',
                        va='center', fontsize=fs, color=color,
                        arrowprops=dict(arrowstyle='-', color=color, lw=0.6,
                                        alpha=0.6, shrinkA=2, shrinkB=4))


def roofline(scoreboard: Scoreboard | None = None, ax=None,
             peak_mpix: float = PEAK_MPIX, dram_bw_bytes: float = DRAM_BW_BYTES):
    """Draw the simple roofline. Ceilings are the PL fabric's; dots are the rungs.

    y-axis is throughput in Mpix/s. The compute ceiling is flat (one pixel/clock).
    The memory ceiling slopes with arithmetic intensity: a design that moves more
    bytes per pixel (low intensity) hits the DRAM wall sooner. Where the two cross is
    the ridge point - left of it you are memory-bound, right of it compute-bound.
    """
    import matplotlib.pyplot as plt
    # one knob: bump every text size together so the figure reads on a projector.
    fs = 12
    if ax is None:
        _, ax = plt.subplots(figsize=(8.5, 5.5))

    # The ridge point is where the sloped memory ceiling meets the flat compute
    # ceiling: intensity = peak_mpix * 1e6 * MACs/pixel / BW. Range the x-axis so the
    # ridge sits about two-thirds across and a clear stretch of the flat roof shows to
    # its right - otherwise, with a low assumed bandwidth, the roof is an off-screen
    # sliver and the plot looks like "just a slope" (which is the thing this fixes).
    ridge = peak_mpix * 1e6 * MACS_PER_PIXEL / dram_bw_bytes
    lo_pts = [v['intensity'] for _, v in scoreboard.ordered()] if scoreboard else []
    x_lo = min([0.5 * ridge] + lo_pts) * 0.5
    x_hi = ridge * 3.0
    # x-axis: arithmetic intensity (MAC/byte), log scale
    xs = np.logspace(np.log10(x_lo), np.log10(x_hi), 300)
    # memory ceiling in Mpix/s = (BW[bytes/s] * intensity[MAC/byte]) / (MACs/pixel) / 1e6
    mem_ceiling = (dram_bw_bytes * xs) / MACS_PER_PIXEL / 1e6
    compute_ceiling = np.full_like(xs, peak_mpix)
    roof = np.minimum(mem_ceiling, compute_ceiling)

    # shade the two regimes so "memory-bound (slope)" vs "compute-bound (roof)" reads
    # at a glance, instead of relying on faint grey text.
    ax.axvspan(x_lo, ridge, color='#3b7dd8', alpha=0.07, zorder=0)
    ax.axvspan(ridge, x_hi, color='#e08a1e', alpha=0.09, zorder=0)

    ax.plot(xs, roof, color='black', lw=2.5, label='roofline (attainable)')
    ax.plot(xs, compute_ceiling, color='gray', ls='--', lw=1.2, alpha=0.7,
            label=f'compute ceiling ({peak_mpix:g} Mpix/s)')
    ax.plot(xs, mem_ceiling, color='gray', ls=':', lw=1.2, alpha=0.7,
            label='DRAM-bandwidth ceiling')

    # mark the ridge and name the two regimes along the top of the plot area.
    ax.axvline(ridge, color='gray', ls='-', lw=0.8, alpha=0.5)
    ax.text(ridge, peak_mpix * 1.3, 'ridge', ha='center', fontsize=fs,
            color='gray')
    ax.text(np.sqrt(x_lo * ridge), peak_mpix * 1.7, 'memory-bound\n(on the slope)',
            ha='center', va='center', fontsize=fs - 3, color='#23538f', weight='bold')
    ax.text(np.sqrt(ridge * x_hi), peak_mpix * 1.7, 'compute-bound\n(on the roof)',
            ha='center', va='center', fontsize=fs - 3, color='#9c5a00', weight='bold')

    if scoreboard is not None:
        pts = []
        for _, v in scoreboard.ordered():
            (line,) = ax.plot(v['intensity'], v['mpix'], 'o', ms=11, zorder=5)
            pts.append((v['intensity'], v['mpix'], v['label'], line.get_color()))
        _place_rung_labels(ax, pts, x_lo, x_hi, fs - 2)

    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlim(x_lo, x_hi)
    # headroom above the roof for the regime labels; a little below the lowest dot.
    ys = [v['mpix'] for _, v in scoreboard.ordered()] if scoreboard else [peak_mpix]
    ax.set_ylim(min(ys + [peak_mpix]) * 0.35, peak_mpix * 3.0)
    ax.set_xlabel('arithmetic intensity (MACs per byte of DRAM traffic)', fontsize=fs)
    ax.set_ylabel('throughput (Mpix/s)', fontsize=fs)
    ax.set_title("Roofline: how far from the hardware's limit?", fontsize=fs + 2)
    ax.tick_params(labelsize=fs - 1)
    ax.grid(alpha=0.3, which='both')
    # legend outside the axes (upper-right) so it never lands on a dot or label;
    # reserve the right margin so it is not clipped in notebook or export.
    ax.legend(fontsize=fs - 2, loc='upper left', bbox_to_anchor=(0.5, 0.4),
              borderaxespad=0, framealpha=0.9)
    ax.figure.tight_layout(rect=(0, 0, 0.78, 1))
    return ax


# ----------------------------------------------------------------------------------
# Display helpers - run one rung, check it, show it
# ----------------------------------------------------------------------------------

def check(out: np.ndarray, image, kernel) -> bool:
    """True if `out` matches the golden NumPy reference bit-for-bit (the contract)."""
    return np.array_equal(out, conv_reference(to_grayscale_u8(image), get_kernel(kernel)))


def show_result(image, out, kernel, title: str = ''):
    """Plot input next to output for one rung."""
    import matplotlib.pyplot as plt
    gray = to_grayscale_u8(image)
    fig, ax = plt.subplots(1, 2, figsize=(6.4, 3.4))
    ax[0].imshow(gray, cmap='gray', vmin=0, vmax=255); ax[0].set_title('input'); ax[0].axis('off')
    ax[1].imshow(out, cmap='gray', vmin=0, vmax=255)
    ax[1].set_title(title or get_kernel(kernel).name); ax[1].axis('off')
    fig.tight_layout(); plt.show()


def run_rung(backend_name, image, kernel='edges', *, repeats: int = 10,
             scoreboard: Scoreboard | None = None, show: bool = True, **kwargs):
    """The one-liner each ladder notebook calls: build the backend, time it the
    standard way, check it against the reference, drop it on the scoreboard, and
    (optionally) show the filtered image. Returns (output, Timing).
    """
    from .backends import BACKEND_LABELS, get_backend
    bk = get_backend(backend_name, **kwargs)
    kernel = get_kernel(kernel)
    out, _ = bk.run(image, kernel, color=False)
    t = time_backend(bk, image, kernel, repeats=repeats)
    label = BACKEND_LABELS.get(backend_name, backend_name)
    ok = check(out, image, kernel)
    print(f'{label}')
    print(f'  bit-exact vs reference : {"YES" if ok else "NO - MISMATCH"}')
    print(f'  cold first run         : {t.first_ms:8.3f} ms   (the cost of not warming up)')
    print(f'  warm best of {repeats:<3d}       : {t.best_ms:8.3f} ms')
    print(f'  warm median +/- stdev  : {t.median_ms:8.3f} +/- {t.stdev_ms:.3f} ms')
    print(f'  throughput             : {t.throughput_mpix:8.2f} Mpix/s'
          f'   ({t.throughput_mpix / PEAK_MPIX * 100:.1f}% of the PL compute ceiling)')
    if scoreboard is not None:
        scoreboard.record(backend_name, t)
    if show:
        show_result(image, out, kernel, title=f'{label}: {kernel.name}')
    bk.close()
    return out, t
