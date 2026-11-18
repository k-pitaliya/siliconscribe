module testbench;

    reg clk;
    reg rst;
    reg load;
    reg up_down;
    reg [7:0] din;
    wire [7:0] dout;
    wire [63:0] dout64;

    integer pass_count = 0;
    integer fail_count = 0;

    reg [8*64-1:0] label;
    reg [7:0] model_q;
    reg [7:0] exp_val;

    integer i;
    integer k;
    integer r;
    integer l;
    integer u;
    integer d;
    reg ri;
    reg li;
    reg ui;
    reg [7:0] di;

    assign dout64 = {56'd0, dout};

    loadable_updown_counter #(
        .WIDTH(8)
    ) dut (
        .clk(clk),
        .rst(rst),
        .load(load),
        .up_down(up_down),
        .din(din),
        .dout(dout)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        rst = 1'b1;
        load = 1'b0;
        up_down = 1'b0;
        din = 8'h00;
        model_q = 8'h00;
    end

    // Standard check task: ONE machine-readable line per comparison.
    //   CHK|<PASS|FAIL>|<category>|<name>|<time>|<expected hex>|<actual hex>|
    // Categories: directed, corner, random, reset, hold, exhaustive, toggle, protocol, undefined_opcode.
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

    // Specification reference model: priority rst > load > count.
    //  - rst=1            -> q <= 0
    //  - rst=0, load=1    -> q <= din
    //  - rst=0, load=0    -> up_down=1 : q+1 mod 256 ; up_down=0 : q-1 mod 256
    function [7:0] nxt;
        input [7:0] q_in;
        input r_in;
        input l_in;
        input u_in;
        input [7:0] d_in;
        begin
            if (r_in === 1'b1) begin
                nxt = 8'h00;
            end else if (l_in === 1'b1) begin
                nxt = d_in;
            end else if (u_in === 1'b1) begin
                nxt = q_in + 8'd1;
            end else begin
                nxt = q_in - 8'd1;
            end
        end
    endfunction

    // Apply one vector at a falling edge, sample the DUT at the next falling edge
    // (i.e. after exactly one rising edge has consumed the vector).
    task step_exp;
        input [8*24-1:0] cat;
        input [8*64-1:0] name;
        input rst_v;
        input load_v;
        input ud_v;
        input [7:0] din_v;
        input [7:0] exp_in;
        begin
            rst     = rst_v;
            load    = load_v;
            up_down = ud_v;
            din     = din_v;
            @(posedge clk);
            @(negedge clk);
            chk(cat, name, {56'd0, exp_in}, dout64);
            model_q = exp_in;
        end
    endtask

    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        // ---------------------------------------------------------------
        // Reset sequence: rst is high from time 0, so the first posegde
        // loads 0x00 synchronously before any functional stimulus.
        // ---------------------------------------------------------------
        @(posedge clk);
        @(negedge clk);
        chk("reset", "dout_defined_zero_after_first_reset_edge", 64'd0, dout64);
        @(posedge clk);
        @(negedge clk);
        chk("reset", "dout_zero_after_second_reset_edge", 64'd0, dout64);
        model_q = 8'h00;

        // ---------------------------------------------------------------
        // Reset priority: rst wins over load, over count, and over any
        // don't-care value on load/up_down/din.
        // ---------------------------------------------------------------
        step_exp("reset", "rst_wins_over_load_all_ones", 1'b1, 1'b1, 1'b1, 8'hFF, 8'h00);
        step_exp("reset", "rst_wins_over_load_a5", 1'b1, 1'b1, 1'b0, 8'hA5, 8'h00);
        step_exp("reset", "rst_wins_over_count_up", 1'b1, 1'b0, 1'b1, 8'h00, 8'h00);
        step_exp("reset", "rst_wins_over_count_down", 1'b1, 1'b0, 1'b0, 8'h00, 8'h00);
        step_exp("undefined", "rst_wins_with_x_load_ud_din", 1'b1, 1'bx, 1'bx, 8'hxx, 8'h00);

        // ---------------------------------------------------------------
        // Directed counting: reset deassertion resumes immediately,
        // both directions, and modulo wrap-around at both ends.
        // ---------------------------------------------------------------
        step_exp("reset", "resumes_count_up_after_reset", 1'b0, 1'b0, 1'b1, 8'h00, 8'h01);
        step_exp("directed", "count_up_to_02", 1'b0, 1'b0, 1'b1, 8'h00, 8'h02);
        step_exp("directed", "count_up_to_03", 1'b0, 1'b0, 1'b1, 8'h00, 8'h03);
        step_exp("directed", "count_down_to_02", 1'b0, 1'b0, 1'b0, 8'h00, 8'h02);
        step_exp("directed", "count_down_to_01", 1'b0, 1'b0, 1'b0, 8'h00, 8'h01);
        step_exp("directed", "count_down_to_00", 1'b0, 1'b0, 1'b0, 8'h00, 8'h00);
        step_exp("corner", "underflow_00_minus_1_is_ff", 1'b0, 1'b0, 1'b0, 8'h00, 8'hFF);
        step_exp("corner", "overflow_ff_plus_1_is_00", 1'b0, 1'b0, 1'b1, 8'h00, 8'h00);
        step_exp("corner", "count_up_after_wrap_is_01", 1'b0, 1'b0, 1'b1, 8'h00, 8'h01);

        // ---------------------------------------------------------------
        // Load priority: load captures din, does NOT count in the same
        // edge, and up_down is ignored during the load cycle.
        // ---------------------------------------------------------------
        step_exp("directed", "load_aa_with_ud1_no_increment", 1'b0, 1'b1, 1'b1, 8'hAA, 8'hAA);
        step_exp("directed", "count_up_after_load_is_ab", 1'b0, 1'b0, 1'b1, 8'h00, 8'hAB);
        step_exp("directed", "load_55_with_ud0_no_decrement", 1'b0, 1'b1, 1'b0, 8'h55, 8'h55);
        step_exp("directed", "count_down_after_load_is_54", 1'b0, 1'b0, 1'b0, 8'h00, 8'h54);
        step_exp("directed", "load_fe_with_ud1_no_increment", 1'b0, 1'b1, 1'b1, 8'hFE, 8'hFE);
        step_exp("corner", "count_up_fe_to_ff", 1'b0, 1'b0, 1'b1, 8'h00, 8'hFF);
        step_exp("directed", "load_01_with_ud0_no_decrement", 1'b0, 1'b1, 1'b0, 8'h01, 8'h01);
        step_exp("corner", "count_down_01_to_00", 1'b0, 1'b0, 1'b0, 8'h00, 8'h00);
        step_exp("directed", "load_80_with_ud1_no_increment", 1'b0, 1'b1, 1'b1, 8'h80, 8'h80);
        step_exp("corner", "count_down_80_to_7f", 1'b0, 1'b0, 1'b0, 8'h00, 8'h7F);
        step_exp("directed", "load_7f_with_ud0_no_decrement", 1'b0, 1'b1, 1'b0, 8'h7F, 8'h7F);
        step_exp("corner", "count_up_7f_to_80", 1'b0, 1'b0, 1'b1, 8'h00, 8'h80);
        step_exp("corner", "load_all_zeros", 1'b0, 1'b1, 1'b1, 8'h00, 8'h00);
        step_exp("corner", "load_all_ones", 1'b0, 1'b1, 1'b0, 8'hFF, 8'hFF);
        step_exp("corner", "count_down_ff_to_fe", 1'b0, 1'b0, 1'b0, 8'h00, 8'hFE);
        step_exp("directed", "load_3c_with_ud1", 1'b0, 1'b1, 1'b1, 8'h3C, 8'h3C);

        // ---------------------------------------------------------------
        // Don't-care inputs: up_down is ignored during load, din is
        // ignored when not loading.
        // ---------------------------------------------------------------
        step_exp("undefined", "x_up_down_ignored_during_load", 1'b0, 1'b1, 1'bx, 8'h5A, 8'h5A);
        step_exp("undefined", "x_din_ignored_when_count_up", 1'b0, 1'b0, 1'b1, 8'hxx, 8'h5B);
        step_exp("undefined", "x_din_ignored_when_count_down", 1'b0, 1'b0, 1'b0, 8'hxx, 8'h5A);
        step_exp("undefined", "x_din_ignored_when_count_down_2", 1'b0, 1'b0, 1'b0, 8'hxx, 8'h59);

        // ---------------------------------------------------------------
        // Walking single-bit load patterns (all ones / all zeros / each
        // single bit set, then each single bit cleared).
        // ---------------------------------------------------------------
        for (i = 0; i < 8; i = i + 1) begin
            di = 8'd1 << i;
            exp_val = di;
            $sformat(label, "load_single_one_bit%0d", i);
            step_exp("corner", label, 1'b0, 1'b1, 1'b1, di, exp_val);
        end
        for (i = 0; i < 8; i = i + 1) begin
            di = ~(8'd1 << i);
            exp_val = di;
            $sformat(label, "load_single_zero_bit%0d", i);
            step_exp("corner", label, 1'b0, 1'b1, 1'b0, di, exp_val);
        end
        step_exp("corner", "count_up_after_walking_is_80", 1'b0, 1'b0, 1'b1, 8'h00, 8'h80);

        // ---------------------------------------------------------------
        // Single-input-change chain: every consecutive vector differs in
        // exactly ONE input, so a stale or gated output is caught.
        // ---------------------------------------------------------------
        step_exp("directed", "toggle_setup_load_zero", 1'b0, 1'b1, 1'b1, 8'h00, 8'h00);
        step_exp("toggle", "only_load_changes_0_to_1_count", 1'b0, 1'b0, 1'b1, 8'h00, 8'h01);
        step_exp("toggle", "only_ud_changes_1_to_0_count", 1'b0, 1'b0, 1'b0, 8'h00, 8'h00);
        step_exp("toggle", "only_ud_changes_0_to_1_count", 1'b0, 1'b0, 1'b1, 8'h00, 8'h01);
        step_exp("toggle", "only_load_changes_0_to_1_load", 1'b0, 1'b1, 1'b1, 8'h00, 8'h00);
        step_exp("toggle", "only_din_changes_load_3c", 1'b0, 1'b1, 1'b1, 8'h3C, 8'h3C);
        step_exp("toggle", "only_load_changes_1_to_0_count", 1'b0, 1'b0, 1'b1, 8'h3C, 8'h3D);
        step_exp("toggle", "only_ud_changes_1_to_0_count", 1'b0, 1'b0, 1'b0, 8'h3C, 8'h3C);
        step_exp("toggle", "only_rst_changes_0_to_1", 1'b1, 1'b0, 1'b0, 8'h3C, 8'h00);
        step_exp("toggle", "only_rst_changes_1_to_0", 1'b0, 1'b0, 1'b0, 8'h3C, 8'hFF);
        step_exp("toggle", "only_ud_changes_0_to_1_count", 1'b0, 1'b0, 1'b1, 8'h3C, 8'h00);
        step_exp("toggle", "only_din_changes_ignored", 1'b0, 1'b0, 1'b1, 8'h7E, 8'h01);
        step_exp("toggle", "only_load_changes_0_to_1_load", 1'b0, 1'b1, 1'b1, 8'h7E, 8'h7E);
        step_exp("toggle", "only_din_changes_load_zero", 1'b0, 1'b1, 1'b1, 8'h00, 8'h00);
        step_exp("toggle", "only_load_changes_1_to_0_count", 1'b0, 1'b0, 1'b1, 8'h00, 8'h01);
        step_exp("toggle", "only_rst_changes_0_to_1", 1'b1, 1'b0, 1'b1, 8'h00, 8'h00);
        step_exp("toggle", "only_rst_changes_1_to_0", 1'b0, 1'b0, 1'b1, 8'h00, 8'h01);

        // ---------------------------------------------------------------
        // Protocol: reset is SYNCHRONOUS (must not clear before a clock
        // edge) and din has NO combinational path to dout.
        // ---------------------------------------------------------------
        rst = 1'b1;
        #2;
        chk("protocol", "sync_reset_no_change_before_posedge", 64'h01, dout64);
        @(posedge clk);
        #1;
        chk("protocol", "sync_reset_applied_at_posedge", 64'h00, dout64);
        @(negedge clk);
        chk("reset", "dout_zero_after_sync_reset", 64'h00, dout64);
        model_q = 8'h00;

        rst = 1'b0;
        #2;
        chk("protocol", "no_change_without_clock_edge", 64'h00, dout64);
        din = 8'hA5;
        #2;
        chk("protocol", "din_no_combinational_path_to_dout", 64'h00, dout64);
        @(posedge clk);
        @(negedge clk);
        chk("hold", "count_up_ignores_new_din_a5", 64'h01, dout64);
        model_q = 8'h01;

        // Hold behaviour checked in a second state (0xAA): dout is stable
        // during the low phase and only changes on the rising edge.
        step_exp("directed", "hold_setup_load_aa", 1'b0, 1'b1, 1'b1, 8'hAA, 8'hAA);
        din = 8'h3C;
        #2;
        chk("hold", "dout_stable_during_low_phase_state_aa", 64'hAA, dout64);
        @(posedge clk);
        @(negedge clk);
        chk("hold", "new_din_captured_only_at_posedge", 64'h3C, dout64);
        model_q = 8'h3C;

        // ---------------------------------------------------------------
        // Exhaustive enumeration of the whole input space
        // (rst, load, up_down, din) = 2*2*2*256 = 2048 vectors.
        // ---------------------------------------------------------------
        for (r = 0; r < 2; r = r + 1) begin
            for (l = 0; l < 2; l = l + 1) begin
                for (u = 0; u < 2; u = u + 1) begin
                    for (d = 0; d < 256; d = d + 1) begin
                        ri = (r != 0);
                        li = (l != 0);
                        ui = (u != 0);
                        di = d;
                        exp_val = nxt(model_q, ri, li, ui, di);
                        $sformat(label, "exh_r%0dl%0du%0dd_%02h", ri, li, ui, di);
                        step_exp("exhaustive", label, ri, li, ui, di, exp_val);
                    end
                end
            end
        end

        // ---------------------------------------------------------------
        // Randomized vectors on top of the exhaustive sweep.
        // ---------------------------------------------------------------
        for (k = 0; k < 300; k = k + 1) begin
            ri = ((($random & 32'h7) == 0) ? 1'b1 : 1'b0);
            li = $random & 1;
            ui = $random & 1;
            di = $random;
            exp_val = nxt(model_q, ri, li, ui, di);
            $sformat(label, "rand_%0d", k);
            step_exp("random", label, ri, li, ui, di, exp_val);
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

    initial begin
        #250000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule