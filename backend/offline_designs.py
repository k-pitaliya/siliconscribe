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
    integer expected;

    counter #(4) dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));

    initial clk = 0;
    always #5 clk = ~clk;

    initial begin
        rst_n = 0; enable = 0; expected = 0;
        @(negedge clk); rst_n = 1; enable = 1;
        repeat (20) begin
            @(negedge clk);
            expected = (expected + 1) % 16;
            if (count === expected[3:0]) pass_count = pass_count + 1;
            else begin
                $display("FAIL: expected=%0d got=%0d", expected, count);
                fail_count = fail_count + 1;
            end
        end
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
"""

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
    integer i;
    reg  [3:0] exp;

    alu_4bit #(4) dut (.a(a), .b(b), .opcode(opcode), .result(result), .overflow(overflow));

    initial begin
        for (i = 0; i < 200; i = i + 1) begin
            a = $random;
            b = $random;
            opcode = i % 5;
            #5;
            case (opcode)
                3'b000: exp = a + b;
                3'b001: exp = a - b;
                3'b010: exp = a & b;
                3'b011: exp = a | b;
                3'b100: exp = a ^ b;
                default: exp = 4'b0;
            endcase
            if (result === exp) pass_count = pass_count + 1;
            else begin
                $display("FAIL: op=%0d a=%0d b=%0d result=%0d exp=%0d", opcode, a, b, result, exp);
                fail_count = fail_count + 1;
            end
        end
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
"""
ALU_TB_8 = """`timescale 1ns/1ps
module testbench;
    reg  [7:0] a, b;
    reg  [2:0] opcode;
    wire [7:0] result;
    wire       overflow;
    integer pass_count = 0;
    integer fail_count = 0;
    integer i;
    reg  [7:0] exp;

    alu_8bit #(8) dut (.a(a), .b(b), .opcode(opcode), .result(result), .overflow(overflow));

    initial begin
        for (i = 0; i < 200; i = i + 1) begin
            a = $random;
            b = $random;
            opcode = i % 5;
            #5;
            case (opcode)
                3'b000: exp = a + b;
                3'b001: exp = a - b;
                3'b010: exp = a & b;
                3'b011: exp = a | b;
                3'b100: exp = a ^ b;
                default: exp = 8'b0;
            endcase
            if (result === exp) pass_count = pass_count + 1;
            else begin
                $display("FAIL: op=%0d a=%0d b=%0d result=%0d exp=%0d", opcode, a, b, result, exp);
                fail_count = fail_count + 1;
            end
        end
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
"""
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

    full_adder dut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));

    initial begin
        for (i = 0; i < 8; i = i + 1) begin
            {a, b, cin} = i[2:0];
            #5;
            if (sum === (a ^ b ^ cin) && cout === ((a & b) | (cin & (a ^ b))))
                pass_count = pass_count + 1;
            else begin
                $display("FAIL: a=%b b=%b cin=%b", a, b, cin);
                fail_count = fail_count + 1;
            end
        end
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
"""

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
    integer i;
    reg  [7:0] exp;

    mux4to1 #(8) dut (.d0(d0), .d1(d1), .d2(d2), .d3(d3), .sel(sel), .y(y));

    initial begin
        for (i = 0; i < 100; i = i + 1) begin
            d0 = $random; d1 = $random; d2 = $random; d3 = $random;
            sel = i % 4;
            #5;
            case (sel)
                2'b00: exp = d0;
                2'b01: exp = d1;
                2'b10: exp = d2;
                default: exp = d3;
            endcase
            if (y === exp) pass_count = pass_count + 1;
            else begin
                $display("FAIL: sel=%0d y=%0d exp=%0d", sel, y, exp);
                fail_count = fail_count + 1;
            end
        end
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        if (fail_count == 0) $display("ALL TESTS PASSED");
        $finish;
    end
endmodule
"""

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
