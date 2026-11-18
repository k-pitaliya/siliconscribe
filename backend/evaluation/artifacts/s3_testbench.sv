module testbench;

    localparam WIDTH = 4;

    reg clk;
    reg rst_n;
    reg [1:0] mode;
    reg [WIDTH-1:0] d;
    reg sin_l;
    reg sin_r;
    wire [WIDTH-1:0] q;

    integer pass_count = 0;
    integer fail_count = 0;

    integer k;
    integer st;
    reg [7:0] vi;
    reg [31:0] rnd;
    reg [1:0] rmode;
    reg [WIDTH-1:0] rdin;
    reg ril;
    reg rir;
    reg [WIDTH-1:0] cur;
    reg [8*64-1:0] label;

    universal_shift_register #(.WIDTH(WIDTH)) dut (
        .clk(clk),
        .rst_n(rst_n),
        .mode(mode),
        .d(d),
        .sin_l(sin_l),
        .sin_r(sin_r),
        .q(q)
    );

    initial begin
        clk = 1'b0;
    end

    always #5 clk = ~clk;

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

    // Reference model derived ONLY from the specification truth table.
    function [WIDTH-1:0] next_q;
        input [WIDTH-1:0] cur_v;
        input [1:0] m;
        input [WIDTH-1:0] din;
        input il;
        input ir;
        begin
            if (m == 2'b00) begin
                next_q = cur_v;
            end else if (m == 2'b01) begin
                next_q = {cur_v[WIDTH-2:0], il};
            end else if (m == 2'b10) begin
                next_q = {ir, cur_v[WIDTH-1:1]};
            end else begin
                next_q = din;
            end
        end
    endfunction

    // Drive inputs one time step after a falling edge, then sample q on the NEXT falling edge.
    task op;
        input [1:0] m;
        input [WIDTH-1:0] din;
        input il;
        input ir;
        input [8*24-1:0] cat;
        input [8*64-1:0] nm;
        begin
            #1;
            mode = m;
            d = din;
            sin_l = il;
            sin_r = ir;
            @(negedge clk);
            cur = next_q(cur, m, din, il, ir);
            chk(cat, nm, {60'h0, cur}, {60'h0, q});
        end
    endtask

    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        rst_n = 1'b0;
        mode = 2'b00;
        d = {WIDTH{1'b0}};
        sin_l = 1'b0;
        sin_r = 1'b0;
        cur = {WIDTH{1'b0}};

        #1;
        chk("reset", "async reset clears q at start", 64'h0, {60'h0, q});

        #1;
        mode = 2'b11;
        d = {WIDTH{1'b1}};
        sin_l = 1'b1;
        sin_r = 1'b1;

        #1;
        chk("reset", "async reset overrides load while low", 64'h0, {60'h0, q});

        @(negedge clk);
        chk("reset", "q stays 0 across edge in reset", 64'h0, {60'h0, q});

        #1;
        rst_n = 1'b1;
        mode = 2'b00;
        d = {WIDTH{1'b0}};
        sin_l = 1'b0;
        sin_r = 1'b0;

        @(negedge clk);
        chk("reset", "q holds cleared 0 after release", 64'h0, {60'h0, q});

        #1;
        mode = 2'b11;
        d = 4'hF;

        @(negedge clk);
        chk("directed", "load 0xF after reset", 64'hF, {60'h0, q});
        cur = 4'hF;

        op(2'b11, 4'h0, 1'b0, 1'b0, "directed", "load all zeros");
        op(2'b11, 4'hF, 1'b1, 1'b1, "directed", "load all ones with sin high");
        op(2'b11, 4'h1, 1'b0, 1'b0, "directed", "load single bit 0");
        op(2'b11, 4'h2, 1'b1, 1'b1, "directed", "load single bit 1");
        op(2'b11, 4'h4, 1'b0, 1'b1, "directed", "load single bit 2");
        op(2'b11, 4'h8, 1'b1, 1'b0, "directed", "load single bit 3");

        op(2'b11, 4'h6, 1'b0, 1'b0, "directed", "load pattern 0110");
        op(2'b00, 4'h0, 1'b0, 1'b0, "hold", "hold retains 0110 cycle 1");
        op(2'b00, 4'hF, 1'b1, 1'b1, "hold", "hold retains 0110 cycle 2");
        op(2'b00, 4'h5, 1'b1, 1'b0, "hold", "hold retains 0110 cycle 3");

        op(2'b11, 4'h8, 1'b0, 1'b0, "corner", "load 1000");
        op(2'b01, 4'h0, 1'b0, 1'b0, "corner", "shift left discards MSB");
        op(2'b01, 4'h0, 1'b1, 1'b0, "corner", "shift left inserts sin_l=1");
        op(2'b11, 4'h1, 1'b0, 1'b0, "corner", "load 0001");
        op(2'b10, 4'h0, 1'b0, 1'b0, "corner", "shift right discards LSB");
        op(2'b10, 4'h0, 1'b0, 1'b1, "corner", "shift right inserts sin_r=1");

        op(2'b11, 4'h9, 1'b0, 1'b0, "directed", "load 1001");
        op(2'b01, 4'h3, 1'b0, 1'b1, "protocol", "shift left ignores sin_r,d");
        op(2'b10, 4'hC, 1'b1, 1'b0, "protocol", "shift right ignores sin_l,d");
        op(2'b00, 4'hA, 1'b1, 1'b1, "protocol", "hold ignores d and both sin");

        op(2'b11, 4'h9, 1'b0, 1'b0, "undefined", "mode 11 defined q known");
        op(2'b00, 4'h0, 1'b0, 1'b0, "undefined", "mode 00 defined q held");
        op(2'b01, 4'h0, 1'b1, 1'b1, "undefined", "mode 01 defined q=0011");
        op(2'b10, 4'h0, 1'b1, 1'b1, "undefined", "mode 10 defined q=1001");

        #1;
        mode = 2'b11;
        d = 4'hF;
        sin_l = 1'b1;
        sin_r = 1'b1;

        #1;
        rst_n = 1'b0;

        #1;
        chk("reset", "async reset clears q mid-cycle", 64'h0, {60'h0, q});

        #1;
        rst_n = 1'b1;
        mode = 2'b00;
        d = 4'h0;
        sin_l = 1'b0;
        sin_r = 1'b0;
        cur = 4'h0;

        @(negedge clk);
        chk("reset", "q=0 after mid-cycle reset release", 64'h0, {60'h0, q});
        #1;

        op(2'b11, 4'hA, 1'b0, 1'b0, "toggle", "tgl0 load 1010");
        op(2'b11, 4'hB, 1'b0, 1'b0, "toggle", "tgl1 change d0 only");
        op(2'b11, 4'hA, 1'b0, 1'b0, "toggle", "tgl2 change d0 back");
        op(2'b10, 4'hA, 1'b0, 1'b0, "toggle", "tgl3 change mode0 only");
        op(2'b10, 4'hA, 1'b0, 1'b1, "toggle", "tgl4 change sin_r only");
        op(2'b10, 4'hA, 1'b1, 1'b1, "toggle", "tgl5 change sin_l only");
        op(2'b00, 4'hA, 1'b1, 1'b1, "toggle", "tgl6 change mode1 only");
        op(2'b00, 4'h2, 1'b1, 1'b1, "toggle", "tgl7 change d3 only");
        op(2'b00, 4'h0, 1'b1, 1'b1, "toggle", "tgl8 change d1 only");
        op(2'b00, 4'h1, 1'b1, 1'b1, "toggle", "tgl9 change d0 only");
        op(2'b00, 4'h5, 1'b1, 1'b1, "toggle", "tgl10 change d2 only");
        op(2'b01, 4'h5, 1'b1, 1'b1, "toggle", "tgl11 change mode0 only");
        op(2'b01, 4'h5, 1'b0, 1'b1, "toggle", "tgl12 change sin_l only");
        op(2'b01, 4'h5, 1'b0, 1'b0, "toggle", "tgl13 change sin_r only");
        op(2'b11, 4'h5, 1'b0, 1'b0, "toggle", "tgl14 change mode1 only");
        op(2'b11, 4'hD, 1'b0, 1'b0, "toggle", "tgl15 change d3 only");
        op(2'b01, 4'hD, 1'b0, 1'b0, "toggle", "tgl16 change mode0 only");
        op(2'b01, 4'hD, 1'b1, 1'b0, "toggle", "tgl17 change sin_l only");

        for (st = 0; st < 16; st = st + 1) begin
            $sformat(label, "exh load state=%0d", st);
            op(2'b11, st, 1'b0, 1'b0, "exhaustive", label);
            for (vi = 8'd0; vi < 8'd128; vi = vi + 1) begin
                $sformat(label, "exh st=%0d m=%0d d=%0h l=%0d r=%0d", st, vi[7:6], vi[5:2], vi[0], vi[1]);
                op(vi[7:6], vi[5:2], vi[0], vi[1], "exhaustive", label);
            end
        end

        for (k = 0; k < 200; k = k + 1) begin
            rnd = $random;
            rmode = rnd[1:0];
            rdin = rnd[5:2];
            ril = rnd[6];
            rir = rnd[7];
            $sformat(label, "rand k=%0d m=%0d d=%0h l=%0d r=%0d", k, rmode, rdin, ril, rir);
            op(rmode, rdin, ril, rir, "random", label);
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

    initial begin
        #300000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule