module bin2gray_4b #(
    parameter WIDTH = 4
) (
    input  wire [WIDTH-1:0] bin,
    output wire [WIDTH-1:0] gray
);

    assign gray = (bin >> 1) ^ bin;

endmodule