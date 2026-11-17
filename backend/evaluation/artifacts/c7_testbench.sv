module testbench;

    reg  [3:0] a;
    reg  [3:0] b;
    reg  [2:0] op;

    wire [3:0] y;
    wire       carry;
    wire       overflow;

    integer pass_count = 0;
    integer fail_count = 0;

    integer ia;
    integer ib;
    integer iop;
    integer i;

    reg [3:0] va;
    reg [3:0] vb;
    reg [2:0] vop;
    reg [2:0] g3;
    reg [3:0] g4;

    reg [3:0] exp_y;
    reg       exp_c;
    reg       exp_o;
    reg [4:0] full5;

    reg [8*64-1:0] label_y;
    reg [8*64-1:0] label_c;
    reg [8*64-1:0] label_o;

    // DUT instantiation with explicit named port connections.
    alu4 #(.WIDTH(4)) dut (
        .a(a),
        .b(b),
        .op(op),
        .y(y),
        .carry(carry),
        .overflow(overflow)
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

    // Drive one vector, wait for combinational settling, derive expected
    // values from the specification only, then verify every output.
    task run_vec;
        input [3:0] ta;
        input [3:0] tb;
        input [2:0] top;
        input [8*24-1:0] cat;
        begin
            a  = ta;
            b  = tb;
            op = top;
            #5;

            exp_y = 4'b0000;
            exp_c = 1'b0;
            exp_o = 1'b0;
            full5 = 5'b00000;

            if (top == 3'b000) begin
                // ADD: 5-bit unsigned sum, carry out of bit 4.
                full5 = {1'b0, ta} + {1'b0, tb};
                exp_y = full5[3:0];
                exp_c = full5[4];
                if ((ta[3] == tb[3]) && (exp_y[3] != ta[3]))
                    exp_o = 1'b1;
                else
                    exp_o = 1'b0;
            end else if (top == 3'b001) begin
                // SUB: low 4 bits of a - b; carry is no-borrow (a >= b).
                exp_y = ta - tb;
                if (ta >= tb)
                    exp_c = 1'b1;
                else
                    exp_c = 1'b0;
                if ((ta[3] != tb[3]) && (exp_y[3] != ta[3]))
                    exp_o = 1'b1;
                else
                    exp_o = 1'b0;
            end else if (top == 3'b010) begin
                exp_y = ta & tb;
                exp_c = 1'b0;
                exp_o = 1'b0;
            end else if (top == 3'b011) begin
                exp_y = ta | tb;
                exp_c = 1'b0;
                exp_o = 1'b0;
            end else if (top == 3'b100) begin
                exp_y = ta ^ tb;
                exp_c = 1'b0;
                exp_o = 1'b0;
            end else begin
                // Reserved opcodes 101, 110, 111: all outputs forced to zero.
                exp_y = 4'b0000;
                exp_c = 1'b0;
                exp_o = 1'b0;
            end

            $sformat(label_y, "a%0h_b%0h_op%0h_y", ta, tb, top);
            $sformat(label_c, "a%0h_b%0h_op%0h_c", ta, tb, top);
            $sformat(label_o, "a%0h_b%0h_op%0h_o", ta, tb, top);

            chk(cat, label_y, {60'b0, exp_y}, {60'b0, y});
            chk(cat, label_c, {63'b0, exp_c}, {63'b0, carry});
            chk(cat, label_o, {63'b0, exp_o}, {63'b0, overflow});
        end
    endtask

    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);
    end

    initial begin
        #200000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

    initial begin
        // ------------------------------------------------------------------
        // Directed corner cases.
        // ------------------------------------------------------------------
        run_vec(4'd0,  4'd0,  3'b000, "directed");
        run_vec(4'd0,  4'd0,  3'b001, "directed");
        run_vec(4'd0,  4'd0,  3'b010, "directed");
        run_vec(4'd0,  4'd0,  3'b011, "directed");
        run_vec(4'd0,  4'd0,  3'b100, "directed");

        run_vec(4'd15, 4'd15, 3'b000, "directed");
        run_vec(4'd15, 4'd15, 3'b001, "directed");
        run_vec(4'd15, 4'd15, 3'b010, "directed");
        run_vec(4'd15, 4'd15, 3'b011, "directed");
        run_vec(4'd15, 4'd15, 3'b100, "directed");

        // Spec examples.
        run_vec(4'd7,  4'd1,  3'b000, "directed");
        run_vec(4'd8,  4'd1,  3'b001, "directed");
        run_vec(4'd15, 4'd1,  3'b001, "directed");
        run_vec(4'd10, 4'd5,  3'b100, "directed");

        // ADD carry / overflow boundaries.
        run_vec(4'd8,  4'd8,  3'b000, "directed");
        run_vec(4'd9,  4'd9,  3'b000, "directed");
        run_vec(4'd15, 4'd8,  3'b000, "directed");
        run_vec(4'd7,  4'd8,  3'b000, "directed");
        run_vec(4'd3,  4'd14, 3'b000, "directed");
        run_vec(4'd1,  4'd15, 3'b000, "directed");
        run_vec(4'd10, 4'd6,  3'b000, "directed");

        // SUB borrow / overflow boundaries.
        run_vec(4'd0,  4'd0,  3'b001, "directed");
        run_vec(4'd0,  4'd1,  3'b001, "directed");
        run_vec(4'd1,  4'd15, 3'b001, "directed");
        run_vec(4'd7,  4'd8,  3'b001, "directed");
        run_vec(4'd8,  4'd7,  3'b001, "directed");
        run_vec(4'd2,  4'd13, 3'b001, "directed");
        run_vec(4'd13, 4'd2,  3'b001, "directed");
        run_vec(4'd15, 4'd0,  3'b001, "directed");

        // Logic operations with mixed patterns.
        run_vec(4'd10, 4'd5,  3'b010, "directed");
        run_vec(4'd10, 4'd5,  3'b011, "directed");
        run_vec(4'd5,  4'd10, 3'b100, "directed");
        run_vec(4'd15, 4'd0,  3'b010, "directed");
        run_vec(4'd15, 4'd0,  3'b011, "directed");
        run_vec(4'd15, 4'd0,  3'b100, "directed");

        // Reserved / undefined opcodes with active data inputs.
        run_vec(4'd15, 4'd15, 3'b101, "undefined");
        run_vec(4'd15, 4'd15, 3'b110, "undefined");
        run_vec(4'd15, 4'd15, 3'b111, "undefined");
        run_vec(4'd8,  4'd7,  3'b101, "undefined");
        run_vec(4'd0,  4'd15, 3'b110, "undefined");
        run_vec(4'd1,  4'd2,  3'b111, "undefined");

        // ------------------------------------------------------------------
        // Corner block: all zeros and all ones across every opcode.
        // ------------------------------------------------------------------
        for (iop = 0; iop < 8; iop = iop + 1) begin
            vop = iop;
            run_vec(4'd0,  4'd0,  vop, "corner");
            run_vec(4'd15, 4'd15, vop, "corner");
        end

        // Each single bit in each operand.
        for (i = 0; i < 4; i = i + 1) begin
            g4 = 4'b0000;
            g4[i] = 1'b1;
            run_vec(g4, 4'd0, 3'b000, "corner");
            run_vec(g4, 4'd0, 3'b001, "corner");
            run_vec(g4, 4'd0, 3'b010, "corner");
            run_vec(g4, 4'd0, 3'b011, "corner");
            run_vec(g4, 4'd0, 3'b100, "corner");
            run_vec(4'd0, g4, 3'b000, "corner");
            run_vec(4'd0, g4, 3'b001, "corner");
            run_vec(g4, g4, 3'b100, "corner");
        end

        // ------------------------------------------------------------------
        // Toggle block: consecutive vectors differ in exactly ONE input bit.
        // ------------------------------------------------------------------
        va  = 4'b0000;
        vb  = 4'b0000;
        vop = 3'b000;
        run_vec(va, vb, vop, "toggle");

        // Gray-coded opcode walk: one bit of op changes at a time.
        for (i = 1; i < 8; i = i + 1) begin
            g3 = (i ^ (i >> 1)) & 7;
            vop = g3;
            run_vec(va, vb, vop, "toggle");
        end

        // Gray-coded operand A walk with b and op held constant.
        vop = 3'b100;
        for (i = 1; i < 16; i = i + 1) begin
            g4 = (i ^ (i >> 1)) & 15;
            va = g4;
            run_vec(va, vb, vop, "toggle");
        end

        // Gray-coded operand B walk with a and op held constant.
        va = 4'b1000;
        for (i = 1; i < 16; i = i + 1) begin
            g4 = (i ^ (i >> 1)) & 15;
            vb = g4;
            run_vec(va, vb, vop, "toggle");
        end

        // ------------------------------------------------------------------
        // Exhaustive enumeration: 16 x 16 x 8 = 2048 vectors (<= 4096).
        // ------------------------------------------------------------------
        for (iop = 0; iop < 8; iop = iop + 1) begin
            for (ia = 0; ia < 16; ia = ia + 1) begin
                for (ib = 0; ib < 16; ib = ib + 1) begin
                    vop = iop;
                    va  = ia;
                    vb  = ib;
                    run_vec(va, vb, vop, "exhaustive");
                end
            end
        end

        // ------------------------------------------------------------------
        // Randomized vectors for extra stress.
        // ------------------------------------------------------------------
        for (i = 0; i < 128; i = i + 1) begin
            va  = $random;
            vb  = $random;
            vop = $random;
            run_vec(va, vb, vop, "random");
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0)
            $display("ALL TESTS PASSED");
        $finish;
    end

endmodule