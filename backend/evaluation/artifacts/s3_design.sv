module universal_shift_register #(
    parameter WIDTH = 4
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire [1:0]       mode,
    input  wire [WIDTH-1:0] d,
    input  wire             sin_l,
    input  wire             sin_r,
    output reg  [WIDTH-1:0] q
);

    // Mode encodings
    localparam [1:0] MODE_HOLD = 2'b00;
    localparam [1:0] MODE_SHL  = 2'b01;
    localparam [1:0] MODE_SHR  = 2'b10;
    localparam [1:0] MODE_LOAD = 2'b11;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            q <= {WIDTH{1'b0}};
        end else begin
            case (mode)
                MODE_HOLD: begin
                    q <= q;
                end
                MODE_SHL: begin
                    q <= {q[WIDTH-2:0], sin_l};
                end
                MODE_SHR: begin
                    q <= {sin_r, q[WIDTH-1:1]};
                end
                MODE_LOAD: begin
                    q <= d;
                end
                default: begin
                    q <= q;
                end
            endcase
        end
    end

endmodule