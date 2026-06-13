// conv3x3_core.sv
// -----------------------------------------------------------------------------
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
//   1. The MAC tree (the nine coeff*pixel products and their sum). Nine multiplies
//      and an adder tree - but NOT all in one cycle. See the pipeline note below.
//
//   2. The line buffers (lb0, lb1). Pixels stream in one per cycle in raster
//      order, but a 3x3 window needs three rows at once. We keep the previous two
//      rows on-chip in BRAM so that, as each new pixel arrives, we instantly have
//      the column of three pixels above/at it. This sliding-window-over-a-stream
//      pattern is how almost all FPGA image processing works.
//
// Pipelining (latency vs throughput): doing the line-buffer read, the nine-tap
// MAC, and the shift/abs/clamp in a single combinational shot is ~38 logic levels
// (~26 ns) - far too slow for the PYNQ-Z2's 100 MHz (10 ns) clock; it misses setup
// by ~16 ns. So we cut the datapath *after the window* into registered stages:
// (S1) the nine products, (S2) the adder tree, (S3) the arithmetic shift + abs,
// (S4) the clamp. Each stage is now a few logic levels and easily fits 10 ns.
// This costs latency - an output pixel now trails its window by four extra cycles
// - but THROUGHPUT is
// unchanged: a new column still enters and a finished pixel still leaves every
// clock. Trading latency for clock speed by inserting registers is the single
// most important trick in hardware design. (conv3x3_core_unpipelined.sv keeps the
// one-shot version around to show the resulting timing failure.)
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

    // ---- output datapath pipeline (after the sliding window) ----
    // The streaming logic above runs in one cycle; the arithmetic that turns a 3x3
    // window into an output pixel is split into four registered stages so each is
    // fast enough for the 10 ns clock. A `valid` bit rides alongside the data
    // through every stage so bubble cycles (pix_valid low) stay bubbles.
    //   S0: latch the nine window operands of this pixel    -> p0_op  / p0_valid
    //   S1: nine signed products coeff[k] * operand[k]      -> p1_prod / p1_valid
    //   S2: sum the nine products (the adder tree)          -> p2_acc  / p2_valid
    //   S3: arithmetic shift (divide) then abs for edges    -> p3_mag  / p3_valid
    //   S4: clamp to [0, 255] into the 8-bit output pixel   -> out_data / out_valid
    // The format step (shift + abs + clamp) is two stages, not one: the abs negate
    // and the two clamp comparisons are each a wide carry chain, and stacking them
    // in one cycle was the slowest path left after the MAC was pipelined.
    logic                        p0_valid, p1_valid, p2_valid, p3_valid;
    logic [PIX_WIDTH-1:0]        p0_op   [0:8];
    logic signed [ACC_WIDTH-1:0] p1_prod [0:8];
    logic signed [ACC_WIDTH-1:0] p2_acc;
    logic signed [ACC_WIDTH-1:0] p3_mag;   // |acc >> shift| (edges) or acc >> shift

    always_ff @(posedge clk) begin
        // local temporaries for this pixel's incoming column, the adder tree, and
        // the arithmetic-shift result before the magnitude/clamp
        logic [PIX_WIDTH-1:0]        col_top, col_mid, col_bot;
        logic signed [ACC_WIDTH-1:0] sum, v;

        if (!rst_n || clr) begin
            col       <= '0;
            row       <= '0;
            out_valid <= 1'b0;
            out_data  <= '0;
            // drop anything in flight in the pipeline (a restart loses partial work)
            p0_valid  <= 1'b0;
            p1_valid  <= 1'b0;
            p2_valid  <= 1'b0;
            p3_valid  <= 1'b0;
            for (int r = 0; r < 3; r++)
                for (int c = 0; c < 3; c++)
                    win[r][c] <= '0;
        end else begin
            // ---- S0: streaming + capture this pixel's window operands ----
            p0_valid <= 1'b0;   // default: no new pixel entered the pipeline

            if (pix_valid) begin
                // The vertical column of the window at this position: two rows from
                // the line buffers, plus the pixel arriving right now.
                col_top = lb0[col];      // row R-2
                col_mid = lb1[col];      // row R-1
                col_bot = pix_data;      // row R

                // Slide the rows down in the line buffers for the next frame row.
                lb0[col] <= lb1[col];
                lb1[col] <= pix_data;

                // Latch the nine operands of the window *after* the new column shifts
                // in: column 2 = this column, columns 1,0 = the previous two. The MAC
                // (coeff[r*3 + c] * window row r, column c) happens in the next stage.
                p0_op[0] <= win[0][1]; p0_op[1] <= win[0][2]; p0_op[2] <= col_top;
                p0_op[3] <= win[1][1]; p0_op[4] <= win[1][2]; p0_op[5] <= col_mid;
                p0_op[6] <= win[2][1]; p0_op[7] <= win[2][2]; p0_op[8] <= col_bot;

                // Shift the window left and bring the new column in on the right.
                win[0][0] <= win[0][1]; win[0][1] <= win[0][2]; win[0][2] <= col_top;
                win[1][0] <= win[1][1]; win[1][1] <= win[1][2]; win[1][2] <= col_mid;
                win[2][0] <= win[2][1]; win[2][1] <= win[2][2]; win[2][2] <= col_bot;

                // This pixel produces an output once the window is fully inside the
                // (padded) frame: at least two full rows buffered and two columns seen.
                if (row >= 2 && col >= 2)
                    p0_valid <= 1'b1;

                // Advance the raster scan.
                if (col == line_width - 12'd1) begin
                    col <= '0;
                    row <= row + 16'd1;
                end else begin
                    col <= col + 12'd1;
                end
            end

            // ---- S1: the nine multiplies (one DSP each, all at once) ----
            for (int k = 0; k < 9; k++)
                p1_prod[k] <= $signed({1'b0, p0_op[k]}) * coeff[k];
            p1_valid <= p0_valid;

            // ---- S2: the adder tree ----
            sum = '0;
            for (int k = 0; k < 9; k++)
                sum += p1_prod[k];
            p2_acc   <= sum;
            p2_valid <= p1_valid;

            // ---- S3: arithmetic shift (= divide by 2^shift), then abs for edges ----
            v = p2_acc >>> shift;
            p3_mag   <= (mode && v < 0) ? -v : v;
            p3_valid <= p2_valid;

            // ---- S4: clamp to [0, 255] into the 8-bit output pixel ----
            if (p3_mag < 0)        out_data <= '0;
            else if (p3_mag > 255) out_data <= 8'd255;
            else                   out_data <= p3_mag[PIX_WIDTH-1:0];
            out_valid <= p3_valid;
        end
    end

endmodule
