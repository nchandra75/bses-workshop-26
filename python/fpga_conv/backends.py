"""Backends for the convolution accelerator.

One interface, one operation made faster rung by rung:

  PyLoopBackend  - a pure-Python triple loop. Correct and brutally slow; the
                   starting rung. Runs on any machine.
  SoftwareBackend- NumPy. The golden reference. Runs on any machine.
  RtlBackend     - the hand-written RTL core (conv0) over AXI-Lite, fed one pixel
                   per MMIO write. Board only. Deliberately slow and legible.
  FpgaBackend    - the Vitis HLS accelerator over the PYNQ overlay, DMA-reading the
                   image from DRAM. Board only. One class drives all three HLS
                   kernels (same register layout, different IP cell): hls_naive
                   (conv3x3_accel_0), hls_opt (conv3x3_accel_fast_0, line buffer),
                   hls_stream (conv3x3_accel_stream_0, dataflow+burst).

The board backends import pynq lazily and share one Overlay (see _load_overlay),
so importing this module never fails on a laptop and the PL is programmed once.
Ask for a backend with get_backend("pyloop" | "software" | "rtl" | "hls_naive" |
"hls_opt" | "hls_stream"); if the hardware/pynq is missing you get a clear
BackendUnavailable, not an ImportError.

Every backend works on a 2-D grayscale image. Colour is handled here in run() by
convolving each RGB channel independently and stacking the results - the hardware
stays simple (one grayscale datapath), and you still get a filtered colour image.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod

import numpy as np

from .core import Kernel, conv_reference, get_kernel, to_grayscale_u8


class BackendUnavailable(RuntimeError):
    """Raised when a backend cannot run in the current environment."""


# One Overlay per bitstream, shared by every FPGA backend. Programming the PL is
# slow and only needs to happen once; the RTL core (conv0) and the HLS accelerator
# (conv3x3_accel_0) live in the SAME bitstream, so the rtl and fpga backends both
# pull their IP out of this one Overlay instead of reprogramming the PL twice.
# Lazily imports pynq so this module still imports on a laptop.
_OVERLAY_CACHE: dict[str, object] = {}


def _load_overlay(bitfile: str | None):
    """Return a cached pynq Overlay for the bitstream, programming the PL once.

    Raises BackendUnavailable (not ImportError) off-board so callers get a clear
    message. The bitstream path defaults to $CONV3X3_BIT, then 'conv3x3.bit'.
    """
    try:
        from pynq import Overlay  # type: ignore
    except Exception as exc:  # ImportError on laptops; other errors off-board
        raise BackendUnavailable(
            "pynq is not available - the FPGA backends only run on the PYNQ board. "
            "Use the software backend on a laptop."
        ) from exc

    bitfile = bitfile or os.environ.get("CONV3X3_BIT", "conv3x3.bit")
    if bitfile not in _OVERLAY_CACHE:
        try:
            _OVERLAY_CACHE[bitfile] = Overlay(bitfile)
        except Exception as exc:
            raise BackendUnavailable(
                f"could not load bitstream '{bitfile}': {exc}"
            ) from exc
    return _OVERLAY_CACHE[bitfile]


def _overlay_contents(overlay) -> str:
    """A short 'name: type' listing of the overlay's IPs and hierarchies, for use
    in error messages so a name mismatch tells you what IS there. Best-effort."""
    try:
        ips = sorted(overlay.ip_dict)
    except Exception:
        ips = []
    try:
        hiers = sorted(overlay.hierarchy_dict)
    except Exception:
        hiers = []
    parts = []
    if ips:
        parts.append("IPs: " + ", ".join(ips))
    if hiers:
        parts.append("hierarchies: " + ", ".join(hiers))
    return "; ".join(parts) if parts else "(could not list overlay contents)"


class Backend(ABC):
    """A way to compute a 3x3 convolution of an image."""

    name: str = "base"

    @abstractmethod
    def _compute(self, image_u8: np.ndarray, kernel: Kernel) -> np.ndarray:
        """Return the 2-D uint8 convolution of a 2-D uint8 image."""

    def run(self, image, kernel, color: bool = False) -> tuple[np.ndarray, float]:
        """Convolve and return (output_image, elapsed_milliseconds).

        With color=True and an RGB image, each channel is filtered separately and
        the result is a colour image; otherwise the image is converted to
        grayscale first. Image conversion is done outside the timed region so the
        number reflects the convolution work, not bookkeeping.
        """
        kernel = get_kernel(kernel)
        arr = np.asarray(image)

        if color and arr.ndim == 3 and arr.shape[2] >= 3:
            channels = [np.ascontiguousarray(arr[:, :, c]).astype(np.uint8, copy=False)
                        for c in range(3)]
            t0 = time.perf_counter()
            out = [self._compute(ch, kernel) for ch in channels]
            t1 = time.perf_counter()
            return np.dstack(out), (t1 - t0) * 1e3

        image_u8 = to_grayscale_u8(arr)
        t0 = time.perf_counter()
        result = self._compute(image_u8, kernel)
        t1 = time.perf_counter()
        return result, (t1 - t0) * 1e3

    def close(self) -> None:  # overridden by backends that hold resources
        pass


class PyLoopBackend(Backend):
    """The first rung of the ladder: a pure-Python triple loop, no NumPy.

    Deliberately slow - it loops over every output pixel and every tap of the 3x3
    window in interpreted Python, which is exactly what you must NOT do, and exactly
    why the rest of the workshop exists. It is bit-exact with conv_reference (same
    zero padding, arithmetic floor-shift, optional magnitude, uint8 clip), so it
    still passes the design contract; it is just orders of magnitude slower. Keep the
    image small (e.g. 64x64) or it takes seconds.
    """

    name = "pyloop"

    def _compute(self, image_u8: np.ndarray, kernel: Kernel) -> np.ndarray:
        src = image_u8
        h, w = src.shape
        coeff = kernel.coeff
        shift = kernel.shift
        mode = kernel.mode
        out = np.empty((h, w), dtype=np.uint8)
        # plain Python: for each pixel, accumulate the nine taps by hand. No NumPy
        # in the inner loops - that is the whole point of this rung.
        for i in range(h):
            for j in range(w):
                acc = 0
                k = 0
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        yi = i + dy
                        xj = j + dx
                        if 0 <= yi < h and 0 <= xj < w:   # zero padding at the border
                            acc += coeff[k] * int(src[yi, xj])
                        k += 1
                v = acc >> shift                          # arithmetic (floor) shift
                if mode:
                    v = -v if v < 0 else v
                if v < 0:
                    v = 0
                elif v > 255:
                    v = 255
                out[i, j] = v
        return out


class SoftwareBackend(Backend):
    """Pure NumPy. The golden reference, and the laptop default."""

    name = "software"

    def _compute(self, image_u8: np.ndarray, kernel: Kernel) -> np.ndarray:
        return conv_reference(image_u8, kernel)


class FpgaBackend(Backend):
    """Drives the convolution accelerator in the PL via raw AXI-Lite MMIO.

    Board only. Construction programs the PL with the bitstream and locates the
    accelerator IP; run() DMA-streams an image through it.

    We talk to the HLS control slave by raw MMIO at the fixed byte offsets below,
    NOT through pynq's register_map. register_map is convenient but for this IP it
    recurses to a stack overflow on the board (a known pynq quirk with some HLS
    register layouts), so we drive the documented ap_ctrl_hs offsets directly -
    the same approach RtlBackend already uses for conv0. The offsets are the
    standard Vitis HLS s_axi_control map and are confirmed against ../../rtl/build/
    conv3x3.hwh (top function conv3x3_accel: pointers in_r / out_r / coeff, scalars
    shift / mode / height / width). If you regenerate the HLS IP and the layout
    moves, re-read them from the .hwh and update here.
    """

    name = "fpga"

    # buffer-reuse cache (class-level defaults so instances built via __new__ in the
    # off-board tests inherit them without running __init__): the in/out DMA buffers
    # are kept between calls and only reallocated when the image size changes.
    _in_buf = None
    _out_buf = None
    _buf_n = 0

    # HLS s_axi_control offsets (from conv3x3.hwh). Pointer args are 64-bit, split
    # into a low (_1) and high (_2) 32-bit word; on the 32-bit Zynq PS the high word
    # is always 0. CTRL bit0 = ap_start, bit1 = ap_done (clear-on-read).
    _CTRL = 0x00
    _IN_LO, _IN_HI = 0x10, 0x14
    _OUT_LO, _OUT_HI = 0x1C, 0x20
    _COEFF_LO, _COEFF_HI = 0x28, 0x2C
    _SHIFT = 0x34
    _MODE = 0x3C
    _HEIGHT = 0x44
    _WIDTH = 0x4C

    def __init__(self, bitfile: str | None = None, ip_name: str = "conv3x3_accel_0"):
        # Lazy import: keep this module importable on a laptop with no pynq.
        try:
            from pynq import allocate  # type: ignore
        except Exception as exc:  # ImportError on laptops; other errors off-board
            raise BackendUnavailable(
                "pynq is not available - the FPGA backend only runs on the PYNQ "
                "board. Use the software backend on a laptop."
            ) from exc

        self._allocate = allocate
        self._overlay = _load_overlay(bitfile)  # shared, programmed once
        try:
            self._accel = getattr(self._overlay, ip_name)
            self._mmio = self._accel.mmio
        except Exception as exc:
            raise BackendUnavailable(
                f"could not find IP '{ip_name}' in the bitstream: {exc}. "
                f"{_overlay_contents(self._overlay)} - set ip_name in BACKEND_KWARGS"
            ) from exc

        # a reusable coefficient buffer (9 signed bytes); image buffers are sized
        # per call since the image dimensions vary
        self._coeff_buf = self._allocate(shape=(9,), dtype=np.int8)

    def _write_ptr(self, lo_off: int, hi_off: int, addr: int) -> None:
        """Write a 64-bit pointer arg as two 32-bit words (high = 0 on Zynq-7000)."""
        self._mmio.write(lo_off, int(addr) & 0xFFFFFFFF)
        self._mmio.write(hi_off, (int(addr) >> 32) & 0xFFFFFFFF)

    def _buffers(self, n: int):
        """Return the cached (in, out) DMA buffers for an n-pixel image, allocating
        only when the size changes. Allocating CMA buffers is the dominant per-call
        cost at small sizes, so reusing them across runs is what makes the DMA path
        actually fast - and lets a benchmark or the clock ramp hit steady state."""
        if self._buf_n != n or self._in_buf is None:
            for old in (self._in_buf, self._out_buf):
                if old is not None:
                    try:
                        old.freebuffer()
                    except Exception:
                        pass
            self._in_buf = self._allocate(shape=(n,), dtype=np.uint8)
            self._out_buf = self._allocate(shape=(n,), dtype=np.uint8)
            self._buf_n = n
        return self._in_buf, self._out_buf

    def _compute(self, image_u8: np.ndarray, kernel: Kernel) -> np.ndarray:
        h, w = image_u8.shape
        n = h * w

        # DRAM the PL can reach (reused across calls). Fill it, then flush the ARM
        # cache so the PL, which reads DRAM directly, does not see stale bytes
        # (troubleshooting #4).
        in_buf, out_buf = self._buffers(n)
        in_buf[:] = image_u8.ravel()
        self._coeff_buf[:] = np.array(kernel.coeff, dtype=np.int8)
        in_buf.flush()
        self._coeff_buf.flush()

        # Hand the PL the physical addresses and the scalar parameters, then start.
        m = self._mmio
        self._write_ptr(self._IN_LO, self._IN_HI, in_buf.device_address)
        self._write_ptr(self._OUT_LO, self._OUT_HI, out_buf.device_address)
        self._write_ptr(self._COEFF_LO, self._COEFF_HI, self._coeff_buf.device_address)
        m.write(self._SHIFT, int(kernel.shift))
        m.write(self._MODE, int(kernel.mode))
        m.write(self._HEIGHT, int(h))
        m.write(self._WIDTH, int(w))

        m.write(self._CTRL, 0x1)                      # ap_start
        while (m.read(self._CTRL) & 0x2) == 0:        # wait for ap_done (troubleshooting #3)
            pass

        # The PL wrote the result to DRAM; invalidate the cache before we read it.
        out_buf.invalidate()
        return np.array(out_buf, dtype=np.uint8).reshape(h, w)

    def close(self) -> None:
        for buf in (self._coeff_buf, self._in_buf, self._out_buf):
            try:
                if buf is not None:
                    buf.freebuffer()
            except Exception:
                pass
        self._in_buf = self._out_buf = None
        self._buf_n = 0


class RtlBackend(Backend):
    """Drives the hand-written RTL core (conv0) over AXI-Lite, one pixel per write.

    Board only. The same SystemVerilog the workshop walks, exposed through the
    conv3x3_axi_lite register file. There is no DMA here: the PS streams the
    (zero-padded) frame into the PIX_IN register one MMIO write at a time and reads
    each finished pixel back out of OUT_DATA. That is deliberately the *slow* path;
    its job is to be legible and observable, not fast.

    conv0 is a block-design module reference, not a packaged IP, so it has no named
    register_map - we talk to it with raw MMIO at the byte offsets documented in
    conv3x3_axi_lite.sv. If you renamed the cell, pass ip_name.
    """

    name = "rtl"

    # register byte offsets (from conv3x3_axi_lite.sv)
    _CTRL = 0x00       # write bit1=1 -> clear window + counters
    _LINE_WIDTH = 0x08  # width of the zero-padded frame (= W + 2)
    _SHIFT = 0x0C
    _MODE = 0x10
    _PIX_IN = 0x14     # write a pixel; the write pulses pix_valid
    _OUT_DATA = 0x18   # most recent output pixel (data[7:0])
    _OUT_COUNT = 0x1C  # number of outputs since the last clear
    _COEF0 = 0x20      # c0 .. c8 at 0x20, 0x24, ... 0x40

    def __init__(self, bitfile: str | None = None, ip_name: str = "conv0"):
        self._overlay = _load_overlay(bitfile)  # shared, programmed once
        # conv0 is a BD module reference, not a packaged IP. Depending on the pynq
        # version and how the .hwh names it, ol.conv0 may be a DefaultIP (has .mmio),
        # a hierarchy (no .mmio), or absent from the attribute namespace entirely. So
        # we don't insist on getattr().mmio - the robust path is the address map: the
        # cell has one AXI-Lite slave at a fixed base, so build an MMIO over it directly.
        self._ip = getattr(self._overlay, ip_name, None)
        self._mmio = getattr(self._ip, "mmio", None)
        if self._mmio is None:
            self._mmio = self._mmio_from_addr_map(ip_name)

    def _mmio_from_addr_map(self, ip_name: str):
        """Build an MMIO over the cell's AXI-Lite window from the overlay's address
        map, when pynq did not hand us a DefaultIP with .mmio (module-ref cells)."""
        from pynq import MMIO  # type: ignore
        entry = None
        try:
            entry = self._overlay.ip_dict.get(ip_name)
        except Exception:
            entry = None
        if entry is None:  # also tolerate a 'conv0/<leaf>' style key
            try:
                entry = next(v for k, v in self._overlay.ip_dict.items()
                             if k == ip_name or k.startswith(ip_name + "/"))
            except StopIteration:
                entry = None
        if entry is None:
            raise BackendUnavailable(
                f"'{ip_name}' is not an addressable IP in this overlay. "
                f"{_overlay_contents(self._overlay)}. The board may be running an "
                f"OLDER bitstream where the RTL core was a hierarchy - re-copy "
                f"rtl/build/conv3x3.{{bit,hwh}} and reload. Or set ip_name in "
                f"BACKEND_KWARGS to the cell shown above."
            )
        base = entry.get("phys_addr", entry.get("base_address"))
        rng = entry.get("addr_range", 0x10000)
        return MMIO(base, rng)

    def _compute(self, image_u8: np.ndarray, kernel: Kernel) -> np.ndarray:
        h, w = image_u8.shape
        line_width = w + 2

        # The datapath only computes full 3x3 windows; we get same-size, zero-padded
        # output by streaming a frame already padded by one pixel on every side - the
        # exact contract the RTL expects (see conv3x3_core.sv "Borders / padding").
        padded = np.zeros((h + 2, w + 2), dtype=np.uint8)
        padded[1:-1, 1:-1] = image_u8
        stream = padded.ravel()

        m = self._mmio
        # load the kernel + frame geometry, then clear the window and counters
        m.write(self._LINE_WIDTH, int(line_width))
        m.write(self._SHIFT, int(kernel.shift))
        m.write(self._MODE, int(kernel.mode))
        for k, c in enumerate(kernel.coeff):
            m.write(self._COEF0 + 4 * k, int(c) & 0xFF)  # HW latches the low 8 bits
        m.write(self._CTRL, 0x2)  # clr pulse

        # Stream the frame one pixel per write. The core emits one output pixel per
        # *interior* input (row>=2 and col>=2), trailing the write by a few PL cycles
        # - far faster than an MMIO round-trip, so by the time we read OUT_COUNT the
        # output has landed. OUT_DATA only holds the latest pixel, so we read it the
        # moment the count ticks up. Outputs arrive in raster order = the HxW result.
        out = np.empty(h * w, dtype=np.uint8)
        idx = 0
        prev = 0
        for px in stream:
            m.write(self._PIX_IN, int(px))
            cnt = m.read(self._OUT_COUNT)
            if cnt != prev:
                out[idx] = m.read(self._OUT_DATA) & 0xFF
                idx += 1
                prev = cnt

        if idx != h * w:  # sanity: every interior pixel should have produced output
            raise RuntimeError(
                f"RTL core produced {idx} output pixels, expected {h * w} "
                f"(OUT_COUNT={prev}); check LINE_WIDTH / the padded frame size"
            )
        return out.reshape(h, w)


# Human-readable labels for the report, in the order the workshop tells the story:
# pure software, the legible RTL core, then the two HLS models - the naive one
# (bandwidth-bound, II=9) and the line-buffer one (II=1, the real fast path).
BACKEND_LABELS: dict[str, str] = {
    "pyloop": "Python loops",
    "software": "Software (NumPy)",
    "rtl": "RTL core (AXI-Lite, MMIO-streamed)",
    "hls_naive": "HLS naive (DMA, II=9)",
    "fpga": "HLS naive (DMA, II=9)",   # back-compat alias for hls_naive
    "hls_opt": "HLS line-buffer (DMA, II=1, mem-bound)",
    "hls_stream": "HLS streaming (DMA, II=1, dataflow+burst)",
}

# the HLS IP cell name each FPGA backend drives (the cells in rtl/build.tcl). All
# three share FpgaBackend and the same register offsets (same arg signature, so the
# Vitis HLS s_axilite layout is byte-identical) - only the cell name differs.
# 'hls_naive' is the canonical name for the naive accelerator; 'fpga' is kept as a
# back-compat alias (older notebooks / scripts).
_HLS_IP_NAMES: dict[str, str] = {
    "hls_naive": "conv3x3_accel_0",
    "fpga": "conv3x3_accel_0",
    "hls_opt": "conv3x3_accel_fast_0",
    "hls_stream": "conv3x3_accel_stream_0",
}


def available_backends() -> list[str]:
    """Names of backends that can actually run here, in story order.

    The pure-Python loop and NumPy backends are always available; the hardware
    backends (rtl, hls_naive, hls_opt line-buffer, hls_stream) only if pynq imports -
    i.e. on the board. Listed in ladder order. Used by the UI/report to decide what
    to offer.
    """
    names = ["pyloop", "software"]
    try:
        import pynq  # noqa: F401  (import-only probe)

        names += ["rtl", "hls_naive", "hls_opt", "hls_stream"]
    except Exception:
        pass
    return names


def get_backend(name: str, **kwargs) -> Backend:
    """Construct a backend by name ('pyloop', 'software', 'rtl', 'hls_naive', 'hls_opt', 'hls_stream').

    'pyloop' is the pure-Python triple loop (the slow first rung); 'software' is
    NumPy; 'hls_naive'/'fpga' is the naive HLS accelerator; 'hls_opt'/'fast' is the line-buffer
    one (II=1 in compute but memory-bound); 'hls_stream'/'stream' is the streaming
    dataflow+burst kernel that actually sustains ~1 pixel/clock. All three are
    FpgaBackend pointed at a different IP cell (filled in here unless the caller
    overrides ip_name).
    """
    name = name.lower()
    if name == "pyloop":
        return PyLoopBackend()
    if name == "software":
        return SoftwareBackend()
    if name == "rtl":
        return RtlBackend(**kwargs)
    if name in ("hls_naive", "fpga", "hls"):  # the naive HLS accelerator
        kwargs.setdefault("ip_name", _HLS_IP_NAMES["hls_naive"])
        return FpgaBackend(**kwargs)
    if name in ("hls_opt", "fast", "fpga_opt"):  # the line-buffer HLS accelerator
        kwargs.setdefault("ip_name", _HLS_IP_NAMES["hls_opt"])
        return FpgaBackend(**kwargs)
    if name in ("hls_stream", "stream"):  # the streaming (dataflow+burst) accelerator
        kwargs.setdefault("ip_name", _HLS_IP_NAMES["hls_stream"])
        return FpgaBackend(**kwargs)
    raise ValueError(
        f"unknown backend '{name}' (expected 'pyloop', 'software', 'rtl', "
        f"'hls_naive', 'hls_opt', or 'hls_stream')"
    )
