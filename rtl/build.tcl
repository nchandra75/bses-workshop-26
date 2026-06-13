# build.tcl
# -----------------------------------------------------------------------------
# Build ONE PYNQ-Z2 bitstream that contains all THREE models the workshop shows:
#
#   * conv3x3_axi_lite   - the hand-written RTL core (Act 2): AXI-Lite only, fed one
#                          pixel per MMIO write, the legible/teaching path.
#   * conv3x3_accel      - the NAIVE Vitis HLS accelerator (Act 3): reads each
#                          pixel's neighbourhood from DRAM, II=9, bandwidth-bound.
#   * conv3x3_accel_fast - the LINE-BUFFER HLS accelerator (Act 3 payoff): streams
#                          each pixel from DRAM once, II=1 in compute - but byte-wide
#                          m_axi, so memory-bound at ~10 Mpix/s on the board.
#   * conv3x3_accel_stream - the STREAMING HLS accelerator: same line-buffer compute
#                          in a DATAFLOW read/compute/write pipeline so DRAM bursts
#                          and hides behind compute - sustains ~1 pixel/clock.
#
# All four sit in a single block design with the Zynq PS, so ONE .bit/.hwh pair
# drives every act. Which model runs is chosen from Python (all IPs always present).
# There is no embedded ILA: Act 2's hardware payoff is the live clock ramp from
# Python (Clocks.fclk0_mhz), which needs no JTAG. The conv0 nets still carry
# (* mark_debug *) so a future remote-ILA-over-XVC rebuild (see docs/observability.md)
# stays trivial, but nothing is inserted here. Generate the bitstream ahead of time.
#
#   cd rtl
#   vivado -mode batch -source build.tcl                 # the one and only build
#
# PREREQUISITE: the HLS IP must already be exported. Run it first:
#   cd ../hls && vitis_hls -f run_hls.tcl
# which leaves the IP in hls/build/conv3x3_hls/sol1/impl/ip. This script reads it
# from there. If it is missing the script stops with a clear message.
#
# Outputs (.bit + the .hwh PYNQ needs) land in rtl/build/.
#
# Toolchain: Vivado 2021.1 (installed under /tools/Xilinx). If you ever move to a
# different version, re-check the part/board names, the HLS IP VLNV, and the
# bd-automation config property names.
# -----------------------------------------------------------------------------

set part      "xc7z020clg400-1"
set proj_name "conv3x3_z2"
set build_dir "[file dirname [info script]]/build"
set src_dir   "[file dirname [info script]]"

# the two IPs exported by ../hls/run_hls.tcl: the naive accelerator and the
# line-buffer (fast) accelerator. Both must be present.
set hls_ip_repos [list \
    "$src_dir/../hls/build/conv3x3_hls/sol1/impl/ip" \
    "$src_dir/../hls/build/conv3x3_fast_hls/sol1/impl/ip" \
    "$src_dir/../hls/build/conv3x3_stream_hls/sol1/impl/ip" ]
foreach repo $hls_ip_repos {
    if {![file isdirectory $repo]} {
        puts "ERROR: HLS IP not found at $repo"
        puts "       Build it first:  cd ../hls && vitis_hls -f run_hls.tcl"
        exit 1
    }
}

file mkdir $build_dir
create_project $proj_name $build_dir/$proj_name -part $part -force

# Use the PYNQ-Z2 board preset if the board files are installed; otherwise the
# part-only flow below still works (the PS preset is applied explicitly).
catch {set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]}

# add the hand-written RTL sources. conv3x3_axi_lite_top.v is a thin Verilog
# wrapper: the block design's module reference (below) needs a Verilog/VHDL top,
# not SystemVerilog, so conv0 references the wrapper and the SV core sits under it.
add_files -norecurse [list \
    $src_dir/conv3x3_core.sv \
    $src_dir/conv3x3_axi_lite.sv \
    $src_dir/conv3x3_axi_lite_top.v ]
set_property file_type SystemVerilog [get_files *.sv]

# make the exported HLS IPs visible to the IP catalog
set_property ip_repo_paths $hls_ip_repos [current_project]
update_ip_catalog -rebuild

# ---- block design ----
create_bd_design "design_1"

# Zynq PS
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
# Part-only flow: NO board preset. The board files aren't installed here, and on
# PYNQ the PS (DDR, MIO, clocks) is configured at boot - the overlay only programs
# the PL - so the bitstream just needs the right PL-facing ports, not board-exact
# DDR timing. Make DDR + FIXED_IO external and disable the default AXI; we set the
# AXI config explicitly below. (Dropping apply_board_preset also avoids the
# "No current board_part set" path that left the HP enables unstuck.)
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} \
    [get_bd_cells ps7]
# one GP master (control path) and ONE HP slave: the NINE HLS masters (three each
# from the naive, line-buffer and streaming accelerators) share it through a single
# SmartConnect (built by the data-path automation below). The coeff masters are tiny
# and only one accelerator runs at a time, so even the streaming kernel's bursty
# image traffic stays well under one HP port's bandwidth - dedicated HP ports would
# just waste PS resources. (SmartConnect handles up to 16 masters, so nine is fine.)
set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} ] [get_bd_cells ps7]

