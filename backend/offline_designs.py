"""
Offline design library.

Powers OFFLINE_MODE (no API key / no internet) and the deterministic tests.
Each design ships a *correct* RTL that simulates to PASS, a self-checking
testbench, and a `buggy` RTL variant used to exercise the self-correction loop:
generate(buggy) -> simulate FAIL -> fix_design -> generate(correct) -> PASS.

Every offline RTL carries a `// [offline:<key>]` marker on line 1 so the offline
fixer can recover the golden version without external state.
"""

import re

MARKER_RE = re.compile(r"//\s*\[offline:(\w+)\]")


def _marker(key: str) -> str:
    return f"// [offline:{key}]\n"


# ---------------------------------------------------------------------------
# Counter (with a buggy variant: increments by 2 instead of 1)
# ---------------------------------------------------------------------------
CHK_TASK = """    // Standard check task: ONE machine-readable line per comparison.
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
"""

COUNTER_SPEC = {
    "module_name": "counter",
    "parameters": [{"name": "WIDTH", "type": "integer", "default": 4}],
    "ports": [
        {"name": "clk", "direction": "input", "width": 1, "description": "Clock"},
        {"name": "rst_n", "direction": "input", "width": 1, "description": "Active-low async reset"},
        {"name": "enable", "direction": "input", "width": 1, "description": "Count enable"},
        {"name": "count", "direction": "output", "width": 4, "description": "Current count"},
    ],
    "behavior": "Synchronous up-counter with async active-low reset and enable.",
    "constraints": ["Sequential", "Async reset"],
}

COUNTER_RTL = _marker("counter") + """module counter #(
    parameter WIDTH = 4
)(
    input  wire             clk,
    input  wire             rst_n,
    input  wire             enable,
    output reg  [WIDTH-1:0] count
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            count <= {WIDTH{1'b0}};
        else if (enable)
            count <= count + 1'b1;
    end
endmodule
"""

COUNTER_RTL_BUGGY = _marker("counter") + """module counter #(
    parameter WIDTH = 4
)(
    input  wire             clk,
    input  wire             rst_n,
    input  wire             enable,
    output reg  [WIDTH-1:0] count
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            count <= {WIDTH{1'b0}};
        else if (enable)
            count <= count + 2'd2;   // BUG: should increment by 1
    end
endmodule
"""

COUNTER_TB = """`timescale 1ns/1ps
module testbench;
    reg clk, rst_n, enable;
    wire [3:0] count;
    integer pass_count = 0;
    integer fail_count = 0;
    integer s;
    reg [3:0] expected;
    reg [8*64-1:0] label;

@@CHK@@
    counter #(4) dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        // Phase 1: power-up asynchronous reset (the count must clear without a clock edge).
        rst_n = 0; enable = 0;
        #1;
        chk("reset", "power_up_reset_clears_count", 0, count);
        @(negedge clk);
        chk("reset", "count_held_while_in_reset", 0, count);

        // Phase 2: count 0..15 and wrap. At EVERY state also prove enable=0 holds the value.
        rst_n = 1; enable = 1;
        chk("reset", "released_count_still_zero", 0, count);
        for (s = 1; s < 17; s = s + 1) begin   // 16 steps: count 1..15, then the wrap to 0
            @(negedge clk);
            expected = s % 16;
            if (s == 16) chk("corner", "wraparound_15_to_0", expected, count);
            else begin
                $sformat(label, "count_up_to_%0d", expected);
                chk("directed", label, expected, count);
            end
            enable = 0;
            $sformat(label, "enable_low_holds_%0d", expected);
            @(negedge clk); chk("hold", label, expected, count);
            @(negedge clk); chk("hold", label, expected, count);
            enable = 1;
        end

        // Phase 3: asynchronous reset in the middle of counting, with enable still high.
        @(negedge clk); chk("directed", "counting_resumes_after_wrap", 1, count);
        @(negedge clk); @(negedge clk);
        #1 rst_n = 0; #1;
        chk("reset", "async_reset_clears_immediately", 0, count);
        @(negedge clk); chk("reset", "reset_wins_over_enable_high", 0, count);
        enable = 0;
        @(negedge clk); chk("reset", "reset_holds_with_enable_low", 0, count);

        // Phase 4: release reset with enable high; counting restarts from zero.
        enable = 1; rst_n = 1;
        @(negedge clk); chk("reset", "counting_restarts_from_zero", 1, count);
        @(negedge clk); chk("reset", "counting_continues", 2, count);

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
""".replace("@@CHK@@", CHK_TASK)

# ---------------------------------------------------------------------------
# ALU — supports both 4-bit and 8-bit via WIDTH param (offline demo)
# ---------------------------------------------------------------------------
ALU_SPEC_4 = {
    "module_name": "alu_4bit",
    "parameters": [{"name": "WIDTH", "type": "integer", "default": 4}],
    "ports": [
        {"name": "a", "direction": "input", "width": 4, "description": "Operand A"},
        {"name": "b", "direction": "input", "width": 4, "description": "Operand B"},
        {"name": "opcode", "direction": "input", "width": 3, "description": "Operation select"},
        {"name": "result", "direction": "output", "width": 4, "description": "Result"},
        {"name": "overflow", "direction": "output", "width": 1, "description": "Carry/overflow"},
    ],
    "behavior": "4-bit ALU: add, sub, and, or, xor with overflow on add/sub.",
    "constraints": ["Combinational"],
}
ALU_SPEC_8 = {
    "module_name": "alu_8bit",
    "parameters": [{"name": "WIDTH", "type": "integer", "default": 8}],
    "ports": [
        {"name": "a", "direction": "input", "width": 8, "description": "Operand A"},
        {"name": "b", "direction": "input", "width": 8, "description": "Operand B"},
        {"name": "opcode", "direction": "input", "width": 3, "description": "Operation select"},
        {"name": "result", "direction": "output", "width": 8, "description": "Result"},
        {"name": "overflow", "direction": "output", "width": 1, "description": "Carry/overflow"},
    ],
    "behavior": "8-bit ALU: add, sub, and, or, xor with overflow on add/sub.",
    "constraints": ["Combinational"],
}
# Keep backward compat alias
ALU_SPEC = ALU_SPEC_4

ALU_RTL_4 = _marker("alu") + """module alu_4bit #(
    parameter WIDTH = 4
)(
    input  wire [WIDTH-1:0] a,
    input  wire [WIDTH-1:0] b,
    input  wire [2:0]       opcode,
    output reg  [WIDTH-1:0] result,
    output reg              overflow
);
    always @(*) begin
        overflow = 1'b0;
        case (opcode)
            3'b000: {overflow, result} = a + b;
            3'b001: {overflow, result} = a - b;
            3'b010: result = a & b;
            3'b011: result = a | b;
            3'b100: result = a ^ b;
            default: result = {WIDTH{1'b0}};
        endcase
    end
endmodule
"""
ALU_RTL_8 = _marker("alu8") + """module alu_8bit #(
    parameter WIDTH = 8
)(
    input  wire [WIDTH-1:0] a,
    input  wire [WIDTH-1:0] b,
    input  wire [2:0]       opcode,
    output reg  [WIDTH-1:0] result,
    output reg              overflow
);
    always @(*) begin
        overflow = 1'b0;
        case (opcode)
            3'b000: {overflow, result} = a + b;
            3'b001: {overflow, result} = a - b;
            3'b010: result = a & b;
            3'b011: result = a | b;
            3'b100: result = a ^ b;
            default: result = {WIDTH{1'b0}};
        endcase
    end
endmodule
"""
ALU_RTL = ALU_RTL_4

