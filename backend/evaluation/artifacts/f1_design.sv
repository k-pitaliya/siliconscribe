module seq_detect_1011_moore (
    input  wire clk,
    input  wire rst_n,
    input  wire serial_in,
    output wire detected
);

    // ------------------------------------------------------------------
    // State encoding
    // ------------------------------------------------------------------
    localparam [2:0] IDLE   = 3'b000;
    localparam [2:0] S1     = 3'b001;
    localparam [2:0] S10    = 3'b010;
    localparam [2:0] S101   = 3'b011;
    localparam [2:0] DETECT = 3'b100;

    // ------------------------------------------------------------------
    // State registers
    // ------------------------------------------------------------------
    reg [2:0] state;
    reg [2:0] next_state;
    reg       detected_reg;

    // Moore output: combinational decode of state only
    assign detected = detected_reg;

    // ------------------------------------------------------------------
    // State register : asynchronous active-low reset
    // ------------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
        end else begin
            state <= next_state;
        end
    end

    // ------------------------------------------------------------------
    // Next-state logic : purely combinational function of state/serial_in
    // ------------------------------------------------------------------
    always @(*) begin
        case (state)
            IDLE: begin
                next_state = serial_in ? S1 : IDLE;
            end
            S1: begin
                next_state = serial_in ? S1 : S10;
            end
            S10: begin
                next_state = serial_in ? S101 : IDLE;
            end
            S101: begin
                next_state = serial_in ? DETECT : S10;
            end
            DETECT: begin
                next_state = serial_in ? S1 : S10;
            end
            default: begin
                next_state = IDLE;
            end
        endcase
    end

    // ------------------------------------------------------------------
    // Output logic : Moore, depends on state only (never on serial_in)
    // ------------------------------------------------------------------
    always @(*) begin
        case (state)
            DETECT: begin
                detected_reg = 1'b1;
            end
            default: begin
                detected_reg = 1'b0;
            end
        endcase
    end

endmodule