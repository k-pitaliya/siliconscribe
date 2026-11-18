# CHAROTAR UNIVERSITY OF SCIENCE AND TECHNOLOGY (CHARUSAT)
## Chandubhai S. Patel Institute of Technology (CSPIT)
### V. T. Patel Department of Electronics & Communication Engineering

---

**Course Code:** EC486: Minor Project  
**Academic Year:** 2026–2027 (Odd Semester)  
**Submission Type:** Progress Report  
**Date of Submission:** October 15, 2026  

---

# PROJECT TITLE
## SiliconScribe: An AI-Assisted EDA Playground with Autonomous RTL Verification and Self-Correction

**Student Name:** Kushal Pitaliya  
**Student ID / Roll No.:** 23EC105  
**Batch:** 2023 B.Tech. Electronics & Communication Engineering  
**Project Category:** Software-based EDA Tool / Electronic Design Automation (Individual Project)  

---

## ABSTRACT

In digital VLSI design, writing Register-Transfer Level (RTL) code and developing self-checking testbenches dominate the front-end of the ASIC development flow, and verification is widely reported as the single largest share of overall project effort. While Large Language Models (LLMs) can generate Verilog code snippets, they often produce syntax errors, unsupported SystemVerilog constructs, and functional bugs. More importantly, existing AI code generators work in an open loop: they cannot execute, simulate, or debug their own code.

To solve this, I have developed **SiliconScribe**, a browser-based Electronic Design Automation (EDA) playground. The system accepts natural language specifications, generates synthesizable Verilog-2001 RTL and self-checking testbenches, simulates them using Icarus Verilog, and runs an **autonomous closed-loop self-correction engine**. When simulation errors or test failures occur, the error logs are analyzed by the AI debugger, which iteratively patches the RTL until it passes. To prevent infinite loops, the engine uses normalized SHA-256 code hashing and cycle-detection guards. The platform also provides an in-browser SVG digital waveform viewer, multi-tier linting, Yosys logic-synthesis cell counts, and a 16-file UVM 1.2 bundle export for QuestaSim. The project is covered by **42 backend pytest cases and 36 frontend vitest unit tests**. On the development machine, 23 backend tests execute and 19 are skipped because Icarus Verilog is not on `PATH`; continuous integration installs `iverilog` and `yosys`, so the full suite executes there.

---

## 1. INTRODUCTION

### 1.1 Motivation and Problem Statement
Digital integrated circuit design requires high precision. Translating design requirements into synthesizable Verilog RTL and verifying functionality through testbenches is time-consuming and prone to human error. 

While general-purpose AI coding tools can suggest code, applying them directly to digital hardware design presents major practical challenges:
1. **Toolchain Incompatibility:** Generic models often generate SystemVerilog constructs (such as `logic`, `always_ff`, classes, and interfaces) that standard open-source tools like Icarus Verilog cannot compile.
2. **Lack of Hardware Execution Awareness:** Language models cannot execute code. They cannot evaluate simulation cycles, clock edges, race conditions, or assertion mismatches.
3. **No Closed-Loop Feedback:** If generated code fails simulation, an engineer must manually debug the compiler output, locate the bug, and prompt the model again.

### 1.2 Project Scope & Objectives
This project was undertaken as an individual software-based minor project for course **EC486**. The primary goal is to build an autonomous, execution-grounded EDA assistant that bridges natural language specification and functional hardware verification.

The key objectives are:
- **Specification Parsing:** Convert natural language prompts into a structured design schema (`RTLDesignSpec`).
- **Target-Constrained Code Generation:** Generate Verilog-2001 synthesizable RTL and self-checking testbenches combining directed corner cases and random stimulus.
- **Autonomous Debugging Loop:** Capture simulation diagnostics and assertion failures to iteratively patch buggy RTL, with oscillation guards to prevent thrashing.
- **In-Browser Visualization:** Implement a native SVG digital waveform viewer (with bus hex display and zoom) and port-level block diagrams.
- **EDA Toolchain Integration:** Integrate multi-tier linting (Verilator / Icarus / regex heuristics), Yosys logic synthesis metrics, and industrial UVM 1.2 testbench export.
- **Zero-Budget Resilience:** Ensure full offline functionality with curated fallback designs so the system never fails when internet or API keys are unavailable.

---

## 2. WORKING (DESIGN, ALGORITHM, AND METHODOLOGY)

### 2.1 System Architecture
SiliconScribe is built on a modular three-tier architecture:

