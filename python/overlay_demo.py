#!/usr/bin/env python3
"""overlay_demo.py - the bare PYNQ overlay API.

Run this ON THE BOARD to show how little it takes to drive the PL from Python.
It is deliberately minimal and linear so you can read it top to bottom.

    python3 overlay_demo.py [path/to/image] [kernel]

kernel is one of: identity, blur, sharpen, edges (default: edges). If no image is
given it makes a synthetic gradient. Point at a bitstream with:
    CONV3X3_BIT=/home/xilinx/workshop/conv3x3.bit python3 overlay_demo.py cat.jpg edges

For the laptop-friendly version with a software fallback and a UI, see the Jupyter
notebook in notebooks/; this file is the no-abstraction, hardware-only teaching
script.
"""

import os
import sys
import time

import numpy as np
from pynq import Overlay, allocate  # board only

from fpga_conv.core import conv_reference, get_kernel, to_grayscale_u8


def load_image(path):
    if path:
        from PIL import Image

        return to_grayscale_u8(np.array(Image.open(path)))
    # synthetic fallback: a smooth gradient with a bright square to filter
    img = np.tile(np.linspace(0, 255, 256, dtype=np.uint8), (256, 1))
    img[96:160, 96:160] = 255
    return img


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    kname = sys.argv[2] if len(sys.argv) > 2 else "edges"
    kernel = get_kernel(kname)

    image = load_image(path)
    h, w = image.shape
    n = h * w

    # --- configure the PL with our circuit (this becomes the hardware) ---
    bitfile = os.environ.get("CONV3X3_BIT", "conv3x3.bit")
    ol = Overlay(bitfile)
    accel = ol.conv3x3_accel_0            # the naive HLS IP
    mmio = accel.mmio                     # raw AXI-Lite window (see offsets below)

    # --- DRAM both the PS and PL can see (shared memory over AXI) ---
    in_buf = allocate(shape=(n,), dtype=np.uint8)
    out_buf = allocate(shape=(n,), dtype=np.uint8)
    coeff_buf = allocate(shape=(9,), dtype=np.int8)
    in_buf[:] = image.ravel()
    coeff_buf[:] = np.array(kernel.coeff, dtype=np.int8)
    in_buf.flush()                        # push image out of the ARM cache to DRAM
    coeff_buf.flush()

    # --- poke the control registers and start the hardware ---
    # Byte offsets in the HLS s_axi_control window (from conv3x3.hwh). We use raw
    # MMIO rather than accel.register_map because register_map recurses to a stack
    # overflow on this board for this IP - a known pynq quirk. Pointer args are
    # 64-bit but the PS is 32-bit, so the high word is always 0. CTRL bit0 = ap_start,
    # bit1 = ap_done.
    CTRL, IN, OUT, COEFF, SHIFT, MODE, HEIGHT, WIDTH = (
        0x00, 0x10, 0x1C, 0x28, 0x34, 0x3C, 0x44, 0x4C)
    t0 = time.perf_counter()
    mmio.write(IN, in_buf.device_address)       # where to read pixels (physical address)
    mmio.write(OUT, out_buf.device_address)     # where to write the result
    mmio.write(COEFF, coeff_buf.device_address)
    mmio.write(SHIFT, int(kernel.shift))
    mmio.write(MODE, int(kernel.mode))
    mmio.write(HEIGHT, h)
    mmio.write(WIDTH, w)
    mmio.write(CTRL, 0x1)                        # ap_start
    while (mmio.read(CTRL) & 0x2) == 0:          # wait for the done bit
        pass
    out_buf.invalidate()                  # pull the result back from DRAM
    hw_ms = (time.perf_counter() - t0) * 1e3
    hw_out = np.array(out_buf, dtype=np.uint8).reshape(h, w)

    # --- compare against the NumPy reference on the PS ---
    t0 = time.perf_counter()
    sw_out = conv_reference(image, kernel)
    sw_ms = (time.perf_counter() - t0) * 1e3

    ok = np.array_equal(hw_out, sw_out)
    print(f"image: {image.shape}  ({n} pixels)   kernel: {kernel.name}")
    print(f"hardware: {hw_ms:8.3f} ms")
    print(f"software: {sw_ms:8.3f} ms")
    print(f"match: {'YES' if ok else 'NO'}")
    if not ok:
        diff = int(np.count_nonzero(hw_out != sw_out))
        print(f"  mismatching pixels: {diff}")

    in_buf.freebuffer()
    out_buf.freebuffer()
    coeff_buf.freebuffer()


if __name__ == "__main__":
    main()
