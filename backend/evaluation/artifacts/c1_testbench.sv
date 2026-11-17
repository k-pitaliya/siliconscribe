module testbench;

    reg  [7:0] in;
    wire [2:0] code;
    wire       valid;

    integer pass_count = 0;
    integer fail_count = 0;
    integer i;
    integer rand_int;

    reg [2:0]  exp_code;
    reg        exp_valid;
    reg        unk_flag;
    reg [7:0]  vec_val;

    reg [8*64-1:0] label;
    reg [8*64-1:0] base_name;

    priority_encoder_8to3 dut (
        .in(in),
        .code(code),
        .valid(valid)
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

    // Independent model derived only from the specification truth table.
    // Highest asserted bit wins; first match in the if/else-if chain wins.
    function [2:0] spec_code;
        input [7:0] v;
        begin
            if (v[7]) begin
                spec_code = 3'd7;
            end else if (v[6]) begin
                spec_code = 3'd6;
            end else if (v[5]) begin
                spec_code = 3'd5;
            end else if (v[4]) begin
                spec_code = 3'd4;
            end else if (v[3]) begin
                spec_code = 3'd3;
            end else if (v[2]) begin
                spec_code = 3'd2;
            end else if (v[1]) begin
                spec_code = 3'd1;
            end else begin
                spec_code = 3'd0;
            end
        end
    endfunction

    // Independent valid model: reduction-OR of the input.
    function spec_valid;
        input [7:0] v;
        begin
            spec_valid = |v;
        end
    endfunction

    // Drive one vector, wait for combinational settling, then check both outputs.
    task apply_vector;
        input [7:0] v;
        input [8*24-1:0] catg;
        input [8*64-1:0] nm;
        begin
            in = v;
            #5;
            exp_code  = spec_code(v);
            exp_valid = spec_valid(v);

            $sformat(label, "%0s_code", nm);
            chk(catg, label, {61'b0, exp_code}, {61'b0, code});

            $sformat(label, "%0s_valid", nm);
            chk(catg, label, {63'b0, exp_valid}, {63'b0, valid});
        end
    endtask

    // Watchdog: a hung design must not hang the simulation.
    initial begin
        #100000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        // Initial state check: outputs must be defined before normal stimulus.
        in = 8'b0;
        #5;
        chk("reset", "powerup_code_zero", 64'd0, {61'b0, code});
        chk("reset", "powerup_valid_zero", 64'd0, {63'b0, valid});
        // Unknown-ness is tested per signal: Icarus mis-evaluates
        // $isunknown() on a concatenation temp net (spurious 1).
        unk_flag = (^code === 1'bx) | (^valid === 1'bx);
        chk("undefined", "powerup_outputs_known", 64'd0, {63'b0, unk_flag});

        // Directed corner cases: all zeros, all ones, every single bit,
        // and boundary values where only the top or bottom bit differs.
        apply_vector(8'h00, "corner", "all_zeros");
        apply_vector(8'hFF, "corner", "all_ones");
        apply_vector(8'h7F, "corner", "all_but_msb");
        apply_vector(8'hFE, "corner", "all_but_lsb");
        apply_vector(8'h80, "corner", "msb_only_boundary");
        apply_vector(8'h01, "corner", "lsb_only_boundary");

        for (i = 0; i < 8; i = i + 1) begin
            $sformat(base_name, "onehot_%0d", i);
            apply_vector(8'd1 << i, "corner", base_name);
        end

        // Directed multi-hot priority conflicts: only the highest bit matters.
        apply_vector(8'h03, "directed", "bits1_0");
        apply_vector(8'h06, "directed", "bits2_1");
        apply_vector(8'h0C, "directed", "bits3_2");
        apply_vector(8'h18, "directed", "bits4_3");
        apply_vector(8'h30, "directed", "bits5_4");
        apply_vector(8'h60, "directed", "bits6_5");
        apply_vector(8'hC0, "directed", "bits7_6");
        apply_vector(8'h81, "directed", "bits7_0");
        apply_vector(8'h42, "directed", "bits6_1");
        apply_vector(8'h24, "directed", "bits5_2");
        apply_vector(8'hAA, "directed", "alt_1010");
        apply_vector(8'h55, "directed", "alt_0101");
        apply_vector(8'hF0, "directed", "upper_nibble");
        apply_vector(8'h0F, "directed", "lower_nibble");
        apply_vector(8'h33, "directed", "pattern_00110011");
        apply_vector(8'hCC, "directed", "pattern_11001100");

        // No undefined or reserved encodings exist; verify outputs are never X/Z.
        in = 8'h00;
        #5;
        unk_flag = (^code === 1'bx) | (^valid === 1'bx);
        chk("undefined", "zero_outputs_known", 64'd0, {63'b0, unk_flag});

        in = 8'hFF;
        #5;
        unk_flag = (^code === 1'bx) | (^valid === 1'bx);
        chk("undefined", "ones_outputs_known", 64'd0, {63'b0, unk_flag});

        // Hold/stability: re-apply the same input after a delay; outputs must
        // remain identical, proving no hidden state or latching.
        apply_vector(8'h08, "hold", "bit3_first");
        #10;
        apply_vector(8'h08, "hold", "bit3_second");
        #10;
        apply_vector(8'h00, "hold", "zero_first");
        #10;
        apply_vector(8'h00, "hold", "zero_second");
        #10;
        apply_vector(8'hA5, "hold", "a5_first");
        #10;
        apply_vector(8'hA5, "hold", "a5_second");

        // Single-input-change sequence: walking ones up, then walking zeros down.
        // Each consecutive pair differs in exactly ONE input bit.
        vec_val = 8'h00;
        apply_vector(vec_val, "toggle", "walk_start");
        for (i = 0; i < 8; i = i + 1) begin
            vec_val = vec_val | (8'd1 << i);
            $sformat(base_name, "walk_up_%0d", i);
            apply_vector(vec_val, "toggle", base_name);
        end
        for (i = 0; i < 8; i = i + 1) begin
            vec_val = vec_val & ~(8'd1 << i);
            $sformat(base_name, "walk_dn_%0d", i);
            apply_vector(vec_val, "toggle", base_name);
        end

        // Exhaustive enumeration of all 256 possible input patterns.
        for (i = 0; i < 256; i = i + 1) begin
            vec_val = i;
            $sformat(base_name, "exh_%0d", i);
            apply_vector(vec_val, "exhaustive", base_name);
        end

        // Additional randomized vectors.
        for (i = 0; i < 100; i = i + 1) begin
            rand_int = $random;
            vec_val  = rand_int[7:0];
            $sformat(base_name, "rand_%0d", i);
            apply_vector(vec_val, "random", base_name);
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

endmodule