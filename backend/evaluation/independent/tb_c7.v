module tb; reg [3:0] a, b; reg [2:0] op; wire [3:0] y; wire carry, overflow; integer i, j, o, bad = 0, badov = 0; reg [3:0] e; reg eov;
  alu4 dut(.a(a), .b(b), .op(op), .y(y), .carry(carry), .overflow(overflow));
  initial begin
    for (o = 0; o < 5; o = o + 1) for (i = 0; i < 16; i = i + 1) for (j = 0; j < 16; j = j + 1) begin
      a = i[3:0]; b = j[3:0]; op = o[2:0]; #1;
      case (o) 0: e = a + b; 1: e = a - b; 2: e = a & b; 3: e = a | b; default: e = a ^ b; endcase
      eov = (o == 0) ? ((a[3] == b[3]) && (e[3] != a[3])) : (o == 1) ? ((a[3] != b[3]) && (e[3] != a[3])) : 1'b0;   // signed overflow
      if (y !== e) bad = bad + 1;
      if (overflow !== eov) badov = badov + 1;
    end
    $display("c7 alu (ops 0-4 in the prompt's order): %0d result mismatches, %0d signed-overflow mismatches of 1280", bad, badov); $finish;
  end
endmodule
