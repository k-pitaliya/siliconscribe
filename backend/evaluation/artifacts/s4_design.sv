module sipo_shift_reg #(
    parameter DATA_WIDTH = 8
) (
    input  wire                  clk,   // Clock, all state changes on posedge
    input  wire                  rst,   // Synchronous active-high reset
    input  wire                  din,   // Serial data input (new dout[0])
    output reg  [DATA_WIDTH-1:0] dout   // Parallel registered output
);

    always @(posedge clk) begin
        if (rst) begin
            dout <= {DATA_WIDTH{1'b0}};
        end else begin
            dout <= {dout[DATA_WIDTH-2:0], din};
        end
    end

endmodule