// conv3x3_core_unpipelined.sv
// -----------------------------------------------------------------------------
// DELIBERATELY UN-PIPELINED, FAILS TIMING ON PURPOSE. Kept as a demo artifact.
//
// This is the original single-cycle version of conv3x3_core: the line-buffer
// read, the nine-tap MAC adder tree, and the shift/abs/clamp formatting all
// happen in one combinational shot between registers (~38 logic levels, ~26 ns).
// At the PYNQ-Z2's 100 MHz (10 ns) it misses setup badly - WNS about -16 ns,
// thousands of failing endpoints. The shipping conv3x3_core.sv pipelines this
// same datapath into stages to close timing; the two are bit-identical in
// simulation (the testbench is latency-agnostic) but only the pipelined one
// meets timing in hardware. Drop this file in (it keeps the module name
// conv3x3_core) to show the class a real timing failure and the negative-slack
// report. NOT part of any build or sim script - swap it in by hand.
//
// The 3x3 image convolution as a circuit (the RTL rung).
//
// This is the operation at the heart of every convolutional neural network - for
// each output pixel we compute a weighted sum of a 3x3 neighbourhood. In software
// that is nine multiply-accumulates per pixel, done one after another. Here the
// nine multipliers are real, separate silicon (DSP blocks) and they ALL fire on
// the same clock edge, producing one finished output pixel every cycle.
//
// Two ideas worth pointing at on the projector:
//
//   1. The MAC tree (the acc = ... line). Nine multiplies and an adder tree, all
//      combinational, all at once.
//
//   2. The line buffers (lb0, lb1). Pixels stream in one per cycle in raster
//      order, but a 3x3 window needs three rows at once. We keep the previous two
//      rows on-chip in BRAM so that, as each new pixel arrives, we instantly have
//      the column of three pixels above/at it. This sliding-window-over-a-stream
//      pattern is how almost all FPGA image processing works.
//
// Borders / padding: the datapath only ever computes *full* 3x3 windows. We get
// same-size, zero-padded output by feeding it a frame that has already been
// zero-padded by one pixel on every side (so a HxW image is streamed as a
// (H+2)x(W+2) frame). Padding in the feeder, not the datapath, keeps the hardware
// simple - exactly how you would do it with a DMA in a real system. `line_width`
// is the width of that padded frame.
//
// The kernel (nine signed coefficients, a right-shift, and a mode bit) is loaded
// over AXI-Lite by Python before the frame streams in - see conv3x3_axi_lite.sv.
//   out = clip( |acc >> shift|  if mode  else  acc >> shift , 0, 255)
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps

