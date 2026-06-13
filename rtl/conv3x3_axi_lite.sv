// conv3x3_axi_lite.sv
// -----------------------------------------------------------------------------
// AXI4-Lite wrapper around conv3x3_core - the "contract over AXI": the PS
// (Python) writes the kernel and streams pixels into these registers, and the PL
// (our convolution datapath) reacts.
//
// Register map (byte offset from the IP base address):
//   0x00  CTRL       (W)  write bit1=1 to clear the window + counters (1-cycle pulse)
//   0x04  STATUS     (R)  bit0 = ready (always 1 in this simple streaming model)
//   0x08  LINE_WIDTH (RW) width of the zero-padded frame being streamed (= W + 2)
//   0x0C  SHIFT      (RW) right-shift applied to the MAC sum (the kernel divisor)
//   0x10  MODE       (RW) bit0: 0 = signed clamp, 1 = abs then clamp (edge kernels)
//   0x14  PIX_IN     (W)  write a pixel in data[7:0]; the write pulses pix_valid
//   0x18  OUT_DATA   (R)  the most recent output pixel produced (data[7:0])
//   0x1C  OUT_COUNT  (R)  number of output pixels produced since the last clear
//   0x20  COEF0      (RW) kernel coefficient c0 (top-left), signed in data[7:0]
//   ...                   c1 .. c7
//   0x40  COEF8      (RW) kernel coefficient c8 (bottom-right), signed in data[7:0]
//
// This feeds pixels one MMIO write at a time, which is deliberately simple
// (great for teaching and small frames; the read-back registers let Python watch
// the datapath) and deliberately
// not high-throughput. The fast path - reading the whole image from DRAM over an
// AXI master - is the HLS kernel in ../hls.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps

