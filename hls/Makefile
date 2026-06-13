# hls/Makefile - build the two HLS accelerator IPs (naive + line-buffer).
#
#   make            # csynth + export both IPs natively (what the bitstream needs)
#   make csim       # quick g++ bit-exactness check of both kernels (no Vitis)
#   make hls-csim   # full Vitis csim + cosim via the Docker wrapper
#   make clean      # remove the build/ tree
#
# Vitis HLS 2021.1 is expected at $(XILINX_VITIS_HLS); override on the command line
# if yours lives elsewhere:  make VITIS_HLS=/path/to/vitis_hls
XILINX_VITIS_HLS ?= /tools/Xilinx/Vitis_HLS/2021.1
VITIS_HLS        ?= $(XILINX_VITIS_HLS)/bin/vitis_hls

# the IP directories run_hls.tcl exports (the bitstream build reads these)
NAIVE_IP  := build/conv3x3_hls/sol1/impl/ip
FAST_IP   := build/conv3x3_fast_hls/sol1/impl/ip
STREAM_IP := build/conv3x3_stream_hls/sol1/impl/ip

.PHONY: all ip csim hls-csim clean
all: ip

# csynth + export both IPs (native: no host-binary link, so no Docker needed).
# Each IP is built in its OWN vitis_hls process: Vitis HLS 2021.1 corrupts the
# second export when two IPs are packaged in one session (the fast IP loses all but
# 3 of its 14 verilog files, breaking the Vivado synth). See run_hls.tcl.
ip: $(NAIVE_IP) $(FAST_IP) $(STREAM_IP)

$(NAIVE_IP): conv3x3.cpp conv3x3.hpp run_hls.tcl conv3x3_tb.cpp conv3x3_check.hpp
	$(VITIS_HLS) -f run_hls.tcl -tclargs naive

$(FAST_IP): conv3x3_fast.cpp conv3x3.hpp run_hls.tcl conv3x3_fast_tb.cpp conv3x3_check.hpp
	$(VITIS_HLS) -f run_hls.tcl -tclargs fast

$(STREAM_IP): conv3x3_stream.cpp conv3x3.hpp run_hls.tcl conv3x3_stream_tb.cpp conv3x3_check.hpp
	$(VITIS_HLS) -f run_hls.tcl -tclargs stream

# fast off-board correctness check - g++ ignores the HLS pragmas, so this just
# exercises the C++ logic against the golden reference. No Vitis, seconds to run.
# The streaming kernel uses hls::stream, whose software model is header-only, so it
# just needs the Vitis HLS include dir on g++'s path.
csim:
	@mkdir -p build
	g++ -std=c++14 -I. conv3x3.cpp        conv3x3_tb.cpp        -o build/csim_naive  && ./build/csim_naive
	g++ -std=c++14 -I. conv3x3_fast.cpp   conv3x3_fast_tb.cpp   -o build/csim_fast   && ./build/csim_fast
	g++ -std=c++14 -I. -I$(XILINX_VITIS_HLS)/include conv3x3_stream.cpp conv3x3_stream_tb.cpp -o build/csim_stream && ./build/csim_stream

# full Vitis C-sim + C/RTL co-sim (needs the ubuntu-20.04 userland in Docker)
hls-csim:
	./run-in-docker.sh

clean:
	rm -rf build
