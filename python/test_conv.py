"""Tests for the convolution software layer - runnable on any machine (no board).

These pin down the golden reference that the RTL testbench and HLS C-sim also
target, and they confirm the software backend and image handling behave.

    .venv/bin/python -m pytest python/ -q
"""

import numpy as np
import pytest

from fpga_conv import (
    KERNELS,
    Kernel,
    conv_reference,
    get_kernel,
    to_grayscale_u8,
    is_color,
    get_backend,
    available_backends,
    SoftwareBackend,
    PyLoopBackend,
)


def test_identity_is_passthrough():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, size=(20, 16), dtype=np.uint8)
    out = conv_reference(img, KERNELS["identity"])
    assert out.shape == img.shape
    assert out.dtype == np.uint8
    np.testing.assert_array_equal(out, img)


def test_blur_constant_interior():
    # a constant image blurred is unchanged in the interior (sum 16 >> 4 == value)
    img = np.full((8, 8), 16, dtype=np.uint8)
    out = conv_reference(img, KERNELS["blur"])
    np.testing.assert_array_equal(out[1:-1, 1:-1], np.full((6, 6), 16, dtype=np.uint8))


def test_edges_constant_interior_is_zero():
    # Laplacian of a flat region is zero in the interior (coeffs sum to 0). The
    # borders are non-zero because the zero padding looks like an edge there.
    img = np.full((10, 10), 123, dtype=np.uint8)
    out = conv_reference(img, KERNELS["edges"])
    np.testing.assert_array_equal(out[1:-1, 1:-1], np.zeros((8, 8), dtype=np.uint8))


def test_known_small_convolution():
    # a single bright pixel in a field of zeros, sharpened: center *5, neighbours *-1
    img = np.zeros((3, 3), dtype=np.uint8)
    img[1, 1] = 10
    out = conv_reference(img, KERNELS["sharpen"])
    assert out[1, 1] == 50            # 5 * 10
    assert out[0, 1] == 0             # -1 * 10 clamps up to 0
    assert out[0, 0] == 0             # corner not in the plus-shaped kernel


def test_clamp_high_and_low():
    img = np.full((3, 3), 200, dtype=np.uint8)
    img[1, 1] = 255
    out = conv_reference(img, KERNELS["sharpen"])  # can exceed 255 and drop below 0
    assert out.max() <= 255
    assert out.min() >= 0


def test_mode_abs_matches_manual():
    # a vertical step; edges (abs) must give a non-negative magnitude response
    img = np.zeros((5, 5), dtype=np.uint8)
    img[:, 2:] = 100
    out = conv_reference(img, KERNELS["edges"])
    assert out.dtype == np.uint8
    assert np.all(out >= 0)
    assert out.max() > 0              # there is an edge to detect


def test_arithmetic_shift_floor_on_negatives():
    # custom kernel that yields a negative sum, mode 0 (signed clamp -> 0)
    k = Kernel((0, 0, 0, 0, -1, 0, 0, 0, 0), shift=1, mode=0)
    img = np.full((3, 3), 6, dtype=np.uint8)
    out = conv_reference(img, k)
    # acc = -6; -6 >> 1 = -3 (floor); clamp to 0
    assert out[1, 1] == 0


def test_to_grayscale_passthrough():
    img = np.array([[0, 1], [2, 3]], dtype=np.uint8)
    np.testing.assert_array_equal(to_grayscale_u8(img), img)


def test_to_grayscale_rgb_and_rgba():
    rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    rgb[..., 0] = 255  # pure red
    gray = to_grayscale_u8(rgb)
    assert gray.shape == (4, 4)
    assert gray.dtype == np.uint8
    assert np.all(gray == round(0.299 * 255))

    rgba = np.dstack([rgb, np.full((4, 4), 128, np.uint8)])  # alpha must be ignored
    np.testing.assert_array_equal(to_grayscale_u8(rgba), gray)


def test_is_color():
    assert is_color(np.zeros((4, 4, 3), dtype=np.uint8))
    assert not is_color(np.zeros((4, 4), dtype=np.uint8))


def test_kernel_validates_length():
    with pytest.raises(ValueError):
        Kernel((1, 2, 3))


def test_get_kernel_by_name_and_object():
    assert get_kernel("blur") is KERNELS["blur"]
    k = KERNELS["edges"]
    assert get_kernel(k) is k
    with pytest.raises(ValueError):
        get_kernel("nonsense")