# fail loudly and early if the HP slave didn't get created (tool/version quirk),
# instead of deep inside the axi4 automation with a misleading message
if {[llength [get_bd_intf_pins -of_objects [get_bd_cells ps7] \
                  -filter {NAME == S_AXI_HP0}]] == 0} {
    error "ps7 S_AXI_HP0 was not created - check the processing_system7 config"
}

# the hand-written RTL core (via its Verilog wrapper), referenced from the sources
create_bd_cell -type module -reference conv3x3_axi_lite_top conv0

# the three HLS accelerators from the exported IP. Cell names matter: the Python
# overlay finds them as ol.conv3x3_accel_0 (naive), ol.conv3x3_accel_fast_0 (line
# buffer) and ol.conv3x3_accel_stream_0 (streaming) - see python/fpga_conv/backends.py.
create_bd_cell -type ip -vlnv xilinx.com:hls:conv3x3_accel:1.0        conv3x3_accel_0
create_bd_cell -type ip -vlnv xilinx.com:hls:conv3x3_accel_fast:1.0   conv3x3_accel_fast_0
create_bd_cell -type ip -vlnv xilinx.com:hls:conv3x3_accel_stream:1.0 conv3x3_accel_stream_0

# the three HLS cells, used wherever we wire them all the same way
set hls_cells [get_bd_cells {conv3x3_accel_0 conv3x3_accel_fast_0 conv3x3_accel_stream_0}]

# ---- control path: PS GP0 master -> all four AXI-Lite slaves ----
# RTL core slave
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Master "/ps7/M_AXI_GP0" Clk "Auto"} \
    [get_bd_intf_pins conv0/s_axi]
# the three HLS control slaves (port name is s_axi_control; find by mode to stay robust)
foreach ctrl [get_bd_intf_pins -of_objects $hls_cells -filter {MODE == Slave}] {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
        -config {Master "/ps7/M_AXI_GP0" Clk "Auto"} \
        [get_bd_intf_pins $ctrl]
}

# ---- data path: all nine HLS m_axi masters -> the one HP slave ----
# Pattern from a known-good DMA->HP design: the FIRST master creates a NEW
# interconnect (pass the HP slave as the object), each subsequent master joins that
# SAME interconnect by name (/axi_mem_intercon, Vivado's auto-name for it). The
# earlier failure used intc_ip {Auto}, which made the rule try to reuse the
# control-path interconnect (the /conv0/s_axi one) - hence the misleading error.
set hls_masters [lsort [get_bd_intf_pins -of_objects $hls_cells \
                            -filter {MODE == Master}]]

# first master: object is the HP slave pin; create the memory interconnect
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config [list Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} \
                 Master [lindex $hls_masters 0] Slave "/ps7/S_AXI_HP0" \
                 intc_ip "New AXI Interconnect" master_apm "0"] \
    [get_bd_intf_pins ps7/S_AXI_HP0]

# remaining masters: object is the master pin; join /axi_mem_intercon
foreach m [lrange $hls_masters 1 end] {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
        -config [list Master $m Slave "/ps7/S_AXI_HP0" \
                     intc_ip "/axi_mem_intercon" master_apm "0"] \
        [get_bd_intf_pins $m]
}

# address assignment
assign_bd_address
regenerate_bd_layout
validate_bd_design
save_bd_design

# ---- HDL wrapper ----
make_wrapper -files [get_files design_1.bd] -top
add_files -norecurse $build_dir/$proj_name/$proj_name.gen/sources_1/bd/design_1/hdl/design_1_wrapper.v
set_property top design_1_wrapper [current_fileset]

# ---- synth, impl, bitstream ----
# wait_on_run returns even when the run FAILED inside its runme.log, and the script
# would otherwise sail on and "finish" with no bitstream. Check each run explicitly
# and stop loudly, pointing at the log.
proc check_run {run} {
    set progress [get_property PROGRESS [get_runs $run]]
    set status   [get_property STATUS   [get_runs $run]]
    if {$progress ne "100%"} {
        error "$run did not complete (progress $progress, status '$status').\
               See [get_property DIRECTORY [get_runs $run]]/runme.log"
    }
}

launch_runs synth_1 -jobs 4
wait_on_run synth_1
check_run synth_1

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
check_run impl_1

# ---- collect outputs (.bit + .hwh) next to each other for PYNQ ----
set bit  [glob -nocomplain $build_dir/$proj_name/$proj_name.runs/impl_1/*.bit]
set hwh  [glob -nocomplain $build_dir/$proj_name/$proj_name.gen/sources_1/bd/design_1/hw_handoff/*.hwh]
set out_base "$build_dir/conv3x3"
if {[llength $bit] > 0} { file copy -force [lindex $bit 0] "$out_base.bit" }
if {[llength $hwh] > 0} { file copy -force [lindex $hwh 0] "$out_base.hwh" }

puts "DONE. conv3x3.bit / .hwh in $build_dir (single combined bitstream)."
