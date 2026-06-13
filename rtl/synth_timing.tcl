# synth_timing.tcl
# -----------------------------------------------------------------------------
# Take ONE RTL block out-of-context (no board, no block design, no AXI), synth it
# for the PYNQ-Z2 part against a single clock, and report timing. This is the
# fast way to see whether a module meets the clock and, if it doesn't, where the
# slow path is - the whole point of the "pipeline it vs don't" demo in Act 2.
#
#   cd rtl
#   vivado -mode batch -source synth_timing.tcl -tclargs <src.sv> [top] [period_ns]
#
# Examples:
#   vivado -mode batch -source synth_timing.tcl -tclargs conv3x3_core.sv
#   vivado -mode batch -source synth_timing.tcl -tclargs conv3x3_core_unpipelined.sv
#   vivado -mode batch -source synth_timing.tcl -tclargs conv3x3_core.sv conv3x3_core 8.0
#
# Args:
#   src       (required) the .sv/.v file to synth (relative to cwd or absolute)
#   top       (optional) top module name           [default conv3x3_core]
#   period_ns (optional) target clock period in ns  [default 10.0 = 100 MHz]
#
# It writes a full timing-summary report next to the source as
#   timing_<top>.<srcbasename>.rpt
# and prints the worst-case slack (WNS) and the slow path to the console. A
# POSITIVE WNS means the block meets the clock; NEGATIVE means it is too slow and
# needs pipelining (or a slower clock). This is OUT-OF-CONTEXT: routing is only
# estimated, so treat the number as a strong indicator, not the final word - the
# full build.tcl run is what signs it off. But the sign, and the slow path, are
# already meaningful here.
#
# Clock assumption: the module is expected to have a port literally named `clk`.
# Any input that is not `clk` is given a relaxed input delay so I/O paths do not
# masquerade as the critical path - we only care about the register-to-register
# logic inside the block.
# -----------------------------------------------------------------------------

set part xc7z020clg400-1

# ---- parse args ----
if {[llength $argv] < 1} {
    puts "ERROR: need a source file. Usage:"
    puts "  vivado -mode batch -source synth_timing.tcl -tclargs <src.sv> \[top\] \[period_ns\]"
    exit 1
}
set src    [lindex $argv 0]
set top    [expr {[llength $argv] >= 2 ? [lindex $argv 1] : "conv3x3_core"}]
set period [expr {[llength $argv] >= 3 ? [lindex $argv 2] : 10.0}]

if {![file exists $src]} {
    puts "ERROR: source file not found: $src"
    exit 1
}

puts "==== OOC synth: $top  <-  $src  @ ${period} ns ([format %.1f [expr {1000.0/$period}]] MHz) ===="

# ---- synth out of context ----
read_verilog -sv $src
synth_design -top $top -part $part -mode out_of_context

# ---- constrain: one clock on `clk`, relaxed delays on the other ports ----
create_clock -name clk -period $period [get_ports clk]
set in_ports  [filter [all_inputs]  {NAME != clk}]
set out_ports [all_outputs]
# small, fixed I/O budget so internal reg-to-reg logic is what shows up as worst
if {[llength $in_ports]  > 0} { set_input_delay  -clock clk 1.0 $in_ports }
if {[llength $out_ports] > 0} { set_output_delay -clock clk 1.0 $out_ports }

# ---- report ----
set rpt "timing_$top.[file rootname [file tail $src]].rpt"
report_timing_summary -delay_type max -max_paths 1 -file $rpt

set paths [get_timing_paths -max_paths 1 -nworst 1 -setup]
if {[llength $paths] == 0} {
    puts "RESULT: no internal timing paths found (purely combinational?)."
    exit 0
}
set p    [lindex $paths 0]
set wns  [get_property SLACK $p]
set src_pin [get_property STARTPOINT_PIN  $p]
set dst_pin [get_property ENDPOINT_PIN    $p]
set levels  [get_property LOGIC_LEVELS    $p]
set delay   [get_property DATAPATH_DELAY  $p]

puts "------------------------------------------------------------------"
puts "  target period : ${period} ns"
puts "  worst slack   : ${wns} ns  ([expr {$wns >= 0 ? "MET - meets the clock" : "VIOLATED - too slow, pipeline it"}])"
puts "  slow path     : $src_pin"
puts "             ->   $dst_pin"
puts "  logic levels  : $levels        datapath delay : ${delay} ns"
puts "  full report   : rtl/$rpt"
puts "------------------------------------------------------------------"
