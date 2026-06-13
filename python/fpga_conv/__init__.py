"""fpga_conv - the Python layer for the 3x3 convolution accelerator.

A ladder of backends behind one interface, from slowest to fastest:

  - PyLoopBackend:   pure-Python triple loop. The slow first rung. Runs anywhere.
  - SoftwareBackend: pure NumPy. The golden reference. Runs anywhere.
  - RtlBackend:      the hand-written RTL core over AXI-Lite MMIO. Board only.
  - FpgaBackend:     drives an HLS accelerator (naive / line-buffer / streaming) in
                     the PL over the PYNQ overlay API. Board only.

The same code (the notebook series, bench.py) runs on a laptop (the two software
rungs) or on the board (all of them), because everything talks to the Backend
interface, not to pynq directly. See backends.py.
"""

from .core import (
    KERNEL_SIZE,
    KERNELS,
    Kernel,
    conv_reference,
    get_kernel,
    is_color,
    to_grayscale_u8,
)
from .backends import (
    Backend,
    PyLoopBackend,
    SoftwareBackend,
    RtlBackend,
    FpgaBackend,
    BackendUnavailable,
    get_backend,
    available_backends,
    BACKEND_LABELS,
)

__all__ = [
    "KERNEL_SIZE",
    "KERNELS",
    "Kernel",
    "conv_reference",
    "get_kernel",
    "is_color",
    "to_grayscale_u8",
    "Backend",
    "PyLoopBackend",
    "SoftwareBackend",
    "RtlBackend",
    "FpgaBackend",
    "BackendUnavailable",
    "get_backend",
    "available_backends",
    "BACKEND_LABELS",
]
