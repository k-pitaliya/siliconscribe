module priority_encoder_8to3 #(
    parameter integer WIDTH     = 8,
    parameter integer OUT_WIDTH = 3
) (
    input  wire [WIDTH-1:0]     in,
    output reg  [OUT_WIDTH-1:0] code,
    output reg                  valid
);

    // Combinational priority chain: highest index wins.
    // Defaults guarantee every output is driven on every path,
    // so no latch or floating value can be inferred.
    always @(*) begin
        code  = {OUT_WIDTH{1'b0}};
        valid = 1'b0;

        if (in[7]) begin
            code  = 3'd7;
            valid = 1'b1;
        end else if (in[6]) begin
            code  = 3'd6;
            valid = 1'b1;
        end else if (in[5]) begin
            code  = 3'd5;
            valid = 1'b1;
        end else if (in[4]) begin
            code  = 3'd4;
            valid = 1'b1;
        end else if (in[3]) begin
            code  = 3'd3;
            valid = 1'b1;
        end else if (in[2]) begin
            code  = 3'd2;
            valid = 1'b1;
        end else if (in[1]) begin
            code  = 3'd1;
            valid = 1'b1;
        end else if (in[0]) begin
            code  = 3'd0;
            valid = 1'b1;
        end else begin
            // in == 8'b0000_0000: no request asserted.
            code  = 3'd0;
            valid = 1'b0;
        end
    end

endmodule