module tb; reg [3:0] bin; wire [3:0] gray; integer i, bad = 0; reg [3:0] prev, d; integer ones;
  bin2gray_4b dut(.bin(bin), .gray(gray));
  initial begin
    for (i = 0; i < 16; i = i + 1) begin
      bin = i[3:0]; #1;
      if (gray !== (bin ^ (bin >> 1))) bad = bad + 1;                       // the definition
      if (i > 0) begin                                                       // the Gray property
        d = gray ^ prev; ones = d[0] + d[1] + d[2] + d[3];
        if (ones != 1) bad = bad + 1;                                        // consecutive codes differ in exactly 1 bit
      end
      prev = gray;
    end
    $display("c2 gray: %0d mismatches of 16 (definition and the one-bit-change property)", bad); $finish;
  end
endmodule
