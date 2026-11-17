module testbench;

    // ------------------------------------------------------------------
    // DUT interface
    // ------------------------------------------------------------------
    reg  [3:0] bin;
    wire [3:0] gray;

    // ------------------------------------------------------------------
    // Check bookkeeping (module scope - the task updates these)
    // ------------------------------------------------------------------
    integer pass_count = 0;
    integer fail_count = 0;

    // ------------------------------------------------------------------
    // Loop / temporary variables (module scope only)
    // ------------------------------------------------------------------
    integer i;
    integer j;
    integer n;
    integer b;
    integer diff_cnt;
    integer seed;
    integer unk;

    // ------------------------------------------------------------------
    // Expected values taken directly from the specification truth table
    // ------------------------------------------------------------------
    reg [3:0] exp_table [0:15];
    reg [3:0] walk_seq  [0:15];
    reg [3:0] hold_seq  [0:2];

    reg [3:0] prev_bin;
    reg [3:0] walk_bin;

    reg [8*64-1:0] label;

    // ------------------------------------------------------------------
    // DUT instantiation with explicit named port connections
    // ------------------------------------------------------------------
    bin2gray_4b dut (
        .bin  (bin),
        .gray (gray)
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
    // Stimulus and checking
    // ------------------------------------------------------------------
    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        // Expected gray codes, transcribed from the specification table and
        // cross-checked against the specification XOR equations
        // (gray = (bin >> 1) ^ bin):
        // 0000->0000, 0001->0001, 0010->0011, 0011->0010,
        // 0100->0110, 0101->0111, 0110->0101, 0111->0100,
        // 1000->1100, 1001->1101, 1010->1111, 1011->1110,
        // 1100->1010, 1101->1011, 1110->1001, 1111->1000
        exp_table[0]  = 4'b0000;
        exp_table[1]  = 4'b0001;
        exp_table[2]  = 4'b0011;
        exp_table[3]  = 4'b0010;
        exp_table[4]  = 4'b0110;
        exp_table[5]  = 4'b0111;
        exp_table[6]  = 4'b0101;
        exp_table[7]  = 4'b0100;
        exp_table[8]  = 4'b1100;
        exp_table[9]  = 4'b1101;
        exp_table[10] = 4'b1111;
        exp_table[11] = 4'b1110;
        exp_table[12] = 4'b1010;
        exp_table[13] = 4'b1011;
        exp_table[14] = 4'b1001;
        exp_table[15] = 4'b1000;

        // Binary-reflected Gray walk: consecutive entries differ in exactly
        // one input bit, used for the single-input-change section.
        walk_seq[0]  = 4'b0000;
        walk_seq[1]  = 4'b0001;
        walk_seq[2]  = 4'b0011;
        walk_seq[3]  = 4'b0010;
        walk_seq[4]  = 4'b0110;
        walk_seq[5]  = 4'b0111;
        walk_seq[6]  = 4'b0101;
        walk_seq[7]  = 4'b0100;
        walk_seq[8]  = 4'b1100;
        walk_seq[9]  = 4'b1101;
        walk_seq[10] = 4'b1111;
        walk_seq[11] = 4'b1110;
        walk_seq[12] = 4'b1010;
        walk_seq[13] = 4'b1011;
        walk_seq[14] = 4'b1001;
        walk_seq[15] = 4'b1000;

        hold_seq[0] = 4'b0101;
        hold_seq[1] = 4'b1010;
        hold_seq[2] = 4'b1111;

        // --------------------------------------------------------------
        // Initial definedness check (no reset exists; output must be
        // known and correct for the first applied input).
        // --------------------------------------------------------------
        bin = 4'b0000;
        #5;
        chk("directed", "initial_bin_0000_defined", {60'b0, exp_table[0]}, {60'b0, gray});
        unk = $isunknown(gray);
        chk("undefined", "initial_gray_not_xz", 64'd0, unk);

        // --------------------------------------------------------------
        // EXHAUSTIVE enumeration: the input space is only 16 vectors.
        // --------------------------------------------------------------
        for (i = 0; i < 16; i = i + 1) begin
            bin = i[3:0];
            #5;
            $sformat(label, "exh_bin_%0d", i);
            chk("exhaustive", label, {60'b0, exp_table[i]}, {60'b0, gray});
            unk = $isunknown(gray);
            $sformat(label, "exh_no_xz_bin_%0d", i);
            chk("undefined", label, 64'd0, unk);
        end

        // --------------------------------------------------------------
        // Directed corners: all zeros, all ones, each single bit,
        // boundaries and the wrap region.
        // --------------------------------------------------------------
        bin = 4'b0000;
        #5;
        chk("corner", "all_zeros_0000", {60'b0, 4'b0000}, {60'b0, gray});

        bin = 4'b1111;
        #5;
        chk("corner", "all_ones_1111", {60'b0, 4'b1000}, {60'b0, gray});

        bin = 4'b0001;
        #5;
        chk("corner", "single_bit0_0001", {60'b0, 4'b0001}, {60'b0, gray});

        bin = 4'b0010;
        #5;
        chk("corner", "single_bit1_0010", {60'b0, 4'b0011}, {60'b0, gray});

        bin = 4'b0100;
        #5;
        chk("corner", "single_bit2_0100", {60'b0, 4'b0110}, {60'b0, gray});

        bin = 4'b1000;
        #5;
        chk("corner", "single_bit3_1000", {60'b0, 4'b1100}, {60'b0, gray});

        bin = 4'b0111;
        #5;
        chk("corner", "boundary_low_max_0111", {60'b0, 4'b0100}, {60'b0, gray});

        bin = 4'b1000;
        #5;
        chk("corner", "boundary_high_min_1000", {60'b0, 4'b1100}, {60'b0, gray});

        bin = 4'b1111;
        #5;
        chk("corner", "wrap_source_1111", {60'b0, 4'b1000}, {60'b0, gray});

        bin = 4'b0000;
        #5;
        chk("corner", "wrap_target_0000", {60'b0, 4'b0000}, {60'b0, gray});

        // --------------------------------------------------------------
        // Single-input-change walk: only ONE input bit changes between
        // consecutive vectors, so a stale/latched output is caught.
        // --------------------------------------------------------------
        prev_bin = 4'b0000;
        for (i = 0; i < 16; i = i + 1) begin
            walk_bin = walk_seq[i];
            bin = walk_bin;
            #5;
            $sformat(label, "toggle_walk_bin_%b", walk_bin);
            chk("toggle", label, {60'b0, exp_table[walk_bin]}, {60'b0, gray});
            if (i > 0) begin
                diff_cnt = 0;
                for (j = 0; j < 4; j = j + 1) begin
                    if (prev_bin[j] !== walk_bin[j]) begin
                        diff_cnt = diff_cnt + 1;
                    end
                end
                $sformat(label, "toggle_one_bit_step_%0d", i);
                chk("toggle", label, 64'd1, diff_cnt);
            end
            prev_bin = walk_bin;
        end

        // --------------------------------------------------------------
        // Hold behaviour: with inputs held constant the combinational
        // output must remain correct and unchanged, in several states.
        // --------------------------------------------------------------
        for (i = 0; i < 3; i = i + 1) begin
            bin = hold_seq[i];
            #5;
            $sformat(label, "hold_bin_%b_t5", hold_seq[i]);
            chk("hold", label, {60'b0, exp_table[hold_seq[i]]}, {60'b0, gray});
            #10;
            $sformat(label, "hold_bin_%b_t15", hold_seq[i]);
            chk("hold", label, {60'b0, exp_table[hold_seq[i]]}, {60'b0, gray});
            #20;
            $sformat(label, "hold_bin_%b_t35", hold_seq[i]);
            chk("hold", label, {60'b0, exp_table[hold_seq[i]]}, {60'b0, gray});
        end

        // --------------------------------------------------------------
        // Randomized vectors with single-bit changes.
        // --------------------------------------------------------------
        seed = 32'h5A5A_C3C3;
        prev_bin = 4'b0000;
        for (n = 0; n < 160; n = n + 1) begin
            bin = $random(seed);
            #5;
            $sformat(label, "rand_bin_%0d_val_%b", n, bin);
            chk("random", label, {60'b0, exp_table[bin]}, {60'b0, gray});
        end

        for (n = 0; n < 64; n = n + 1) begin
            walk_bin = prev_bin;
            b = $random(seed) & 32'd3;
            walk_bin[b] = ~walk_bin[b];
            bin = walk_bin;
            #5;
            $sformat(label, "rand_toggle_%0d_bin_%b", n, walk_bin);
            chk("toggle", label, {60'b0, exp_table[walk_bin]}, {60'b0, gray});
            prev_bin = walk_bin;
        end

        // --------------------------------------------------------------
        // Summary
        // --------------------------------------------------------------
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

    // ------------------------------------------------------------------
    // Watchdog: expected run time is roughly 1.5 us
    // ------------------------------------------------------------------
    initial begin
        #25000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule