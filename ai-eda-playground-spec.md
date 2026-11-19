# AI-Driven EDA Playground — Product Requirements Document

## 1. Product Vision

**One-liner:** A browser-based RTL design environment where natural language prompts generate Verilog modules, testbenches, run simulation, and auto-verify results — closing the design loop without human intervention.

**Target Users:**
- Primary: Students/early-career engineers learning RTL design and verification
- Secondary: Interview candidates preparing for hardware design roles
- Tertiary: Engineers wanting quick prototyping without tool setup overhead

**What Success Looks Like:**
User types: *"design a 4-bit ALU with add, sub, and, or, xor operations with overflow detection"*

System responds with:
1. Generated RTL module (parameterizable, clean style)
2. Auto-generated testbench with directed + random tests
3. Simulation run (Icarus Verilog backend)
4. Pass/fail verdict with coverage summary
5. Waveform viewer showing key signals
6. AI-generated explanation of design decisions

---

## 2. Core User Flows

### Flow A: Natural Language → Working Design

```
User Prompt → Intent Parser → RTL Spec → Code Generator → 
Testbench Generator → Simulator → Result Analyzer → 
Output (Code + Waveform + Explanation)
```

**Steps:**
1. User enters natural language description
2. AI parses intent into structured RTL specification
3. System generates Verilog module with proper ports, parameters
4. System generates SystemVerilog testbench with:
   - Clock/reset generation
   - Directed test vectors (corner cases)
   - Constrained random stimulus
   - Self-checking assertions
   - Coverage collection
5. Backend compiles and runs simulation (Icarus Verilog)
6. AI analyzes simulation output:
   - Parse transcript for pass/fail
   - Extract coverage metrics
   - Identify failures and root cause
7. Display results in unified output panel

### Flow B: Self-Correction Loop (Critical Differentiator)

```
Simulation Failed → AI Reads Error Log + Waveform → 
Diagnoses Bug → Patches RTL → Re-runs → (Loop until pass or max iterations)
```

This is what makes it "agentic" — not just a code generator, but an autonomous debugger.

### Flow C: Schematic Entry (Phase 2)

```
Drag-and-drop gates → Auto-generate Verilog → Continue from Flow A
```

### Flow D: Upload Existing Code

```
Upload .v file → AI analyzes → Suggests improvements → 
Generates testbench if missing → Verifies
```

---

## 3. System Architecture

### High-Level Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │  Prompt  │  │  Code    │  │ Waveform │  │     AI Chat      │ │
│  │  Input   │  │  Editor  │  │  Viewer  │  │     Panel        │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┤
│  │              Schematic Viewer (Gate Netlist Visualization)   │
│  └──────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND (Python FastAPI)                   │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Intent       │  │ RTL          │  │ Testbench            │  │
│  │ Parser       │  │ Generator    │  │ Generator            │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Simulation   │  │ Result       │  │ Bug                  │  │
│  │ Orchestrator │  │ Analyzer     │  │ Explainer            │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              LLM Integration Layer (OpenAI/Claude)       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EDA ENGINE (Containerized)                   │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Icarus       │  │ Verilator    │  │ Yosys                │  │
│  │ Verilog      │  │ (optional)   │  │ (synthesis)          │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User Prompt
    │
    ▼