```
+---------------------------------------------------------------------------------+
|                          FRONTEND (React 18 + Vite)                             |
|  - Prompt Panel (Model picker, frequency slider, preset examples)               |
|  - CodeMirror 6 Editor (Dual tabs: RTL .v and Testbench .sv, editable)          |
|  - Results Panel (Status badge, pass-rate metrics, self-correction timeline)   |
|  - Interactive SVG Waveform Viewer (Hex bus transitions, zoom, time ruler)      |
|  - AI Agent Chat Timeline (Real-time SSE event stream)                          |
+---------------------------------------+-----------------------------------------+
                                        | HTTP POST / SSE Stream
                                        v
+---------------------------------------------------------------------------------+
|                         BACKEND API (FastAPI + Python)                          |
|  - Intent Parser -> Verilog-2001 Generator -> Self-Checking TB Generator        |
|  - Multi-Tier Linter (Verilator -> Icarus -> Regex Heuristics)                  |
|  - Autonomous Self-Correction Loop (Normalized hash & oscillation detector)     |
|  - Post-Processing: VCD Parser, Yosys Synthesis Wrapper, SQLite Persistence    |
|  - UVM 1.2 Bundle Generator (16 Questa-style verification files)                |
+---------------------------------------+-----------------------------------------+
                                        | Subprocess Execution
                                        v
+---------------------------------------------------------------------------------+
|                           LOCAL EDA TOOLCHAIN                                   |
|  - Icarus Verilog (`iverilog` -g2012 -Wall, `vvp` runtime engine)               |
|  - Yosys Open Synthesis Suite (`synth -top`, `stat`, `write_json`)              |
+---------------------------------------------------------------------------------+
```

### 2.2 End-to-End Pipeline Workflow
When a user submits a design requirement (e.g., *"Design a 4-bit synchronous counter with enable and async reset"*), the system executes the following automated pipeline:

1. **Intent Parsing:** Extracts module name, parameters, port list (name, direction, bit-width), behavior, and constraints into a structured JSON model (`RTLDesignSpec`).
2. **Synthesizable RTL Generation:** Generates clean Verilog-2001 code. Enforces `reg`/`wire` instead of `logic`, and standard `always @(posedge clk)` blocks to ensure compatibility with Icarus Verilog.
3. **Pre-Simulation Linting:** Runs a non-blocking check for syntax errors, missing semicolons, duplicate module definitions, and vector width mismatches.
4. **Self-Checking Testbench Generation:** Instantiates the DUT with named ports, sets up clock/reset generators, injects VCD dumping tasks (`$dumpfile`, `$dumpvars`), and implements self-checking comparisons (`===`) with pass/fail counters.
5. **Simulation Execution:** Compiles the files using `iverilog -o testbench.vvp -g2012 -Wall` and runs the simulation via `vvp` within an isolated workspace directory subject to a 30-second timeout.
6. **Autonomous Debugging (if FAIL/ERROR):** If errors are detected, the self-correction engine is triggered (detailed below).
7. **Post-Processing & Artifact Generation:**
   - Evaluates functional test vector pass rate.
   - Parses `design.vcd` into structured waveform data.
   - Runs Yosys synthesis to extract cell counts and estimated silicon area.
   - Persists the run into SQLite (`projects.db`) and streams the completed results to the frontend.

### 2.3 The Autonomous Closed-Loop Debugger Algorithm
The core innovation of the project is the autonomous self-correction loop:

```
Algorithm: Autonomous Hardware Self-Correction
-------------------------------------------------------------------------------
1.  Initialize RTL = RTL_0, TB = TB_0
2.  SeenHashes = { NormHash(RTL_0) }
3.  Status, Log, PassCount, FailCount = Simulate(RTL, TB)
4.  Iteration = 0
5.  while (Status in ["FAIL", "ERROR"] and Iteration < MaxIterations):
6.      Iteration = Iteration + 1
7.      Patch = LLM_FixDesign(RTL, TB, Log)
8.      New_RTL = Patch.rtl_code
9.      New_Hash = NormHash(New_RTL)
10.     // Oscillation and No-Op Guard
11.     if New_Hash == NormHash(RTL):
12.         Stop loop ("Model returned no changes")
13.         break
14.     if New_Hash in SeenHashes:
15.         Stop loop ("Oscillation detected: repeated previous RTL")
16.         break
17.     SeenHashes.add(New_Hash)
18.     RTL = New_RTL
19.     Status, Log, PassCount, FailCount = Simulate(RTL, TB)
20. end while
21. return RTL, TB, Status
-------------------------------------------------------------------------------
```