ALU_TB_4 = """`timescale 1ns/1ps
module testbench;
    reg  [3:0] a, b;
    reg  [2:0] opcode;
    wire [3:0] result;
    wire       overflow;
    integer pass_count = 0;
    integer fail_count = 0;
    integer op, ia, ib;
    reg  [3:0] exp;
    reg        exp_ovf;
    reg  [4:0] wide;
    reg  [8*5-1:0] opn;
    reg  [8*64-1:0] label;

@@CHK@@
    alu_4bit #(4) dut (.a(a), .b(b), .opcode(opcode), .result(result), .overflow(overflow));

    // Settle, compute the reference result for the CURRENT a/b/opcode, and compare
    // {overflow, result}. (expected/actual in the CHK lines are {overflow, result}.)
    task run_vec;
        input [8*24-1:0] cat;
        begin
            #5;
            exp_ovf = 1'b0;
            case (opcode)
                3'b000: begin wide = {1'b0, a} + {1'b0, b}; exp = wide[3:0]; exp_ovf = wide[4]; opn = "ADD"; end
                3'b001: begin wide = {1'b0, a} - {1'b0, b}; exp = wide[3:0]; exp_ovf = wide[4]; opn = "SUB"; end
                3'b010: begin exp = a & b; opn = "AND"; end
                3'b011: begin exp = a | b; opn = "OR"; end
                3'b100: begin exp = a ^ b; opn = "XOR"; end
                default: begin exp = 4'b0; opn = "UNDEF"; end
            endcase
            $sformat(label, "%0s a=%0d b=%0d", opn, a, b);
            chk(cat, label, {exp_ovf, exp}, {overflow, result});
        end
    endtask

    initial begin
        // Exhaustive: every opcode (5..7 are undefined and must give 0) x every a x every b.
        for (op = 0; op < 8; op = op + 1)
            for (ia = 0; ia < 16; ia = ia + 1)
                for (ib = 0; ib < 16; ib = ib + 1) begin
                    opcode = op; a = ia; b = ib;
                    if (op < 5) run_vec("exhaustive"); else run_vec("undefined_opcode");
                end

        // Single-input-change phases: exactly ONE input changes between consecutive vectors,
        // so a result that is not re-evaluated (missing sensitivity-list entry) is caught.
        a = 4'd5; b = 4'd9; opcode = 3'd0; run_vec("toggle");
        for (op = 1; op < 8; op = op + 1) begin opcode = op; run_vec("toggle"); end
        for (op = 0; op < 2; op = op + 1) begin
            opcode = op; run_vec("toggle");
            for (ia = 0; ia < 16; ia = ia + 1) begin a = ia; run_vec("toggle"); end
            for (ib = 0; ib < 16; ib = ib + 1) begin b = ib; run_vec("toggle"); end
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
""".replace("@@CHK@@", CHK_TASK)
ALU_TB_8 = """`timescale 1ns/1ps
module testbench;
    reg  [7:0] a, b;
    reg  [2:0] opcode;
    wire [7:0] result;
    wire       overflow;
    integer pass_count = 0;
    integer fail_count = 0;
    integer op, ia, ib;
    reg  [7:0] exp;
    reg        exp_ovf;
    reg  [8:0] wide;
    reg  [8*5-1:0] opn;
    reg  [8*64-1:0] label;
    reg  [7:0] cv [0:10];

@@CHK@@
    alu_8bit #(8) dut (.a(a), .b(b), .opcode(opcode), .result(result), .overflow(overflow));

    // Settle, compute the reference result for the CURRENT a/b/opcode, and compare
    // {overflow, result}. (expected/actual in the CHK lines are {overflow, result}.)
    task run_vec;
        input [8*24-1:0] cat;
        begin
            #5;
            exp_ovf = 1'b0;
            case (opcode)
                3'b000: begin wide = {1'b0, a} + {1'b0, b}; exp = wide[7:0]; exp_ovf = wide[8]; opn = "ADD"; end
                3'b001: begin wide = {1'b0, a} - {1'b0, b}; exp = wide[7:0]; exp_ovf = wide[8]; opn = "SUB"; end
                3'b010: begin exp = a & b; opn = "AND"; end
                3'b011: begin exp = a | b; opn = "OR"; end
                3'b100: begin exp = a ^ b; opn = "XOR"; end
                default: begin exp = 8'b0; opn = "UNDEF"; end
            endcase
            $sformat(label, "%0s a=%0d b=%0d", opn, a, b);
            chk(cat, label, {exp_ovf, exp}, {overflow, result});
        end
    endtask

    initial begin
        // Corner values: zero, one, two, mid-range, all-ones, all-ones minus one, patterns.
        cv[0] = 8'd0;   cv[1] = 8'd1;   cv[2] = 8'd2;   cv[3] = 8'd127; cv[4] = 8'd128;
        cv[5] = 8'd254; cv[6] = 8'd255; cv[7] = 8'h55;  cv[8] = 8'hAA;  cv[9] = 8'h0F; cv[10] = 8'hF0;
        for (op = 0; op < 8; op = op + 1)
            for (ia = 0; ia < 11; ia = ia + 1)
                for (ib = 0; ib < 11; ib = ib + 1) begin
                    opcode = op; a = cv[ia]; b = cv[ib];
                    if (op < 5) run_vec("corner"); else run_vec("undefined_opcode");
                end

        // Random vectors across all eight opcodes.
        for (ia = 0; ia < 200; ia = ia + 1) begin
            a = $random; b = $random; opcode = ia % 8;
            run_vec("random");
        end

        // Single-input-change phases (catch a result that is not re-evaluated).
        a = cv[7]; b = cv[8]; opcode = 3'd0; run_vec("toggle");
        for (op = 1; op < 8; op = op + 1) begin opcode = op; run_vec("toggle"); end
        for (op = 0; op < 2; op = op + 1) begin
            opcode = op; run_vec("toggle");
            for (ia = 0; ia < 11; ia = ia + 1) begin a = cv[ia]; run_vec("toggle"); end
            for (ib = 0; ib < 11; ib = ib + 1) begin b = cv[ib]; run_vec("toggle"); end
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
""".replace("@@CHK@@", CHK_TASK)
ALU_TB = ALU_TB_4

# ---------------------------------------------------------------------------
# Full adder
# ---------------------------------------------------------------------------
ADDER_SPEC = {
    "module_name": "full_adder",
    "parameters": [],
    "ports": [
        {"name": "a", "direction": "input", "width": 1, "description": "A"},
        {"name": "b", "direction": "input", "width": 1, "description": "B"},
        {"name": "cin", "direction": "input", "width": 1, "description": "Carry in"},
        {"name": "sum", "direction": "output", "width": 1, "description": "Sum"},
        {"name": "cout", "direction": "output", "width": 1, "description": "Carry out"},
    ],
    "behavior": "1-bit full adder.",
    "constraints": ["Combinational"],
}

ADDER_RTL = _marker("adder") + """module full_adder (
    input  wire a,
    input  wire b,
    input  wire cin,
    output wire sum,
    output wire cout
);
    assign sum  = a ^ b ^ cin;
    assign cout = (a & b) | (cin & (a ^ b));
endmodule
"""

ADDER_TB = """`timescale 1ns/1ps
module testbench;
    reg a, b, cin;
    wire sum, cout;
    integer pass_count = 0;
    integer fail_count = 0;
    integer i;
    reg [2:0] gray;
    reg [1:0] exp;
    reg [8*64-1:0] label;

@@CHK@@
    full_adder dut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));

    initial begin
        // All 8 input combinations in Gray-code order: every step changes exactly one input.
        // The reference is plain arithmetic, so it is independent of how the RTL builds sum/cout.
        for (i = 0; i < 8; i = i + 1) begin
            gray = i[2:0] ^ (i[2:0] >> 1);
            {a, b, cin} = gray;
            #5;
            exp = {1'b0, a} + {1'b0, b} + {1'b0, cin};
            $sformat(label, "a=%0b b=%0b cin=%0b", a, b, cin);
            chk("exhaustive", label, exp, {cout, sum});
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
""".replace("@@CHK@@", CHK_TASK)

# ---------------------------------------------------------------------------
# 4:1 multiplexer
# ---------------------------------------------------------------------------
MUX_SPEC = {
    "module_name": "mux4to1",
    "parameters": [{"name": "WIDTH", "type": "integer", "default": 8}],
    "ports": [
        {"name": "d0", "direction": "input", "width": 8, "description": "Input 0"},
        {"name": "d1", "direction": "input", "width": 8, "description": "Input 1"},
        {"name": "d2", "direction": "input", "width": 8, "description": "Input 2"},
        {"name": "d3", "direction": "input", "width": 8, "description": "Input 3"},
        {"name": "sel", "direction": "input", "width": 2, "description": "Select"},
        {"name": "y", "direction": "output", "width": 8, "description": "Output"},
    ],
    "behavior": "4:1 multiplexer.",
    "constraints": ["Combinational"],
}

MUX_RTL = _marker("mux") + """module mux4to1 #(
    parameter WIDTH = 8
)(
    input  wire [WIDTH-1:0] d0,
    input  wire [WIDTH-1:0] d1,
    input  wire [WIDTH-1:0] d2,
    input  wire [WIDTH-1:0] d3,
    input  wire [1:0]       sel,
    output reg  [WIDTH-1:0] y
);
    always @(*) begin
        case (sel)
            2'b00: y = d0;
            2'b01: y = d1;
            2'b10: y = d2;
            default: y = d3;
        endcase
    end
endmodule
"""

MUX_TB = """`timescale 1ns/1ps
module testbench;
    reg  [7:0] d0, d1, d2, d3;
    reg  [1:0] sel;
    wire [7:0] y;
    integer pass_count = 0;
    integer fail_count = 0;
    integer i, k;
    reg  [7:0] exp;
    reg  [8*64-1:0] label;

@@CHK@@
    mux4to1 #(8) dut (.d0(d0), .d1(d1), .d2(d2), .d3(d3), .sel(sel), .y(y));

    task run_vec;
        input [8*24-1:0] cat;
        begin
            #5;
            case (sel)
                2'b00: exp = d0;
                2'b01: exp = d1;
                2'b10: exp = d2;
                default: exp = d3;
            endcase
            $sformat(label, "sel=%0d d0=%0h d1=%0h d2=%0h d3=%0h", sel, d0, d1, d2, d3);
            chk(cat, label, exp, y);
        end
    endtask

    initial begin
        // Directed: a distinct pattern on every input, select each input in turn.
        d0 = 8'h11; d1 = 8'h22; d2 = 8'h44; d3 = 8'h88;
        for (i = 0; i < 4; i = i + 1) begin sel = i; run_vec("directed"); end

        // Walking ones through each data input while that input is selected.
        for (i = 0; i < 4; i = i + 1) begin
            sel = i;
            for (k = 0; k < 8; k = k + 1) begin
                d0 = 8'h00; d1 = 8'h00; d2 = 8'h00; d3 = 8'h00;
                case (i)
                    0: d0 = 8'h01 << k;
                    1: d1 = 8'h01 << k;
                    2: d2 = 8'h01 << k;
                    default: d3 = 8'h01 << k;
                endcase
                run_vec("walking_one");
            end
        end

        // Single-input-change phases: only sel changes, then only the selected data changes.
        d0 = 8'h5A; d1 = 8'hA5; d2 = 8'h3C; d3 = 8'hC3;
        sel = 2'd0; run_vec("toggle");
        for (i = 1; i < 8; i = i + 1) begin sel = i % 4; run_vec("toggle"); end
        sel = 2'd2;
        for (k = 0; k < 8; k = k + 1) begin d2 = d2 ^ (8'h01 << k); run_vec("toggle"); end

        // Random data on all four inputs, rotating the select.
        for (i = 0; i < 100; i = i + 1) begin
            d0 = $random; d1 = $random; d2 = $random; d3 = $random;
            sel = i % 4;
            run_vec("random");
        end

        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
""".replace("@@CHK@@", CHK_TASK)

DESIGNS = {
    "alu": {"spec": ALU_SPEC_4, "rtl": ALU_RTL_4, "tb": ALU_TB_4,
            "explanation": "A combinational 4-bit ALU. opcode selects add/sub/and/or/xor; "
                           "add and subtract expose carry/borrow on the overflow output via "
                           "a 5-bit concatenation assignment."},
    "alu8": {"spec": ALU_SPEC_8, "rtl": ALU_RTL_8, "tb": ALU_TB_8,
            "explanation": "A combinational 8-bit ALU. opcode selects add/sub/and/or/xor; "
                           "add and subtract expose carry/borrow on the overflow output via "
                           "a 9-bit concatenation assignment."},
    "counter": {"spec": COUNTER_SPEC, "rtl": COUNTER_RTL, "rtl_buggy": COUNTER_RTL_BUGGY,
                "tb": COUNTER_TB,
                "explanation": "A parameterizable synchronous up-counter with an asynchronous "
                               "active-low reset and an enable. Counts on the rising clock edge."},
    "adder": {"spec": ADDER_SPEC, "rtl": ADDER_RTL, "tb": ADDER_TB,
              "explanation": "A purely combinational 1-bit full adder built from XOR/AND/OR gates."},
    "mux": {"spec": MUX_SPEC, "rtl": MUX_RTL, "tb": MUX_TB,
            "explanation": "A parameterizable 4:1 multiplexer using a combinational case statement."},
}

_KEYWORDS = [
    ("alu", ["alu", "arithmetic logic"]),
    ("counter", ["counter", "count"]),
    ("adder", ["adder", "full adder", "add two bits"]),
    ("mux", ["mux", "multiplexer", "multiplexor", "selector"]),
]


def match_design(prompt: str) -> str:
    p = prompt.lower()
    # Check for 8-bit ALU before generic ALU (width-specific)
    if "alu" in p and "8" in p:
        return "alu8"
    for key, words in _KEYWORDS:
        if any(w in p for w in words):
            return key
    return "counter"  # sensible default that exercises sequential logic


def is_exact_match(prompt: str) -> bool:
    """Return True if the prompt matched a known design keyword, False on fallback."""
    p = prompt.lower()
    for _key, words in _KEYWORDS:
        if any(w in p for w in words):
            return True
    return False


def is_buggy_request(prompt: str) -> bool:
    return "buggy" in prompt.lower() or "with a bug" in prompt.lower()


def get_design(key: str) -> dict:
    return DESIGNS.get(key, DESIGNS["counter"])


def design_key_from_rtl(rtl: str) -> str | None:
    m = MARKER_RE.search(rtl)
    return m.group(1) if m else None
