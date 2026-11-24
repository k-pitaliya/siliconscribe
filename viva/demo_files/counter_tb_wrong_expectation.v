`timescale 1ns/1ps
module testbench;
    reg clk, rst_n, enable;
    wire [3:0] count;
    integer pass_count = 0;
    integer fail_count = 0;
    integer s;
    reg [3:0] expected;
    reg [8*64-1:0] label;

    // Standard check task: ONE machine-readable line per comparison.
    //   CHK|<PASS|FAIL>|<category>|<name>|<time>|<expected hex>|<actual hex>|
    // Categories: directed, corner, random, reset, hold, exhaustive, toggle, protocol, undefined_opcode.
    task chk;
        input [8*24-1:0] cat;     // Verilog keeps the RIGHTMOST characters of an over-long string,
        input [8*64-1:0] name;    // so keep categories <= 24 and names <= 64 chars
        input [255:0] exp_v;      // 256 bits: a 64-bit task silently ignored the upper bits of wider ports
        input [255:0] act_v;      // (self-review: a 72-bit design that dropped its top byte PASSED)
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

    counter #(4) dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        // Phase 1: power-up asynchronous reset (the count must clear without a clock edge).
        rst_n = 0; enable = 0;
        #1;
        chk("reset", "power_up_reset_clears_count", 0, count);
        @(negedge clk);
        chk("reset", "count_held_while_in_reset", 0, count);

        // Phase 2: count 0..15 and wrap. At EVERY state also prove enable=0 holds the value.
        rst_n = 1; enable = 1;
        chk("reset", "released_count_still_zero", 0, count);
        for (s = 1; s < 17; s = s + 1) begin   // 16 steps: count 1..15, then the wrap to 0
            @(negedge clk);
            expected = s % 16;
            if (s == 16) chk("corner", "wraparound_15_to_0", expected, count);
            else begin
                $sformat(label, "count_up_to_%0d", expected);
                chk("directed", label, expected, count);
            end
            enable = 0;
            $sformat(label, "enable_low_holds_%0d", expected);
            @(negedge clk); chk("hold", label, expected, count);
            @(negedge clk); chk("hold", label, expected, count);
            enable = 1;
        end

        // Phase 3: asynchronous reset in the middle of counting, with enable still high.
        @(negedge clk); chk("directed", "counting_resumes_after_wrap", 1, count);
        @(negedge clk); @(negedge clk);
        #1 rst_n = 0; #1;
        chk("reset", "async_reset_clears_immediately", 0, count);
        @(negedge clk); chk("reset", "reset_wins_over_enable_high", 0, count);
        enable = 0;
        @(negedge clk); chk("reset", "reset_holds_with_enable_low", 0, count);

        // Phase 4: release reset with enable high; counting restarts from zero.
        enable = 1; rst_n = 1;
        @(negedge clk); chk("reset", "counting_restarts_from_zero", 1, count);
        @(negedge clk); chk("reset", "counting_continues", 3, count);

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
