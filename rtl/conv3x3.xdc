# conv3x3.xdc
# -----------------------------------------------------------------------------
# Timing constraint for the convolution accelerator.
#
# In the normal flow this IP sits inside a block design and is clocked by the
# Zynq PS (FCLK_CLK0), so Vivado derives the clock automatically and no pin
# constraints are needed - the AXI-Lite interface connects to the PS internally,
# not to package pins.
#
# This file only declares the clock period so that out-of-context synthesis of
# the module on its own reports meaningful timing. 100 MHz is the default PYNQ-Z2
# FCLK - and the clock the Act 2 demo ramps past to make the design fail live.
# -----------------------------------------------------------------------------

create_clock -period 10.000 -name s_axi_aclk [get_ports s_axi_aclk]
