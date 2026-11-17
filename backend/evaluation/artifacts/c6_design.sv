module mag_compare_4bit #(
    parameter WIDTH = 4
) (
    input  wire [WIDTH-1:0] a,   // First unsigned operand, a[WIDTH-1] is MSB
    input  wire [WIDTH-1:0] b,   // Second unsigned operand, b[WIDTH-1] is MSB
    output wire             gt,  // High when a > b
    output wire             eq,  // High when a == b
    output wire             lt   // High when a < b
);

    assign eq = (a == b);
    assign gt = (a > b);
    assign lt = (a < b);

endmodule