// Independent reference for f2 "traffic light controller FSM with red, green and yellow states and a synchronous reset".
// Written from the prompt as a behavioural model. Properties checked: exactly one light is on at all times after reset;
// the order is red -> green -> yellow -> red; each colour lasts a fixed number of enabled cycles (the prompt gives no
// numbers, so the design's declared defaults 30/30/10 are used); `enable` low freezes the controller; the
// active-high reset is SYNCHRONOUS (it only takes effect at a clock edge) and returns to red.
module tb;
  localparam integer DUR_R = 30, DUR_G = 30, DUR_Y = 10;
  reg clk = 0, rst = 0, enable = 0;
  wire red, green, yellow;
  integer st = 0, age = 0;                                  // st: 0 red, 1 green, 2 yellow; age: enabled edges spent in this colour
  reg known = 0;
  integer i, bad = 0, n = 0, changes = 0;
  traffic_light_controller dut(.clk(clk), .rst(rst), .enable(enable), .red(red), .green(green), .yellow(yellow));
  always #5 clk = ~clk;

  function integer dur(input integer s);
    dur = (s == 0) ? DUR_R : (s == 1) ? DUR_G : DUR_Y;
  endfunction

  task check;
    begin
      n = n + 1; if ({red, green, yellow} !== ((st == 0) ? 3'b100 : (st == 1) ? 3'b010 : 3'b001)) bad = bad + 1;
    end
  endtask

  task step(input r, input e);
    begin
      @(negedge clk); rst = r; enable = e; #1;
      if (known) check;                                      // inputs changed between edges: lights must not have moved
      @(posedge clk); #1;
      if (r) begin st = 0; age = 0; end
      else if (e) begin
        if (age == dur(st) - 1) begin st = (st + 1) % 3; age = 0; changes = changes + 1; end
        else age = age + 1;
      end
      known = 1;
      check;
    end
  endtask

  initial begin
    step(1, 1);                                              // reset
    for (i = 0; i < 3 * (DUR_R + DUR_G + DUR_Y) + 5; i = i + 1) step(0, 1);    // three full cycles
    for (i = 0; i < 25; i = i + 1) step(0, 0);               // frozen
    for (i = 0; i < 100; i = i + 1) step(0, 1);
    step(1, 0);                                              // reset works with enable low
    for (i = 0; i < 40000; i = i + 1) step(($random & 255) == 0, ($random & 7) != 0);
    if (changes < 300) begin bad = bad + 1; n = n + 1; end   // many colour changes were exercised
    $display("f2 traffic light controller (one-hot, order, durations, enable, sync reset): %0d mismatches of %0d checks, %0d colour changes", bad, n, changes);
    $finish;
  end
endmodule