#### Hash Normalization & Cycle Prevention
To prevent LLM oscillation (repeatedly flipping between two buggy implementations or adding cosmetic comments), `NormHash()` strips all single-line comments (`//`), block comments (`/* */`), and whitespace before computing a SHA-256 digest. If a candidate patch produces a hash already present in `SeenHashes`, the loop breaks immediately, conserving token usage and preventing deadlocks.

### 2.4 Digital Waveform Parsing & SVG Rendering
Instead of requiring an external tool like GTKWave, SiliconScribe features an integrated VCD parser (`backend/vcd_parser.py`):
- Reads time steps (`#0`, `#10`, `#20`) and signal value transitions.
- Converts multi-bit binary vectors into clean hexadecimal representations (`0x0`, `0xA`), while handling unknown (`x`) and high-impedance (`z`) states.
- Implements safety limits ($\le 40$ signals, $\le 2000$ changes per signal) to prevent browser memory freezes.
- The frontend (`WaveformViewer.tsx`) renders responsive SVG graphics with zoom in/out, pan, and a dynamic time ruler.

### 2.5 Industrial UVM 1.2 Export Engine
For advanced verification environments, SiliconScribe generates a full 16-file UVM testbench suite (`backend/uvm_templates.py`):
- DUT interface (`_if.sv`) with clocking blocks.
- UVM sequence items, sequences, sequencers, drivers, monitors, and scoreboards.
- Functional coverage subscriber with covergroups.
- Testbench top (`tb_top.sv`), package file, QuestaSim `Makefile`, and `filelist.f`.
- The bundle is packaged in-memory and delivered as a single-click downloadable `.zip`.

---

## 3. RESULTS AND DISCUSSION

### 3.1 Work Completed So Far (Milestone Status: 15/10/2026)
As of this progress report, the following components have been developed, integrated, and verified:
- Full end-to-end pipeline from natural language prompt to simulation output.
- Autonomous self-correction engine with verified hash cycle prevention.
- Multi-tier linter and Yosys logic synthesis wrapper.
- Interactive web frontend with CodeMirror editor, SVG waveform viewer, and project history drawer.
- SQLite persistence layer and 16-file UVM bundle generator.
- 100% offline fallback mode with 5 pre-validated hardware design modules.

### 3.2 Verification Case Study: Self-Correcting 4-Bit Up-Counter
To evaluate the self-correction loop, a deliberately buggy prompt was tested:
> *"Design a 4-bit synchronous up-counter with async reset and enable, but make it buggy."*

**Mode disclosure (important).** SiliconScribe has two provider modes, and the loop behaves differently in each. This case study was run in **offline demo mode** (`OFFLINE_MODE=1`), which is the mode used for all automated regression tests and for the deployed Docker image when no API key is present. In offline mode the system serves *curated* designs: the buggy RTL (`count <= count + 2'd2`) is a known defect seeded on purpose, and the "fix" is a **scripted swap to a stored known-correct implementation**, reported honestly in the UI timeline and in `iteration_history` as `fix_type = "offline_scripted"`. The purpose of this mode is to validate the **loop machinery** — defect detection, log parsing, re-simulation, normalized-hash cycle prevention, and the PASS/FAIL decision path — deterministically and with zero API cost.

In **live LLM mode** (a provider key is configured), the same loop instead sends the RTL, testbench, and simulator log to the model, which performs genuine log-driven diagnosis and emits a patch. The offline case study below is therefore a *fault-injection regression test of the loop*, not a claim that a language model diagnosed the bug.

- **Iteration 0 (Initial Attempt):**
  - The served RTL contained the seeded defect: `count <= count + 2'd2;` (incrementing by 2 instead of 1).
  - Testbench ran 20 directed vectors: **0 Passed, 20 Failed (Status: FAIL)**.
  - Transcript captured: `FAIL: expected=1 got=2`, `FAIL: expected=2 got=4`...
- **Iteration 1 (Automated Patch):**
  - The loop captured the failure log and invoked the debugger.
  - The known-correct implementation was substituted (`count <= count + 1'b1;`), tagged `fix_type = "offline_scripted"`.
  - Re-simulated automatically: **20 Passed, 0 Failed (Status: PASS)**.
  - The UI displayed the step-by-step resolution on the timeline, including the scripted-fix disclosure.

### 3.3 Offline Benchmark Designs
To ensure reliability without relying on internet access, 5 hardware designs were implemented and benchmarked:

