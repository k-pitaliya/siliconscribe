module testbench;

    reg        clk;
    reg        rst_n;
    reg        serial_in;
    wire       detected;

    integer pass_count = 0;
    integer fail_count = 0;

    integer i;
    integer j;
    integer k;
    integer nwig;

    reg        bitv;
    reg        rndbit;
    reg [3:0]  hist;      // last four sampled bits in the reference model
    reg [3:0]  nhist;
    reg        exp_bit;
    reg [8*64-1:0] label;

    seq_detect_1011_moore dut (
        .clk       (clk),
        .rst_n     (rst_n),
        .serial_in (serial_in),
        .detected  (detected)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
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

    // Drive one serial bit on the falling-edge boundary and check the Moore
    // output after the following rising edge has been consumed.
    // Entry point: just after a negedge (negedge+1 or later, never at an edge).
    // Exit point : just after the next negedge (negedge+1).
    task do_bit;
        input b;
        input [8*24-1:0] c;
        input [8*64-1:0] nm;
        input wig;
        begin
            serial_in = b;
            nhist = {hist[2:0], b};
            exp_bit = (nhist == 4'b1011) ? 1'b1 : 1'b0;
            @(posedge clk);
            #1;
            if (wig) begin
                serial_in = ~b;
                #1;
                nwig = nwig + 1;
                $sformat(label, "serial_indep_%0d", nwig);
                chk("toggle", label, {63'b0, exp_bit}, {63'b0, detected});
                #1;
                serial_in = b;
            end
            @(negedge clk);
            chk(c, nm, {63'b0, exp_bit}, {63'b0, detected});
            hist = nhist;
            #1;
        end
    endtask

    // Asynchronous reset: assert, prove detected clears without any clock edge,
    // hold through a clock edge, then release.  Exit just after a negedge.
    task apply_reset;
        begin
            rst_n = 1'b0;
            serial_in = 1'b0;
            #1;
            chk("reset", "async_reset_clears_detect", 64'd0, {63'b0, detected});
            hist = 4'b0000;
            @(negedge clk);
            #1;
            chk("reset", "reset_held_detect_low", 64'd0, {63'b0, detected});
            #1;
            rst_n = 1'b1;
        end
    endtask

    // Mid-cycle stimulus wiggle: the only combinational input is serial_in,
    // and detected must not react to it.  Entry just after a negedge.
    task midcycle_toggle;
        input expd;
        begin
            serial_in = 1'b0;
            #1;
            nwig = nwig + 1;
            $sformat(label, "mid_cycle_indep_%0d", nwig);
            chk("toggle", label, {63'b0, expd}, {63'b0, detected});
            serial_in = 1'b1;
            #1;
            nwig = nwig + 1;
            $sformat(label, "mid_cycle_indep_%0d", nwig);
            chk("toggle", label, {63'b0, expd}, {63'b0, detected});
            #1;
        end
    endtask

    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        rst_n = 1'b0;
        serial_in = 1'b0;
        hist = 4'b0000;
        nwig = 0;

        // ---------------- reset sequence ----------------
        #1;
        chk("reset", "reset_detected_zero", 64'd0, {63'b0, detected});
        chk("undefined", "reset_detected_known", 64'd1, {63'b0, !$isunknown(detected)});

        serial_in = 1'b1;
        #2;
        chk("reset", "reset_ignores_in_high", 64'd0, {63'b0, detected});
        serial_in = 1'b0;
        #3;
        chk("reset", "reset_ignores_in_low", 64'd0, {63'b0, detected});
        serial_in = 1'b1;
        #3;
        chk("reset", "reset_ignores_in_high2", 64'd0, {63'b0, detected});

        @(negedge clk);
        #1;
        chk("reset", "reset_idle_before_release", 64'd0, {63'b0, detected});
        #1;
        rst_n = 1'b1;

        // ---------------- directed worked example: 1,0,1,1,0,1,1 ----------------
        do_bit(1'b1, "directed", "worked_b1_one", 1'b0);
        do_bit(1'b0, "directed", "worked_b2_zero", 1'b0);
        midcycle_toggle(1'b0);
        do_bit(1'b1, "directed", "worked_b3_one", 1'b0);
        do_bit(1'b1, "directed", "worked_b4_detect", 1'b0);
        chk("hold", "worked_b4_pulse_holds", 64'd1, {63'b0, detected});
        do_bit(1'b0, "directed", "worked_b5_no_detect", 1'b0);
        midcycle_toggle(1'b0);
        do_bit(1'b1, "directed", "worked_b6_one", 1'b0);
        do_bit(1'b1, "directed", "worked_b7_detect_again", 1'b0);
        chk("hold", "worked_b7_pulse_holds", 64'd1, {63'b0, detected});
        midcycle_toggle(1'b1);
        do_bit(1'b0, "directed", "worked_b8_no_detect", 1'b0);

        // ---------------- corner: all zeros ----------------
        apply_reset;
        for (i = 1; i <= 8; i = i + 1) begin
            $sformat(label, "all_zero_b%0d", i);
            do_bit(1'b0, "corner", label, 1'b0);
        end

        // ---------------- corner: all ones ----------------
        apply_reset;
        for (i = 1; i <= 8; i = i + 1) begin
            $sformat(label, "all_one_b%0d", i);
            do_bit(1'b1, "corner", label, 1'b0);
        end

        // ---------------- corner: single one pulse in each position ----------------
        for (k = 0; k < 5; k = k + 1) begin
            apply_reset;
            for (i = 1; i <= 6; i = i + 1) begin
                $sformat(label, "one_hot_%0d_b%0d", k, i);
                if (i == (k + 1)) begin
                    do_bit(1'b1, "corner", label, 1'b0);
                end else begin
                    do_bit(1'b0, "corner", label, 1'b0);
                end
            end
        end

        // ---------------- corner: single zero glitch inside a one stream ----------------
        for (k = 0; k < 2; k = k + 1) begin
            apply_reset;
            for (i = 1; i <= 6; i = i + 1) begin
                $sformat(label, "zero_hot_%0d_b%0d", k, i);
                if (i == (k + 2)) begin
                    do_bit(1'b0, "corner", label, 1'b0);
                end else begin
                    do_bit(1'b1, "corner", label, 1'b0);
                end
            end
        end

        // ---------------- corner: detection preceded by zeros (00001011) ----------------
        apply_reset;
        do_bit(1'b0, "corner", "lead_b1", 1'b0);
        do_bit(1'b0, "corner", "lead_b2", 1'b0);
        do_bit(1'b0, "corner", "lead_b3", 1'b0);
        do_bit(1'b0, "corner", "lead_b4", 1'b0);
        do_bit(1'b1, "corner", "lead_b5_one", 1'b0);
        do_bit(1'b0, "corner", "lead_b6_zero", 1'b0);
        do_bit(1'b1, "corner", "lead_b7_one", 1'b0);
        do_bit(1'b1, "corner", "lead_b8_detect", 1'b0);
        do_bit(1'b1, "corner", "lead_b9_after", 1'b0);

        // ---------------- corner: 01011, window not starting at bit 1 ----------------
        apply_reset;
        do_bit(1'b0, "corner", "pre0_b1", 1'b0);
        do_bit(1'b1, "corner", "pre0_b2", 1'b0);
        do_bit(1'b0, "corner", "pre0_b3", 1'b0);
        do_bit(1'b1, "corner", "pre0_b4", 1'b0);
        do_bit(1'b1, "corner", "pre0_b5_detect", 1'b0);

        // ---------------- corner: overlap 1011011011 (detections 4,7,10) ----------------
        apply_reset;
        do_bit(1'b1, "corner", "ovl_b1", 1'b0);
        do_bit(1'b0, "corner", "ovl_b2", 1'b0);
        do_bit(1'b1, "corner", "ovl_b3", 1'b0);
        do_bit(1'b1, "corner", "ovl_b4_detect", 1'b0);
        do_bit(1'b0, "corner", "ovl_b5", 1'b0);
        do_bit(1'b1, "corner", "ovl_b6", 1'b0);
        do_bit(1'b1, "corner", "ovl_b7_detect", 1'b0);
        do_bit(1'b0, "corner", "ovl_b8", 1'b0);
        do_bit(1'b1, "corner", "ovl_b9", 1'b0);
        do_bit(1'b1, "corner", "ovl_b10_detect", 1'b0);

        // ---------------- corner: 10111011 (detections 4 and 8) ----------------
        apply_reset;
        do_bit(1'b1, "corner", "bb_b1", 1'b0);
        do_bit(1'b0, "corner", "bb_b2", 1'b0);
        do_bit(1'b1, "corner", "bb_b3", 1'b0);
        do_bit(1'b1, "corner", "bb_b4_detect", 1'b0);
        do_bit(1'b1, "corner", "bb_b5", 1'b0);
        do_bit(1'b0, "corner", "bb_b6", 1'b0);
        do_bit(1'b1, "corner", "bb_b7", 1'b0);
        do_bit(1'b1, "corner", "bb_b8_detect", 1'b0);

        // ---------------- hold behaviour ----------------
        apply_reset;
        do_bit(1'b1, "hold", "hold_s1_b1", 1'b0);
        for (i = 0; i < 4; i = i + 1) begin
            $sformat(label, "hold_s1_one_%0d", i);
            do_bit(1'b1, "hold", label, 1'b0);
        end
        do_bit(1'b0, "hold", "hold_s1_to_s10", 1'b0);
        for (i = 0; i < 3; i = i + 1) begin
            $sformat(label, "hold_s10_zero_%0d", i);
            do_bit(1'b0, "hold", label, 1'b0);
        end

        apply_reset;
        do_bit(1'b1, "hold", "hold2_s1", 1'b0);
        do_bit(1'b0, "hold", "hold2_s10", 1'b0);
        for (i = 0; i < 4; i = i + 1) begin
            $sformat(label, "hold_s101_one_%0d", i);
            do_bit(1'b1, "hold", label, 1'b0);
        end

        // ---------------- async reset from DETECT with serial_in active ----------------
        apply_reset;
        do_bit(1'b1, "protocol", "arst_b1", 1'b0);
        do_bit(1'b0, "protocol", "arst_b2", 1'b0);
        do_bit(1'b1, "protocol", "arst_b3", 1'b0);
        do_bit(1'b1, "protocol", "arst_b4_detect", 1'b0);
        chk("protocol", "detect_active_before_arst", 64'd1, {63'b0, detected});
        serial_in = 1'b1;
        rst_n = 1'b0;
        #2;
        chk("protocol", "arst_clears_detect_no_clk", 64'd0, {63'b0, detected});
        serial_in = 1'b0;
        #1;
        chk("protocol", "arst_holds_detect_low", 64'd0, {63'b0, detected});
        @(negedge clk);
        #1;
        chk("protocol", "arst_bits_ignored", 64'd0, {63'b0, detected});
        #1;
        rst_n = 1'b1;
        hist = 4'b0000;
        do_bit(1'b1, "protocol", "arst_restart_b1", 1'b0);
        do_bit(1'b0, "protocol", "arst_restart_b2", 1'b0);
        do_bit(1'b1, "protocol", "arst_restart_b3", 1'b0);
        do_bit(1'b1, "protocol", "arst_restart_b4_detect", 1'b0);

        // ---------------- exhaustive: all 4-bit streams ----------------
        for (k = 0; k < 16; k = k + 1) begin
            apply_reset;
            for (j = 3; j >= 0; j = j - 1) begin
                bitv = (k >> j) & 1;
                $sformat(label, "exh4_%0d_b%0d", k, 4 - j);
                do_bit(bitv, "exhaustive", label, 1'b0);
            end
        end

        // ---------------- exhaustive: all 5-bit streams ----------------
        for (k = 0; k < 32; k = k + 1) begin
            apply_reset;
            for (j = 4; j >= 0; j = j - 1) begin
                bitv = (k >> j) & 1;
                $sformat(label, "exh5_%0d_b%0d", k, 5 - j);
                do_bit(bitv, "exhaustive", label, 1'b0);
            end
        end

        // ---------------- exhaustive: all 6-bit streams ----------------
        for (k = 0; k < 64; k = k + 1) begin
            apply_reset;
            for (j = 5; j >= 0; j = j - 1) begin
                bitv = (k >> j) & 1;
                $sformat(label, "exh6_%0d_b%0d", k, 6 - j);
                do_bit(bitv, "exhaustive", label, 1'b0);
            end
        end

        // ---------------- random streams ----------------
        apply_reset;
        for (i = 0; i < 256; i = i + 1) begin
            rndbit = $random & 1'b1;
            $sformat(label, "rand_b%0d", i);
            if ((i % 16) == 0) begin
                do_bit(rndbit, "random", label, 1'b1);
            end else begin
                do_bit(rndbit, "random", label, 1'b0);
            end
            if ((i % 32) == 31) begin
                $sformat(label, "rand_defined_%0d", i);
                chk("undefined", label, 64'd1, {63'b0, !$isunknown(detected)});
            end
        end

        // ---------------- final output sanity ----------------
        chk("undefined", "final_detected_known", 64'd1, {63'b0, !$isunknown(detected)});
        chk("undefined", "final_detected_low", 64'd0, {63'b0, detected});

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

    initial begin
        #200000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule