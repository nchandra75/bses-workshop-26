# rtl/Makefile - simulate the RTL core and build the combined bitstream.
#
#   make            # build the single bitstream (RTL core + both HLS accelerators)
#   make sim        # run the SystemVerilog testbench in xsim (prints PASS)
#   make timing     # out-of-context synth of conv3x3_core.sv, print the slack
#   make clean      # remove the build/ tree and sim/journal junk
#
# The bitstream depends on the two HLS IPs; if they are missing this calls the hls
# Makefile to build them first. Vivado 2021.1 is expected at $(XILINX_VIVADO).
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2021.1
VIVADO        ?= $(XILINX_VIVADO)/bin/vivado

HLS_NAIVE_IP := ../hls/build/conv3x3_hls/sol1/impl/ip
HLS_FAST_IP  := ../hls/build/conv3x3_fast_hls/sol1/impl/ip
RTL_SRC      := conv3x3_core.sv conv3x3_axi_lite.sv conv3x3_axi_lite_top.v
BIT          := build/conv3x3.bit

.PHONY: all bitstream sim timing clean
all: bitstream
bitstream: $(BIT)

# one combined .bit/.hwh from the RTL sources + both exported HLS IPs
$(BIT): build.tcl $(RTL_SRC) $(HLS_NAIVE_IP) $(HLS_FAST_IP)
	$(VIVADO) -mode batch -source build.tcl

# build the HLS IPs on demand if the export directories are missing
$(HLS_NAIVE_IP) $(HLS_FAST_IP):
	$(MAKE) -C ../hls ip

sim:
	$(VIVADO) -mode batch -source sim.tcl

timing:
	./synth_timing.sh conv3x3_core.sv

clean:
	rm -rf build .Xil xsim.dir *.jou *.log *.pb *.wdb webtalk*
