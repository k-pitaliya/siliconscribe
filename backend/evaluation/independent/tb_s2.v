// Independent reference for s2 "8-bit loadable up/down counter with synchronous reset" (hand-written from the prompt,
// not from the model's design or testbench). Priority: synchronous reset, then load, then count up (up_down=1) or down.
module tb;
  reg clk = 0, rst = 0, load = 0, up_down = 0;
  reg [7:0] din = 0;
  wire [7:0] dout;
  reg [7:0] model;
  reg known = 0;                                   // defined only after the first reset edge
  integer i, bad = 0, n = 0;
  loadable_updown_counter dut(.clk(clk), .rst(rst), .load(load), .up_down(up_down), .din(din), .dout(dout));
  always #5 clk = ~clk;

  // one clock cycle: drive on the falling edge, update the reference model, compare just after the rising edge
  task step(input r, input l, input u, input [7:0] d);
    begin
      @(negedge clk); rst = r; load = l; up_down = u; din = d; #1;
      if (known) begin n = n + 1; if (dout !== model) bad = bad + 1; end   // inputs changed between edges: no effect yet
      @(posedge clk); #1;
      if (r) model = 8'd0; else if (l) model = d; else if (u) model = model + 8'd1; else model = model - 8'd1;
      known = 1;
      n = n + 1;
      if (dout !== model) bad = bad + 1;
    end
  endtask

  initial begin
    step(1, 0, 0, 8'h00);                         // reset first: the state is defined from here on
    step(0, 1, 1, 8'hFE);                         // load 0xFE
    step(0, 0, 1, 8'h00); step(0, 0, 1, 8'h00); step(0, 0, 1, 8'h00);   // FF, 00 (wrap up), 01
    step(0, 1, 0, 8'h01);                         // load 0x01
    step(0, 0, 0, 8'h00); step(0, 0, 0, 8'h00); step(0, 0, 0, 8'h00);   // 00, FF (wrap down), FE
    step(1, 1, 1, 8'hAA);                         // reset beats load and count
    step(1, 0, 0, 8'h55); step(0, 0, 0, 8'h00);   // reset then count down from 0 -> FF
    step(0, 1, 1, 8'h80); step(0, 1, 0, 8'h7F);   // consecutive loads: the last one wins
    for (i = 0; i < 20000; i = i + 1)
      step(($random & 15) == 0, ($random & 3) == 0, $random, $random);
    $display("s2 loadable up/down counter (reset > load > count): %0d mismatches of %0d cycles", bad, n);
    $finish;
  end
endmodule