┌─────────────────────┐
│ Intent Parser (LLM) │
│ - Extract module name
│ - Identify ports (name, width, direction)
│ - Identify parameters
│ - Parse behavioral description
│ - Output: JSON RTL Spec
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ RTL Generator (LLM) │
│ - Input: JSON RTL Spec
│ - Output: Verilog module code
│ - Style: IEEE 1800, parameterizable
│ - Include: Comments for documentation
└─────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Testbench Generator (LLM)   │
│ - Input: Generated RTL
│ - Output: SystemVerilog TB
│   - Clock/reset driver
│   - Interface or direct port binding
│   - Directed tests (corner cases)
│   - Constrained random stimulus
│   - Self-checking assertions
│   - Coverage groups
│   - Scoreboard (if complex)
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Simulation Orchestrator     │
│ - Write .v and .sv files
│ - Call Icarus Verilog: iverilog -o design.vvp design.v tb.sv
│ - Run: vvp design.vvp
│ - Capture: transcript.log, design.vcd
│ - Timeout handling (max 60s)
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Result Analyzer (LLM)       │
│ - Input: transcript.log, coverage data
│ - Parse pass/fail
│ - Extract error messages
│ - Parse coverage metrics
│ - Output: Structured result JSON
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Bug Explainer (LLM)         │
│ - If simulation failed:
│   - Read error log
│   - Parse VCD for signal states
│   - Generate human explanation
│   - Suggest specific code fix
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│ Self-Correction Loop        │
│ - If bug found AND iterations < max:
│   - Apply suggested fix
│   - Re-generate testbench if needed
│   - Re-run simulation
│ - Else: Return results to user
└─────────────────────────────┘
```

---

## 4. Data Models

### 4.1 RTL Specification Schema (JSON)

```json
{
  "module_name": "full_adder",
  "parameters": [
    {
      "name": "WIDTH",
      "type": "integer",
      "default": 1
    }
  ],
  "ports": [
    {
      "name": "a",
      "direction": "input",
      "width": "WIDTH",
      "description": "First operand"
    },
    {
      "name": "b",
      "direction": "input",
      "width": "WIDTH",
      "description": "Second operand"
    },
    {
      "name": "cin",
      "direction": "input",
      "width": 1,
      "description": "Carry in"
    },
    {
      "name": "sum",
      "direction": "output",
      "width": "WIDTH",
      "description": "Sum output"
    },
    {
      "name": "cout",
      "direction": "output",
      "width": 1,
      "description": "Carry out"
    }
  ],
  "behavior": "Implements a full adder with carry chain. sum = a ^ b ^ cin, cout = (a & b) | (cin & (a ^ b))",
  "constraints": [
    "Combinational logic only",
    "No latches",
    "Parameterizable width"
  ],
  "verification_requirements": {
    "corner_cases": [
      "All zeros input",
      "All ones input", 
      "Maximum value overflow",
      "Carry propagation across all bits"
    ],
    "coverage_goals": [
      "Toggle all input combinations",
      "Exercise carry chain",
      "Overflow conditions"
    ]
  }
}
```

### 4.2 Simulation Result Schema (JSON)

```json
{
  "status": "PASS" | "FAIL" | "TIMEOUT" | "ERROR",
  "module_name": "full_adder",
  "simulation_time_ns": 1500,
  "test_count": 100,
  "pass_count": 98,
  "fail_count": 2,
  "coverage": {
    "line_coverage": 100,
    "branch_coverage": 95.5,
    "toggle_coverage": 88.2,
    "functional_coverage": 92.0
  },
  "errors": [
    {
      "test_id": 47,
      "inputs": {"a": 15, "b": 1, "cin": 1},
      "expected": {"sum": 1, "cout": 1},
      "actual": {"sum": 17, "cout": 0},
      "timestamp_ns": 940
    }
  ],
  "waveform_file": "design.vcd",
  "transcript_file": "transcript.log",
  "synthesis_metrics": {
    "cell_count": 45,
    "area_estimate_um2": 320.5
  }
}
```

### 4.3 Bug Analysis Schema (JSON)

```json
{
  "bug_type": "LOGIC_ERROR" | "TIMING_ERROR" | "SYNTAX_ERROR" | "ASSERTION_FAILURE",
  "severity": "CRITICAL" | "MAJOR" | "MINOR",
  "root_cause": "Carry chain logic incorrect for WIDTH > 1 case",
  "explanation": "The module implements a 1-bit full adder but the parameter WIDTH is not properly used. When WIDTH=4, the carry should propagate through all bits, but the current implementation treats the entire bus as a single add operation.",
  "evidence": [
    "Test case 47: a=15, b=1, cin=1 → expected sum=1, cout=1, got sum=17, cout=0",
    "This indicates carry was not propagated, suggestingWIDTH parameter is ignored"
  ],
  "suggested_fix": {
    "file": "full_adder.v",
    "line": 12,
    "original_code": "assign {cout, sum} = a + b + cin;",
    "fixed_code": "assign {cout, sum} = a + b + cin; // This works for any WIDTH",
    "explanation": "Verilog's + operator handles carry correctly for any width. The issue is likely in how the carry out is extracted for WIDTH > 1."
  },
  "confidence": 0.85
}
```

---

## 5. API Specifications

### Backend API (FastAPI)

#### 5.1 Generate Design

```
POST /api/design/generate
```

**Request:**
```json
{
  "prompt": "Design a 4-bit ALU with add, sub, and, or, xor operations and overflow detection",
  "options": {
    "style": "parameterized",
    "target_frequency_mhz": null,
    "optimization": "balanced"
  }
}
```

**Response:**
```json
{
  "design_id": "uuid-1234",
  "rtl_spec": { ... },
  "rtl_code": "module alu_4bit (...); ... endmodule",
  "testbench_code": "module tb_alu_4bit; ... endmodule",
  "explanation": "This ALU implements 5 operations controlled by a 3-bit opcode..."
}
```

#### 5.2 Run Simulation

```
POST /api/simulation/run
```

**Request:**
```json
{
  "design_id": "uuid-1234",
  "rtl_code": "...",
  "testbench_code": "...",
  "options": {
    "timeout_seconds": 60,
    "coverage": true,
    "waveform": true,
    "self_correct": true,
    "max_iterations": 3
  }
}
```

**Response:**
```json
{
  "simulation_id": "uuid-5678",
  "status": "completed",
  "result": {
    "status": "PASS",
    "coverage": { ... },
    "errors": [],
    ...
  },
  "artifacts": {
    "vcd_url": "/api/artifacts/uuid-5678/design.vcd",
    "transcript_url": "/api/artifacts/uuid-5678/transcript.log"
  }
}
```

#### 5.3 Analyze Failure

```
POST /api/analysis/diagnose
```

**Request:**
```json
{
  "simulation_id": "uuid-5678",
  "transcript": "...",
  "vcd_signals": ["a", "b", "sum", "cout"]
}
```

**Response:**
```json
{
  "bug_analysis": { ... },
  "suggested_fix": { ... },
  "confidence": 0.85
}
```

#### 5.4 WebSocket: Real-time Simulation Status

```
WS /api/simulation/{simulation_id}/status
```

**Messages:**
```json
{"event": "compiling", "progress": 10}
{"event": "simulating", "progress": 50, "time_ns": 750}
{"event": "analyzing", "progress": 90}
{"event": "completed", "progress": 100, "result": {...}}
```

---

## 6. LLM Prompt Engineering

### 6.1 Intent Parser System Prompt

```
You are an expert RTL design specification parser. Your job is to convert natural language hardware design descriptions into a structured JSON specification.

