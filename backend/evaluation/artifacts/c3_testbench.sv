module testbench;

    // ---------------------------------------------------------------
    // DUT connections (fixed widths: a[3:0], b[3:0], cin, sum[3:0], cout)
    // ---------------------------------------------------------------
    reg  [3:0] a;
    reg  [3:0] b;
    reg        cin;
    wire [3:0] sum;
    wire       cout;

    // ---------------------------------------------------------------
    // Scoreboard
    // ---------------------------------------------------------------
    integer pass_count = 0;
    integer fail_count = 0;

    // ---------------------------------------------------------------
    // Independent reference model, derived ONLY from the specification:
    //   c[0] = cin
    //   s[i] = a[i] ^ b[i] ^ c[i]
    //   c[i+1] = (a[i] & b[i]) | (c[i] & (a[i] ^ b[i]))
    //   sum = {s[3],s[2],s[1],s[0]}, cout = c[4]
    // The same expressions make X/Z propagate exactly as specified.
    // ---------------------------------------------------------------
    reg [4:0] cref;
    reg [3:0] sref;
    reg [3:0] exp_sum;
    reg       exp_cout;

    always @(*) begin
        cref[0] = cin;
        sref[0] = a[0] ^ b[0] ^ cref[0];
        cref[1] = (a[0] & b[0]) | (cref[0] & (a[0] ^ b[0]));
        sref[1] = a[1] ^ b[1] ^ cref[1];
        cref[2] = (a[1] & b[1]) | (cref[1] & (a[1] ^ b[1]));
        sref[2] = a[2] ^ b[2] ^ cref[2];
        cref[3] = (a[2] & b[2]) | (cref[2] & (a[2] ^ b[2]));
        sref[3] = a[3] ^ b[3] ^ cref[3];
        cref[4] = (a[3] & b[3]) | (cref[3] & (a[3] ^ b[3]));
        exp_sum  = sref;
        exp_cout = cref[4];
    end

    // ---------------------------------------------------------------
    // Stimulus helpers
    // ---------------------------------------------------------------
    reg [8*64-1:0] label;
    reg [3:0] ta;
    reg [3:0] tb;
    reg       tc;
    reg [3:0] ra;
    reg [3:0] rb;
    reg       rc_in;
    reg [3:0] ea;
    reg [3:0] eb;
    reg       ec;
    integer i;
    integer n;
    integer ia;
    integer ib;
    integer ic;

    // ---------------------------------------------------------------
    // DUT
    // ---------------------------------------------------------------
    ripple_carry_adder #(
        .WIDTH(4)
    ) dut (
        .a(a),
        .b(b),
        .cin(cin),
        .sum(sum),
        .cout(cout)
    );

    // ---------------------------------------------------------------
    // Standard check task: ONE machine-readable line per comparison.
    //   CHK|<PASS|FAIL>|<category>|<name>|<time>|<expected hex>|<actual hex>|
    // Categories: directed, corner, random, reset, hold, exhaustive, toggle, protocol, undefined_opcode.
    // ---------------------------------------------------------------
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

    // Drive inputs, let combinational logic settle, then compare.
    task apply_and_check;
        input [8*24-1:0] cat;
        input [8*64-1:0] name;
        input [3:0] va;
        input [3:0] vb;
        input       vc;
        begin
            a   = va;
            b   = vb;
            cin = vc;
            #5;
            chk(cat, name, {exp_cout, exp_sum}, {cout, sum});
        end
    endtask

    // Directed vector with an auto-generated, value-based label.
    task directed_vec;
        input [3:0] va;
        input [3:0] vb;
        input       vc;
        begin
            $sformat(label, "dir_a%0d_b%0d_c%0d", va, vb, vc);
            apply_and_check("directed", label, va, vb, vc);
        end
    endtask

    // ---------------------------------------------------------------
    // Main stimulus
    // ---------------------------------------------------------------
    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        // Pre-stimulus sanity: all inputs known and zero, outputs defined.
        a   = 4'b0000;
        b   = 4'b0000;
        cin = 1'b0;
        #5;
        chk("reset", "powerup_sum_defined", 1'b0, $isunknown(sum));
        chk("reset", "powerup_cout_defined", 1'b0, $isunknown(cout));
        chk("reset", "powerup_zero_plus_zero", 5'b00000, {cout, sum});

        // ---------------- Directed corner cases ----------------
        directed_vec(4'd0,  4'd0,  1'b0);
        directed_vec(4'd0,  4'd0,  1'b1);
        directed_vec(4'd0,  4'd15, 1'b0);
        directed_vec(4'd0,  4'd15, 1'b1);
        directed_vec(4'd15, 4'd0,  1'b0);
        directed_vec(4'd15, 4'd0,  1'b1);
        directed_vec(4'd15, 4'd1,  1'b0);
        directed_vec(4'd15, 4'd1,  1'b1);
        directed_vec(4'd15, 4'd15, 1'b0);
        directed_vec(4'd15, 4'd15, 1'b1);
        directed_vec(4'd7,  4'd8,  1'b0);
        directed_vec(4'd8,  4'd7,  1'b0);
        directed_vec(4'd8,  4'd8,  1'b0);
        directed_vec(4'd8,  4'd8,  1'b1);
        directed_vec(4'd3,  4'd5,  1'b1);
        directed_vec(4'd5,  4'd9,  1'b0);
        directed_vec(4'd9,  4'd7,  1'b1);
        directed_vec(4'd10, 4'd10, 1'b1);
        directed_vec(4'd6,  4'd9,  1'b0);
        directed_vec(4'd14, 4'd1,  1'b1);
        directed_vec(4'd1,  4'd14, 1'b1);
        directed_vec(4'd15, 4'd2,  1'b0);

        // Single-bit walks on a, b, a==b (carry generated per slice), cin=1
        for (i = 0; i < 4; i = i + 1) begin
            directed_vec(4'b0001 << i, 4'b0000, 1'b0);
            directed_vec(4'b0000, 4'b0001 << i, 1'b0);
            directed_vec(4'b0001 << i, 4'b0001 << i, 1'b0);
            directed_vec(4'b0001 << i, 4'b0000, 1'b1);
            directed_vec(4'b0001 << i, 4'b0001 << i, 1'b1);
            directed_vec(~(4'b0001 << i), 4'b0000, 1'b0);
            directed_vec(~(4'b0001 << i), 4'b0001 << i, 1'b1);
        end

        // Overflow / wrap boundary values
        directed_vec(4'd15, 4'd15, 1'b1);
        directed_vec(4'd14, 4'd2,  1'b1);
        directed_vec(4'd13, 4'd2,  1'b1);
        directed_vec(4'd12, 4'd4,  1'b1);
        directed_vec(4'd11, 4'd5,  1'b1);

        // ---------------- Single-input-change (toggle) walk ----------------
        ta = 4'b0000;
        tb = 4'b0000;
        tc = 1'b0;
        apply_and_check("toggle", "tog_seed_a0_b0_c0", ta, tb, tc);

        for (i = 0; i < 4; i = i + 1) begin
            ta = ta ^ (4'b0001 << i);
            $sformat(label, "tog_a%0d_rise", i);
            apply_and_check("toggle", label, ta, tb, tc);
        end

        for (i = 0; i < 4; i = i + 1) begin
            tb = tb ^ (4'b0001 << i);
            $sformat(label, "tog_b%0d_rise", i);
            apply_and_check("toggle", label, ta, tb, tc);
        end

        tc = ~tc;
        $sformat(label, "tog_cin_rise");
        apply_and_check("toggle", label, ta, tb, tc);

        tc = ~tc;
        $sformat(label, "tog_cin_fall");
        apply_and_check("toggle", label, ta, tb, tc);

        for (i = 3; i >= 0; i = i - 1) begin
            ta = ta ^ (4'b0001 << i);
            $sformat(label, "tog_a%0d_fall", i);
            apply_and_check("toggle", label, ta, tb, tc);
        end

        for (i = 3; i >= 0; i = i - 1) begin
            tb = tb ^ (4'b0001 << i);
            $sformat(label, "tog_b%0d_fall", i);
            apply_and_check("toggle", label, ta, tb, tc);
        end

        // ---------------- Exhaustive enumeration: 16*16*2 = 512 vectors ----------------
        for (ia = 0; ia < 16; ia = ia + 1) begin
            for (ib = 0; ib < 16; ib = ib + 1) begin
                for (ic = 0; ic < 2; ic = ic + 1) begin
                    ea = ia[3:0];
                    eb = ib[3:0];
                    ec = ic[0];
                    $sformat(label, "exh_a%0d_b%0d_c%0d", ea, eb, ec);
                    apply_and_check("exhaustive", label, ea, eb, ec);
                end
            end
        end

        // ---------------- Randomized vectors (independent of the sweep) ----------------
        for (n = 0; n < 150; n = n + 1) begin
            ra    = $random;
            rb    = $random;
            rc_in = $random;
            $sformat(label, "rnd_a%0d_b%0d_c%0d", ra, rb, rc_in);
            apply_and_check("random", label, ra, rb, rc_in);
        end

        // ---------------- Unknown-value propagation ----------------
        apply_and_check("undefined", "undef_a_lsb_x_b0_c0", 4'b000x, 4'b0000, 1'b0);
        apply_and_check("undefined", "undef_a_msb_x_b0_c0", 4'bx000, 4'b0000, 1'b0);
        apply_and_check("undefined", "undef_a_all_x_b0_c0", 4'bxxxx, 4'b0000, 1'b0);
        apply_and_check("undefined", "undef_b_all_z_a0_c1", 4'b0000, 4'bzzzz, 1'b1);
        apply_and_check("undefined", "undef_cin_x_a0_b0",   4'b0000, 4'b0000, 1'bx);
        apply_and_check("undefined", "undef_b_lsb_x_a15_c0", 4'b1111, 4'b000x, 1'b0);
        apply_and_check("undefined", "undef_a_mid_x_b0_c1",  4'b0x00, 4'b0000, 1'b1);
        apply_and_check("undefined", "undef_cin_z_a15_b15",  4'b1111, 4'b1111, 1'bz);

        // ---------------- Summary ----------------
        #5;
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

    // ---------------------------------------------------------------
    // Watchdog: expected run time is a few thousand ns; never hang.
    // ---------------------------------------------------------------
    initial begin
        #50000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule