module testbench;

    // ---------------------------------------------------------------
    // DUT interface
    // ---------------------------------------------------------------
    reg  [3:0] a;
    reg  [3:0] b;
    wire       gt;
    wire       eq;
    wire       lt;

    // ---------------------------------------------------------------
    // Bookkeeping
    // ---------------------------------------------------------------
    integer pass_count = 0;
    integer fail_count = 0;

    integer i;
    integer j;
    integer k;
    integer r;
    integer vec_id;
    integer bitpos;

    // ---------------------------------------------------------------
    // Independent expectation model (derived from the specification)
    // ---------------------------------------------------------------
    reg exp_gt;
    reg exp_eq;
    reg exp_lt;

    reg [63:0] exp_v;
    reg [63:0] act_v;

    reg [8*64-1:0] l_gt;
    reg [8*64-1:0] l_eq;
    reg [8*64-1:0] l_lt;
    reg [8*64-1:0] l_one;

    reg        isunk;
    reg [63:0] exh_cnt;

    reg  [3:0] ia;
    reg  [3:0] ib;
    reg  [3:0] ga;
    reg  [3:0] gb;
    reg  [3:0] ra;
    reg  [3:0] rb;
    reg  [3:0] onehot;

    // ---------------------------------------------------------------
    // DUT instance
    // ---------------------------------------------------------------
    mag_compare_4bit #(.WIDTH(4)) dut (
        .a  (a),
        .b  (b),
        .gt (gt),
        .eq (eq),
        .lt (lt)
    );

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

    // ---------------------------------------------------------------
    // Expected value model: verbatim specification equations.
    //   gt = msb-first strictly-greater chain, eq = bit-identical,
    //   lt = ~gt & ~eq (one-hot invariant).
    // ---------------------------------------------------------------
    task expect_for;
        input [3:0] av;
        input [3:0] bv;
        begin
            exp_gt = (av[3] & ~bv[3])
                   | (~(av[3] ^ bv[3]) & ((av[2] & ~bv[2])
                   | (~(av[2] ^ bv[2]) & ((av[1] & ~bv[1])
                   | (~(av[1] ^ bv[1]) & av[0] & ~bv[0])))));
            exp_eq = (av == bv);
            exp_lt = (~exp_gt) & (~exp_eq);
        end
    endtask

    // ---------------------------------------------------------------
    // Compare the CURRENT settled outputs against the model.
    // ---------------------------------------------------------------
    task compare_pair;
        input [8*24-1:0] cat;
        input [3:0] av;
        input [3:0] bv;
        begin
            vec_id = vec_id + 1;

            $sformat(l_gt,  "n%0d_a%0d_b%0d_gt", vec_id, av, bv);
            $sformat(l_eq,  "n%0d_a%0d_b%0d_eq", vec_id, av, bv);
            $sformat(l_lt,  "n%0d_a%0d_b%0d_lt", vec_id, av, bv);
            $sformat(l_one, "n%0d_a%0d_b%0d_oh", vec_id, av, bv);

            expect_for(av, bv);

            exp_v = {63'b0, exp_gt};
            act_v = {63'b0, gt};
            chk(cat, l_gt, exp_v, act_v);

            exp_v = {63'b0, exp_eq};
            act_v = {63'b0, eq};
            chk(cat, l_eq, exp_v, act_v);

            exp_v = {63'b0, exp_lt};
            act_v = {63'b0, lt};
            chk(cat, l_lt, exp_v, act_v);

            exp_v = 64'd1;
            act_v = {63'b0, gt} + {63'b0, eq} + {63'b0, lt};
            chk(cat, l_one, exp_v, act_v);
        end
    endtask

    // Drive inputs, allow combinational settling, then compare.
    task check_pair;
        input [8*24-1:0] cat;
        input [3:0] av;
        input [3:0] bv;
        begin
            a = av;
            b = bv;
            #5;
            compare_pair(cat, av, bv);
        end
    endtask

    task drive_pair;
        input [3:0] av;
        input [3:0] bv;
        begin
            a = av;
            b = bv;
            #5;
        end
    endtask

    // ---------------------------------------------------------------
    // Stimulus
    // ---------------------------------------------------------------
    initial begin
        vec_id  = 0;
        exh_cnt = 64'd0;

        a = 4'b0000;
        b = 4'b0000;

        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        // -----------------------------------------------------------
        // Power-up / reset-equivalent check: no reset port exists, so
        // outputs must already be defined and correct at time 0.
        // -----------------------------------------------------------
        #5;
        compare_pair("reset", 4'b0000, 4'b0000);

        // Probe each output bit individually: $isunknown() on the wide
        // concatenation {gt,eq,lt} mis-reports in this simulator, so the
        // same "no X/Z on any output" intent is expressed per signal.
        isunk = $isunknown(gt) | $isunknown(eq) | $isunknown(lt);
        exp_v = 64'd0;
        act_v = {63'b0, isunk};
        chk("reset", "powerup_outputs_defined", exp_v, act_v);

        // -----------------------------------------------------------
        // Directed vectors from the specification
        // -----------------------------------------------------------
        check_pair("directed", 4'b0000, 4'b0000);
        check_pair("directed", 4'b0101, 4'b0011);
        check_pair("directed", 4'b0011, 4'b0101);
        check_pair("directed", 4'b1111, 4'b0000);
        check_pair("directed", 4'b0000, 4'b1111);
        check_pair("directed", 4'b1000, 4'b0111);
        check_pair("directed", 4'b0111, 4'b1000);
        check_pair("directed", 4'b1010, 4'b1010);

        // -----------------------------------------------------------
        // Corner cases: all zeros, all ones, boundaries around the
        // 0/15 wrap edges, MSB dominance, adjacent values.
        // -----------------------------------------------------------
        check_pair("corner", 4'b0000, 4'b0000);
        check_pair("corner", 4'b1111, 4'b1111);
        check_pair("corner", 4'b0000, 4'b1111);
        check_pair("corner", 4'b1111, 4'b0000);
        check_pair("corner", 4'b0001, 4'b0000);
        check_pair("corner", 4'b0000, 4'b0001);
        check_pair("corner", 4'b1110, 4'b1111);
        check_pair("corner", 4'b1111, 4'b1110);
        check_pair("corner", 4'b1111, 4'b0001);
        check_pair("corner", 4'b0001, 4'b1111);
        check_pair("corner", 4'b1000, 4'b0111);
        check_pair("corner", 4'b0111, 4'b1000);
        check_pair("corner", 4'b1000, 4'b1000);
        check_pair("corner", 4'b0111, 4'b0111);

        // -----------------------------------------------------------
        // Each single bit, in both operands, alone and in context.
        //-----------------------------------------------------------
        for (bitpos = 0; bitpos < 4; bitpos = bitpos + 1) begin
            onehot = 4'b0001 << bitpos;
            check_pair("corner", onehot, 4'b0000);
            check_pair("corner", 4'b0000, onehot);
            check_pair("corner", onehot, onehot);
            check_pair("corner", onehot, 4'b1111);
            check_pair("corner", 4'b1111, onehot);
        end

        // -----------------------------------------------------------
        // Exhaustive enumeration: all 256 (a,b) pairs.
        // -----------------------------------------------------------
        for (i = 0; i < 16; i = i + 1) begin
            for (j = 0; j < 16; j = j + 1) begin
                ia = i;
                ib = j;
                check_pair("exhaustive", ia, ib);
                exh_cnt = exh_cnt + 64'd1;
            end
        end

        exp_v = 64'd256;
        chk("protocol", "exhaustive_pairs_covered", exp_v, exh_cnt);

        // -----------------------------------------------------------
        // Single-input-change walk over a (Gray code: one bit changes
        // per step while b is held at 0).
        // -----------------------------------------------------------
        check_pair("toggle", 4'b0000, 4'b0000);
        for (k = 0; k < 16; k = k + 1) begin
            ga = (k >> 1) ^ k;
            check_pair("toggle", ga, 4'b0000);
        end

        // -----------------------------------------------------------
        // Single-input-change walk over b (a held at 0, Gray code).
        // -----------------------------------------------------------
        check_pair("toggle", 4'b0000, 4'b0000);
        for (k = 0; k < 16; k = k + 1) begin
            gb = (k >> 1) ^ k;
            check_pair("toggle", 4'b0000, gb);
        end

        // -----------------------------------------------------------
        // Output-state transitions eq -> gt -> eq -> lt -> eq, each
        // step changing exactly one input bit.
        // -----------------------------------------------------------
        check_pair("toggle", 4'b0000, 4'b0000);
        check_pair("toggle", 4'b0001, 4'b0000);
        check_pair("toggle", 4'b0001, 4'b0001);
        check_pair("toggle", 4'b0000, 4'b0001);
        check_pair("toggle", 4'b0000, 4'b0000);
        check_pair("toggle", 4'b1111, 4'b1111);
        check_pair("toggle", 4'b1110, 4'b1111);
        check_pair("toggle", 4'b1110, 4'b1110);

        // -----------------------------------------------------------
        // Hold / stability behaviour in several distinct states:
        // inputs unchanged, outputs must remain identical.
        // -----------------------------------------------------------
        drive_pair(4'b1010, 4'b0101);
        compare_pair("hold", 4'b1010, 4'b0101);
        #10;
        compare_pair("hold", 4'b1010, 4'b0101);
        #10;
        compare_pair("hold", 4'b1010, 4'b0101);

        drive_pair(4'b0000, 4'b1111);
        compare_pair("hold", 4'b0000, 4'b1111);
        #10;
        compare_pair("hold", 4'b0000, 4'b1111);

        drive_pair(4'b1111, 4'b0000);
        compare_pair("hold", 4'b1111, 4'b0000);
        #10;
        compare_pair("hold", 4'b1111, 4'b0000);

        drive_pair(4'b0110, 4'b0110);
        compare_pair("hold", 4'b0110, 4'b0110);
        #10;
        compare_pair("hold", 4'b0110, 4'b0110);

        drive_pair(4'b0011, 4'b1100);
        compare_pair("hold", 4'b0011, 4'b1100);
        #10;
        compare_pair("hold", 4'b0011, 4'b1100);

        // -----------------------------------------------------------
        // Randomized vectors (200) in addition to the corners.
        // -----------------------------------------------------------
        for (r = 0; r < 200; r = r + 1) begin
            ra = $random;
            rb = $random;
            check_pair("random", ra, rb);
        end

        // -----------------------------------------------------------
        // No input is illegal for this design, but the outputs must
        // never be X or Z (fully specified truth table).
        // -----------------------------------------------------------
        drive_pair(4'b0101, 4'b0011);

        isunk = $isunknown(gt);
        chk("undefined", "gt_not_unknown", 64'd0, {63'b0, isunk});

        isunk = $isunknown(eq);
        chk("undefined", "eq_not_unknown", 64'd0, {63'b0, isunk});

        isunk = $isunknown(lt);
        chk("undefined", "lt_not_unknown", 64'd0, {63'b0, isunk});

        isunk = $isunknown(gt) | $isunknown(eq) | $isunknown(lt);
        chk("undefined", "all_outputs_not_unknown", 64'd0, {63'b0, isunk});

        drive_pair(4'b0000, 4'b0000);
        isunk = $isunknown(gt) | $isunknown(eq) | $isunknown(lt);
        chk("undefined", "zero_inputs_outputs_known", 64'd0, {63'b0, isunk});

        drive_pair(4'b1111, 4'b1111);
        isunk = $isunknown(gt) | $isunknown(eq) | $isunknown(lt);
        chk("undefined", "ones_inputs_outputs_known", 64'd0, {63'b0, isunk});

        // -----------------------------------------------------------
        // Summary
        // -----------------------------------------------------------
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end

        $finish;
    end

    // ---------------------------------------------------------------
    // Watchdog: expected run time is a few microseconds of sim time.
    // ---------------------------------------------------------------
    initial begin
        #100000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule