module traffic_light_controller #(
    parameter integer RED_CYCLES    = 30,
    parameter integer GREEN_CYCLES  = 30,
    parameter integer YELLOW_CYCLES = 10
) (
    input  wire clk,
    input  wire rst,
    input  wire enable,
    output reg  red,
    output reg  green,
    output reg  yellow
);

    // ------------------------------------------------------------------
    // State encoding
    // ------------------------------------------------------------------
    localparam [1:0] S_RED    = 2'b00;
    localparam [1:0] S_GREEN  = 2'b01;
    localparam [1:0] S_YELLOW = 2'b10;

    // ------------------------------------------------------------------
    // Constant functions used only to size the counter at elaboration time
    // ------------------------------------------------------------------
    function integer max3;
        input integer a;
        input integer b;
        input integer c;
        begin
            max3 = a;
            if (b > max3) begin
                max3 = b;
            end
            if (c > max3) begin
                max3 = c;
            end
        end
    endfunction

    function integer clog2;
        input integer value;
        integer v;
        begin
            v = value - 1;
            clog2 = 0;
            while (v > 0) begin
                clog2 = clog2 + 1;
                v = v >> 1;
            end
        end
    endfunction

    localparam integer MAX_DURATION = max3(RED_CYCLES, GREEN_CYCLES, YELLOW_CYCLES);
    localparam integer COUNT_WIDTH  = (MAX_DURATION > 1) ? clog2(MAX_DURATION) : 1;

    // ------------------------------------------------------------------
    // Registers
    // ------------------------------------------------------------------
    reg [1:0]             state;
    reg [COUNT_WIDTH-1:0] counter;
    reg [1:0]             next_state;
    reg [COUNT_WIDTH-1:0] terminal; // duration(state) - 1

    // ------------------------------------------------------------------
    // Duration comparator value for the current state
    // ------------------------------------------------------------------
    always @(*) begin
        case (state)
            S_GREEN: begin
                terminal = GREEN_CYCLES - 1;
            end
            S_YELLOW: begin
                terminal = YELLOW_CYCLES - 1;
            end
            default: begin
                terminal = RED_CYCLES - 1;
            end
        endcase
    end

    // ------------------------------------------------------------------
    // Next-state logic (fixed cyclic sequence, illegal state recovers to red)
    // ------------------------------------------------------------------
    always @(*) begin
        case (state)
            S_RED: begin
                next_state = S_GREEN;
            end
            S_GREEN: begin
                next_state = S_YELLOW;
            end
            S_YELLOW: begin
                next_state = S_RED;
            end
            default: begin
                next_state = S_RED;
            end
        endcase
    end

    // ------------------------------------------------------------------
    // State register, counter and registered lamp outputs
    // Priority: (1) synchronous reset  (2) enable low -> hold
    //           (3) enable high -> count / transition
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst) begin
            state   <= S_RED;
            counter <= {COUNT_WIDTH{1'b0}};
            red     <= 1'b1;
            green   <= 1'b0;
            yellow  <= 1'b0;
        end else if (enable) begin
            if ((state == S_RED) || (state == S_GREEN) || (state == S_YELLOW)) begin
                if (counter == terminal) begin
                    state   <= next_state;
                    counter <= {COUNT_WIDTH{1'b0}};
                    red     <= (next_state == S_RED);
                    green   <= (next_state == S_GREEN);
                    yellow  <= (next_state == S_YELLOW);
                end else begin
                    counter <= counter + 1'b1;
                end
            end else begin
                // Illegal or unknown encoding: force the safe red indication
                // and return to S_RED.
                state   <= S_RED;
                counter <= {COUNT_WIDTH{1'b0}};
                red     <= 1'b1;
                green   <= 1'b0;
                yellow  <= 1'b0;
            end
        end
    end

endmodule