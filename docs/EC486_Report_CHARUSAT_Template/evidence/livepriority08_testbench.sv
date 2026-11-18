module testbench;

  reg [7:0] in_tb;
  wire [2:0] code_tb;
  wire valid_tb;

  integer i;
  integer pass_count;
  integer fail_count;
  integer found;
  reg [2:0] exp_code;
  reg exp_valid;

  priority_encoder_8to3 dut (
    .in   (in_tb),
    .code (code_tb),
    .valid(valid_tb)
  );

  initial begin
    $dumpfile("design.vcd");
    $dumpvars(0, testbench);

    pass_count = 0;
    fail_count = 0;

    // Directed corner-case tests
    in_tb = 8'b00000000; #1; check_output(3'd0, 1'b0);
    in_tb = 8'b00000001; #1; check_output(3'd0, 1'b1);
    in_tb = 8'b00000010; #1; check_output(3'd1, 1'b1);
    in_tb = 8'b00000100; #1; check_output(3'd2, 1'b1);
    in_tb = 8'b00001000; #1; check_output(3'd3, 1'b1);
    in_tb = 8'b00010000; #1; check_output(3'd4, 1'b1);
    in_tb = 8'b00100000; #1; check_output(3'd5, 1'b1);
    in_tb = 8'b01000000; #1; check_output(3'd6, 1'b1);
    in_tb = 8'b10000000; #1; check_output(3'd7, 1'b1);
    in_tb = 8'b11111111; #1; check_output(3'd7, 1'b1);
    in_tb = 8'b01111111; #1; check_output(3'd6, 1'b1);
    in_tb = 8'b00111111; #1; check_output(3'd5, 1'b1);
    in_tb = 8'b00011111; #1; check_output(3'd4, 1'b1);
    in_tb = 8'b00001111; #1; check_output(3'd3, 1'b1);
    in_tb = 8'b00000111; #1; check_output(3'd2, 1'b1);
    in_tb = 8'b00000011; #1; check_output(3'd1, 1'b1);

    // Randomized stimulus
    for (i = 0; i < 100; i = i + 1) begin
      in_tb = $random;
      #1;
      compute_expected(in_tb);
      if (code_tb === exp_code && valid_tb === exp_valid) begin
        pass_count = pass_count + 1;
      end else begin
        fail_count = fail_count + 1;
        $display("FAIL: in=%b code=%b valid=%b exp_code=%b exp_valid=%b",
                 in_tb, code_tb, valid_tb, exp_code, exp_valid);
      end
    end

    $display("Passed: %0d", pass_count);
    $display("Failed: %0d", fail_count);
    if (fail_count == 0) begin
      $display("ALL TESTS PASSED");
    end
    $finish;
  end

  task check_output;
    input [2:0] expected_code;
    input expected_valid;
    begin
      compute_expected(in_tb);
      if (code_tb === exp_code && valid_tb === exp_valid) begin
        pass_count = pass_count + 1;
      end else begin
        fail_count = fail_count + 1;
        $display("FAIL: in=%b code=%b valid=%b exp_code=%b exp_valid=%b",
                 in_tb, code_tb, valid_tb, exp_code, exp_valid);
      end
    end
  endtask

  task compute_expected;
    input [7:0] din;
    begin
      exp_code = 3'd0;
      exp_valid = 1'b0;
      found = 0;
      if (din[7] && !found) begin exp_code = 3'd7; exp_valid = 1'b1; found = 1; end
      if (din[6] && !found) begin exp_code = 3'd6; exp_valid = 1'b1; found = 1; end
      if (din[5] && !found) begin exp_code = 3'd5; exp_valid = 1'b1; found = 1; end
      if (din[4] && !found) begin exp_code = 3'd4; exp_valid = 1'b1; found = 1; end
      if (din[3] && !found) begin exp_code = 3'd3; exp_valid = 1'b1; found = 1; end
      if (din[2] && !found) begin exp_code = 3'd2; exp_valid = 1'b1; found = 1; end
      if (din[1] && !found) begin exp_code = 3'd1; exp_valid = 1'b1; found = 1; end
      if (din[0] && !found) begin exp_code = 3'd0; exp_valid = 1'b1; found = 1; end
    end
  endtask

endmodule