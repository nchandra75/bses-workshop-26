#!/usr/bin/env bash
# Run the full HLS flow (csim + cosim + csynth + export) inside a container whose
# userland the Vitis HLS 2021.1 toolchain can actually link against. The toolchain
# is bind-mounted from the host; nothing is copied into the image.
#
# Why: this box (Debian forky/sid, glibc 2.42) is too new - the bundled
# binutils-2.26 can't read its .so files (.relr.dyn). csynth/export work natively;
# only csim/cosim need this. See run_hls.tcl.
#
#   ./run-in-docker.sh            # csim + cosim + csynth + export
#   ./run-in-docker.sh csim       # just add csim (skip cosim)
set -euo pipefail
cd "$(dirname "$0")"

# what to run; default to both sim steps
args="${*:-csim cosim}"

xilinx_root="${XILINX_ROOT:-/tools/Xilinx}"
hls_settings="$xilinx_root/Vitis_HLS/2021.1/settings64.sh"

docker build -t workshop-hls:2021.1 .

# -u keeps build/ owned by the host user; HOME must be writable for vitis_hls.
docker run --rm -t \
    -v "$xilinx_root":"$xilinx_root":ro \
    -v "$PWD":/work -w /work \
    -u "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    workshop-hls:2021.1 \
    bash -lc "source '$hls_settings' && vitis_hls -f run_hls.tcl -tclargs $args"
