module testbench;

    parameter DATA_WIDTH = 8;
    parameter DEPTH      = 4;
    parameter ADDR_WIDTH = 2;

    reg                   clk;
    reg                   rst_n;
    reg                   wr_en;
    reg                   rd_en;
    reg  [DATA_WIDTH-1:0] din;

    wire [DATA_WIDTH-1:0] dout;
    wire                  full;
    wire                  empty;

    integer pass_count = 0;
    integer fail_count = 0;

    integer i;
    integer seq_idx;
    integer seed;
    integer t_next;
    integer t_nchg;
    integer t_rand;

    reg [DATA_WIDTH-1:0] m_mem [0:DEPTH-1];
    integer              m_count;
    integer              m_wptr;
    integer              m_rptr;
    reg [DATA_WIDTH-1:0] m_dout;
    reg                  m_full;
    reg                  m_empty;

    reg                  t_wr_ok;
    reg                  t_rd_ok;
    reg [DATA_WIDTH-1:0] t_exp_dout;
    reg                  t_exp_full;
    reg                  t_exp_empty;

    reg [8*64-1:0]       label;

    reg                  prev_wr;
    reg                  prev_rd;
    reg [7:0]            prev_din;

    reg                  t_rwr;
    reg                  t_rrd;
    reg [7:0]            t_rdin;

    initial begin
        clk = 1'b0;
    end

    always #5 clk = ~clk;

    sync_fifo #(
        .DATA_WIDTH (DATA_WIDTH),
        .DEPTH      (DEPTH),
        .ADDR_WIDTH (ADDR_WIDTH)
    ) dut (
        .clk   (clk),
        .rst_n (rst_n),
        .wr_en (wr_en),
        .rd_en (rd_en),
        .din   (din),
        .dout  (dout),
        .full  (full),
        .empty (empty)
    );

    // Standard check task: ONE machine-readable line per comparison.
    //   CHK|<PASS|FAIL>|<category>|<name>|<time>|<expected hex>|<actual hex>|
    // Categories: directed, corner, random, reset, hold, exhaustive, toggle, protocol, undefined_opcode.
    task chk;
        input [8*24-1:0] cat;     // Verilog keeps the RIGHTMOST characters of an over-long string,
        input [8*64-1:0] name;    // so keep categories <= 24 and names <= 64 chars
        input [63:0] exp_v;
        input [63:0] act_v;
        begin
            if (act_v === exp_v) begin
                pass_count = pass_count + 1;
                $display("CHK|PASS|%0s|%0s|%0t|%0h|%0h|", cat, name, $time, exp_v, act_v);
            end else begin
                fail_count = fail_count + 1;
                $display("CHK|FAIL|%0s|%0s|%0t|%0h|%0h|", cat, name, $time, exp_v, act_v);
                $display("FAIL: [%0s] %0s expected=%0h got=%0h", cat, name, exp_v, act_v);
            end
        end
    endtask

    // ------------------------------------------------------------------
    // Reference model of the FIFO, driven purely by the specification.
    // Expectations for the cycle are computed from the pre-edge state,
    // then the new inputs are applied and the outputs are sampled on the
    // NEXT falling edge (i.e. after the DUT has clocked on the rising edge).
    // ------------------------------------------------------------------
    task step;
        input             wr;
        input             rd;
        input [7:0]       d;
        input [8*24-1:0]  cat;
        begin
            t_wr_ok = wr & (~m_full);
            t_rd_ok = rd & (~m_empty);
            t_next  = m_count + (t_wr_ok ? 1 : 0) - (t_rd_ok ? 1 : 0);

            if (t_rd_ok)
                t_exp_dout = m_mem[m_rptr];
            else
                t_exp_dout = m_dout;

            t_exp_full  = (t_next == DEPTH) ? 1'b1 : 1'b0;
            t_exp_empty = (t_next == 0)     ? 1'b1 : 1'b0;

            wr_en = wr;
            rd_en = rd;
            din   = d;

            @(negedge clk);

            label = 0;
            $sformat(label, "dout_%0d_w%0d_r%0d_d%02h", seq_idx, wr, rd, d);
            chk(cat, label, {56'd0, t_exp_dout}, {56'd0, dout});

            label = 0;
            $sformat(label, "full_%0d_w%0d_r%0d_d%02h", seq_idx, wr, rd, d);
            chk(cat, label, {63'd0, t_exp_full}, {63'd0, full});

            label = 0;
            $sformat(label, "empty_%0d_w%0d_r%0d_d%02h", seq_idx, wr, rd, d);
            chk(cat, label, {63'd0, t_exp_empty}, {63'd0, empty});

            label = 0;
            $sformat(label, "no_full_empty_%0d", seq_idx);
            chk("protocol", label, 64'd0, {63'd0, (full & empty)});

            if (t_wr_ok) begin
                m_mem[m_wptr] = d;
                m_wptr = (m_wptr + 1) % DEPTH;
            end

            if (t_rd_ok) begin
                m_rptr = (m_rptr + 1) % DEPTH;
            end

            m_dout  = t_exp_dout;
            m_count = t_next;
            m_full  = t_exp_full;
            m_empty = t_exp_empty;

            seq_idx = seq_idx + 1;
        end
    endtask

    // Single-input-change vector: exactly one of wr_en / rd_en / din differs
    // from the previous vector, then the vector is applied and checked.
    task tg_step;
        input       wr;
        input       rd;
        input [7:0] d;
        begin
            t_nchg = 0;
            if (wr !== prev_wr)
                t_nchg = t_nchg + 1;
            if (rd !== prev_rd)
                t_nchg = t_nchg + 1;
            if (d !== prev_din)
                t_nchg = t_nchg + 1;

            label = 0;
            $sformat(label, "single_input_change_%0d", seq_idx);
            chk("toggle", label, 64'd1, {32'd0, t_nchg});

            prev_wr  = wr;
            prev_rd  = rd;
            prev_din = d;

            step(wr, rd, d, "toggle");
        end
    endtask

    // Asynchronous reset applied while other inputs are active.
    task async_reset_now;
        begin
            wr_en = 1'b1;
            rd_en = 1'b1;
            din   = 8'hC7;
            rst_n = 1'b0;

            #1;

            label = 0;
            $sformat(label, "async_rst_dout_%0d", seq_idx);
            chk("reset", label, 64'h0, {56'd0, dout});

            label = 0;
            $sformat(label, "async_rst_empty_%0d", seq_idx);
            chk("reset", label, 64'h1, {63'd0, empty});

            label = 0;
            $sformat(label, "async_rst_full_%0d", seq_idx);
            chk("reset", label, 64'h0, {63'd0, full});

            m_count = 0;
            m_wptr  = 0;
            m_rptr  = 0;
            m_dout  = 8'h00;
            m_full  = 1'b0;
            m_empty = 1'b1;
            for (i = 0; i < DEPTH; i = i + 1)
                m_mem[i] = 8'h00;

            wr_en = 1'b0;
            rd_en = 1'b0;
            din   = 8'h00;
            rst_n = 1'b1;

            @(negedge clk);

            prev_wr  = 1'b0;
            prev_rd  = 1'b0;
            prev_din = 8'h00;
        end
    endtask

    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        rst_n   = 1'b0;
        wr_en   = 1'b0;
        rd_en   = 1'b0;
        din     = 8'h00;
        seq_idx = 0;
        seed    = 32'h0000_2A5C;

        m_count = 0;
        m_wptr  = 0;
        m_rptr  = 0;
        m_dout  = 8'h00;
        m_full  = 1'b0;
        m_empty = 1'b1;
        for (i = 0; i < DEPTH; i = i + 1)
            m_mem[i] = 8'h00;

        prev_wr  = 1'b0;
        prev_rd  = 1'b0;
        prev_din = 8'h00;

        // ================= RESET PHASE (before any clock edge) =================
        #1;

        chk("reset", "async_reset_dout_zero", 64'h0, {56'd0, dout});
        chk("reset", "async_reset_empty_one", 64'h1, {63'd0, empty});
        chk("reset", "async_reset_full_zero", 64'h0, {63'd0, full});

        // Hold reset while writes and reads are requested, across clock edges.
        wr_en = 1'b1;
        rd_en = 1'b1;
        din   = 8'hA5;
        @(negedge clk);
        @(negedge clk);

        chk("reset", "reset_held_dout_zero", 64'h0, {56'd0, dout});
        chk("reset", "reset_held_empty_one", 64'h1, {63'd0, empty});
        chk("reset", "reset_held_full_zero", 64'h0, {63'd0, full});

        // Release reset with idle inputs.
        wr_en = 1'b0;
        rd_en = 1'b0;
        din   = 8'h00;
        rst_n = 1'b1;
        @(negedge clk);

        chk("reset", "after_reset_empty", 64'h1, {63'd0, empty});
        chk("reset", "after_reset_full", 64'h0, {63'd0, full});
        chk("reset", "after_reset_dout", 64'h0, {56'd0, dout});

        // ================= DIRECTED FILL / DRAIN =================
        step(1'b0, 1'b0, 8'h00, "directed");   // idle while empty
        step(1'b0, 1'b1, 8'h00, "corner");     // read while empty -> ignored
        chk("protocol", "empty_read_ignored_count", {63'd0, 1'b0}, {63'd0, m_full});

        step(1'b1, 1'b1, 8'h3C, "directed");   // read dropped, write wins -> count 1
        step(1'b0, 1'b0, 8'hFF, "hold");       // dout holds, count 1
        step(1'b0, 1'b0, 8'hFF, "hold");       // dout holds again
        step(1'b1, 1'b0, 8'h5A, "directed");   // count 2
        step(1'b1, 1'b1, 8'hA5, "directed");   // both -> count 3, dout = mem[rptr]
        step(1'b1, 1'b0, 8'h0F, "directed");   // count 4 -> full

        step(1'b0, 1'b0, 8'h00, "hold");       // idle while full, dout holds
        step(1'b1, 1'b0, 8'h77, "corner");     // write while full -> dropped
        step(1'b1, 1'b1, 8'h88, "corner");     // write dropped, read proceeds
        step(1'b0, 1'b1, 8'h00, "directed");
        step(1'b1, 1'b1, 8'h99, "directed");   // simultaneous read/write, count 2
        step(1'b0, 1'b1, 8'h00, "directed");   // count 1
        step(1'b0, 1'b1, 8'h00, "directed");   // count 0 -> empty

        // Underflow
        step(1'b0, 1'b1, 8'h00, "corner");     // read while empty -> ignored
        step(1'b0, 1'b1, 8'h00, "corner");

        // All-zero and all-one data
        step(1'b1, 1'b0, 8'h00, "corner");
        step(1'b1, 1'b0, 8'hFF, "corner");
        step(1'b0, 1'b1, 8'h00, "directed");
        step(1'b0, 1'b1, 8'h00, "directed");

        // Walk of every single data bit
        for (i = 0; i < 8; i = i + 1) begin
            step(1'b1, 1'b0, (8'h01 << i), "corner");
            step(1'b0, 1'b1, 8'h00, "corner");
        end

        // Overflow: fill, push four more (all dropped), then drain originals
        step(1'b1, 1'b0, 8'hA0, "corner");
        step(1'b1, 1'b0, 8'hA1, "corner");
        step(1'b1, 1'b0, 8'hA2, "corner");
        step(1'b1, 1'b0, 8'hA3, "corner");
        step(1'b1, 1'b0, 8'hB0, "corner");     // dropped
        step(1'b1, 1'b0, 8'hB1, "corner");     // dropped
        step(1'b1, 1'b1, 8'hB2, "corner");     // dropped write, valid read
        step(1'b0, 1'b1, 8'h00, "corner");
        step(1'b0, 1'b1, 8'h00, "corner");
        step(1'b0, 1'b1, 8'h00, "corner");
        step(1'b0, 1'b0, 8'h00, "hold");

        // ================= ASYNC RESET IN THE MIDDLE OF OPERATION =================
        async_reset_now;

        step(1'b1, 1'b0, 8'h11, "directed");
        step(1'b1, 1'b0, 8'h22, "directed");
        async_reset_now;                        // reset with count = 2

        step(1'b1, 1'b0, 8'h31, "directed");
        step(1'b1, 1'b0, 8'h32, "directed");
        step(1'b1, 1'b0, 8'h33, "directed");
        step(1'b1, 1'b0, 8'h34, "directed");    // full
        async_reset_now;                        // reset while full

        chk("reset", "post_reset_full_zero", 64'h0, {63'd0, full});
        chk("reset", "post_reset_empty_one", 64'h1, {63'd0, empty});

        // ================= EXHAUSTIVE din SWEEP (all 256 values) =================
        for (i = 0; i < DEPTH; i = i + 1) begin
            t_rdin = i;
            step(1'b1, 1'b0, t_rdin, "exhaustive");
        end

        for (i = DEPTH; i < 256; i = i + 1) begin
            t_rdin = i;
            step(1'b1, 1'b1, t_rdin, "exhaustive");
        end

        for (i = 0; i < DEPTH; i = i + 1) begin
            step(1'b0, 1'b1, 8'h00, "exhaustive");
        end

        // ================= SINGLE-INPUT-CHANGE VECTORS =================
        prev_wr  = 1'b0;
        prev_rd  = 1'b0;
        prev_din = 8'h00;

        tg_step(1'b1, 1'b0, 8'h00);
        tg_step(1'b1, 1'b0, 8'h01);
        tg_step(1'b1, 1'b0, 8'h03);
        tg_step(1'b1, 1'b1, 8'h03);
        tg_step(1'b0, 1'b1, 8'h03);
        tg_step(1'b0, 1'b0, 8'h03);
        tg_step(1'b1, 1'b0, 8'h03);
        tg_step(1'b1, 1'b0, 8'h02);
        tg_step(1'b1, 1'b0, 8'h00);
        tg_step(1'b1, 1'b0, 8'h80);
        tg_step(1'b0, 1'b0, 8'h80);
        tg_step(1'b0, 1'b1, 8'h80);
        tg_step(1'b0, 1'b1, 8'h00);
        tg_step(1'b0, 1'b1, 8'hFF);
        tg_step(1'b0, 1'b0, 8'hFF);
        tg_step(1'b1, 1'b0, 8'hFF);
        tg_step(1'b1, 1'b0, 8'hFE);
        tg_step(1'b1, 1'b0, 8'hFC);
        tg_step(1'b0, 1'b0, 8'hFC);
        tg_step(1'b0, 1'b1, 8'hFC);
        tg_step(1'b0, 1'b1, 8'h00);
        tg_step(1'b0, 1'b0, 8'h00);

        // ================= RANDOM TRAFFIC =================
        for (i = 0; i < 300; i = i + 1) begin
            t_rand = $random(seed);
            t_rwr  = t_rand[0];
            t_rrd  = t_rand[1];
            t_rdin = (t_rand >> 8) & 8'hFF;
            step(t_rwr, t_rrd, t_rdin, "random");
        end

        // Drain anything left over.
        for (i = 0; i < DEPTH; i = i + 1) begin
            if (m_empty == 1'b0)
                step(1'b0, 1'b1, 8'h00, "random");
        end

        chk("random", "final_empty_flag", 64'h1, {63'd0, empty});
        chk("random", "final_full_flag", 64'h0, {63'd0, full});
        chk("protocol", "final_not_full_and_empty", 64'd0, {63'd0, (full & empty)});

        // One last fill/drain sanity pass.
        step(1'b1, 1'b0, 8'h5A, "directed");
        step(1'b1, 1'b0, 8'hC3, "directed");
        step(1'b0, 1'b1, 8'h00, "directed");
        step(1'b0, 1'b1, 8'h00, "directed");
        step(1'b0, 1'b0, 8'h00, "hold");

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0)
            $display("ALL TESTS PASSED");
        $finish;
    end

    // Watchdog: expected run time is well under 10 us; abort at 100 us.
    initial begin
        #100000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule