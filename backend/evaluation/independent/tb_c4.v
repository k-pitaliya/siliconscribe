module tb; reg [7:0] i0, i1, i2, i3; reg [1:0] sel; wire [7:0] y; integer n, s, bad = 0; reg [7:0] e;
  mux_4to1 dut(.in0(i0), .in1(i1), .in2(i2), .in3(i3), .sel(sel), .y(y));
  initial begin
    for (n = 0; n < 400; n = n + 1) for (s = 0; s < 4; s = s + 1) begin
      i0 = $random; i1 = $random; i2 = $random; i3 = $random; sel = s[1:0]; #1;
      e = (s == 0) ? i0 : (s == 1) ? i1 : (s == 2) ? i2 : i3;
      if (y !== e) bad = bad + 1;
    end
    $display("c4 mux: %0d mismatches of 1600 (random data, every select)", bad); $finish;
  end
endmodule
