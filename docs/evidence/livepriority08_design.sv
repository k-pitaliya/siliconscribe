module priority_encoder_8to3 (
    input  wire [7:0] in,
    output reg  [2:0] code,
    output reg        valid
);

    always @(*) begin
        code  = 3'd0;
        valid = 1'b0;

        casez (in)
            8'b1???????: begin code = 3'd7; valid = 1'b1; end
            8'b01??????: begin code = 3'd6; valid = 1'b1; end
            8'b001?????: begin code = 3'd5; valid = 1'b1; end
            8'b0001????: begin code = 3'd4; valid = 1'b1; end
            8'b00001???: begin code = 3'd3; valid = 1'b1; end
            8'b000001??: begin code = 3'd2; valid = 1'b1; end
            8'b0000001?: begin code = 3'd1; valid = 1'b1; end
            8'b00000001: begin code = 3'd0; valid = 1'b1; end
            default:     begin code = 3'd0; valid = 1'b0; end
        endcase
    end

endmodule