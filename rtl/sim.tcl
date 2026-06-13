# sim.tcl
# -----------------------------------------------------------------------------
# Run the self-checking conv3x3_core testbench in Vivado's simulator (xsim), in
# batch mode, no GUI. Prints PASS/FAIL to the console.
#
#   cd rtl
#   vivado -mode batch -source sim.tcl
#
# An optional argument picks which core source to compile (default conv3x3_core.sv).
# Both the pipelined core and conv3x3_core_unpipelined.sv share the module name
# conv3x3_core, so the same testbench drives either - handy for showing the class
# that the slow, un-pipelined version is bit-identical in simulation yet fails
# timing in synth (see synth_timing.tcl):
#   vivado -mode batch -source sim.tcl -tclargs conv3x3_core_unpipelined.sv
#
# To watch the waveform interactively in Act 2, open the Vivado GUI instead,
# add conv3x3_core.sv + tb_conv3x3_core.sv to a project, set tb_conv3x3_core as
# the simulation top, and Run Simulation. Add pix_valid, pix_data, dut.win[...],
# out_valid, and out_data to the wave window: watch the window slide across the
# stream and an output pixel pop out a cycle later.
# -----------------------------------------------------------------------------

set src_dir [file dirname [info script]]

# which core to simulate (default the shipping pipelined one)
set core [expr {[llength $argv] >= 1 ? [lindex $argv 0] : "conv3x3_core.sv"}]

# compile
exec xvlog -sv \
    [file join $src_dir $core] \
    [file join $src_dir tb_conv3x3_core.sv] >@ stdout

# elaborate
exec xelab -debug typical tb_conv3x3_core -s tb_sim >@ stdout

# run
exec xsim tb_sim -runall >@ stdout
