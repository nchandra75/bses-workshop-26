#!/usr/bin/env bash
# synth_timing.sh - convenience wrapper around synth_timing.tcl
# -----------------------------------------------------------------------------
# Push one RTL block through out-of-context synthesis and print its timing, then
# clean up the scratch files Vivado leaves behind. Run from the rtl/ directory.
#
#   ./synth_timing.sh conv3x3_core.sv
#   ./synth_timing.sh conv3x3_core_unpipelined.sv          # the slow one, fails
#   ./synth_timing.sh conv3x3_core.sv conv3x3_core 8.0     # try 125 MHz
#
# Args are passed straight through to synth_timing.tcl: <src> [top] [period_ns].
# -----------------------------------------------------------------------------
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: ./synth_timing.sh <src.sv> [top] [period_ns]" >&2
    exit 1
fi

export PATH=/tools/Xilinx/Vivado/2021.1/bin:$PATH

vivado -mode batch -source synth_timing.tcl -tclargs "$@"

# tidy up Vivado's batch droppings (keep the timing_*.rpt reports)
rm -rf .Xil vivado.jou vivado.log vivado*.backup.jou vivado*.backup.log \
       clockInfo.txt *.pb 2>/dev/null || true
