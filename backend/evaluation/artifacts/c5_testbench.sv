module testbench;

    reg  [2:0] a;
    reg        en;
    wire [7:0] y;

    integer pass_count = 0;
    integer fail_count = 0;

    integer i;
    integer j;
    integer r;

    reg [7:0]      exp_y;
    reg [63:0]     exp_val;
    reg [63:0]     act_val;
    reg [8*64-1:0] label;

    decoder_3to8 dut (
        .a  (a),
        .en (en),
        .y  (y)
    );

    // Independent behavioural model derived only from the specification:
    //   y[k] = en && (a == k), k = 0..7, with a treated as unsigned.
    function [7:0] model_y;
        input       e;
        input [2:0] sel;
        reg   [7:0] t;
        begin
            t = 8'b0000_0000;
            if (e === 1'b1) begin
                case (sel)
                    3'b000: t = 8'b0000_0001;
                    3'b001: t = 8'b0000_0010;
                    3'b010: t = 8'b0000_0100;
                    3'b011: t = 8'b0000_1000;
                    3'b100: t = 8'b0001_0000;
                    3'b101: t = 8'b0010_0000;
                    3'b110: t = 8'b0100_0000;
                    3'b111: t = 8'b1000_0000;
                    default: t = 8'b0000_0000;
                endcase
            end
            model_y = t;
        end
    endfunction

    // Count of bits that are exactly 1 (X/Z never count as asserted).
    function integer count_ones;
        input [7:0] v;
        integer n;
        integer b;
        begin
            n = 0;
            for (b = 0; b < 8; b = b + 1) begin
                if (v[b] === 1'b1) begin
                    n = n + 1;
                end
            end
            count_ones = n;
        end
    endfunction

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

    // Watchdog: a hung design cannot hang the run.
    initial begin
        #20000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        en = 1'b0;
        a  = 3'b000;

        // ---------------------------------------------------------------
        // Initial defined-state check (design has no reset port).
        // ---------------------------------------------------------------
        #5;
        chk("reset", "initial_defined_en0_a000", 64'h0000000000000000, {56'd0, y});
        chk("reset", "initial_no_unknown_bits", 64'd0, {63'd0, $isunknown(y)});

        // ---------------------------------------------------------------
        // Directed corner cases taken from the specification truth table.
        // ---------------------------------------------------------------
        en = 1'b0;
        a  = 3'b000;
        #5;
        chk("corner", "all_zero_inputs", 64'h0000000000000000, {56'd0, y});

        en = 1'b1;
        a  = 3'b111;
        #5;
        chk("corner", "all_ones_select_enabled", 64'h0000000000000080, {56'd0, y});

        en = 1'b0;
        a  = 3'b111;
        #5;
        chk("corner", "all_ones_select_disabled", 64'h0000000000000000, {56'd0, y});

        for (i = 0; i < 3; i = i + 1) begin
            en = 1'b1;
            a  = 3'b000;
            a[i] = 1'b1;
            #5;
            exp_y = model_y(en, a);
            $sformat(label, "single_select_bit_%0d_enabled", i);
            chk("corner", label, {56'd0, exp_y}, {56'd0, y});
        end

        // Boundary decode targets.
        en = 1'b1;
        a  = 3'b000;
        #5;
        chk("directed", "boundary_low_en1_a000", 64'h0000000000000001, {56'd0, y});

        en = 1'b1;
        a  = 3'b111;
        #5;
        chk("directed", "boundary_high_en1_a111", 64'h0000000000000080, {56'd0, y});

        // Wrap-around between the extremes.
        en = 1'b1;
        a  = 3'b111;
        #5;
        a = 3'b000;
        #5;
        chk("directed", "wrap_7_to_0", 64'h0000000000000001, {56'd0, y});
        a = 3'b111;
        #5;
        chk("directed", "wrap_0_to_7", 64'h0000000000000080, {56'd0, y});

        // Mid-range single target checks.
        en = 1'b1;
        a  = 3'b010;
        #5;
        chk("directed", "mid_target_en1_a010", 64'h0000000000000004, {56'd0, y});

        en = 1'b1;
        a  = 3'b101;
        #5;
        chk("directed", "mid_target_en1_a101", 64'h0000000000000020, {56'd0, y});

        // ---------------------------------------------------------------
        // Exhaustive enumeration: 2 enable values x 8 select codes = 16.
        // ---------------------------------------------------------------
        for (i = 0; i < 2; i = i + 1) begin
            for (j = 0; j < 8; j = j + 1) begin
                if (i == 0) begin
                    en = 1'b0;
                end else begin
                    en = 1'b1;
                end
                a = j;
                #5;
                exp_y = model_y(en, a);
                $sformat(label, "exh_en%0d_a%0d", i, j);
                chk("exhaustive", label, {56'd0, exp_y}, {56'd0, y});
                if (i == 0) begin
                    $sformat(label, "exh_zero_hot_en0_a%0d", j);
                    chk("protocol", label, 64'd0, count_ones(y));
                end else begin
                    $sformat(label, "exh_one_hot_en1_a%0d", j);
                    chk("protocol", label, 64'd1, count_ones(y));
                end
            end
        end

        // ---------------------------------------------------------------
        // Undefined select encodings while disabled: y must be all zero.
        // ---------------------------------------------------------------
        en = 1'b0;
        a = 3'bxxx;
        #5;
        chk("undefined", "disabled_select_xxx", 64'h0000000000000000, {56'd0, y});
        chk("protocol", "disabled_select_xxx_zero_hot", 64'd0, count_ones(y));

        en = 1'b0;
        a = 3'bzzz;
        #5;
        chk("undefined", "disabled_select_zzz", 64'h0000000000000000, {56'd0, y});

        en = 1'b0;
        a = 3'bx1z;
        #5;
        chk("undefined", "disabled_select_x1z", 64'h0000000000000000, {56'd0, y});

        en = 1'b0;
        a = 3'b0z1;
        #5;
        chk("undefined", "disabled_select_0z1", 64'h0000000000000000, {56'd0, y});

        en = 1'b0;
        a = 3'b1x0;
        #5;
        chk("undefined", "disabled_select_1x0", 64'h0000000000000000, {56'd0, y});

        // ---------------------------------------------------------------
        // Single-input-change chain: only one of {en, a} changes per step.
        // The select walks in Gray-code order so consecutive vectors differ
        // by exactly one select bit; en is toggled alone at each code.
        // ---------------------------------------------------------------
        en = 1'b0;
        a  = 3'b000;
        #5;
        chk("toggle", "chain_start_en0_a000", 64'h0000000000000000, {56'd0, y});

        en = 1'b1;
        #5;
        chk("toggle", "chain_en_only_rise_a000", 64'h0000000000000001, {56'd0, y});

        for (j = 1; j < 8; j = j + 1) begin
            a = (j ^ (j >> 1));
            #5;
            exp_y = model_y(1'b1, a);
            $sformat(label, "chain_a_only_one_bit_a%0d", a);
            chk("toggle", label, {56'd0, exp_y}, {56'd0, y});

            en = 1'b0;
            #5;
            $sformat(label, "chain_en_only_fall_a%0d", a);
            chk("toggle", label, 64'h0000000000000000, {56'd0, y});

            en = 1'b1;
            #5;
            $sformat(label, "chain_en_only_rise_a%0d", a);
            chk("toggle", label, {56'd0, exp_y}, {56'd0, y});
        end

        // ---------------------------------------------------------------
        // Hold checks: stable inputs must keep stable outputs in several states.
        // ---------------------------------------------------------------
        en = 1'b1;
        a  = 3'b110;
        #5;
        exp_y = model_y(en, a);
        chk("hold", "enabled_hot_hold_a110_t0", {56'd0, exp_y}, {56'd0, y});
        #10;
        chk("hold", "enabled_hot_hold_a110_t10", {56'd0, exp_y}, {56'd0, y});
        #20;
        chk("hold", "enabled_hot_hold_a110_t30", {56'd0, exp_y}, {56'd0, y});

        en = 1'b1;
        a  = 3'b001;
        #5;
        exp_y = model_y(en, a);
        chk("hold", "enabled_hot_hold_a001_t0", {56'd0, exp_y}, {56'd0, y});
        #15;
        chk("hold", "enabled_hot_hold_a001_t15", {56'd0, exp_y}, {56'd0, y});

        en = 1'b0;
        a  = 3'b001;
        #5;
        chk("hold", "disabled_hold_a001_t0", 64'h0000000000000000, {56'd0, y});
        #15;
        chk("hold", "disabled_hold_a001_t15", 64'h0000000000000000, {56'd0, y});
        #10;
        chk("hold", "disabled_hold_a001_t25", 64'h0000000000000000, {56'd0, y});

        // Same inputs applied again must reproduce the same output (no state).
        en = 1'b1;
        a  = 3'b110;
        #5;
        exp_y = model_y(en, a);
        chk("hold", "repeat_vector_en1_a110", {56'd0, exp_y}, {56'd0, y});

        // ---------------------------------------------------------------
        // Randomized vectors: 200 random (en, a) pairs against the model.
        // ---------------------------------------------------------------
        for (r = 0; r < 200; r = r + 1) begin
            en = $random;
            a  = $random;
            #5;
            exp_y = model_y(en, a);
            $sformat(label, "rand_%0d_en%0d_a%0d", r, en, a);
            chk("random", label, {56'd0, exp_y}, {56'd0, y});
            if (en === 1'b1) begin
                $sformat(label, "rand_proto_%0d_one_hot", r);
                chk("protocol", label, 64'd1, count_ones(y));
            end else begin
                $sformat(label, "rand_proto_%0d_zero_hot", r);
                chk("protocol", label, 64'd0, count_ones(y));
            end
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

endmodule