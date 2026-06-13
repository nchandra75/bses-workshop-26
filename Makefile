# Top-level Makefile - rebuild the whole workshop design from scratch.
#
# One operation made faster rung by rung; this drives the hardware half end to end
# so you do not have to remember the per-tool incantations.
#
#   make            # everything: HLS IPs -> combined bitstream
#   make hls        # just the three HLS accelerator IPs (csynth + export)
#   make bitstream  # the single .bit/.hwh (builds the HLS IPs first if needed)
#   make sim        # RTL testbench in xsim (prints PASS)
#   make csim       # quick g++ bit-exactness check of the HLS kernels (no Vitis)
#   make test       # the Python test suite (golden reference + backends)
#   make publish    # dry-run the clean public export (no push); see tools/publish.sh
#   make clean      # remove all generated build trees
#
# Tool locations can be overridden:  make VIVADO=... VITIS_HLS=...
# The bitstream + .hwh are intentionally NOT committed (see .gitignore); copy the
# pair in rtl/build/ to the board after a build.

PYTHON ?= .venv/bin/python

.PHONY: all hls bitstream sim csim test publish clean
all: bitstream

hls:
	$(MAKE) -C hls ip

bitstream: hls
	$(MAKE) -C rtl bitstream

sim:
	$(MAKE) -C rtl sim

csim:
	$(MAKE) -C hls csim

test:
	$(PYTHON) -m pytest python/ -q

publish:
	tools/publish.sh

clean:
	$(MAKE) -C hls clean
	$(MAKE) -C rtl clean
