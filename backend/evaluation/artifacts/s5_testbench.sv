module testbench;

    reg  clk;
    reg  rst_n;
    wire clk_out;

    reg [8*64-1:0] label;

    integer pass_count = 0;
    integer fail_count = 0;

    integer i;
    integer j;
    integer edges;          // rising clk edges counted since reset release
    integer hi_cnt;         // sampled clk cycles with clk_out high
    integer lo_cnt;         // sampled clk cycles with clk_out low
    integer t_a;
    integer t_b;
    integer t_c;
    integer seed;
    integer x_events;

    reg exp_out;            // expected clk_out from the reference model
    reg prev_exp;           // previous expected value
    reg prev_out;           // previous sampled value
    reg out_after_edge;     // value captured just after a rising edge
    reg mon_enable;         // enable the unknown-value monitor after reset

    // -----------------------------------------------------------------------
    // Standard check task: ONE machine-readable line per comparison.
    //   CHK|<PASS|FAIL>|<category>|<name>|<time>|<expected hex>|<actual hex>|
    // Categories: directed, corner, random, reset, hold, exhaustive, toggle,
    //             protocol, undefined_opcode.
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
    // DUT with explicit named port connections
    // -----------------------------------------------------------------------
    clk_div_by4 uut (
        .clk     (clk),
        .rst_n   (rst_n),
        .clk_out (clk_out)
    );

    // -----------------------------------------------------------------------
    // Clock generator: 10 ns period, first rising edge at t = 5 ns
    // -----------------------------------------------------------------------
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    // -----------------------------------------------------------------------
    // Monitor: clk_out must never become X/Z once reset has been released
    // -----------------------------------------------------------------------
    always @(clk_out) begin
        if (mon_enable && $isunknown(clk_out)) begin
            x_events = x_events + 1;
        end
    end

    // -----------------------------------------------------------------------
    // Watchdog: expected run time is a few microseconds
    // -----------------------------------------------------------------------
    initial begin
        #25000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

    // -----------------------------------------------------------------------
    // Main stimulus / checking sequence
    // -----------------------------------------------------------------------
    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        seed           = 32'h1234ABCD;
        rst_n          = 1'b0;
        edges          = 0;
        exp_out        = 1'b0;
        prev_exp       = 1'b0;
        prev_out       = 1'b0;
        out_after_edge = 1'b0;
        hi_cnt         = 0;
        lo_cnt         = 0;
        x_events       = 0;
        t_a            = 0;
        t_b            = 0;
        t_c            = 0;
        mon_enable     = 1'b0;

        // ===================================================================
        // PHASE 1 : reset asserted from time 0 (asynchronous, active low)
        // Only rst_n is exercised here (single input change vs. idle clk).
        // ===================================================================
        #1;
        chk("reset", "async_reset_t0_out_low",   64'd0, clk_out);
        chk("reset", "async_reset_t0_out_known", 64'd0, {63'b0, $isunknown(clk_out)});

        for (i = 0; i < 2; i = i + 1) begin
            @(posedge clk);
            #1;
            $sformat(label, "reset_held_after_posedge_%0d", i);
            chk("reset", label, 64'd0, clk_out);
            @(negedge clk);
            $sformat(label, "reset_held_after_negedge_%0d", i);
            chk("reset", label, 64'd0, clk_out);
        end

        // Release reset synchronously to clk at a falling edge
        rst_n = 1'b1;
        #1;
        chk("reset", "out_low_at_reset_release", 64'd0, clk_out);
        mon_enable = 1'b1;

        // ===================================================================
        // PHASE 2 : directed corner walk over the complete truth table
        //   00 -> 01 (out 0); 01 -> 10 (out 1);
        //   10 -> 11 (out 1); 11 -> 00 (out 0, wrap / overflow)
        // ===================================================================
        @(negedge clk);
        chk("corner", "cnt_00_to_01_out_low",    64'd0, clk_out);

        @(negedge clk);
        chk("corner", "cnt_01_to_10_out_high",   64'd1, clk_out);

        @(negedge clk);
        chk("corner", "cnt_10_to_11_out_high",   64'd1, clk_out);

        @(negedge clk);
        chk("corner", "cnt_11_to_00_wrap_out_low", 64'd0, clk_out);

        // ===================================================================
        // PHASE 3 : exhaustive walk of all four counter states
        // 12 complete divide-by-4 periods = 48 rising edges.
        // Reference model: toggle once every 2nd rising edge.
        // ===================================================================
        edges    = 0;
        exp_out  = 1'b0;
        prev_exp = 1'b0;
        prev_out = 1'b0;
        hi_cnt   = 0;
        lo_cnt   = 0;

        for (i = 0; i < 12; i = i + 1) begin
            for (j = 0; j < 4; j = j + 1) begin
                @(negedge clk);

                edges    = edges + 1;
                prev_exp = exp_out;
                if ((edges % 2) == 0) begin
                    exp_out = ~exp_out;
                end

                $sformat(label, "period_%0d_state_%0d_edge_%0d", i, j, edges);
                chk("exhaustive", label, exp_out, clk_out);

                if (exp_out !== prev_exp) begin
                    $sformat(label, "toggle_on_edge_%0d", edges);
                    chk("toggle", label, exp_out, clk_out);
                end else begin
                    $sformat(label, "hold_between_edge_%0d", edges);
                    chk("hold", label, prev_exp, clk_out);
                end

                if (clk_out === 1'b1) begin
                    hi_cnt = hi_cnt + 1;
                end else begin
                    lo_cnt = lo_cnt + 1;
                end

                prev_out = clk_out;
            end
        end

        chk("protocol", "duty_high_count_over_48_edges", 64'd24, hi_cnt);
        chk("protocol", "duty_low_count_over_48_edges",  64'd24, lo_cnt);

        // ===================================================================
        // PHASE 4 : measured period / duty of clk_out (protocol checks)
        // ===================================================================
        @(posedge clk_out);
        t_a = $time;
        @(negedge clk_out);
        t_b = $time;
        @(posedge clk_out);
        t_c = $time;

        chk("protocol", "clk_out_high_time_is_20ns", 64'd20, t_b - t_a);
        chk("protocol", "clk_out_low_time_is_20ns",  64'd20, t_c - t_b);
        chk("protocol", "clk_out_period_is_40ns",    64'd40, t_c - t_a);

        // ===================================================================
        // PHASE 5 : asynchronous reset applied while the design is running
        // (rst_n is the only input that changes; asserted mid-cycle, between
        //  clock edges, while clk_out is high)
        // ===================================================================
        @(negedge clk);
        if (clk_out !== 1'b1) begin
            @(negedge clk);
        end

        #2;
        chk("directed", "out_high_before_async_reset", 64'd1, clk_out);
        rst_n = 1'b0;
        #1;
        chk("reset", "async_reset_mid_cycle_out_low",   64'd0, clk_out);
        chk("reset", "async_reset_without_clk_edge",    64'd0, clk_out);

        for (i = 0; i < 2; i = i + 1) begin
            @(posedge clk);
            #1;
            $sformat(label, "reset_during_clk_high_%0d", i);
            chk("reset", label, 64'd0, clk_out);
            @(negedge clk);
            $sformat(label, "reset_during_clk_low_%0d", i);
            chk("reset", label, 64'd0, clk_out);
        end

        rst_n = 1'b1;
        #1;
        chk("reset", "out_low_after_second_release", 64'd0, clk_out);

        // ===================================================================
        // PHASE 6 : hold / glitch-free behaviour in two different states
        // (rst_n held at 1: only clk changes between consecutive vectors)
        // ===================================================================
        edges   = 0;
        exp_out = 1'b0;

        @(posedge clk);
        #1;
        edges          = edges + 1;
        out_after_edge = clk_out;
        chk("corner", "all_ones_inputs_out_holds_low", 64'd0, clk_out);
        chk("hold", "clk_high_plateau_out_low",   out_after_edge, clk_out);
        #2;
        chk("hold", "clk_high_plateau_out_low_late", out_after_edge, clk_out);
        @(negedge clk);
        chk("hold", "clk_low_plateau_out_low",    out_after_edge, clk_out);

        @(posedge clk);
        #1;
        edges          = edges + 1;
        exp_out        = 1'b1;
        out_after_edge = clk_out;
        chk("corner", "all_ones_inputs_out_holds_high", 64'd1, clk_out);
        chk("hold", "clk_high_plateau_out_high", out_after_edge, clk_out);
        #3;
        chk("hold", "clk_high_plateau_out_high_late", out_after_edge, clk_out);
        @(negedge clk);
        chk("hold", "clk_low_plateau_out_high",  out_after_edge, clk_out);

        // ===================================================================
        // PHASE 7 : toggle section, single input change (only clk moves,
        // rst_n is a constant 1 so a stale combinational output is caught)
        // ===================================================================
        for (i = 0; i < 20; i = i + 1) begin
            @(negedge clk);

            edges    = edges + 1;
            prev_exp = exp_out;
            if ((edges % 2) == 0) begin
                exp_out = ~exp_out;
            end

            if (exp_out !== prev_exp) begin
                $sformat(label, "single_change_toggle_edge_%0d", edges);
                chk("toggle", label, exp_out, clk_out);
            end else begin
                $sformat(label, "single_change_hold_edge_%0d", edges);
                chk("hold", label, prev_exp, clk_out);
            end
        end

        // ===================================================================
        // PHASE 8 : randomized stimulus (120 vectors)
        // rst_n is randomly re-driven at falling edges, reset held for whole
        // cycles; the model restarts whenever the design was in reset.
        // ===================================================================
        for (i = 0; i < 120; i = i + 1) begin
            @(negedge clk);

            if (rst_n === 1'b0) begin
                edges   = 0;
                exp_out = 1'b0;
            end else begin
                edges = edges + 1;
                if ((edges % 2) == 0) begin
                    exp_out = ~exp_out;
                end
            end

            $sformat(label, "random_vector_%0d", i);
            chk("random", label, exp_out, clk_out);

            // drive the next random input vector, away from the sampling instant
            #1;
            if (((($random(seed) & 32'h0000FFFF) % 100)) < 20) begin
                rst_n = 1'b0;
            end else begin
                rst_n = 1'b1;
            end
        end

        // ===================================================================
        // PHASE 9 : final reset recovery and summary
        // ===================================================================
        @(negedge clk);
        rst_n = 1'b0;
        #1;
        chk("reset", "final_reset_forces_out_low", 64'd0, clk_out);

        @(posedge clk);
        #1;
        chk("reset", "final_reset_holds_through_posedge", 64'd0, clk_out);

        @(negedge clk);
        chk("reset", "final_reset_holds_at_negedge", 64'd0, clk_out);

        rst_n = 1'b1;
        #1;
        chk("reset", "final_release_out_low", 64'd0, clk_out);

        @(negedge clk);
        chk("corner", "post_final_reset_first_edge_low", 64'd0, clk_out);

        @(negedge clk);
        chk("corner", "post_final_reset_second_edge_high", 64'd1, clk_out);

        chk("undefined", "clk_out_never_unknown_in_run", 64'd0, x_events);

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

endmodule