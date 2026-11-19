// Independent reference for s3 "4-bit universal shift register with hold, shift left, shift right and parallel load".
// Written from the prompt, not from the design. Mode encoding follows the order the prompt names the operations:
// 00 hold, 01 shift left (toward the MSB, serial input enters at bit 0), 10 shift right (serial input enters at the MSB),
// 11 parallel load. Reset is asynchronous and active low: it must clear the register at once, without a clock edge.
module tb;
  reg clk = 0, rst_n = 1, sin_l = 0, sin_r = 0;
  reg [1:0] mode = 0;
  reg [3:0] d = 0;
  wire [3:0] q;
  reg [3:0] model = 0;
  reg known = 0;                                   // defined only after the first reset
  integer i, bad = 0, n = 0;
  universal_shift_register dut(.clk(clk), .rst_n(rst_n), .mode(mode), .d(d), .sin_l(sin_l), .sin_r(sin_r), .q(q));
  always #5 clk = ~clk;

  task step(input r_n, input [1:0] m, input [3:0] dd, input sl, input sr);
    begin
      @(negedge clk); rst_n = r_n; mode = m; d = dd; sin_l = sl; sin_r = sr;
      #1;
      if (!r_n) model = 4'd0;                                           // asynchronous clear: no clock edge needed
      if (!r_n || known) begin n = n + 1; if (q !== model) bad = bad + 1; end   // otherwise nothing may move between edges
      @(posedge clk); #1;
      if (!r_n) model = 4'd0;
      else case (m)
        2'd0: model = model;
        2'd1: model = {model[2:0], sl};
        2'd2: model = {sr, model[3:1]};
        default: model = dd;
      endcase
      known = 1;
      n = n + 1; if (q !== model) bad = bad + 1;
    end
  endtask

  initial begin
    step(0, 2'd0, 4'd0, 0, 0);                                  // reset first
    step(1, 2'd3, 4'b1010, 0, 0);                               // load 1010
    step(1, 2'd0, 4'b0000, 1, 1); step(1, 2'd0, 4'b1111, 0, 0);// hold ignores every other input
    step(1, 2'd1, 4'b0000, 1, 0); step(1, 2'd1, 4'b0000, 0, 1);// shift left twice: serial-left enters at bit 0
    step(1, 2'd2, 4'b0000, 0, 1); step(1, 2'd2, 4'b0000, 1, 0);// shift right twice: serial-right enters at the MSB
    step(1, 2'd3, 4'b1111, 0, 0); step(1, 2'd1, 4'b0000, 0, 0); step(1, 2'd1, 4'b0000, 0, 0); step(1, 2'd1, 4'b0000, 0, 0); step(1, 2'd1, 4'b0000, 0, 0);
    step(0, 2'd3, 4'b1001, 1, 1);                               // reset beats load
    for (i = 0; i < 20000; i = i + 1)
      step(($random & 15) != 0, $random, $random, $random, $random);
    $display("s3 universal shift register (hold/left/right/load, async reset): %0d mismatches of %0d checks", bad, n);
    $finish;
  end
endmodule
