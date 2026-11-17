module alu4 #(
    parameter integer WIDTH = 4
) (
    input  wire [WIDTH-1:0] a,
    input  wire [WIDTH-1:0] b,
    input  wire [2:0]       op,
    output reg  [WIDTH-1:0] y,
    output reg              carry,
    output reg              overflow
);

    // Extended-width scratch register used for ADD / SUB arithmetic.
    reg [WIDTH:0] tmp;

    always @(*) begin
        // Defaults guarantee every output is assigned on every path.
        y        = {WIDTH{1'b0}};
        carry    = 1'b0;
        overflow = 1'b0;
        tmp      = {(WIDTH+1){1'b0}};

        case (op)
            3'b000: begin
                // ADD: full unsigned sum, low bits to y, MSB to carry.
                tmp      = {1'b0, a} + {1'b0, b};
                y        = tmp[WIDTH-1:0];
                carry    = tmp[WIDTH];
                overflow = (a[WIDTH-1] == b[WIDTH-1]) &&
                           (y[WIDTH-1] != a[WIDTH-1]);
            end

            3'b001: begin
                // SUB: a - b modulo 2**WIDTH, no-borrow flag on carry.
                tmp      = {1'b0, a} - {1'b0, b};
                y        = tmp[WIDTH-1:0];
                carry    = ~tmp[WIDTH];
                overflow = (a[WIDTH-1] != b[WIDTH-1]) &&
                           (y[WIDTH-1] != a[WIDTH-1]);
            end

            3'b010: begin
                y        = a & b;
                carry    = 1'b0;
                overflow = 1'b0;
            end

            3'b011: begin
                y        = a | b;
                carry    = 1'b0;
                overflow = 1'b0;
            end

            3'b100: begin
                y        = a ^ b;
                carry    = 1'b0;
                overflow = 1'b0;
            end

            default: begin
                // 101, 110, 111: reserved / undefined -> all zeros.
                y        = {WIDTH{1'b0}};
                carry    = 1'b0;
                overflow = 1'b0;
            end
        endcase
    end

endmodule