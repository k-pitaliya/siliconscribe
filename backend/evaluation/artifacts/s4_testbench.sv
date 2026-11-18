module testbench;

    // -----------------------------------------------------------------------
    // DUT connections
    // -----------------------------------------------------------------------
    reg        clk;
    reg        rst;
    reg        din;
    wire [7:0] dout;

    // -----------------------------------------------------------------------
    // Check bookkeeping
    // -----------------------------------------------------------------------
    integer pass_count = 0;
    integer fail_count = 0;

    reg [8*64-1:0] label;
    reg [7:0]      model;        // expected register content
    reg [7:0]      pat8;         // current exhaustive pattern
    reg [7:0]      exp_byte;     // hand-computed expected byte
    reg            unknown_flag;

    integer i;
    integer k;
    integer pat;
    integer rnd;

    // -----------------------------------------------------------------------
    // Clock: 10 ns period (posedge at t=5,15,25 ... neqedge at 10,20,30 ...)
    // -----------------------------------------------------------------------
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    // -----------------------------------------------------------------------
    // DUT
    // -----------------------------------------------------------------------
    sipo_shift_reg #(
        .DATA_WIDTH (8)
    ) dut (
        .clk  (clk),
        .rst  (rst),
        .din  (din),
        .dout (dout)
    );

    // -----------------------------------------------------------------------
    // Reference model (specification semantics, non-blocking, posedge only)
    // -----------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst)
            model <= 8'h00;
        else
            model <= {model[6:0], din};
    end

    // -----------------------------------------------------------------------
    // Standard check task
    // -----------------------------------------------------------------------
    task chk;
        input [8*24-1:0] cat;     // Verilog keeps the RIGHTMOST characters of an over-long string,
        input [8*64-1:0] name;    // so keep categories <= 24 and names <= 64 chars
        input [63:0] exp_v;
        input [63:0] act_v;
        begin
            if (act_v === exp_v) begin
                pass_count = pass_count + 1;
                $display("CHK|PASS|%0s|%0s|%0t|%0h|%0h|", cat, name, $time, exp_v, act_v);
            end else begin
                fail_count = fail_count + 1;
                $display("CHK|FAIL|%0s|%0s|%0t|%0h|%0h|", cat, name, $time, exp_v, act_v);
                $display("FAIL: [%0s] %0s expected=%0h got=%0h", cat, name, exp_v, act_v);
            end
        end
    endtask

    // -----------------------------------------------------------------------
    // Main stimulus
    // -----------------------------------------------------------------------
    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        rst = 1'b1;
        din = 1'b0;

        // ===================================================================
        // 1. RESET SEQUENCE (asserted from time 0, released after checks)
        // ===================================================================
        @(negedge clk);
        chk("reset", "reset_state_all_zero", 64'h0000000000000000, {56'b0, dout});

        rst = 1'b1;
        din = 1'b1;
        @(negedge clk);
        chk("reset", "reset_dominates_din_high", 64'h0000000000000000, {56'b0, dout});

        din = 1'b0;
        @(negedge clk);
        chk("reset", "reset_holds_zero_din_low", 64'h0000000000000000, {56'b0, dout});

        rst = 1'b0;
        din = 1'b0;
        @(negedge clk);
        chk("directed", "post_reset_shift_zero", 64'h0000000000000000, {56'b0, dout});

        // ===================================================================
        // 2. DIRECTED: serial fill with ones (values taken from the spec text)
        // ===================================================================
        for (i = 0; i < 8; i = i + 1) begin
            rst = 1'b0;
            din = 1'b1;
            @(negedge clk);
            exp_byte = 8'hFF >> (7 - i);
            $sformat(label, "ones_fill_step%d", i);
            chk("directed", label, {56'b0, exp_byte}, {56'b0, dout});
        end
        chk("corner", "all_ones_reached", 64'h00000000000000FF, {56'b0, dout});

        // ===================================================================
        // 3. DIRECTED: single zero walks from dout[0] to dout[7]
        // ===================================================================
        for (i = 0; i < 8; i = i + 1) begin
            rst = 1'b0;
            if (i == 0)
                din = 1'b0;
            else
                din = 1'b1;
            @(negedge clk);
            exp_byte = ~(8'h01 << i);
            $sformat(label, "single_zero_step%d", i);
            chk("directed", label, {56'b0, exp_byte}, {56'b0, dout});
        end

        // ===================================================================
        // 4. DIRECTED: shift zeros in until the register is empty
        // ===================================================================
        for (i = 0; i < 8; i = i + 1) begin
            rst = 1'b0;
            din = 1'b0;
            @(negedge clk);
            $sformat(label, "clear_to_zero_step%d", i);
            chk("directed", label, {56'b0, model}, {56'b0, dout});
        end
        chk("corner", "all_zeros_reached", 64'h0000000000000000, {56'b0, dout});

        // ===================================================================
        // 5. DIRECTED: single one walks from dout[0] to dout[7]
        // ===================================================================
        for (i = 0; i < 8; i = i + 1) begin
            rst = 1'b0;
            if (i == 0)
                din = 1'b1;
            else
                din = 1'b0;
            @(negedge clk);
            exp_byte = 8'h01 << i;
            $sformat(label, "single_one_step%d", i);
            chk("directed", label, {56'b0, exp_byte}, {56'b0, dout});
        end

        // ===================================================================
        // 6. DIRECTED: empty the register again
        // ===================================================================
        for (i = 0; i < 8; i = i + 1) begin
            rst = 1'b0;
            din = 1'b0;
            @(negedge clk);
            $sformat(label, "clear2_step%d", i);
            chk("directed", label, {56'b0, model}, {56'b0, dout});
        end

        // ===================================================================
        // 7. TOGGLE: only din changes between consecutive vectors
        // ===================================================================
        for (i = 0; i < 8; i = i + 1) begin
            rst = 1'b0;
            if ((i % 2) == 0)
                din = 1'b1;
            else
                din = 1'b0;
            @(negedge clk);
            $sformat(label, "toggle_step%d", i);
            chk("toggle", label, {56'b0, model}, {56'b0, dout});
        end
        chk("toggle", "toggle_pattern_1010_reaches_AA", 64'h00000000000000AA, {56'b0, dout});

        // ===================================================================
        // 8. HOLD: register content must be stable for the whole clock period.
        //    Checked in two different states (there is no enable in this DUT).
        // ===================================================================
        @(posedge clk);
        #2;
        chk("hold", "stable_mid_cycle_state_A", {56'b0, model}, {56'b0, dout});
        @(negedge clk);
        chk("hold", "stable_at_falling_edge_state_A", {56'b0, model}, {56'b0, dout});

        din = 1'b1;
        @(posedge clk);
        #3;
        chk("hold", "stable_mid_cycle_state_B", {56'b0, model}, {56'b0, dout});
        @(negedge clk);
        chk("hold", "stable_at_falling_edge_state_B", {56'b0, model}, {56'b0, dout});

        // ===================================================================
        // 9. PROTOCOL: reset is synchronous; mid-cycle assertion has no
        //    immediate effect, and reset wins over an active din.
        //    All sampling is done at/after a RISING edge, because a
        //    synchronous reset is only sampled on posedge clk and dout
        //    retains its value between the assertion and that edge.
        // ===================================================================
        rst = 1'b0;
        din = 1'b1;
        @(posedge clk);
        #2;
        rst = 1'b1;
        #1;
        chk("protocol", "reset_no_immediate_effect", {56'b0, model}, {56'b0, dout});

        @(posedge clk);
        #1;
        chk("protocol", "reset_effective_on_next_edge", 64'h0000000000000000, {56'b0, dout});

        rst = 1'b1;
        din = 1'b1;
        @(posedge clk);
        #1;
        chk("protocol", "reset_wins_over_din_midstream", 64'h0000000000000000, {56'b0, dout});

        rst = 1'b0;
        din = 1'b0;

        // ===================================================================
        // 10. EXHAUSTIVE: every one of the 256 serial bytes, MSB shifted first,
        //     with a model check after every single edge and a hard-coded
        //     full-byte check after each group of eight edges.
        // ===================================================================
        for (pat = 0; pat < 256; pat = pat + 1) begin
            pat8 = pat[7:0];
            for (k = 0; k < 8; k = k + 1) begin
                rst = 1'b0;
                din = pat8[7 - k];
                @(negedge clk);
                $sformat(label, "pat%02h_bit%d", pat8, k);
                chk("exhaustive", label, {56'b0, model}, {56'b0, dout});
            end
            $sformat(label, "pat%02h_final", pat8);
            chk("exhaustive", label, {56'b0, pat8}, {56'b0, dout});
        end

        // ===================================================================
        // 11. UNDEFINED: the output must never be X or Z once reset was seen.
        // ===================================================================
        unknown_flag = $isunknown(dout);
        chk("undefined", "dout_fully_defined_after_exhaustive", 64'h0000000000000000, {63'b0, unknown_flag});

        // ===================================================================
        // 12. RANDOM: 150 pseudo-random vectors (din and rst)
        // ===================================================================
        for (i = 0; i < 150; i = i + 1) begin
            rnd = $random;
            if (rnd[3:0] == 4'd0) begin
                rst = 1'b1;
                din = rnd[9];
            end else begin
                rst = 1'b0;
                din = rnd[9];
            end
            @(negedge clk);
            $sformat(label, "random_vec%d", i);
            chk("random", label, {56'b0, model}, {56'b0, dout});
        end

        rnd = $random;
        rst = 1'b1;
        din = rnd[9];
        @(negedge clk);
        chk("random", "random_reset_recovery", 64'h0000000000000000, {56'b0, dout});

        // ===================================================================
        // Summary
        // ===================================================================
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0)
            $display("ALL TESTS PASSED");
        $finish;
    end

    // -----------------------------------------------------------------------
    // Watchdog: expected run time is about 23 us, allow 300 us
    // -----------------------------------------------------------------------
    initial begin
        #300000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule