"""Core convolution helpers shared by every backend.

conv_reference is the golden reference for the whole workshop - the RTL testbench,
the HLS C-sim, and the FPGA hardware are all checked against this. The arithmetic
is defined to be bit-exact across all of them:

    S        = sum over the 3x3 window of  coeff[k] * pixel[k]   (zero-padded edges)
    v        = S >> shift                  (arithmetic / floor shift = divide by 2^shift)
    out(i,j) = clip( |v| if mode else v , 0, 255)               (uint8)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

KERNEL_SIZE = 3  # 3x3 convolution


@dataclass(frozen=True)
class Kernel:
    """A 3x3 convolution kernel: 9 signed integer coefficients, a divisor, a mode.

    coeff is row-major (coeff[0] = top-left .. coeff[8] = bottom-right).
    shift is a right-shift applied to the weighted sum (so shift=4 divides by 16).
    mode  is 0 for a signed clamp to [0,255], or 1 to take the magnitude first
          (used by edge kernels, whose output is naturally signed).
    """

    coeff: tuple[int, ...]
    shift: int = 0
    mode: int = 0
    name: str = ""
    description: str = ""

    def __post_init__(self):
        if len(self.coeff) != KERNEL_SIZE * KERNEL_SIZE:
            raise ValueError(f"a 3x3 kernel needs 9 coefficients, got {len(self.coeff)}")

    @property
    def matrix(self) -> np.ndarray:
        """The coefficients as a 3x3 int array (handy for display)."""
        return np.array(self.coeff, dtype=np.int32).reshape(KERNEL_SIZE, KERNEL_SIZE)


# The built-in kernels offered in the notebook. Each is "one conv layer" you can
# watch run on the hardware.
KERNELS: dict[str, Kernel] = {
    "identity": Kernel((0, 0, 0, 0, 1, 0, 0, 0, 0), 0, 0, "identity",
                       "passes the image through unchanged (sanity check)"),
    "blur": Kernel((1, 2, 1, 2, 4, 2, 1, 2, 1), 4, 0, "blur",
                   "Gaussian blur (divide by 16)"),
    "sharpen": Kernel((0, -1, 0, -1, 5, -1, 0, -1, 0), 0, 0, "sharpen",
                      "unsharp - boosts local contrast"),
    "edges": Kernel((-1, -1, -1, -1, 8, -1, -1, -1, -1), 0, 1, "edges",
                    "Laplacian edge detector (magnitude)"),
}


def to_grayscale_u8(image) -> np.ndarray:
    """Coerce an arbitrary image array to a 2-D uint8 grayscale image.

    Accepts a flat pixel vector, HxW, HxWx3 (RGB), or HxWx4 (RGBA). Anything
    already 8-bit and 1-/2-D is returned as-is. Uses the standard luma weights
    for colour input.
    """
    arr = np.asarray(image)

    if arr.ndim == 3:
        # drop alpha if present, then luma-weight the RGB channels
        rgb = arr[:, :, :3].astype(np.float32)
        gray = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        arr = gray
    elif arr.ndim not in (1, 2):
        raise ValueError(f"expected a 1-D, 2-D, or 3-D image, got shape {arr.shape}")

    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)

    return arr


def is_color(image) -> bool:
    """True if the array looks like an HxWx3/4 colour image."""
    arr = np.asarray(image)
    return arr.ndim == 3 and arr.shape[2] >= 3


def conv_reference(image_u8: np.ndarray, kernel: Kernel) -> np.ndarray:
    """The golden 3x3 convolution of a 2-D uint8 image.

    Same-size output with zero-padded borders. This is the definition every other
    implementation (RTL, HLS, FPGA) must match bit-for-bit.
    """
    src = np.asarray(image_u8)
    if src.ndim != 2:
        src = to_grayscale_u8(src)

    h, w = src.shape
    padded = np.zeros((h + 2, w + 2), dtype=np.int32)
    padded[1:-1, 1:-1] = src.astype(np.int32)

    acc = np.zeros((h, w), dtype=np.int32)
    k = 0
    for dy in range(KERNEL_SIZE):
        for dx in range(KERNEL_SIZE):
            if kernel.coeff[k]:
                acc += kernel.coeff[k] * padded[dy:dy + h, dx:dx + w]
            k += 1

    v = acc >> kernel.shift           # arithmetic (floor) shift, matches HW
    if kernel.mode:
        v = np.abs(v)
    return np.clip(v, 0, 255).astype(np.uint8)


def get_kernel(kernel) -> Kernel:
    """Accept a Kernel, or the name of a built-in one, and return a Kernel."""
    if isinstance(kernel, Kernel):
        return kernel
    if isinstance(kernel, str):
        try:
            return KERNELS[kernel]
        except KeyError:
            raise ValueError(
                f"unknown kernel '{kernel}' (choices: {', '.join(KERNELS)})"
            ) from None
    raise TypeError(f"expected a Kernel or kernel name, got {type(kernel).__name__}")