module conv3x3_axi_lite #(
    parameter int C_S_AXI_DATA_WIDTH = 32,
    parameter int C_S_AXI_ADDR_WIDTH = 7    // 128 bytes of register space (32 words)
) (
    // AXI4-Lite slave interface
    input  logic                              s_axi_aclk,
    input  logic                              s_axi_aresetn,

    input  logic [C_S_AXI_ADDR_WIDTH-1:0]     s_axi_awaddr,
    input  logic [2:0]                        s_axi_awprot,
    input  logic                              s_axi_awvalid,
    output logic                              s_axi_awready,

    input  logic [C_S_AXI_DATA_WIDTH-1:0]     s_axi_wdata,
    input  logic [(C_S_AXI_DATA_WIDTH/8)-1:0] s_axi_wstrb,
    input  logic                              s_axi_wvalid,
    output logic                              s_axi_wready,

    output logic [1:0]                        s_axi_bresp,
    output logic                              s_axi_bvalid,
    input  logic                              s_axi_bready,

    input  logic [C_S_AXI_ADDR_WIDTH-1:0]     s_axi_araddr,
    input  logic [2:0]                        s_axi_arprot,
    input  logic                              s_axi_arvalid,
    output logic                              s_axi_arready,

    output logic [C_S_AXI_DATA_WIDTH-1:0]     s_axi_rdata,
    output logic [1:0]                        s_axi_rresp,
    output logic                              s_axi_rvalid,
    input  logic                              s_axi_rready
);

    // ---- register offsets (word index = addr[6:2]) ----
    localparam int ADDR_LSB = 2;
    localparam logic [4:0] REG_CTRL       = 5'h00;  // 0x00
    localparam logic [4:0] REG_STATUS     = 5'h01;  // 0x04
    localparam logic [4:0] REG_LINE_WIDTH = 5'h02;  // 0x08
    localparam logic [4:0] REG_SHIFT      = 5'h03;  // 0x0C
    localparam logic [4:0] REG_MODE       = 5'h04;  // 0x10
    localparam logic [4:0] REG_PIX_IN     = 5'h05;  // 0x14
    localparam logic [4:0] REG_OUT_DATA   = 5'h06;  // 0x18
    localparam logic [4:0] REG_OUT_COUNT  = 5'h07;  // 0x1C
    localparam logic [4:0] REG_COEF0      = 5'h08;  // 0x20 .. 0x40 (c0..c8)

    // ---- AXI write channel ----
    logic                          axi_awready, axi_wready, axi_bvalid;
    logic [C_S_AXI_ADDR_WIDTH-1:0] axi_awaddr;

    wire write_en = axi_awready & s_axi_awvalid & axi_wready & s_axi_wvalid;

    always_ff @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            axi_awready <= 1'b0;
            axi_wready  <= 1'b0;
            axi_awaddr  <= '0;
            axi_bvalid  <= 1'b0;
        end else begin
            if (!axi_awready && s_axi_awvalid && s_axi_wvalid) begin
                axi_awready <= 1'b1;
                axi_awaddr  <= s_axi_awaddr;
            end else begin
                axi_awready <= 1'b0;
            end

            if (!axi_wready && s_axi_wvalid && s_axi_awvalid) begin
                axi_wready <= 1'b1;
            end else begin
                axi_wready <= 1'b0;
            end

            if (write_en) begin
                axi_bvalid <= 1'b1;
            end else if (s_axi_bready && axi_bvalid) begin
                axi_bvalid <= 1'b0;
            end
        end
    end

    // ---- register file writes + control pulses ----
    logic                            clr_pulse;
    // mark_debug kept so a future remote-ILA-over-XVC rebuild can probe these nets
    // without relying on net-naming (see docs/observability.md). The current build
    // inserts no ILA - the hardware demo is the live clock ramp instead.
    (* mark_debug = "true" *) logic            pix_valid;
    (* mark_debug = "true" *) logic [7:0]      pix_data;
    logic [11:0]                     line_width;
    logic [4:0]                      shift;
    logic                            mode;
    logic signed [7:0]               coeff [0:8];

    wire [4:0] waddr_word = axi_awaddr[ADDR_LSB+4 : ADDR_LSB];

    always_ff @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            clr_pulse  <= 1'b0;
            pix_valid  <= 1'b0;
            pix_data   <= '0;
            line_width <= 12'd0;
            shift      <= 5'd0;
            mode       <= 1'b0;
            for (int i = 0; i < 9; i++) coeff[i] <= 8'sd0;
        end else begin
            // pulses are one cycle wide: clear them every cycle by default
            clr_pulse <= 1'b0;
            pix_valid <= 1'b0;

            if (write_en) begin
                if (waddr_word >= REG_COEF0 && waddr_word <= REG_COEF0 + 5'd8) begin
                    coeff[waddr_word - REG_COEF0] <= s_axi_wdata[7:0];
                end else begin
                    unique case (waddr_word)
                        REG_CTRL:       clr_pulse  <= s_axi_wdata[1];
                        REG_LINE_WIDTH: line_width <= s_axi_wdata[11:0];
                        REG_SHIFT:      shift      <= s_axi_wdata[4:0];
                        REG_MODE:       mode       <= s_axi_wdata[0];
                        REG_PIX_IN: begin
                            pix_valid <= 1'b1;
                            pix_data  <= s_axi_wdata[7:0];
                        end
                        default: ; // read-only registers ignore writes
                    endcase
                end
            end
        end
    end

    // ---- the convolution core ----
    (* mark_debug = "true" *) logic       out_valid;
    (* mark_debug = "true" *) logic [7:0] out_data;
    logic [7:0] out_data_last;
    logic [31:0] out_count;

    conv3x3_core #(
        .PIX_WIDTH(8),
        .COEF_WIDTH(8),
        .ACC_WIDTH(32)
    ) u_core (
        .clk        (s_axi_aclk),
        .rst_n      (s_axi_aresetn),
        .clr        (clr_pulse),
        .coeff      (coeff),
        .shift      (shift),
        .mode       (mode),
        .line_width (line_width),
        .pix_valid  (pix_valid),
        .pix_data   (pix_data),
        .out_valid  (out_valid),
        .out_data   (out_data)
    );

    // capture the latest output and count outputs for read-back / sanity
    always_ff @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            out_data_last <= '0;
            out_count     <= '0;
        end else if (clr_pulse) begin
            out_count     <= '0;
        end else if (out_valid) begin
            out_data_last <= out_data;
            out_count     <= out_count + 32'd1;
        end
    end

    // ---- AXI read channel ----
    logic                          axi_arready, axi_rvalid;
    logic [C_S_AXI_ADDR_WIDTH-1:0] axi_araddr;
    logic [C_S_AXI_DATA_WIDTH-1:0] axi_rdata;

    always_ff @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            axi_arready <= 1'b0;
            axi_araddr  <= '0;
            axi_rvalid  <= 1'b0;
        end else begin
            if (!axi_arready && s_axi_arvalid) begin
                axi_arready <= 1'b1;
                axi_araddr  <= s_axi_araddr;
            end else begin
                axi_arready <= 1'b0;
            end

            if (axi_arready && s_axi_arvalid && !axi_rvalid) begin
                axi_rvalid <= 1'b1;
            end else if (axi_rvalid && s_axi_rready) begin
                axi_rvalid <= 1'b0;
            end
        end
    end

    wire [4:0] raddr_word = axi_araddr[ADDR_LSB+4 : ADDR_LSB];

    always_comb begin
        if (raddr_word >= REG_COEF0 && raddr_word <= REG_COEF0 + 5'd8) begin
            axi_rdata = {{24{coeff[raddr_word - REG_COEF0][7]}}, coeff[raddr_word - REG_COEF0]};
        end else begin
            unique case (raddr_word)
                REG_STATUS:     axi_rdata = 32'h0000_0001;            // ready
                REG_LINE_WIDTH: axi_rdata = {20'b0, line_width};
                REG_SHIFT:      axi_rdata = {27'b0, shift};
                REG_MODE:       axi_rdata = {31'b0, mode};
                REG_OUT_DATA:   axi_rdata = {24'b0, out_data_last};
                REG_OUT_COUNT:  axi_rdata = out_count;
                default:        axi_rdata = 32'h0000_0000;
            endcase
        end
    end

    // ---- output assignments ----
    assign s_axi_awready = axi_awready;
    assign s_axi_wready  = axi_wready;
    assign s_axi_bresp   = 2'b00;       // OKAY
    assign s_axi_bvalid  = axi_bvalid;
    assign s_axi_arready = axi_arready;
    assign s_axi_rdata   = axi_rdata;
    assign s_axi_rresp   = 2'b00;       // OKAY
    assign s_axi_rvalid  = axi_rvalid;

endmodule