Extract:
1. Module name (infer from description if not explicit)
2. Port list with names, directions, widths, and descriptions
3. Parameters with types and default values
4. Behavioral description (what the module does)
5. Design constraints (combinational/sequential, timing requirements)
6. Verification requirements (corner cases, coverage goals)

Output ONLY valid JSON matching the RTL Specification Schema. No explanations.
```

### 6.2 RTL Generator System Prompt

```
You are an expert Verilog/SystemVerilog RTL designer. Generate clean, synthesizable, industry-standard code.

Rules:
- IEEE 1800-2017 compliant
- Parameterizable where applicable
- Proper indentation (4 spaces)
- Meaningful signal names
- Include header comment with: module purpose, ports, parameters, author
- No "x" or "z" in synthesis code unless tri-state
- Use "always_ff" for sequential, "always_comb" for combinational
- Proper reset handling (active low, synchronous preferred)
- No latches inferred unintentionally

For verification considerations:
- Add assertions for critical invariants
- Include coverage points if complex logic
- Ensure observability of internal state

Output ONLY Verilog code. No explanations before or after.
```

### 6.3 Testbench Generator System Prompt

```
You are an expert SystemVerilog verification engineer. Generate comprehensive testbenches.

Structure:
1. Clock/reset generation (if needed)
2. DUT instantiation with parameter override
3. Interface or direct port binding
4. Test stimulus:
   - Directed tests for corner cases (all 0s, all 1s, boundaries)
   - Constrained random stimulus (at least 100 iterations)
   - Error injection tests (if applicable)
5. Self-checking:
   - Assertions for protocol compliance
   - Expected vs actual comparison
   - Automatic pass/fail reporting
6. Coverage:
   - Functional coverage bins for operations
   - Toggle coverage for critical signals
   - Cross coverage where relevant
7. Task/function wrappers for common operations

Style:
- Use SystemVerilog (not Verilog-2001)
- UVM-style naming conventions (even if not full UVM)
- Clear test names and comments
- $display for pass/fail summary
- $finish at end of simulation

Output ONLY SystemVerilog testbench code.
```

### 6.4 Bug Explainer System Prompt

```
You are an expert hardware debugger analyzing simulation failures.

Given:
- RTL code
- Testbench code  
- Error transcript
- VCD signal traces (key signals)

Your task:
1. Identify the specific test case(s) that failed
2. Analyze the input values that triggered the failure
3. Trace through the logic to find the root cause
4. Explain in plain English what went wrong
5. Suggest a specific fix with code diff

Be precise. Reference specific line numbers and signal values. 
Distinguish between:
- Logic errors (wrong Boolean equation)
- Timing errors (setup/hold violations - not applicable to RTL sim)
- Syntax errors (compiler issues)
- Assertion failures (protocol violations)

Output structured JSON matching Bug Analysis Schema.
```

---

## 7. EDA Tool Integration

### 7.1 Icarus Verilog Setup

```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    iverilog \
    gtkwave \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /eda

# Volume mount point for design files
VOLUME ["/eda/workspace"]
```

### 7.2 Simulation Wrapper (Python)

```python
import subprocess
import os
from pathlib import Path
from typing import Optional, Tuple
import json

