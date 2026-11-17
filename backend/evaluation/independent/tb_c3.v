module tb; reg [3:0] a, b; reg cin; wire [3:0] sum; wire cout; integer i, j, c, bad = 0; reg [4:0] e;
  ripple_carry_adder dut(.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
  initial begin
    for (i = 0; i < 16; i = i + 1) for (j = 0; j < 16; j = j + 1) for (c = 0; c < 2; c = c + 1) begin
      a = i[3:0]; b = j[3:0]; cin = c[0]; #1; e = i + j + c;
      if ({cout, sum} !== e) bad = bad + 1;
    end
    $display("c3 adder: %0d mismatches of 512", bad); $finish;
  end
endmodule
