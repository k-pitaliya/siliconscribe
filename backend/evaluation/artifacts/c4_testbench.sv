module testbench;

    // ------------------------------------------------------------------
    // DUT interface signals
    // ------------------------------------------------------------------
    reg  [7:0] in0;
    reg  [7:0] in1;
    reg  [7:0] in2;
    reg  [7:0] in3;
    reg  [1:0] sel;
    wire [7:0] y;

    // ------------------------------------------------------------------
    // Check bookkeeping
    // ------------------------------------------------------------------
    integer pass_count = 0;
    integer fail_count = 0;

    reg [8*64-1:0] label;
    reg [7:0] exp_y;
    reg [7:0] bit_val;
    reg [7:0] bias_val;
    reg [7:0] hold_val;
    reg [1:0] s2;

    integer i;
    integer j;
    integer k;
    integer v;
    integer seed;

    reg [7:0] bvals [0:5];

    // ------------------------------------------------------------------
    // Device under test (explicit named port connections)
    // ------------------------------------------------------------------
    mux_4to1 dut (
        .in0 (in0),
        .in1 (in1),
        .in2 (in2),
        .in3 (in3),
        .sel (sel),
        .y   (y)
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

    // ------------------------------------------------------------------
    // Helper: check the 8-bit output y against an 8-bit expected value
    // ------------------------------------------------------------------
    task do_check;
        input [8*24-1:0] c;
        input [8*64-1:0] nm;
        input [7:0] e;
        begin
            chk(c, nm, {56'd0, e}, {56'd0, y});
        end
    endtask

    // ------------------------------------------------------------------
    // Helper: drive all inputs and let the combinational logic settle
    // ------------------------------------------------------------------
    task drive;
        input [7:0] a0;
        input [7:0] a1;
        input [7:0] a2;
        input [7:0] a3;
        input [1:0] s;
        begin
            in0 = a0;
            in1 = a1;
            in2 = a2;
            in3 = a3;
            sel = s;
            #5;
        end
    endtask

    // ------------------------------------------------------------------
    // Helper: put "val" on the lane addressed by "lane", "other" on the rest
    // ------------------------------------------------------------------
    task drive_lane;
        input integer lane;
        input [7:0] val;
        input [7:0] other;
        input [1:0] s;
        begin
            if (lane == 0) begin
                drive(val, other, other, other, s);
            end else if (lane == 1) begin
                drive(other, val, other, other, s);
            end else if (lane == 2) begin
                drive(other, other, val, other, s);
            end else begin
                drive(other, other, other, val, s);
            end
        end
    endtask

    // ------------------------------------------------------------------
    // Waveform dump
    // ------------------------------------------------------------------
    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);
    end

    // ------------------------------------------------------------------
    // Watchdog: expected run time is < 10 us, so 100 us is ~10x that
    // ------------------------------------------------------------------
    initial begin
        #100000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

    // ------------------------------------------------------------------
    // Main stimulus and checking
    // ------------------------------------------------------------------
    initial begin
        seed = 32'h0BADF00D;

        // 0) Power-up definedness: inputs all zero, sel = 00 -> y must be 00
        in0 = 8'h00;
        in1 = 8'h00;
        in2 = 8'h00;
        in3 = 8'h00;
        sel = 2'b00;
        #5;
        chk("directed", "powerup_zero_defined", 64'h0000000000000000, {56'd0, y});

        // 1) All-zero data with every select encoding
        for (i = 0; i < 4; i = i + 1) begin
            s2 = i;
            drive(8'h00, 8'h00, 8'h00, 8'h00, s2);
            $sformat(label, "all_zero_sel%0d", i);
            do_check("corner", label, 8'h00);
        end

        // 2) All-ones data with every select encoding
        for (i = 0; i < 4; i = i + 1) begin
            s2 = i;
            drive(8'hFF, 8'hFF, 8'hFF, 8'hFF, s2);
            $sformat(label, "all_ones_sel%0d", i);
            do_check("corner", label, 8'hFF);
        end

        // 3) Four distinct lanes, forward order (lane swap / wrong-lane catch)
        for (i = 0; i < 4; i = i + 1) begin
            s2 = i;
            drive(8'h00, 8'h55, 8'hAA, 8'hFF, s2);
            case (s2)
                2'd0: exp_y = 8'h00;
                2'd1: exp_y = 8'h55;
                2'd2: exp_y = 8'hAA;
                2'd3: exp_y = 8'hFF;
            endcase
            $sformat(label, "pattern_fwd_sel%0d", i);
            do_check("directed", label, exp_y);
        end

        // 4) Four distinct lanes, reverse order
        for (i = 0; i < 4; i = i + 1) begin
            s2 = i;
            drive(8'hFF, 8'hAA, 8'h55, 8'h00, s2);
            case (s2)
                2'd0: exp_y = 8'hFF;
                2'd1: exp_y = 8'hAA;
                2'd2: exp_y = 8'h55;
                2'd3: exp_y = 8'h00;
            endcase
            $sformat(label, "pattern_rev_sel%0d", i);
            do_check("directed", label, exp_y);
        end

        // 5) Walking single bit on each lane, other lanes hold the complement
        for (j = 0; j < 4; j = j + 1) begin
            for (k = 0; k < 8; k = k + 1) begin
                bit_val = 8'h01 << k;
                bias_val = ~bit_val;
                s2 = j;
                drive_lane(j, bit_val, bias_val, s2);
                $sformat(label, "walk_lane%0d_bit%0d", j, k);
                do_check("toggle", label, bit_val);
            end
        end

        // 6) Boundary values on every lane; non-selected lanes hold 8'hA5
        bvals[0] = 8'h00;
        bvals[1] = 8'h01;
        bvals[2] = 8'h7F;
        bvals[3] = 8'h80;
        bvals[4] = 8'hFE;
        bvals[5] = 8'hFF;
        for (j = 0; j < 4; j = j + 1) begin
            for (v = 0; v < 6; v = v + 1) begin
                s2 = j;
                drive_lane(j, bvals[v], 8'hA5, s2);
                $sformat(label, "bound_lane%0d_val%0d", j, v);
                do_check("corner", label, bvals[v]);
            end
        end

        // 7) Non-selected lanes must not influence y (hold behaviour, all 4 sels)
        for (j = 0; j < 4; j = j + 1) begin
            s2 = j;
            hold_val = 8'hC3;

            drive_lane(j, hold_val, 8'hA5, s2);
            $sformat(label, "hold_sel%0d_initial", j);
            do_check("hold", label, hold_val);

            drive_lane(j, hold_val, 8'h5A, s2);
            $sformat(label, "hold_sel%0d_nonsel_flip", j);
            do_check("hold", label, hold_val);

            drive_lane(j, 8'h3C, 8'h5A, s2);
            $sformat(label, "hold_sel%0d_sel_changed", j);
            do_check("hold", label, 8'h3C);
        end

        // 8) Single-input-change sequence (only one signal changes per step)
        drive(8'h11, 8'h22, 8'h33, 8'h44, 2'b00);
        chk("protocol", "sic_base_sel0", {56'd0, 8'h11}, {56'd0, y});

        in0 = 8'hA5;
        #5;
        chk("protocol", "sic_in0_only", {56'd0, 8'hA5}, {56'd0, y});

        sel = 2'b01;
        #5;
        chk("protocol", "sic_sel_0_to_1", {56'd0, 8'h22}, {56'd0, y});

        in1 = 8'h5A;
        #5;
        chk("protocol", "sic_in1_only", {56'd0, 8'h5A}, {56'd0, y});

        sel = 2'b10;
        #5;
        chk("protocol", "sic_sel_1_to_2", {56'd0, 8'h33}, {56'd0, y});

        in2 = 8'hC3;
        #5;
        chk("protocol", "sic_in2_only", {56'd0, 8'hC3}, {56'd0, y});

        sel = 2'b11;
        #5;
        chk("protocol", "sic_sel_2_to_3", {56'd0, 8'h44}, {56'd0, y});

        in3 = 8'h3C;
        #5;
        chk("protocol", "sic_in3_only", {56'd0, 8'h3C}, {56'd0, y});

        // Returning to a previously used select must show the CURRENT data
        sel = 2'b00;
        #5;
        chk("protocol", "sic_sel_3_to_0_revisit", {56'd0, 8'hA5}, {56'd0, y});

        in0 = 8'h00;
        #5;
        chk("protocol", "sic_sel0_data_now_zero", {56'd0, 8'h00}, {56'd0, y});

        sel = 2'b01;
        #5;
        chk("protocol", "sic_sel1_revisit", {56'd0, 8'h5A}, {56'd0, y});

        sel = 2'b10;
        #5;
        chk("protocol", "sic_sel2_revisit", {56'd0, 8'hC3}, {56'd0, y});

        sel = 2'b11;
        #5;
        chk("protocol", "sic_sel3_revisit", {56'd0, 8'h3C}, {56'd0, y});

        sel = 2'b00;
        #5;
        chk("protocol", "sic_sel0_revisit_zero", {56'd0, 8'h00}, {56'd0, y});

        in0 = 8'hFF;
        #5;
        chk("protocol", "sic_sel0_all_ones", {56'd0, 8'hFF}, {56'd0, y});

        // 9) Unknown handling
        // unknown on NON-selected lanes must not disturb the defined output
        drive(8'h5A, 8'hxx, 8'hxx, 8'hxx, 2'b00);
        chk("undefined", "x_nonselected_sel0", {56'd0, 8'h5A}, {56'd0, y});

        drive(8'hA5, 8'h00, 8'hxx, 8'h00, 2'b01);
        chk("undefined", "x_nonselected_sel1", {56'd0, 8'h00}, {56'd0, y});

        drive(8'hA5, 8'h11, 8'h22, 8'h33, 2'b10);
        chk("undefined", "defined_after_cleanup_sel2", {56'd0, 8'h22}, {56'd0, y});

        // unknown on the SELECTED lane propagates to y
        drive(8'hxx, 8'h11, 8'h22, 8'h33, 2'b00);
        chk("undefined", "x_selected_sel0", 64'h00000000000000xx, {56'd0, y});

        drive(8'h11, 8'h22, 8'h33, 8'hxx, 2'b11);
        chk("undefined", "x_selected_sel3", 64'h00000000000000xx, {56'd0, y});

        // unknown select, all four lanes pairwise bit-different -> y all X
        drive(8'h00, 8'hFF, 8'hAA, 8'h55, 2'bxx);
        chk("undefined", "x_sel_all_lanes_differ", 64'h00000000000000xx, {56'd0, y});

        drive(8'h00, 8'hFF, 8'hAA, 8'h55, 2'b0z);
        chk("undefined", "z_sel_lsb", 64'h00000000000000xx, {56'd0, y});

        // 10) Random vectors: 200 random data sets x all four select encodings
        for (i = 0; i < 200; i = i + 1) begin
            in0 = $random(seed);
            in1 = $random(seed);
            in2 = $random(seed);
            in3 = $random(seed);
            #5;

            for (k = 0; k < 4; k = k + 1) begin
                s2 = k;
                sel = s2;
                #5;

                case (sel)
                    2'd0: exp_y = in0;
                    2'd1: exp_y = in1;
                    2'd2: exp_y = in2;
                    2'd3: exp_y = in3;
                endcase

                $sformat(label, "rand_data%0d_sel%0d", i, k);
                do_check("random", label, exp_y);
            end
        end

        // 11) Summary
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

endmodule