module conv3x3_core #(
    parameter int PIX_WIDTH = 8,     // bits per pixel (grayscale)
    parameter int COEF_WIDTH = 8,    // bits per signed kernel coefficient
    parameter int ACC_WIDTH = 32,    // accumulator width (generous; a few suffice)
    parameter int MAX_WIDTH = 2048   // line-buffer depth = widest frame supported
) (
    input  logic clk,
    input  logic rst_n,   // active-low synchronous reset
    input  logic clr,     // synchronous restart: clears window + counters (1-cycle pulse)

    // kernel parameters (held constant while a frame streams through)
    input  logic signed [COEF_WIDTH-1:0] coeff [0:8],  // row-major: c0=top-left .. c8=bottom-right
    input  logic [4:0]                   shift,        // right-shift applied to the sum (the divisor)
    input  logic                         mode,         // 0 = signed clamp, 1 = abs then clamp (edges)
    input  logic [11:0]                  line_width,   // width of the (already padded) frame

    // pixel input stream (raster order, one pixel per cycle when pix_valid)
    input  logic                 pix_valid,
    input  logic [PIX_WIDTH-1:0] pix_data,

    // output pixel stream (trails the input by the line-buffer fill latency)
    output logic                 out_valid,
    output logic [PIX_WIDTH-1:0] out_data
);

    // ---- on-chip line buffers: the previous two rows of the frame ----
    // When we are processing row R column C, lb1[C] holds row R-1's pixel and
    // lb0[C] holds row R-2's pixel. Together with the incoming pixel that is the
    // full vertical column of the 3x3 window. (Inferred as BRAM; not reset.)
    logic [PIX_WIDTH-1:0] lb0 [0:MAX_WIDTH-1];
    logic [PIX_WIDTH-1:0] lb1 [0:MAX_WIDTH-1];

    // ---- the 3x3 window of registers ----
    // win[r][c]: r is the row (0 = top), c is the column (0 = oldest/leftmost).
    // A new column is shifted in on the right (c=2) every pixel.
    logic [PIX_WIDTH-1:0] win [0:2][0:2];

    // ---- raster position within the padded frame ----
    logic [11:0] col;
    logic [15:0] row;

    // Format the accumulator into an 8-bit output pixel: arithmetic shift, then
    // optional magnitude (for edge kernels), then clamp to [0, 255].
    function automatic logic [PIX_WIDTH-1:0] format_out(input logic signed [ACC_WIDTH-1:0] acc);
        logic signed [ACC_WIDTH-1:0] v, mag;
        v   = acc >>> shift;                 // arithmetic shift = divide by 2^shift
        mag = (mode && v < 0) ? -v : v;
        if (mag < 0)        return '0;
        else if (mag > 255) return 8'd255;
        else                return mag[PIX_WIDTH-1:0];
    endfunction

    always_ff @(posedge clk) begin
        // local temporaries for this pixel's column and MAC result
        logic [PIX_WIDTH-1:0]        col_top, col_mid, col_bot;
        logic signed [ACC_WIDTH-1:0] acc;

        if (!rst_n || clr) begin
            col       <= '0;
            row       <= '0;
            out_valid <= 1'b0;
            out_data  <= '0;
            for (int r = 0; r < 3; r++)
                for (int c = 0; c < 3; c++)
                    win[r][c] <= '0;
        end else begin
            out_valid <= 1'b0;   // default: no output this cycle

            if (pix_valid) begin
                // The vertical column of the window at this position: two rows from
                // the line buffers, plus the pixel arriving right now.
                col_top = lb0[col];      // row R-2
                col_mid = lb1[col];      // row R-1
                col_bot = pix_data;      // row R

                // Slide the rows down in the line buffers for the next frame row.
                lb0[col] <= lb1[col];
                lb1[col] <= pix_data;

                // The MAC tree over the window *after* shifting the new column in:
                //   new window column 2 = this column; columns 1,0 = previous two.
                // coeff[r*3 + c] multiplies window row r, column c.
                // #region mac-tree
                acc = $signed({1'b0, win[0][1]}) * coeff[0]
                    + $signed({1'b0, win[0][2]}) * coeff[1]
                    + $signed({1'b0, col_top})   * coeff[2]
                    + $signed({1'b0, win[1][1]}) * coeff[3]
                    + $signed({1'b0, win[1][2]}) * coeff[4]
                    + $signed({1'b0, col_mid})   * coeff[5]
                    + $signed({1'b0, win[2][1]}) * coeff[6]
                    + $signed({1'b0, win[2][2]}) * coeff[7]
                    + $signed({1'b0, col_bot})   * coeff[8];
                // #endregion mac-tree

                // Shift the window left and bring the new column in on the right.
                win[0][0] <= win[0][1]; win[0][1] <= win[0][2]; win[0][2] <= col_top;
                win[1][0] <= win[1][1]; win[1][1] <= win[1][2]; win[1][2] <= col_mid;
                win[2][0] <= win[2][1]; win[2][1] <= win[2][2]; win[2][2] <= col_bot;

                // Emit once the window is fully inside the (padded) frame: we have
                // at least two full rows buffered and at least two columns seen.
                if (row >= 2 && col >= 2) begin
                    out_valid <= 1'b1;
                    out_data  <= format_out(acc);
                end

                // Advance the raster scan.
                if (col == line_width - 12'd1) begin
                    col <= '0;
                    row <= row + 16'd1;
                end else begin
                    col <= col + 12'd1;
                end
            end
        end
    end

endmodule