| Module Name | Functionality | Bit Width | Simulation Time | Test Vectors | Pass Rate |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **`counter`** | Synchronous up-counter with enable & async reset | 4-bit | 100 ns | 20 (directed) | **100% (PASS)** |
| **`alu_4bit`** | Arithmetic Logic Unit (ADD, SUB, AND, OR, XOR) | 4-bit | Comb | 200 (directed + `$random`) | **100% (PASS)** |
| **`alu_8bit`** | 8-bit ALU with carry/overflow detection | 8-bit | Comb | 200 (directed + `$random`) | **100% (PASS)** |
| **`full_adder`** | Gate-level full adder with carry logic | 1-bit | Comb | 8 (Exhaustive) | **100% (PASS)** |
| **`mux4to1`** | 4-to-1 multiplexer with parameterizable width | 8-bit | Comb | 100 (directed + `$random`) | **100% (PASS)** |

Vector counts are taken directly from the testbench loop bounds in `backend/offline_designs.py` (`repeat (20)` for the counter; `for i = 0..199` for both ALUs; `for i = 0..7`, exhaustive, for the full adder; `for i = 0..99` for the mux). The counter testbench is fully directed (no `$random`); the ALU and mux testbenches mix directed opcode/walkthrough coverage with randomized stimulus.

### 3.4 Logic Synthesis Metrics (Yosys)
Synthesizing generated designs with Yosys yielded standard cell counts. **Important caveat:** Yosys is run *without* a liberty file, so it maps the RTL onto Yosys's generic gate library (`$_AND_`, `$_NOT_`, `$_DFF_`, …). This means the flow performs **no technology mapping**, and therefore produces **no physical area figure**. Cell counts are real and correct; the `area_estimate` field returned by the API is a **dimensionless relative proxy** (`cell_count × 5`) used only to rank designs against one another — it is explicitly *not* a physical area in µm², and the API flags this via `liberty_mapped: false`, `area_units: "relative_proxy"`, and `tech_node: null`.

- **`full_adder`:** 2 generic cells (relative area proxy 10).
- **`counter`:** 12 generic cells (D-flip-flops + adder logic), relative area proxy 60.
- **`alu_4bit`:** 22 generic cells, relative area proxy 110.

Obtaining genuine PPA numbers requires supplying a PDK liberty file (e.g. SkyWater 130 nm or Nangate 45 nm) and running technology mapping plus static timing analysis, which is planned for the final submission.

### 3.5 Automated Test Suite Execution
The software was tested using automated test suites:
- **Backend Tests (pytest):** **42 test cases** covering Pydantic models, linter heuristics, VCD parsing, rate limiting, and the orchestrator self-correction loop. On the development machine **23 pass and 19 are skipped** because Icarus Verilog is not installed on `PATH` (`@pytest.mark.skipif(shutil.which("iverilog") is None)`). The GitHub Actions workflow installs `iverilog` and `yosys` before running the suite, so all 42 execute in CI.
- **Frontend Tests (vitest):** **36 passed unit tests** covering `PromptPanel`, `ResultsPanel`, and `WaveformViewer`.
- **TypeScript Build:** Compiled with zero errors (`tsc -b && vite build`).
- **Continuous Integration:** the CI pipeline runs `ruff` lint, the full pytest suite with `iverilog`/`yosys` installed, an end-to-end `POST /api/design/run` assertion that returns `status == "PASS"`, a 16-file UVM bundle generation check, the frontend type-check/test/build, and a Docker image build.

An honest note on test strength: 19 of the 23 locally-executed backend tests exercise pure-Python paths (models, linter fallbacks, VCD parsing, rate limiting, sanitisation). The tests that prove the *self-correction loop* reach a passing state require a real simulator, which is why they skip locally and run in CI.

---

## 4. LIMITATIONS