def test_software_backend_grayscale():
    backend = SoftwareBackend()
    img = np.full((10, 10), 42, dtype=np.uint8)
    out, ms = backend.run(img, "identity")
    np.testing.assert_array_equal(out, img)
    assert out.ndim == 2
    assert ms >= 0.0


def test_software_backend_color_keeps_three_channels():
    backend = SoftwareBackend()
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, size=(12, 12, 3), dtype=np.uint8)
    out, ms = backend.run(img, "blur", color=True)
    assert out.shape == (12, 12, 3)
    assert out.dtype == np.uint8
    # each channel must equal the per-channel reference
    for c in range(3):
        np.testing.assert_array_equal(out[:, :, c], conv_reference(img[:, :, c], KERNELS["blur"]))


def test_software_always_available():
    assert "software" in available_backends()


@pytest.mark.parametrize("kname", list(KERNELS))
def test_pyloop_backend_matches_reference(kname):
    # the slow first rung must still satisfy the design contract bit-for-bit
    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, size=(11, 13), dtype=np.uint8)
    out, ms = PyLoopBackend().run(img, kname)
    np.testing.assert_array_equal(out, conv_reference(img, KERNELS[kname]))
    assert out.dtype == np.uint8 and ms >= 0.0


def test_pyloop_always_available():
    assert "pyloop" in available_backends()


def test_get_backend_pyloop():
    assert isinstance(get_backend("pyloop"), PyLoopBackend)


def test_hls_naive_alias_resolves_to_same_ip():
    # 'hls_naive' is the canonical name; 'fpga' is the back-compat alias - both must
    # drive the same naive HLS accelerator cell.
    from fpga_conv.backends import _HLS_IP_NAMES
    assert _HLS_IP_NAMES["hls_naive"] == _HLS_IP_NAMES["fpga"] == "conv3x3_accel_0"


def test_get_backend_unknown():
    with pytest.raises(ValueError):
        get_backend("nonsense")


class _FakeConv0MMIO:
    """A functional model of the conv3x3_axi_lite register file + core.

    Mimics the byte-offset register map and the streaming/read-back semantics the
    RtlBackend drives, so the backend's MMIO logic can be exercised off-board. It
    reproduces the RTL contract: stream a zero-padded frame one pixel per PIX_IN
    write, an output appears (row>=2 and col>=2) and bumps OUT_COUNT, OUT_DATA holds
    the latest pixel. Arithmetic matches conv_reference.
    """

    CTRL, LINE_WIDTH, SHIFT, MODE, PIX_IN, OUT_DATA, OUT_COUNT, COEF0 = (
        0x00, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20)

    def __init__(self):
        self.coeff = [0] * 9
        self.shift = self.mode = self.lw = 0
        self.row = self.col = 0
        self.lb0, self.lb1 = {}, {}
        self.win = [[0] * 3 for _ in range(3)]
        self.out_count = self.out_data = 0

    def write(self, off, val):
        val &= 0xFFFFFFFF
        if self.COEF0 <= off <= self.COEF0 + 32:
            v = val & 0xFF
            self.coeff[(off - self.COEF0) // 4] = v - 256 if v >= 128 else v
        elif off == self.LINE_WIDTH:
            self.lw = val
        elif off == self.SHIFT:
            self.shift = val & 0x1F
        elif off == self.MODE:
            self.mode = val & 1
        elif off == self.CTRL and (val & 0x2):
            self.row = self.col = 0
            self.out_count = 0
            self.lb0, self.lb1 = {}, {}
            self.win = [[0] * 3 for _ in range(3)]
        elif off == self.PIX_IN:
            self._pix(val & 0xFF)

    def _pix(self, p):
        col = self.col
        col_top, col_mid, col_bot = self.lb0.get(col, 0), self.lb1.get(col, 0), p
        self.lb0[col], self.lb1[col] = self.lb1.get(col, 0), p
        op = [self.win[0][1], self.win[0][2], col_top,
              self.win[1][1], self.win[1][2], col_mid,
              self.win[2][1], self.win[2][2], col_bot]
        produce = self.row >= 2 and self.col >= 2
        self.win = [[self.win[0][1], self.win[0][2], col_top],
                    [self.win[1][1], self.win[1][2], col_mid],
                    [self.win[2][1], self.win[2][2], col_bot]]
        if produce:
            acc = sum(self.coeff[k] * op[k] for k in range(9))
            v = acc >> self.shift            # arithmetic floor shift
            if self.mode and v < 0:
                v = -v
            self.out_data = max(0, min(255, v))
            self.out_count += 1
        if self.col == self.lw - 1:
            self.col, self.row = 0, self.row + 1
        else:
            self.col += 1

    def read(self, off):
        return {self.OUT_COUNT: self.out_count, self.OUT_DATA: self.out_data}.get(off, 0)


@pytest.mark.parametrize("kname", ["identity", "blur", "sharpen", "edges"])
def test_rtl_backend_matches_reference(kname):
    # Drive the real RtlBackend against the functional register-file model; its
    # MMIO stream/read-back must reproduce the golden reference bit-for-bit.
    from fpga_conv import RtlBackend

    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, size=(17, 23), dtype=np.uint8)  # non-square on purpose
    backend = RtlBackend.__new__(RtlBackend)  # skip pynq-dependent __init__
    backend._mmio = _FakeConv0MMIO()

    out = backend._compute(img, KERNELS[kname])
    np.testing.assert_array_equal(out, conv_reference(img, KERNELS[kname]))


