module tb; reg [2:0] a; reg en; wire [7:0] y; integer i, e, bad = 0; reg [7:0] exp_y;
  decoder_3to8 dut(.a(a), .en(en), .y(y));
  initial begin
    for (e = 0; e < 2; e = e + 1) for (i = 0; i < 8; i = i + 1) begin
      a = i[2:0]; en = e[0]; #1; exp_y = en ? (8'd1 << i) : 8'd0;     // one-hot when enabled (active high), all zero otherwise
      if (y !== exp_y) bad = bad + 1;
    end
    $display("c5 decoder: %0d mismatches of 16", bad); $finish;
  end
endmodule
