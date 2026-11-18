// Independent reference for s5 "clock divider that divides the input clock by 4 with an asynchronous reset".
// Written from the prompt: the output must be a clock whose period is exactly 4 input periods with a 50% duty
// cycle, and an asynchronous reset must force it low at once. The phase relative to reset is not specified by the
// prompt, so it is not checked. Input period is 10 ns, so: output period 40 ns, output high 20 ns.
module tb;
  reg clk = 0, rst_n = 1;
  wire clk_out;
  integer bad = 0, n = 0, rises = 0, k;
  time last_rise = 0;
  reg have_rise = 0;
  clk_div_by4 dut(.clk(clk), .rst_n(rst_n), .clk_out(clk_out));
  always #5 clk = ~clk;

  always @(posedge clk_out) begin
    if (have_rise) begin n = n + 1; if (($time - last_rise) != 40) bad = bad + 1; end
    last_rise = $time; have_rise = 1; rises = rises + 1;
  end
  always @(negedge clk_out) if (have_rise) begin n = n + 1; if (($time - last_rise) != 20) bad = bad + 1; end

  task apply_reset(input integer hold_ns);
    begin
      have_rise = 0; rst_n = 0; #1;
      n = n + 1; if (clk_out !== 1'b0) bad = bad + 1;       // asynchronous: low immediately, no clock edge needed
      #(hold_ns); rst_n = 1;
    end
  endtask

  initial begin
    @(negedge clk); apply_reset(30);
    repeat (400) @(posedge clk);
    if (rises < 90) bad = bad + 1; n = n + 1;                // it really toggles, about 100 rising edges in 400 cycles
    for (k = 0; k < 40; k = k + 1) begin
      repeat (5 + ({$random} % 40)) @(posedge clk);
      #(1 + ({$random} % 9));                                // reset at an arbitrary moment inside the cycle
      apply_reset(1 + ({$random} % 25));
    end
    repeat (200) @(posedge clk);
    $display("s5 clock divide-by-4 (period 4x, duty 50%%, async reset): %0d mismatches of %0d checks, %0d output edges", bad, n, rises);
    $finish;
  end
endmodule