1. **Circular Verification (most important open limitation).** The same language model generates both the RTL *and* the self-checking testbench, and the debugger prompt instructs it to *"treat the testbench's intent as the specification."* The self-correction loop therefore demonstrates **self-consistency, not ground-truth correctness**: if the model misreads the natural-language spec (for example, swapping active-high and active-low reset), it can emit a DUT and a testbench that are *consistently wrong together* and still report 100% PASS. Fully closing this requires an **independent golden reference model** (e.g. a Python or C behavioural model the testbench compares against), which is planned for the final submission.
2. **No Static Timing Analysis or PPA Sign-off.** The `target_frequency_mhz` field is appended to the RTL-generation prompt as a textual hint only. The flow contains no SDC constraints, no `create_clock`, no `abc -D` delay optimisation, and no setup/hold analysis. Consequently the platform reports **no timing slack and no real power/area/performance figures**.
3. **Synthesis Is Unmapped (no technology library).** Yosys is invoked without a liberty file, so RTL is mapped onto Yosys's generic gate library rather than a standard-cell library. Cell counts are genuine, but the accompanying `area_estimate` is a **dimensionless relative proxy** (`cell_count × 5`) used only to rank designs against one another — it is explicitly **not** a physical area in µm². The API surfaces this via `liberty_mapped: false`, `area_units: "relative_proxy"`, and `tech_node: null`. Real PPA requires a PDK `.lib` (e.g. SkyWater 130 nm or Nangate 45 nm) plus technology mapping and STA.
4. **Testbench-Reported, Not Instrumented, Coverage.** The coverage figure is a regex parse of `$display` output emitted by the testbench itself (pass rate, plus any `COV:` bins or printed percentages). It is **not** instrumented toggle/line/branch coverage, which would require simulator instrumentation such as `verilator --coverage`.
5. **UVM Bundle Is Export-Only and Never Compiled.** The 16-file UVM 1.2 bundle is generated as SystemVerilog (`logic`, `always_ff`, classes) intended for a commercial simulator. Icarus Verilog cannot compile UVM, and no commercial licence was available in this project, so the generated bundle has **not been compiled or simulated**. It should be treated as a structured template export, not as a verified working testbench. Structural integrity is checked in CI (file count and generation success), not compilation.
6. **UVM Execution Dependency:** While the platform generates UVM 1.2 testbenches, Icarus Verilog does not support SystemVerilog OOP classes. Simulating the bundles requires commercial tools like Siemens QuestaSim or Synopsys VCS.
7. **Schematic Display Depth:** The browser viewer displays a clean port-level block diagram showing pin directions and bus widths. Gate-level logic diagrams require the planned `netlistsvg` integration over Yosys JSON output.
8. **Design Hierarchy Scope:** The implementation is optimized for single-module designs or small digital blocks ($\le 1000$ lines of RTL). Complex SoC architectures with multi-clock domains and bus protocols exceed single-prompt LLM context windows.

---

## 5. CONCLUSION AND NEXT STEPS

### 5.1 Conclusion
For this minor project milestone, **SiliconScribe** has been successfully designed, implemented, and verified. By combining natural language processing, synthesizable Verilog-2001 code generation, Icarus Verilog simulation, and an autonomous self-correction loop with oscillation guards, the system proves that AI can act as a reliable, execution-grounded assistant for digital circuit design and verification.

### 5.2 Plan for Final Submission (Deadline: 06/11/2026)
Between this progress milestone and the final evaluation, I plan to complete, in priority order:
1. **Independent Golden Reference Model (highest priority).** To break the circular-verification limitation, add a language-independent behavioural model (Python) of each benchmark design. The testbench will compare the DUT against this model rather than against an expectation derived from the same RTL, so a spec misreading cannot pass silently.
2. **Real PPA via Liberty-Based Technology Mapping.** Run Yosys with an open PDK liberty file (SkyWater 130 nm or Nangate 45 nm) using `read_liberty`, `abc`, and `stat -tech`, replacing the dimensionless area proxy with genuine cell area and estimated delay in physical units.
3. **Gate-Level Netlist Visualization:** Integrate `netlistsvg` to render gate-level logic diagrams directly in the browser using Yosys JSON outputs.
4. **Instrumented Coverage:** Add real toggle/line coverage via `verilator --coverage` to replace the current testbench-reported metric.
5. **Poster and Presentation Preparation:** Finalize the project poster, slide deck, and live demonstration for the final EC486 evaluation.

---

## 6. REFERENCES

1. IEEE Standard for SystemVerilog—Unified Hardware Design, Specification, and Verification Language, **IEEE Std 1800-2017**, pp. 1–1315, 2017.
2. Accellera Systems Initiative, *Universal Verification Methodology (UVM) 1.2 User's Guide*, Accellera, 2015.
3. S. Thakur et al., *"VeriGen: A Large Language Model for Verilog Code Generation,"* ACM TODAES, vol. 29, no. 3, pp. 1–31, 2024.
4. M. Liu et al., *"ChipNeMo: Domain-Adapted LLMs for Chip Design,"* in *Proc. 61st ACM/IEEE Design Automation Conference (DAC)*, 2024, pp. 1–6.
5. S. Williams, *"Icarus Verilog: An Open-Source Verilog Compiler and Simulator,"* `http://iverilog.icarus.com/`, 2026.
6. C. Wolf, *"Yosys Open Synthesis Suite,"* in *Proc. 21st International Workshop on Logic & Synthesis (IWLS)*, 2012.
7. W. Snyder, *"Verilator: Fast Open-Source Verilog Simulator,"* Veripool.org, 2024.

---
*(End of Progress Report)*
