module loadable_updown_counter #(
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst,
    input  wire             load,
    input  wire             up_down,
    input  wire [WIDTH-1:0] din,
    output wire [WIDTH-1:0] dout
);

    reg [WIDTH-1:0] q;

    always @(posedge clk) begin
        if (rst) begin
            q <= {WIDTH{1'b0}};
        end else if (load) begin
            q <= din;
        end else if (up_down) begin
            q <= q + 1'b1;
        end else begin
            q <= q - 1'b1;
        end
    end

    assign dout = q;

endmodule