// Independent reference for f1 "Moore FSM that detects the serial bit sequence 1011 with overlapping allowed".
// Written from the definition, not from any state table: after a clock edge the output must be 1 exactly when the
// last four sampled bits are 1011 (so 1011011 is detected twice, the second 1 of the first match starting the next).
// It is a Moore machine: the output depends only on the state, so changing the input in the middle of a cycle
// must not change it. Reset is asynchronous and active low.
module tb;
  reg clk = 0, rst_n = 1, serial_in = 0;
  wire detected;
  reg [3:0] hist = 0;
  reg expect_d;
  integer i, bad = 0, n = 0, hits = 0;
  seq_detect_1011_moore dut(.clk(clk), .rst_n(rst_n), .serial_in(serial_in), .detected(detected));
  always #5 clk = ~clk;

  task step(input r_n, input b);
    begin
      @(negedge clk); rst_n = r_n; serial_in = b;
      if (!r_n) begin hist = 4'b0000; #1; n = n + 1; if (detected !== 1'b0) bad = bad + 1; end   // asynchronous reset
      @(posedge clk); #1;
      if (!r_n) hist = 4'b0000; else hist = {hist[2:0], b};
      expect_d = (hist == 4'b1011);
      if (expect_d) hits = hits + 1;
      n = n + 1; if (detected !== expect_d) bad = bad + 1;
      serial_in = ~b; #1;                                         // Moore: a mid-cycle input change must not move the output
      n = n + 1; if (detected !== expect_d) bad = bad + 1;
    end
  endtask

  initial begin
    step(0, 0);
    // directed streams: plain match, overlapping match, near misses, back-to-back, reset in the middle of a match
    step(1,1); step(1,0); step(1,1); step(1,1);                                   // 1011
    step(1,0); step(1,1); step(1,1);                                              // ...1011 again, overlapping the last 1
    step(1,1); step(1,0); step(1,1); step(1,0); step(1,1); step(1,1);             // 1 0 1 0 1 1: matches only at the end
    step(1,1); step(1,0); step(1,0); step(1,1); step(1,1);                        // 1 0 0 1 1: no match
    step(1,1); step(1,0); step(1,1); step(0,1); step(1,1);                        // reset before the final bit: no match
    for (i = 0; i < 20000; i = i + 1) step(($random & 63) != 0, $random);
    if (hits < 500) begin bad = bad + 1; n = n + 1; end                           // the random stream contained many matches
    $display("f1 Moore 1011 detector (overlapping, async reset): %0d mismatches of %0d checks, %0d matches", bad, n, hits);
    $finish;
  end
endmodule
