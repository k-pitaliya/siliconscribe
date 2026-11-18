module sync_fifo #(
    parameter integer DATA_WIDTH = 8,
    parameter integer DEPTH      = 4,
    parameter integer ADDR_WIDTH = 2
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  wr_en,
    input  wire                  rd_en,
    input  wire [DATA_WIDTH-1:0] din,
    output reg  [DATA_WIDTH-1:0] dout,
    output reg                   full,
    output reg                   empty
);

    // Occupancy counter width: enough to represent 0 .. DEPTH
    localparam integer COUNT_WIDTH = $clog2(DEPTH + 1);

    // Storage and pointer state
    reg [DATA_WIDTH-1:0]  mem [0:DEPTH-1];
    reg [ADDR_WIDTH-1:0]  wptr;
    reg [ADDR_WIDTH-1:0]  rptr;
    reg [COUNT_WIDTH-1:0] count;

    // Accept signals use the flag values present before the clock edge
    wire wr_ok;
    wire rd_ok;

    // Next occupancy value that also drives the next flag values
    wire [COUNT_WIDTH-1:0] count_next;

    assign wr_ok = wr_en & ~full;
    assign rd_ok = rd_en & ~empty;

    assign count_next = count + (wr_ok ? 1'b1 : 1'b0) - (rd_ok ? 1'b1 : 1'b0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wptr  <= {ADDR_WIDTH{1'b0}};
            rptr  <= {ADDR_WIDTH{1'b0}};
            count <= {COUNT_WIDTH{1'b0}};
            dout  <= {DATA_WIDTH{1'b0}};
            full  <= 1'b0;
            empty <= 1'b1;
        end else begin
            // Accepted write: store data and advance the write pointer
            if (wr_ok) begin
                mem[wptr] <= din;
                if (wptr == DEPTH - 1) begin
                    wptr <= {ADDR_WIDTH{1'b0}};
                end else begin
                    wptr <= wptr + 1'b1;
                end
            end

            // Accepted read: register the data and advance the read pointer
            if (rd_ok) begin
                dout <= mem[rptr];
                if (rptr == DEPTH - 1) begin
                    rptr <= {ADDR_WIDTH{1'b0}};
                end else begin
                    rptr <= rptr + 1'b1;
                end
            end

            // Occupancy counter and registered flags
            count <= count_next;
            full  <= (count_next == DEPTH);
            empty <= (count_next == 0);
        end
    end

endmodule