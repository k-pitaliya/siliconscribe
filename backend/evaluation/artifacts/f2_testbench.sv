module testbench;

    // ------------------------------------------------------------------
    // Specification-derived duration parameters (module defaults)
    // ------------------------------------------------------------------
    localparam integer RED_CYCLES    = 30;
    localparam integer GREEN_CYCLES  = 30;
    localparam integer YELLOW_CYCLES = 10;

    // DUT interconnect
    reg  clk;
    reg  rst;
    reg  enable;

    wire red;
    wire green;
    wire yellow;

    // Score keeping
    integer pass_count = 0;
    integer fail_count = 0;

    // String and loop scratch
    reg [8*64-1:0] label;
    reg [8*48-1:0] vbase;

    integer i;
    integer combo;
    integer rep;
    integer guard;
    integer act_sum;

    reg rb;
    reg eb;
    reg legal_chk;

    // Scratch regs for the known-value check: Icarus 12 miscompiles
    // $isunknown(<concat>) when it is used directly as a task argument,
    // so the lamp snapshot and its known-ness are latched first.
    reg [2:0] lamp_bits;
    reg       unk_flag;

    // ------------------------------------------------------------------
    // Independent reference model (derived from the specification only)
    //   state encoding: RED=00, GREEN=01, YELLOW=10
    //   transition: RED->GREEN->YELLOW->RED, entry always with cnt=0
    //   a transition happens on an enabled edge when cnt == duration-1
    // ------------------------------------------------------------------
    reg [1:0] m_state;
    integer   m_cnt;
    reg       e_red;
    reg       e_green;
    reg       e_yellow;

    // Protocol tracking from previously sampled observations
    reg       pv_valid;
    reg [1:0] pv_obs;
    reg       pv_rst;
    reg       pv_en;
    reg [1:0] o_obs;

    traffic_light_controller #(
        .RED_CYCLES    (RED_CYCLES),
        .GREEN_CYCLES  (GREEN_CYCLES),
        .YELLOW_CYCLES (YELLOW_CYCLES)
    ) dut (
        .clk    (clk),
        .rst    (rst),
        .enable (enable),
        .red    (red),
        .green  (green),
        .yellow (yellow)
    );

    initial begin
        clk = 1'b0;
    end

    always begin
        #5 clk = ~clk;
    end

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
    // Reference-model helpers
    // ------------------------------------------------------------------
    function integer dur_of;
        input [1:0] s;
        begin
            if (s == 2'd0) begin
                dur_of = RED_CYCLES;
            end else if (s == 2'd1) begin
                dur_of = GREEN_CYCLES;
            end else if (s == 2'd2) begin
                dur_of = YELLOW_CYCLES;
            end else begin
                dur_of = 1;
            end
        end
    endfunction

    function [1:0] next_of;
        input [1:0] s;
        begin
            if (s === 2'd0) begin
                next_of = 2'd1;
            end else if (s === 2'd1) begin
                next_of = 2'd2;
            end else begin
                next_of = 2'd0;
            end
        end
    endfunction

    function [1:0] obs_code;
        input r;
        input g;
        input y;
        begin
            if (r === 1'b1) begin
                obs_code = 2'd0;
            end else if (g === 1'b1) begin
                obs_code = 2'd1;
            end else if (y === 1'b1) begin
                obs_code = 2'd2;
            end else begin
                obs_code = 2'd3;
            end
        end
    endfunction

    // Advance the reference model by one clock edge with the given inputs.
    task model_update;
        input u_rst;
        input u_en;
        begin
            if (u_rst === 1'b1) begin
                m_state = 2'd0;
                m_cnt   = 0;
            end else if (u_en === 1'b1) begin
                if (m_cnt >= (dur_of(m_state) - 1)) begin
                    m_state = next_of(m_state);
                    m_cnt   = 0;
                end else begin
                    m_cnt = m_cnt + 1;
                end
            end

            if (m_state === 2'd0) begin
                e_red    = 1'b1;
                e_green  = 1'b0;
                e_yellow = 1'b0;
            end else if (m_state === 2'd1) begin
                e_red    = 1'b0;
                e_green  = 1'b1;
                e_yellow = 1'b0;
            end else if (m_state === 2'd2) begin
                e_red    = 1'b0;
                e_green  = 1'b0;
                e_yellow = 1'b1;
            end else begin
                e_red    = 1'b1;
                e_green  = 1'b0;
                e_yellow = 1'b0;
            end
        end
    endtask

    // Compare all registered outputs plus safety properties for one vector.
    task do_checks;
        input [8*24-1:0] cat;
        input [8*48-1:0] base;
        begin
            $sformat(label, "%0s_red", base);
            chk(cat, label, {63'b0, e_red}, {63'b0, red});

            $sformat(label, "%0s_grn", base);
            chk(cat, label, {63'b0, e_green}, {63'b0, green});

            $sformat(label, "%0s_yel", base);
            chk(cat, label, {63'b0, e_yellow}, {63'b0, yellow});

            act_sum = {31'b0, red} + {31'b0, green} + {31'b0, yellow};
            $sformat(label, "%0s_1hot", base);
            chk("protocol", label, 64'd1, act_sum);

            lamp_bits = {red, green, yellow};
            unk_flag  = $isunknown(lamp_bits);
            $sformat(label, "%0s_knwn", base);
            chk("undefined", label, 64'd0, {{63{1'b0}}, unk_flag});
        end
    endtask

    // Structural protocol checks that do not depend on the reference counter.
    task proto_check;
        input p_rst;
        input p_en;
        input [8*48-1:0] base;
        begin
            o_obs = obs_code(red, green, yellow);

            if (pv_valid === 1'b1) begin
                if (p_rst === 1'b1) begin
                    $sformat(label, "%0s_prst", base);
                    chk("reset", label, 64'd0, {62'b0, o_obs});
                end else if (p_en === 1'b1) begin
                    if ((o_obs === pv_obs) || (o_obs === next_of(pv_obs))) begin
                        legal_chk = 1'b1;
                    end else begin
                        legal_chk = 1'b0;
                    end
                    $sformat(label, "%0s_pdir", base);
                    chk("protocol", label, 64'd1, {63'b0, legal_chk});
                end else begin
                    $sformat(label, "%0s_phld", base);
                    chk("hold", label, {62'b0, pv_obs}, {62'b0, o_obs});
                end
            end

            pv_obs   = o_obs;
            pv_rst   = p_rst;
            pv_en    = p_en;
            pv_valid = 1'b1;
        end
    endtask

    // Drive one input vector on the falling edge, then sample on the next
    // falling edge so exactly one rising edge has been exercised.
    task step;
        input s_rst;
        input s_en;
        input [8*24-1:0] cat;
        input [8*48-1:0] base;
        begin
            model_update(s_rst, s_en);
            rst    = s_rst;
            enable = s_en;
            @(negedge clk);
            do_checks(cat, base);
            proto_check(s_rst, s_en, base);
        end
    endtask

    // Navigate with enable=1 until the reference model reaches target.
    task run_until_state;
        input [1:0] target;
        input integer maxsteps;
        begin
            for (guard = 0; ((guard < maxsteps) && (m_state !== target)); guard = guard + 1) begin
                $sformat(vbase, "nav_s%0d_%0d", target, guard);
                step(1'b0, 1'b1, "directed", vbase);
            end
        end
    endtask

    // ------------------------------------------------------------------
    // Stimulus
    // ------------------------------------------------------------------
    initial begin
        $dumpfile("design.vcd");
        $dumpvars(0, testbench);

        rst      = 1'b1;
        enable   = 1'b0;
        m_state  = 2'd0;
        m_cnt    = 0;
        e_red    = 1'b1;
        e_green  = 1'b0;
        e_yellow = 1'b0;
        pv_valid = 1'b0;
        pv_obs   = 2'd0;
        pv_rst   = 1'b0;
        pv_en    = 1'b0;
        o_obs    = 2'd0;
        act_sum  = 0;
        legal_chk = 1'b0;
        lamp_bits = 3'b000;
        unk_flag  = 1'b0;

        // ---------------- reset sequence (first stimulus) ----------------
        step(1'b1, 1'b0, "reset", "rst_a_en0");
        step(1'b1, 1'b1, "reset", "rst_b_en1");
        step(1'b1, 1'b0, "reset", "rst_c_en0");
        step(1'b1, 1'b1, "reset", "rst_d_en1");
        // reset released while enable is 0: state must stay frozen in RED
        step(1'b0, 1'b0, "reset", "rst_rel_en0");

        // ---------------- hold behaviour in RED ----------------
        step(1'b0, 1'b0, "hold", "hold_red_a");
        step(1'b0, 1'b0, "hold", "hold_red_b");
        step(1'b0, 1'b0, "hold", "hold_red_c");

        // ---------------- RED lasts RED_CYCLES enabled edges ----------------
        for (i = 0; i < (RED_CYCLES - 2); i = i + 1) begin
            $sformat(vbase, "red_%0d", i);
            step(1'b0, 1'b1, "directed", vbase);
        end
        step(1'b0, 1'b0, "hold",    "hold_red_d");
        step(1'b0, 1'b0, "hold",    "hold_red_e");
        step(1'b0, 1'b1, "corner",  "red_last_cnt");
        step(1'b0, 1'b1, "directed", "red_to_green");

        // ---------------- hold behaviour in GREEN ----------------
        step(1'b0, 1'b0, "hold", "hold_grn_a");
        step(1'b0, 1'b0, "hold", "hold_grn_b");
        step(1'b0, 1'b0, "hold", "hold_grn_c");

        // ---------------- GREEN lasts GREEN_CYCLES enabled edges --------------
        for (i = 0; i < (GREEN_CYCLES - 1); i = i + 1) begin
            $sformat(vbase, "grn_%0d", i);
            step(1'b0, 1'b1, "directed", vbase);
        end
        step(1'b0, 1'b1, "corner", "grn_last_cnt");
        step(1'b0, 1'b1, "directed", "grn_to_yellow");

        // ---------------- hold behaviour in YELLOW ----------------
        step(1'b0, 1'b0, "hold", "hold_yel_a");
        step(1'b0, 1'b0, "hold", "hold_yel_b");

        // ---------------- YELLOW lasts YELLOW_CYCLES enabled edges ------------
        for (i = 0; i < (YELLOW_CYCLES - 2); i = i + 1) begin
            $sformat(vbase, "yel_%0d", i);
            step(1'b0, 1'b1, "directed", vbase);
        end
        step(1'b0, 1'b1, "corner", "yel_last_cnt");

        // reset while YELLOW is active and enable is high (reset priority)
        step(1'b1, 1'b1, "reset", "rst_in_yellow_en1");

        // reset while GREEN is active and enable is low
        run_until_state(2'd1, 100);
        step(1'b0, 1'b1, "directed", "grn_pre_rst_a");
        step(1'b0, 1'b1, "directed", "grn_pre_rst_b");
        step(1'b1, 1'b0, "reset",    "rst_in_green_en0");

        // ---------------- two full cycles of soak (wrap RED->...->RED) --------
        for (i = 0; i < 140; i = i + 1) begin
            $sformat(vbase, "soak_%0d", i);
            step(1'b0, 1'b1, "directed", vbase);
        end

        // ---------------- single-input-change vectors (enable toggles) --------
        for (i = 0; i < 20; i = i + 1) begin
            eb = i % 2;
            $sformat(vbase, "tog_en_%0d", i);
            step(1'b0, eb, "toggle", vbase);
        end
        step(1'b1, 1'b1, "toggle", "tog_rst_a");
        step(1'b0, 1'b1, "toggle", "tog_rst_b");

        // ---------------- input corner cases ---------------------------------
        step(1'b0, 1'b0, "corner", "corner_all_zero");
        step(1'b0, 1'b1, "corner", "corner_en_only");
        step(1'b1, 1'b0, "corner", "corner_rst_only");
        step(1'b1, 1'b1, "corner", "corner_all_one");
        step(1'b1, 1'b1, "corner", "corner_all_one_b");
        step(1'b0, 1'b0, "corner", "corner_all_zero_b");

        // ---------------- exhaustive input-space sweep (2 bits => 4 vectors) --
        for (combo = 0; combo < 4; combo = combo + 1) begin
            for (rep = 0; rep < 2; rep = rep + 1) begin
                rb = (combo / 2) % 2;
                eb = combo % 2;
                $sformat(vbase, "exh_a_%0d_%0d", combo, rep);
                step(rb, eb, "exhaustive", vbase);
            end
        end

        // same exhaustive sweep while parked in GREEN
        run_until_state(2'd1, 100);
        for (combo = 0; combo < 4; combo = combo + 1) begin
            for (rep = 0; rep < 2; rep = rep + 1) begin
                rb = (combo / 2) % 2;
                eb = combo % 2;
                $sformat(vbase, "exh_g_%0d_%0d", combo, rep);
                step(rb, eb, "exhaustive", vbase);
            end
        end

        // ---------------- randomized vectors ---------------------------------
        for (i = 0; i < 300; i = i + 1) begin
            if (($urandom % 16) == 0) begin
                rb = 1'b1;
            end else begin
                rb = 1'b0;
            end
            if (($urandom % 4) == 0) begin
                eb = 1'b0;
            end else begin
                eb = 1'b1;
            end
            $sformat(vbase, "rnd_%0d", i);
            step(rb, eb, "random", vbase);
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) begin
            $display("ALL TESTS PASSED");
        end
        $finish;
    end

    // ------------------------------------------------------------------
    // Watchdog
    // ------------------------------------------------------------------
    initial begin
        #100000;
        $display("FAIL: watchdog timeout");
        $finish;
    end

endmodule