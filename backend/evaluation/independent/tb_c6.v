module tb; reg [3:0] a, b; wire gt, eq, lt; integer i, j, bad = 0;
  mag_compare_4bit dut(.a(a), .b(b), .gt(gt), .eq(eq), .lt(lt));
  initial begin
    for (i = 0; i < 16; i = i + 1) for (j = 0; j < 16; j = j + 1) begin
      a = i[3:0]; b = j[3:0]; #1;
      if (gt !== (i > j) || eq !== (i == j) || lt !== (i < j)) bad = bad + 1;
    end
    $display("c6 comparator: %0d mismatches of 256", bad); $finish;
  end
endmodule
