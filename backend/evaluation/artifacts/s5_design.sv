module clk_div_by4 (
    input  wire clk,
    input  wire rst_n,
    output wire clk_out
);

    reg [1:0] cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 2'b00;
        end else begin
            cnt <= cnt + 2'b01;
        end
    end

    assign clk_out = cnt[1];

endmodule