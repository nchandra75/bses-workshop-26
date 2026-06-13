# run_hls.tcl
# -----------------------------------------------------------------------------
# Vitis HLS flow for BOTH convolution accelerators: C simulation, C synthesis, and
# IP export. Run from the hls/ directory:
#
#   cd hls
#   vitis_hls -f run_hls.tcl
#
# This builds three IPs from the same contract:
#   * conv3x3_accel        (conv3x3.cpp)        - NAIVE: re-reads the neighbourhood
#                                                 from DRAM per pixel, II=9, the
#                                                 "HLS is not a free lunch" exhibit.
#   * conv3x3_accel_fast   (conv3x3_fast.cpp)   - LINE BUFFER: streams each pixel
#                                                 from DRAM once, II=1 in compute -
#                                                 but byte-wide m_axi, so memory-bound.
#   * conv3x3_accel_stream (conv3x3_stream.cpp) - STREAMING: same line-buffer compute
#                                                 in a DATAFLOW read/compute/write
#                                                 pipeline so DRAM bursts and hides
#                                                 behind compute - the sustained path.
#
# Exported IP lands at:
#   build/conv3x3_hls/sol1/impl/ip            (naive)
#   build/conv3x3_fast_hls/sol1/impl/ip       (line buffer)
#   build/conv3x3_stream_hls/sol1/impl/ip     (streaming)
# ../rtl/build.tcl reads all three from there and assembles ONE bitstream that
# carries the RTL core plus the three HLS accelerators (see docs/instructor-setup.md).
#
# Synthesis reports for the Act 3 II / DSP / BRAM comparison:
#   build/conv3x3_hls/sol1/syn/report/conv3x3_accel_csynth.rpt
#   build/conv3x3_fast_hls/sol1/syn/report/conv3x3_accel_fast_csynth.rpt
#   build/conv3x3_stream_hls/sol1/syn/report/conv3x3_accel_stream_csynth.rpt
# -----------------------------------------------------------------------------

set part "xc7z020clg400-1"

# Vitis HLS won't accept a '/' in the project name, so the output location is set
# by the working directory: make build/ and run from inside it.
file mkdir build
cd build

# Vitis HLS 2021.1 ships gcc 6.2.0, which doesn't search Debian's multiarch include
# dir, so its bundled libc headers fail to find bits/wordsize.h. Point the compiler
# at it, and at .. so the sources find their headers. (-cflags covers csim+csynth.)
set cflags "-I/usr/include/x86_64-linux-gnu -I.."

# csim and cosim LINK a host executable, which the toolchain's bundled binutils-2.26
# cannot do against this box's glibc (forky/sid uses .relr.dyn relocations it doesn't
# understand). So they are OFF by default and only run when asked, via the Docker
# wrapper (./run-in-docker.sh) which provides a compatible ubuntu-20.04 userland.
# csynth + IP export do NOT link a host binary and run fine natively - which is all
# ../rtl/build.tcl needs. (For a quick correctness check off-board with no Vitis at
# all, just: g++ -std=c++14 conv3x3_fast.cpp conv3x3_fast_tb.cpp && ./a.out)
#
#   vitis_hls -f run_hls.tcl                      # native: csynth + export both
#   ./run-in-docker.sh                            # adds csim + cosim
set do_csim  [expr {[lsearch $argv "csim"]  >= 0}]
set do_cosim [expr {[lsearch $argv "cosim"] >= 0}]
set ldflags "-L/usr/lib/x86_64-linux-gnu"

# IMPORTANT: export_design in Vitis HLS 2021.1 must NOT package two IPs in the same
# vitis_hls process. Building the naive IP first leaves catalog state that makes the
# SECOND export drop almost every submodule from the IP's component.xml (the fast IP
# came out with only 3 of its 14 verilog files, so Vivado synth failed with "module
# conv3x3_accel_fast_lb0 not found"). Each IP must be exported in its own process.
# So the Makefile calls this script once per IP with a selector token ('naive' or
# 'fast'); with no token we build both in one session (kept only for the Docker
# csim/cosim path, where the exported IPs are not what feeds the bitstream).
set want_naive  [expr {[lsearch $argv "naive"]  >= 0}]
set want_fast   [expr {[lsearch $argv "fast"]   >= 0}]
set want_stream [expr {[lsearch $argv "stream"] >= 0}]
if {!$want_naive && !$want_fast && !$want_stream} {
    set want_naive 1; set want_fast 1; set want_stream 1
}

# Build one IP: open project, set top, add source + its tb, synth/sim/export.
proc build_ip {proj top src tb} {
    global part cflags ldflags do_csim do_cosim
    puts "==== HLS: building $top from $src ===="
    open_project -reset $proj
    set_top $top
    add_files ../$src -cflags $cflags
    add_files -tb ../$tb -cflags $cflags

    open_solution -reset "sol1"
    set_part $part
    create_clock -period 10 -name default       ;# 100 MHz, matches the PYNQ-Z2 FCLK

    if {$do_csim} { csim_design -ldflags $ldflags }
    csynth_design
    if {$do_cosim} { cosim_design -ldflags $ldflags }
    export_design -format ip_catalog
    close_project
}

if {$want_naive}  { build_ip conv3x3_hls        conv3x3_accel        conv3x3.cpp        conv3x3_tb.cpp }
if {$want_fast}   { build_ip conv3x3_fast_hls   conv3x3_accel_fast   conv3x3_fast.cpp   conv3x3_fast_tb.cpp }
if {$want_stream} { build_ip conv3x3_stream_hls conv3x3_accel_stream conv3x3_stream.cpp conv3x3_stream_tb.cpp }

exit