class IcarusVerilogSimulator:
    def __init__(self, workspace: str = "/eda/workspace"):
        self.workspace = Path(workspace)
        self.timeout_seconds = 60
        
    def compile(self, rtl_file: str, tb_file: str, top_module: str) -> Tuple[bool, str]:
        """Compile RTL and testbench into VVP."""
        output_vvp = self.workspace / f"{top_module}.vvp"
        
        cmd = [
            "iverilog",
            "-o", str(output_vvp),
            "-g2012",  # SystemVerilog 2012
            "-Wall",
            rtl_file,
            tb_file
        ]
        
        result = subprocess.run(
            cmd,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return result.returncode == 0, result.stderr
    
    def run(self, top_module: str, timeout: Optional[int] = None) -> Tuple[bool, dict]:
        """Run compiled VVP and capture results."""
        vvp_file = self.workspace / f"{top_module}.vvp"
        vcd_file = self.workspace / "design.vcd"
        log_file = self.workspace / "transcript.log"
        
        timeout = timeout or self.timeout_seconds
        
        cmd = ["vvp", str(vvp_file)]
        
        try:
            with open(log_file, 'w') as log:
                result = subprocess.run(
                    cmd,
                    cwd=self.workspace,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout
                )
        except subprocess.TimeoutExpired:
            return False, {"error": "Simulation timeout", "status": "TIMEOUT"}
        
        # Parse results
        return self.parse_results(log_file, vcd_file)
    
    def parse_results(self, log_file: Path, vcd_file: Path) -> Tuple[bool, dict]:
        """Parse simulation log for pass/fail."""
        with open(log_file, 'r') as f:
            log_content = f.read()
        
        # Look for standard patterns
        passed = "Test passed" in log_content or "ALL TESTS PASSED" in log_content
        failed = "Test failed" in log_content or "Assertion failed" in log_content
        error = "ERROR" in log_content or "FATAL" in log_content
        
        status = "PASS" if passed and not failed else "FAIL"
        if error:
            status = "ERROR"
        
        return True, {
            "status": status,
            "transcript_file": str(log_file),
            "vcd_file": str(vcd_file) if vcd_file.exists() else None,
            "log_excerpt": log_content[-2000:]  # Last 2000 chars
        }
```

---

## 8. Frontend Components

### 8.1 Tech Stack

- **Framework:** React 18 with TypeScript
- **Styling:** Tailwind CSS
- **Code Editor:** Monaco Editor (VS Code editor component)
- **Waveform Viewer:** Custom SVG-based (or integrate wavedrom)
- **Diagrams:** React Flow for schematic visualization
- **State Management:** Zustand
- **API Client:** Axios

### 8.2 Component Structure

```
src/
├── components/
│   ├── PromptInput/
│   │   ├── PromptInput.tsx        # Natural language input
│   │   └── PromptSuggestions.tsx  # Example prompts
│   │
│   ├── CodeEditor/
│   │   ├── CodeEditor.tsx         # Monaco wrapper
│   │   ├── RTLTab.tsx             # Verilog editor
│   │   └── TestbenchTab.tsx       # TB editor
│   │
│   ├── WaveformViewer/
│   │   ├── WaveformViewer.tsx     # VCD renderer
│   │   ├── SignalList.tsx         # Signal selector
│   │   └── TimeAxis.tsx           # Time ruler
│   │
│   ├── ResultsPanel/
│   │   ├── ResultsPanel.tsx       # Pass/fail summary
│   │   ├── CoverageReport.tsx     # Coverage metrics
│   │   └── BugExplanation.tsx     # AI debug analysis
│   │
│   ├── SchematicViewer/
│   │   └── SchematicViewer.tsx    # Gate-level diagram
│   │
│   └── ChatPanel/
│       └── ChatPanel.tsx          # AI follow-up Q&A
│
├── hooks/
│   ├── useSimulation.ts           # WebSocket simulation status
│   └── useWaveform.ts             # VCD parsing
│
├── services/
│   ├── api.ts                     # REST API client
│   └── websocket.ts               # WS connection
│
└── utils/
    ├── vcdParser.ts               # Parse VCD files
    └── codeGenerator.ts           # Code formatting
```

### 8.3 Monaco Editor Setup

```typescript
import Editor from '@monaco-editor/react';

const RTL_LANGUAGE_ID = 'verilog';

// Register Verilog language
monaco.languages.register({ id: RTL_LANGUAGE_ID });

// Define syntax highlighting
monaco.languages.setMonarchTokensProvider(RTL_LANGUAGE_ID, {
  keywords: [
    'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
    'parameter', 'localparam', 'assign', 'always', 'always_ff', 'always_comb',
    'if', 'else', 'case', 'endcase', 'default', 'begin', 'end',
    'posedge', 'negedge', 'or', 'and', 'not', 'xor', 'nand', 'nor'
  ],
  operators: [
    '=', '+=', '-=', '*=', '/=', '==', '!=', '===', '!==',
    '<', '>', '<=', '>=', '&', '|', '^', '~', '<<', '>>'
  ],
  symbols: /[=><!~?:&|+\-*\/\^%]+/,
  tokenizer: {
    root: [
      [/[a-zA-Z_]\w*/, { 
        cases: { 
          '@keywords': 'keyword',
          '@default': 'identifier' 
        }
      }],
      [/[0-9]+(?:'[bdhBDH][0-9a-fA-F_xzXZ]+)?/, 'number'],
      [/\/\/.*$/, 'comment'],
      [/\/\*/, 'comment', '@comment'],
    ],
    comment: [
      [/[^\/*]+/, 'comment'],
      ['\\*/', 'comment', '@pop'],
    ]
  }
});
```

### 8.4 Waveform Viewer (VCD Parsing)

```typescript
interface VCDSignal {
  name: string;
  width: number;
  values: Array<{
    time: number;
    value: string;
  }>;
}

interface VCDDump {
  timescale: string;
  signals: VCDSignal[];
}

function parseVCD(vcdContent: string): VCDDump {
  const lines = vcdContent.split('\n');
  const signals: VCDSignal[] = [];
  const signalMap: Record<string, VCDSignal> = {};
  let currentTime = 0;
  
  for (const line of lines) {
    if (line.startsWith('$timescale')) {
      // Parse timescale
    } else if (line.startsWith('$var')) {
      // Parse signal declaration: $var wire 4 ! data[3:0] $end
      const parts = line.split(/\s+/);
      const width = parseInt(parts[2]);
      const id = parts[3];
      const name = parts[4];
      const signal: VCDSignal = { name, width, values: [] };
      signals.push(signal);
      signalMap[id] = signal;
    } else if (line.match(/^#\d+/)) {
      currentTime = parseInt(line.substring(1));
    } else if (line.match(/^[01xzXZ]/)) {
      // Scalar value change
      const value = line[0];
      const id = line.substring(1).trim();
      if (signalMap[id]) {
        signalMap[id].values.push({ time: currentTime, value });
      }
    } else if (line.match(/^b[01xzXZ]+/)) {
      // Vector value change: b0101 !
      const match = line.match(/^b([01xzXZ]+)\s+(.+)/);
      if (match) {
        const value = match[1];
        const id = match[2];
        if (signalMap[id]) {
          signalMap[id].values.push({ time: currentTime, value });
        }
      }
    }
  }
  
  return { timescale: '1ns', signals };
}
```

---

## 9. Development Phases

### Phase 1: Core Loop (4-6 weeks)

**Goal:** Natural language prompt → RTL → Testbench → Simulation → Pass/Fail

**Deliverables:**
- [ ] Backend: FastAPI server with endpoints for generate, simulate, analyze
- [ ] LLM Integration: OpenAI API integration with structured prompts
- [ ] EDA Backend: Dockerized Icarus Verilog with Python wrapper
- [ ] Basic Frontend: Single-page app with:
  - Prompt input
  - Code viewer (Monaco editor)
  - Simulation log viewer
  - Pass/fail display

**MVP Success Criteria:**
User can type "design a full adder" and get:
1. Generated Verilog code (viewable)
2. Generated testbench (viewable)
3. Simulation result (PASS/FAIL)
4. Error log if failed

**Week-by-week:**
- Week 1: Backend scaffolding, API design, OpenAI integration
- Week 2: RTL + TB generation prompts, JSON schema enforcement
- Week 3: Icarus Verilog Docker setup, simulation wrapper
- Week 4: Frontend skeleton, Monaco integration, API wiring
- Week 5: End-to-end integration, error handling
- Week 6: Testing, bug fixes, basic documentation

---

### Phase 2: Self-Correction Loop (2-3 weeks)

**Goal:** Automatic debugging and iterative fix

**Deliverables:**
- [ ] Bug explainer prompt with VCD analysis
- [ ] Automated fix suggestion + code patching
- [ ] Iteration loop (max 3 attempts)
- [ ] User can accept/reject AI fixes

**MVP Success Criteria:**
If simulation fails, AI automatically:
1. Reads error log
2. Analyzes waveform
3. Suggests fix
4. Applies fix
5. Re-runs simulation
6. Repeats until pass or max iterations

---

### Phase 3: Waveform + Coverage (3-4 weeks)

**Goal:** Visual debugging tools

**Deliverables:**
- [ ] VCD file generation in simulation
- [ ] Frontend waveform viewer (SVG-based)
- [ ] Signal selector (which signals to display)
- [ ] Time navigation (zoom, pan)
- [ ] Coverage collection in testbench
- [ ] Coverage report visualization

**MVP Success Criteria:**
After simulation, user sees:
1. Waveform viewer with key signals
2. Coverage percentage breakdown
3. Uncovered branches highlighted

---

### Phase 4: UVM Testbench Generation (4-6 weeks)

**Goal:** Professional-grade verification scaffolding

**Deliverables:**
- [ ] UVM environment generator:
  - Interface definition
  - Driver
  - Monitor
  - Scoreboard
  - Agent
  - Environment
  - Test
- [ ] Sequence library generator
- [ ] Coverage model generator
- [ ] UVM-specific prompts and validation

**MVP Success Criteria:**
User can request "UVM testbench for AXI4-lite slave" and get:
1. Full UVM environment with all components
2. Basic sequence library
3. Coverage model
4. Runs with Questa/VCS (or open-source UVM with Icarus)

---

### Phase 5: Advanced Features (6-8 weeks)

**Goal:** Polish and differentiation

**Deliverables:**
- [ ] Schematic viewer (Yosys synthesis + gate-level viz)
- [ ] Visual block diagram entry (React Flow)
- [ ] Design comparison (diff view)
- [ ] Interview prep mode (circuit library + quiz generation)
- [ ] Code upload and analysis
- [ ] Export: .v, .vcd, PDF report, shareable link
- [ ] User accounts + project saving

---

## 10. Technical Challenges & Solutions

### Challenge 1: LLM Code Quality

**Problem:** LLMs generate syntactically correct but stylistically poor Verilog

**Solution:**
1. Few-shot prompting with high-quality examples
2. Post-processing linter (Verilator --lint-only)
3. Structured output enforcement (JSON schema for spec, then code)
4. Iterative refinement prompt: "Review this code for synthesizability and improve"

### Challenge 2: Testbench Effectiveness

**Problem:** Auto-generated testbenches might miss critical corner cases

**Solution:**
1. Explicit corner case extraction in intent parsing
2. Coverage-driven: if coverage < 90%, auto-generate additional tests
3. Assertion generation for invariants
4. Multiple rounds: generate → run → analyze coverage → add tests

### Challenge 3: Simulation Performance

**Problem:** Large designs might timeout in 60s

**Solution:**
1. Timeout + progress reporting via WebSocket
2. Early termination if failures detected
3. Hierarchical verification: test submodules first
4. Cloud-based simulation for large designs (Phase 5+)

### Challenge 4: VCD Parsing at Scale

**Problem:** Large VCD files (100MB+) are slow to parse and render

**Solution:**
1. Streaming VCD parser (process line by line)
2. Server-side VCD → JSON conversion
3. Client-side lazy loading (only requested time window)
4. Signal aggregation for buses (show as hex, not individual bits)

### Challenge 5: LLM Hallucination

**Problem:** LLM might invent non-existent modules or signals

**Solution:**
1. Strict JSON schema validation
2. Verilog linting before simulation
3. Post-generation validation: "Does this code match the spec?"
4. User confirmation before self-correction applies fixes

---

## 11. Testing Strategy

### Unit Tests

- RTL spec parser: JSON validation
- Code generator: syntax check with Icarus
- VCD parser: known VCD files → expected signal structures
- Simulation wrapper: mock Icarus output

### Integration Tests

- End-to-end: Prompt → Code → Sim → Result (5 standard circuits)
- Self-correction loop: Inject known bug, verify fix
- API: All endpoints with mock LLM

### Test Circuits (Golden Suite)

1. Full adder (combinational, simple)
2. 4-bit counter (sequential, reset handling)
3. 8-bit ALU (multiple operations, parameterized)
4. FIFO (complex state, corner cases)
5. SPI slave (protocol, timing)
6. Priority encoder (one-hot, cascading)
7. 4-bit multiplier (complex combinational)
8. Divider (sequential algorithm)
9. Arbiter (concurrent state machines)
10. Memory controller (complex timing)

---

## 12. Success Metrics

### Technical Metrics
- RTL generation success rate: >95% (compiles without syntax errors)
- Testbench compilation rate: >90%
- Simulation pass rate (for correct designs): >90%
- Self-correction success rate: >70% (fixes bug within 3 iterations)
- Average latency: <30s (prompt to result for simple designs)

### User Metrics (if deployed)
- Daily active users
- Designs created per user
- Self-correction usage rate
- User satisfaction (thumbs up/down on generated code)

---

## 13. Deployment Architecture

### Development
- Local: Docker Compose (backend + EDA container + frontend)
- LLM: OpenAI API (paid tier for reliability)

### Production (Phase 5+)
- Frontend: Vercel or Netlify (static React app)
- Backend: AWS ECS or Google Cloud Run (containerized FastAPI)
- EDA Engine: AWS Fargate (containerized Icarus)
- Database: PostgreSQL (user accounts, saved designs)
- Storage: S3 (VCD files, transcripts, exports)
- LLM: OpenAI API with rate limiting

### Cost Estimation (Monthly)
- LLM API: $50-200 (depends on usage, GPT-4 vs GPT-3.5)
- Cloud compute: $50-150 (container hosting)
- Storage: $10-30 (S3)
- **Total: $110-380/month**

---

## 14. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| LLM generates incorrect Verilog | High | Medium | Lint check + few-shot prompting + user review |
| Simulation timeout | Medium | Low | Timeout + progress reporting + early termination |
| VCD parsing slow | Medium | Medium | Streaming parser + server-side processing |
| Self-correction infinite loop | Low | Medium | Max iteration limit (3) + user confirmation |
| LLM API rate limits | Medium | High | Caching + request queuing + fallback to GPT-3.5 |
| Security (code injection) | Low | High | Sandbox container + no shell execution + input validation |

---

## 15. Future Enhancements (Post-MVP)

1. **Multi-language support:** VHDL generation, Chisel generation
2. **Formal verification integration:** SVA assertion checking, model checking
3. **FPGA synthesis:** Xilinx Vivado integration for bitstream generation
4. **Collaborative editing:** Real-time multi-user design review
5. **Version control integration:** Git repo auto-commit, branch for alternatives
6. **Performance analysis:** Timing estimation, critical path visualization
7. **Custom training:** Fine-tuned LLM on verified RTL corpus
8. **Enterprise features:** Private deployment, custom IP integration, audit logs

---

## 16. Getting Started Checklist

### Prerequisites
- [ ] Python 3.10+ installed
- [ ] Node.js 18+ installed
- [ ] Docker Desktop installed
- [ ] OpenAI API key
- [ ] Basic familiarity with FastAPI, React, Docker

### Week 1 Tasks
- [ ] Initialize FastAPI project: `fastapi new ai-eda-backend`
- [ ] Set up project structure (see Section 8)
- [ ] Create OpenAI client wrapper
- [ ] Design RTL spec JSON schema
- [ ] Write first intent parser prompt
- [ ] Test with simple prompt: "design a 2-input AND gate"
- [ ] Verify JSON output structure

### Week 2 Tasks
- [ ] Write RTL generator prompt
- [ ] Test RTL generation with 5 standard circuits
- [ ] Implement Verilog syntax validation (Icarus --lint)
- [ ] Write testbench generator prompt
- [ ] Generate testbenches for same 5 circuits
- [ ] Manual verification: Do testbenches compile?

### Week 3 Tasks
- [ ] Create Dockerfile for EDA container
- [ ] Install Icarus Verilog, set up workspace
- [ ] Write simulation wrapper (see Section 7.2)
- [ ] Test: compile + run full adder manually
- [ ] Integrate wrapper into FastAPI endpoint
- [ ] Handle timeout, error cases

---

## Appendix A: Example End-to-End Flow

**User Prompt:** "Design a 4-bit counter with synchronous reset and enable"

### Step 1: Intent Parser Output

```json
{
  "module_name": "counter_4bit",
  "parameters": [],
  "ports": [
    {"name": "clk", "direction": "input", "width": 1, "description": "Clock input"},
    {"name": "rst_n", "direction": "input", "width": 1, "description": "Active-low synchronous reset"},
    {"name": "enable", "direction": "input", "width": 1, "description": "Count enable"},
    {"name": "count", "direction": "output", "width": 4, "description": "Counter value"}
  ],
  "behavior": "4-bit up counter. Increments on posedge clk when enable=1. Resets to 0 when rst_n=0.",
  "verification_requirements": {
    "corner_cases": [
      "Reset value (count should be 0)",
      "Max value rollover (15 → 0)",
      "Enable disabled (count should hold)",
      "Enable toggling at boundaries"
    ],
    "coverage_goals": [
      "All count values 0-15",
      "Rollover transition",
      "Enable true and false"
    ]
  }
}
```

### Step 2: Generated RTL

```verilog
// counter_4bit.v
// 4-bit synchronous counter with enable and reset
// Generated by AI-EDA Playground

module counter_4bit (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       enable,
    output logic [3:0] count
);

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            count <= 4'b0000;
        end else if (enable) begin
            count <= count + 1'b1;
        end
    end

    // Assertions for verification
    `ifdef FORMAL
        assert property (@(posedge clk) disable iff (!rst_n) 
            count >= 0 && count <= 15);
    `endif

endmodule
```

### Step 3: Generated Testbench

```verilog
// tb_counter_4bit.sv
// Testbench for 4-bit counter
// Generated by AI-EDA Playground

`timescale 1ns/1ps

module tb_counter_4bit;

    logic       clk;
    logic       rst_n;
    logic       enable;
    logic [3:0] count;

    // Instantiate DUT
    counter_4bit dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .count(count)
    );

    // Clock generation - 100MHz
    initial clk = 0;
    always #5 clk = ~clk;

    // Coverage collection
    covergroup cg_counter;
        cp_count: coverpoint count {
            bins zero = {0};
            bins low = {[1:7]};
            bins mid = {[8:11]};
            bins high = {[12:14]};
            bins max = {15};
        }
        cp_enable: coverpoint enable;
        cp_rst_n: coverpoint rst_n;
        cross cp_count, cp_enable;
    endgroup

    cg_counter cg = new();

    // Self-checking logic
    logic [3:0] expected_count;
    int pass_count = 0;
    int fail_count = 0;

    task check_count(input logic [3:0] exp, input string test_name);
        if (count !== exp) begin
            $display("[%0t] FAIL: %s - Expected %0d, Got %0d", 
                     $time, test_name, exp, count);
            fail_count++;
        end else begin
            $display("[%0t] PASS: %s", $time, test_name);
            pass_count++;
        end
        cg.sample();
    endtask

    // Test stimulus
    initial begin
        // Initialize
        rst_n = 0;
        enable = 0;
        expected_count = 0;

        // Test 1: Reset
        #20;
        check_count(0, "Reset test");
        
        // Release reset
        rst_n = 1;
        #10;

        // Test 2: Enable disabled (should hold)
        enable = 0;
        #20;
        check_count(0, "Enable disabled test");

        // Test 3: Count up
        enable = 1;
        repeat(20) #10;
        check_count(4, "Count up test");

        // Test 4: Rollover
        enable = 1;
        repeat(12) #10;
        check_count(0, "Rollover test");

        // Test 5: Mid-count reset
        enable = 1;
        repeat(5) #10;
        rst_n = 0;
        #10;
        check_count(0, "Mid-count reset test");
        rst_n = 1;

        // Test 6: Random stimulus
        repeat(100) begin
            enable = $urandom_range(0, 1);
            #10;
            if (enable) expected_count++;
            if (expected_count > 15) expected_count = 0;
            cg.sample();
        end

        // Final report
        $display("\n=== Test Summary ===");
        $display("Passed: %0d", pass_count);
        $display("Failed: %0d", fail_count);
        $display("Coverage: %.1f%%", cg.get_coverage());
        
        if (fail_count == 0)
            $display("ALL TESTS PASSED");
        else
            $display("TESTS FAILED");

        $finish;
    end

    // Timeout
    initial #10000 $finish;

endmodule
```

### Step 4: Simulation Result

```json
{
  "status": "PASS",
  "module_name": "counter_4bit",
  "simulation_time_ns": 2170,
  "test_count": 6,
  "pass_count": 6,
  "fail_count": 0,
  "coverage": {
    "line_coverage": 100,
    "branch_coverage": 100,
    "functional_coverage": 91.7
  },
  "errors": [],
  "transcript_excerpt": "=== Test Summary ===\nPassed: 6\nFailed: 0\nCoverage: 91.7%\nALL TESTS PASSED"
}
```

### Step 5: User Interface

```
┌─────────────────────────────────────────────────────────────────────┐
│  AI EDA Playground                            [New] [Save] [Export]│
├─────────────────────────────────────────────────────────────────────┤
│ Prompt: Design a 4-bit counter with synchronous reset and enable    │
│ [Generate]                                                         │
├────────────────────┬────────────────────┬──────────────────────────┤
│  RTL Code          │  Testbench         │  Results                 │
│                    │                    │                          │
│ module counter_4bit│ module tb_counter..│  ✅ SIMULATION PASSED    │
│   (               │                    │                          │
│     input clk,    │                    │  Coverage:               │
│     input rst_n,  │                    │  ├ Line:     100%        │
│     input enable, │                    │  ├ Branch:   100%        │
│     output [3:0]..│                    │  └ Function: 91.7%      │
│   );               │                    │                          │
│                    │                    │  Tests: 6 passed, 0 fail│
│   always_ff @(posed│                    │                          │
│     if (!rst_n)    │                    │  [View Waveform]         │
│       count <= 0;  │                    │  [Download VCD]          │
│     else if (enable│                    │                          │
│       count <=     │                    │                          │
│         count + 1; │                    │                          │
│   end              │                    │                          │
│ endmodule          │                    │                          │
├────────────────────┴────────────────────┴──────────────────────────┤
│  AI Chat: "Why is functional coverage 91.7% instead of 100%?"      │
│  [Type your question here...]                              [Send]  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Appendix B: References

### Tools
- Icarus Verilog: http://iverilog.icarus.com/
- Verilator: https://www.veripool.org/verilator/
- Yosys: https://yosyshq.net/yosys/
- Monaco Editor: https://microsoft.github.io/monaco-editor/
- WaveDrom: https://wavedrom.com/

### Learning Resources
- SystemVerilog LRM (IEEE 1800-2017)
- UVM Cookbook: https://verificationacademy.com/
- ChipHack: https://github.com/chiphack

### Similar Projects
- EDA Playground: https://www.edaplayground.com/
- Makerchip: https://makerchip.com/
- Silice: https://github.com/sylefeb/Silice

---

**Document Version:** 1.0
**Last Updated:** 2026-04-08
**Author:** AI-EDA Playground Project