class _FakeBuffer(np.ndarray):
    """A pynq-allocate stand-in: a numpy array with a (fake) device_address and the
    cache no-ops the FpgaBackend calls. device_address is what gets written into the
    HLS pointer registers, so _FakeAccelMMIO can find this buffer again by address."""

    _next_addr = 0x10000000

    def __new__(cls, shape, dtype):
        obj = np.zeros(shape, dtype=dtype).view(cls)
        obj.device_address = _FakeBuffer._next_addr
        _FakeBuffer._next_addr += 0x10000
        _FAKE_DRAM[obj.device_address] = obj
        return obj

    def flush(self): pass
    def invalidate(self): pass
    def freebuffer(self): pass


_FAKE_DRAM: dict[int, np.ndarray] = {}


def _fake_allocate(shape, dtype):
    return _FakeBuffer(shape, dtype)


class _FakeAccelMMIO:
    """A functional model of the HLS conv3x3_accel s_axi_control slave + DMA.

    Records register writes at the same byte offsets FpgaBackend drives (the Vitis
    HLS map confirmed against conv3x3.hwh), and on ap_start reads the pointed-to
    DRAM buffers, runs conv_reference, and writes the result back to the out buffer -
    exactly what the real accelerator does. Exercises the backend's offset map and
    64-bit pointer handling off-board. read(CTRL) returns ap_done set."""

    CTRL, IN, OUT, COEFF, SHIFT, MODE, HEIGHT, WIDTH = (
        0x00, 0x10, 0x1C, 0x28, 0x34, 0x3C, 0x44, 0x4C)

    def __init__(self):
        self.reg: dict[int, int] = {}

    def write(self, off, val):
        self.reg[off] = val & 0xFFFFFFFF
        if off == self.CTRL and (val & 0x1):     # ap_start: run the "DMA"
            in_buf = _FAKE_DRAM[self.reg[self.IN]]
            out_buf = _FAKE_DRAM[self.reg[self.OUT]]
            coeff = _FAKE_DRAM[self.reg[self.COEFF]]
            h, w = self.reg[self.HEIGHT], self.reg[self.WIDTH]
            kernel = Kernel(tuple(int(c) for c in coeff),
                            shift=self.reg[self.SHIFT], mode=self.reg[self.MODE])
            out_buf[:] = conv_reference(in_buf.reshape(h, w), kernel).ravel()

    def read(self, off):
        if off == self.CTRL:
            return 0x2                            # ap_done always ready
        return self.reg.get(off, 0)


@pytest.mark.parametrize("kname", ["identity", "blur", "sharpen", "edges"])
def test_fpga_backend_matches_reference(kname):
    # Drive the real FpgaBackend against the functional accelerator model; its raw
    # MMIO offset map + 64-bit pointer writes must reproduce the golden reference.
    from fpga_conv import FpgaBackend

    rng = np.random.default_rng(11)
    img = rng.integers(0, 256, size=(17, 23), dtype=np.uint8)  # non-square on purpose
    backend = FpgaBackend.__new__(FpgaBackend)  # skip pynq-dependent __init__
    backend._allocate = _fake_allocate
    backend._mmio = _FakeAccelMMIO()
    backend._coeff_buf = _fake_allocate(shape=(9,), dtype=np.int8)

    out = backend._compute(img, KERNELS[kname])
    np.testing.assert_array_equal(out, conv_reference(img, KERNELS[kname]))
