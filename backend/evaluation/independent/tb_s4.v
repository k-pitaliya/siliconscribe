// Independent reference for s4 "serial-in parallel-out 8-bit shift register with synchronous reset".
// Written from the prompt. Each clock edge shifts the serial bit in at bit 0 (older bits move toward the MSB);
// the active-high reset is SYNCHRONOUS, so changing it between clock edges must change nothing.
module tb;
  reg clk = 0, rst = 0, din = 0;
  wire [7:0] dout;
  reg [7:0] model = 0;
  reg known = 0;                                   // the register is only defined after the first reset edge
  integer i, bad = 0, n = 0;
  sipo_shift_reg dut(.clk(clk), .rst(rst), .din(din), .dout(dout));
  always #5 clk = ~clk;

  task step(input r, input b);
    begin
      @(negedge clk); rst = r; din = b; #1;
      if (known) begin n = n + 1; if (dout !== model) bad = bad + 1; end   // inputs changed between edges: no effect yet
      @(posedge clk); #1;
      if (r) model = 8'd0; else model = {model[6:0], b};
      known = 1;
      n = n + 1; if (dout !== model) bad = bad + 1;
    end
  endtask

  initial begin
    step(1, 0);
    for (i = 0; i < 8; i = i + 1) step(0, 1);          // fill with ones
    for (i = 0; i < 8; i = i + 1) step(0, i[0]);       // then an alternating pattern
    step(1, 1); step(0, 1); step(1, 0); step(1, 1);    // reset overrides the incoming bit, also back to back
    for (i = 0; i < 20000; i = i + 1) step(($random & 15) == 0, $random);
    $display("s4 serial-in parallel-out shift register (sync reset): %0d mismatches of %0d checks", bad, n);
    $finish;
  end
endmodule
