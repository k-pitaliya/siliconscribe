module tb; reg [7:0] in; wire [2:0] code; wire valid; integer i, bad = 0; reg [2:0] exp_c; reg exp_v; integer k;
  priority_encoder_8to3 dut(.in(in), .code(code), .valid(valid));
  initial begin
    for (i = 0; i < 256; i = i + 1) begin
      in = i[7:0]; #1;
      exp_v = (in != 0); exp_c = 0;
      for (k = 0; k < 8; k = k + 1) if (in[k]) exp_c = k[2:0];     // highest set bit wins
      if (code !== exp_c || valid !== exp_v) begin bad = bad + 1; if (bad < 4) $display("MISMATCH in=%b code=%b valid=%b exp=%b/%b", in, code, valid, exp_c, exp_v); end
    end
    $display("c1 priority encoder: %0d mismatches of 256", bad); $finish;
  end
endmodule
