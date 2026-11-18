// Independent reference for s6 "synchronous FIFO with 8-bit data and depth 4 with full and empty flags".
// Written from the prompt as a plain queue model. Conventions the prompt leaves open, chosen as the common ones:
//  * a write while full is ignored, and a read while empty is ignored, even if the other operation happens in the
//    same cycle (so a simultaneous read does not make room for a write in the same cycle);
//  * the read data register `dout` is updated on the clock edge that accepts a read (registered read), so it is
//    only compared after a read has been accepted since reset;
//  * full/empty reflect the occupancy after the clock edge; reset is asynchronous and gives empty, not full.
module tb;
  reg clk = 0, rst_n = 1, wr_en = 0, rd_en = 0;
  reg [7:0] din = 0;
  wire [7:0] dout;
  wire full, empty;
  reg [7:0] fm [0:3];
  reg [7:0] dout_model = 0;
  reg dout_valid = 0;
  integer head = 0, tail = 0, cnt = 0;
  integer i, p, bad = 0, n = 0, saw_full = 0, saw_empty = 0;
  reg do_w, do_r;
  sync_fifo dut(.clk(clk), .rst_n(rst_n), .wr_en(wr_en), .rd_en(rd_en), .din(din), .dout(dout), .full(full), .empty(empty));
  always #5 clk = ~clk;

  task check;
    begin
      n = n + 1; if (full !== (cnt == 4)) bad = bad + 1;
      n = n + 1; if (empty !== (cnt == 0)) bad = bad + 1;
      if (dout_valid) begin n = n + 1; if (dout !== dout_model) bad = bad + 1; end
      if (cnt == 4) saw_full = saw_full + 1;
      if (cnt == 0) saw_empty = saw_empty + 1;
    end
  endtask

  task step(input r_n, input w, input r, input [7:0] d);
    begin
      @(negedge clk); rst_n = r_n; wr_en = w; rd_en = r; din = d;
      if (!r_n) begin #1; head = 0; tail = 0; cnt = 0; dout_valid = 0; check; end   // asynchronous reset
      @(posedge clk); #1;
      if (!r_n) begin head = 0; tail = 0; cnt = 0; dout_valid = 0; end
      else begin
        do_w = w && (cnt != 4);
        do_r = r && (cnt != 0);
        if (do_r) begin dout_model = fm[head]; dout_valid = 1; head = (head + 1) % 4; end
        if (do_w) begin fm[tail] = d; tail = (tail + 1) % 4; end
        cnt = cnt + (do_w ? 1 : 0) - (do_r ? 1 : 0);
      end
      check;
    end
  endtask

  initial begin
    step(0, 0, 0, 8'h00);                                        // reset: empty, not full
    step(1, 0, 1, 8'h00);                                        // read while empty is ignored
    for (i = 0; i < 6; i = i + 1) step(1, 1, 0, 8'hA0 + i);      // fill past full: the last two writes are ignored
    for (i = 0; i < 6; i = i + 1) step(1, 0, 1, 8'h00);          // drain past empty: first four come out in order
    for (i = 0; i < 30000; i = i + 1) begin
      p = (i / 200) % 3;                                         // write-heavy, read-heavy, balanced phases
      step(($random & 63) != 0,
           (p == 0) ? (($random & 7) != 0) : (p == 1) ? (($random & 7) == 0) : $random,
           (p == 0) ? (($random & 7) == 0) : (p == 1) ? (($random & 7) != 0) : $random,
           $random);
    end
    if (saw_full < 100 || saw_empty < 100) begin bad = bad + 1; n = n + 1; end    // the stimulus really reached both limits
    $display("s6 synchronous FIFO depth 4 (order, full, empty, no overflow/underflow): %0d mismatches of %0d checks", bad, n);
    $finish;
  end
endmodule
