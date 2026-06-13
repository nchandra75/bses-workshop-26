// tb_conv3x3_core.sv
// -----------------------------------------------------------------------------
// Self-checking testbench for conv3x3_core: stream a small zero-padded image
// through the convolution datapath, watch
// the window slide and an output pixel appear in the waveform, then let the
// testbench confirm every output matches a software-computed reference - the same
// arithmetic the Python golden reference (conv_reference) uses.
//
// It runs several kernels (sharpen, blur, edges) so the check exercises negative
// coefficients, the right-shift divisor, and the abs-clamp (edge) mode.
//
// Run it with: cd rtl && vivado -mode batch -source sim.tcl     (see README)
// or point any SystemVerilog simulator at conv3x3_core.sv + this file.
// -----------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_conv3x3_core;

    localparam int PIX_WIDTH = 8;
    localparam int IMG_H     = 6;          // image (unpadded) height
    localparam int IMG_W     = 8;          // image (unpadded) width
    localparam int PAD_H     = IMG_H + 2;  // zero-padded frame height
    localparam int PAD_W     = IMG_W + 2;  // zero-padded frame width
    localparam int N_OUT     = IMG_H * IMG_W;
    localparam time TCLK      = 10ns;      // 100 MHz

    logic                 clk = 0;
    logic                 rst_n;
    logic                 clr;
    logic signed [7:0]    coeff [0:8];
    logic [4:0]           shift;
    logic                 mode;
    logic [11:0]          line_width;
    logic                 pix_valid;
    logic [PIX_WIDTH-1:0] pix_data;
    logic                 out_valid;
    logic [PIX_WIDTH-1:0] out_data;

    // the test image and its zero-padded frame
    logic [7:0] img    [0:IMG_H-1][0:IMG_W-1];
    logic [7:0] padded [0:PAD_H-1][0:PAD_W-1];

    // captured hardware outputs (raster order) and the software reference
    logic [7:0] got      [0:N_OUT-1];
    logic [7:0] expected  [0:N_OUT-1];
    int         k;                 // capture index, reset before each kernel
    int         total_errors = 0;

    conv3x3_core #(
        .PIX_WIDTH(PIX_WIDTH)
    ) dut (
        .clk        (clk),
        .rst_n      (rst_n),
        .clr        (clr),
        .coeff      (coeff),
        .shift      (shift),
        .mode       (mode),
        .line_width (line_width),
        .pix_valid  (pix_valid),
        .pix_data   (pix_data),
        .out_valid  (out_valid),
        .out_data   (out_data)
    );

    always #(TCLK/2) clk = ~clk;

    // capture every output pixel the core emits, in order
    always @(posedge clk)
        if (rst_n && out_valid) begin
            if (k < N_OUT) got[k] = out_data;
            k++;
        end

    // drive one pixel for one clock (a bubble cycle separates pixels - harmless,
    // the core only advances on pix_valid)
    task automatic push_pixel(input logic [7:0] v);
        @(negedge clk);
        pix_valid = 1'b1;
        pix_data  = v;
        @(negedge clk);
        pix_valid = 1'b0;
    endtask

    // software reference for one output pixel (i, j) of the IMG_H x IMG_W image
    function automatic logic [7:0] ref_pixel(input int i, input int j);
        logic signed [31:0] acc, v, mag;
        acc = 0;
        for (int dy = 0; dy < 3; dy++)
            for (int dx = 0; dx < 3; dx++)
                acc += $signed({1'b0, padded[i+dy][j+dx]}) * coeff[dy*3 + dx];
        v   = acc >>> shift;
        mag = (mode && v < 0) ? -v : v;
        if (mag < 0)        return 8'd0;
        else if (mag > 255) return 8'd255;
        else                return mag[7:0];
    endfunction

    // run the whole padded frame through the core for the current kernel and check
    task automatic run_kernel(input string name);
        int errors;
        errors = 0;

        // restart the datapath and the capture index
        @(negedge clk);
        clr = 1'b1;
        @(negedge clk);
        clr = 1'b0;
        k   = 0;

        // build the software reference for this kernel
        for (int i = 0; i < IMG_H; i++)
            for (int j = 0; j < IMG_W; j++)
                expected[i*IMG_W + j] = ref_pixel(i, j);

        // stream the zero-padded frame in raster order
        for (int r = 0; r < PAD_H; r++)
            for (int c = 0; c < PAD_W; c++)
                push_pixel(padded[r][c]);

        // let the last output drain through the datapath pipeline and settle
        repeat (8) @(negedge clk);

        // check count and values
        if (k !== N_OUT) begin
            $error("[%s] output COUNT mismatch: got %0d expected %0d", name, k, N_OUT);
            errors++;
        end
        for (int n = 0; n < N_OUT; n++) begin
            if (got[n] !== expected[n]) begin
                if (errors < 10)
                    $error("[%s] pixel %0d (row %0d col %0d): hw=%0d expected=%0d",
                           name, n, n / IMG_W, n % IMG_W, got[n], expected[n]);
                errors++;
            end
        end

        if (errors == 0)
            $display("  [%s] PASS: all %0d output pixels match the reference", name, N_OUT);
        else
            $display("  [%s] FAIL: %0d mismatches", name, errors);

        total_errors += errors;
    endtask

    // load a kernel into the coeff/shift/mode inputs (signed coefficients)
    task automatic set_kernel(input int c [0:8], input int sh, input bit md);
        for (int i = 0; i < 9; i++) coeff[i] = c[i][7:0];  // truncate to signed 8-bit
        shift = sh[4:0];
        mode  = md;
    endtask

    initial begin
        // init
        rst_n      = 1'b0;
        clr        = 1'b0;
        pix_valid  = 1'b0;
        pix_data   = '0;
        line_width = PAD_W[11:0];
        shift      = '0;
        mode       = 1'b0;
        for (int i = 0; i < 9; i++) coeff[i] = '0;

        // a deterministic pseudo-random image, zero-padded by one pixel all round
        for (int i = 0; i < IMG_H; i++)
            for (int j = 0; j < IMG_W; j++)
                img[i][j] = $urandom_range(0, 255);
        for (int r = 0; r < PAD_H; r++)
            for (int c = 0; c < PAD_W; c++)
                padded[r][c] = '0;
        for (int i = 0; i < IMG_H; i++)
            for (int j = 0; j < IMG_W; j++)
                padded[i+1][j+1] = img[i][j];

        // reset for a few cycles
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);

        $display("==== conv3x3_core: %0dx%0d image, %0dx%0d padded frame ====",
                 IMG_H, IMG_W, PAD_H, PAD_W);

        // sharpen: negative coeffs, center 5, no shift, signed clamp (can exceed 255 and go <0)
        set_kernel('{0, -1, 0, -1, 5, -1, 0, -1, 0}, 0, 1'b0);
        run_kernel("sharpen");

        // blur: all positive, divide by 16 via shift, signed clamp
        set_kernel('{1, 2, 1, 2, 4, 2, 1, 2, 1}, 4, 1'b0);
        run_kernel("blur");

        // edges (Laplacian): magnitude (abs) then clamp
        set_kernel('{-1, -1, -1, -1, 8, -1, -1, -1, -1}, 0, 1'b1);
        run_kernel("edges");

        if (total_errors == 0)
            $display("==== TEST PASSED: all kernels match the reference ====");
        else
            $display("==== TEST FAILED: %0d total mismatches ====", total_errors);

        $finish;
    end

    // safety timeout
    initial begin
        #1ms;
        $error("TIMEOUT");
        $finish;
    end

endmodule
