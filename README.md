# SiliconScribe

**AI-driven RTL design and verification: a per-run model menu, an independent testbench, measured testbench strength and toggle coverage, a pre-layout timing and area estimate with a formal netlist proof, and gate-level schematics.** Type a hardware design in plain English and the system generates synthesizable Verilog RTL and a self-checking testbench, simulates both with Icarus Verilog 12.0, and **runs a self-correction loop** that feeds simulation failures back to the model until the design passes. The simulator decides PASS or FAIL, never the model. Results, a real VCD waveform, every executed check, a schematic, lint and synthesis metrics, testbench strength, toggle coverage, timing and area, and a step-by-step agent trace are shown in the browser. Projects persist in SQLite; UVM bundles export for Questa.

```
Natural language ─▶ Specification ─▶ RTL gen ─▶ Testbench gen ─▶ Lint
   (optional review)                    (spec only, never the RTL)    │
                                                                      ▼
                          ┌──────────── Simulate (Icarus 12.0) ◀──────┘
                          │                  │
                     PASS │            FAIL / ERROR
                          ▼                  ▼
   Synthesis, strength, timing,    Fix (compiler repair or model diagnosis)
   toggle coverage, second opinion        ── loop ≤ 5 iterations
```

## Highlights

- **Self-correction loop**: compile errors *and* test failures are fed back to the model; it returns a structured diagnosis (`symptom`, `root_cause`, `fix_location`, `confidence`) and patches the RTL *or* the testbench oracle, then re-runs until PASS or the iteration cap (5). Each attempt is recorded and shown as a timeline. Deterministic compiler-evidenced repairs (wire→reg, Icarus `disable`→`return`) are applied first and labelled `compiler_repair`. A whitespace/comment-insensitive state hash plus an oscillation and no-op guard stops a loop that is going nowhere.
- **Independent verification**: the testbench generator receives only the parsed specification, never the RTL body, so a consistently-wrong RTL/TB pair cannot trivially agree. A fix that removes self-checks is rejected. If a repair changed the testbench, the result says so and the ORIGINAL testbench is re-run against the final design.
- **Model menu (per run)**: the sidebar lists models from three sources and the choice is sent with each run (and remembered in the browser):
  - **OpenCode**: every model the installed OpenCode app lists (about 460); free ones first by name, the rest behind "Show other models" because they may use credits.
  - **Cloudflare Workers AI**: the live catalogue of the account (40 text models when tested).
  - **NVIDIA NIM**: the live catalogue (15 chat models when tested). Model names change and old ones are retired, which is why both catalogues are read live.
  - **GitHub Copilot** appears through OpenCode as `github-copilot/auto` only: GitHub picks the model and does not say which one.

  A model the user chose that fails is reported in plain words, never silently replaced by the scripted demo. Every result records which model wrote it. Model ids are validated (no leading dash, no shell characters) because they become subprocess arguments.
- **Specification review (optional)**: tick "Review the specification before generating" to see the parsed specification (module, ports, behaviour, constraints) first. You can edit the behaviour and constraints, and the run uses exactly that specification. A user-edited spec is bounded in size and must use plain identifiers. The specification used is shown read-only in the results.
- **Separate testbench model (optional)**: "Testbench written by" lets a different model, even from another provider, write the testbench. Then a FAILING check is never rewritten away by the design model; only a testbench that does not compile or hangs may be repaired. If the two models disagree, the result says so and names both.
- **Second opinion**: when a PASS only came after a repair rewrote the testbench, a FRESH testbench is generated from the same specification and run on the final design. The result shows agreement, disagreement (a warning on the PASS) or "unavailable".
- **Honest degraded mode**: an unreachable provider may fall back to a curated design *before* any live artifact exists, and the run carries a visible `fallback_notice`. Once a live call has succeeded, a later outage fails loudly instead of silently replacing the user's design. Offline scripted fixes report `fix_type="offline_scripted"` and no invented diagnosis.
- **Offline demo mode**: with no model configured (or `OFFLINE_MODE=1`) it serves curated designs (ALU, counter, adder, mux) and still demonstrates the full loop, so a demo works without internet. The UI badge says when this is in use.
- **Real simulation**: Icarus Verilog (`iverilog`/`vvp`) 12.0, `-g2012`, Verilog-2001 style (reg/wire/integer, `always @(*)`, `always @(posedge clk)`).
- **Lint**: `backend/linter.py` tries `verilator --lint-only`, falls back to `iverilog -o /dev/null -g2012 -Wall`, then a heuristic (missing semicolon, duplicate module, width mismatch). Benign `timescale` warnings filtered. Non-blocking `lint` stage in the agent panel.
- **Real waveforms**: `$dumpvars` is auto-injected if missing; the backend parses the VCD (`MAX 40 signals / 2000 changes`) and the UI renders it as SVG.
- **Synthesis (generic cells)**: `yosys` (`read_verilog -sv → synth → stat → write_json`) when available, graceful fallback to a port-level block diagram. `POST /api/synthesis/run` returns `cell_count` and a **relative area proxy** (`area_estimate` = generic-cell count × 5) with `liberty_mapped: false`, `area_units: "relative_proxy"`, `tech_node: null`. This proxy is only for ranking designs against each other. Mapped area in µm² comes from the timing step below.
- **Timing and area (pre-layout estimate)**: after a PASS, Yosys 0.71 maps the design to SkyWater 130 nm `sky130_fd_sc_hd` cells (typical corner, 25 C, 1.8 V) and OpenSTA 3.2.0 times the netlist. It reports slack at the target clock, the minimum clock period / maximum frequency for clocked designs, the **longest input-to-output path** for designs with no clock (never a clock rate), the critical path, mapped area in µm², cell count and flip-flops. Hierarchy is flattened, clocks are read from the mapped netlist (any port name, several clocks) and parameters the testbench overrides are applied.
  - **Limits (also stated in the app)**: one typical corner, no wire delay (no place and route), ideal clock, zero I/O delays, setup only. Not sign-off. Power is not reported.
  - **Refuses with a reason** instead of printing a number: tri-states (Yosys would silently turn them into wires), latches, combinational loops, derived or gated clocks, designs with no logic cells.
  - **Needs** `yosys`, OpenSTA's `sta` on `PATH`, and `backend/pdk/sky130hd_tt.lib`. The library is git-ignored (12 MB); fetch it as described in [`backend/pdk/README.md`](backend/pdk/README.md). Without them the app shows timing and area as "not available" and never invents numbers. `TIMING_ENABLED=0` skips the step.
  - **Formally proven** (`backend/equivalence.py`): after mapping, Yosys' built-in SAT solver proves the sky130 netlist equals the RTL. Combinational designs: a miter plus SAT over every defined input value. Sequential designs: registers paired by name, temporal induction. If induction cannot decide (for example synthesis re-encoded FSM state) the app says **not proven**, never passed; a mismatch is an alert that invalidates the timing and area. On the 14 evaluation designs and the 4 built-in ones: **16 proven, 2 not proven (the two FSMs), 0 different**; a deliberately sabotaged netlist is reported as different. This proves netlist = RTL, not that the RTL is correct.
  - **Critical path, pin by pin**: the worst path from OpenSTA with each sky130 cell, edge and delay. Example: the built-in 8-bit ALU's path is its ripple-carry chain (`b[0]` → nor2b → seven maj3 → o21ai → o22ai → `overflow`, 2.69 ns).
  - **Also checked** by `backend/tools/verify_mapping.py` on 19 designs: the mapped gate netlist, simulated with the SAME testbench, gives identical pass counts to the RTL; area and cell count recomputed from netlist + liberty match; the minimum period does not change with the target. Example: the built-in 4-bit counter is 11 cells, 150.144 µm², minimum period 0.727 ns (meets 100 MHz with +9.27 ns slack).
- **UVM Export (Questa style)**: `POST /api/uvm/export` generates a 16-file Questa/ModelSim bundle (`logic`/`always_ff`, `uvm_*`, `uvm_config_db#(virtual *_if)`, `run_test()`, `Makefile`/`filelist.f`/`README`). Export-only, never simulated with Icarus.
- **Projects**: SQLite `backend/workspace/projects.db` persists every design/run. `GET /api/projects` (paginated), `GET /api/projects/{id}`, `DELETE`. Frontend drawer with Load/Delete.
- **Editable code**: CodeMirror with Verilog highlighting, Copy per tab, `Ctrl+Enter` to generate; edit and **Re-run** (`POST /api/simulation/run`).
- **Live agent stream**: the pipeline streams over Server-Sent Events into the agent panel (spec, RTL, testbench, lint, simulate, fix, synthesis, strength, timing, second opinion).
- **Sandbox policy (defence in depth, not a jail)**: before anything is compiled, linted, synthesized or timed, RTL/testbench are rejected if they use a system task outside an allow-list (`$display`/`$monitor`/`$finish`/`$dump*`/`$random`/math helpers…), `` `include ``, `$readmemh`, `$system`, file I/O, macro token pasting or a non-plain `$dumpfile`; RTL may not print the testbench's `Passed:`/`Failed:` lines or call `$finish`. The child process gets a scrubbed environment (API keys never reach `vvp`), a closed stdin, CPU-time / file-size / memory limits (the memory limit is enforced on Linux, not macOS) and at most `SIM_MAX_CONCURRENT` (default 2) simulations run at once.
- **Verdict integrity**: PASS needs a whole-line `Passed: N` / `Failed: 0` summary with N > 0 (at least one executed check), no `FAIL`/`ERROR` line contradicting it, and a clean `vvp` exit. Zero executed checks is never a PASS. A testbench whose watchdog fires before its summary is ERROR. PASS is evidence, not proof: it is only as strong as the testbench that prints it.
- **Per-test-case results**: testbenches that log one `CHK|PASS/FAIL|category|name|time|expected|actual|` line per comparison get a *Test cases* tab: totals, test types with pass ratios, a filterable and searchable table, bit-level diff for failures, and a jump to that moment in the waveform.
- **Waveform viewer**: fits the pane, signals grouped by role (clock/reset, inputs, outputs, internal; testbench variables hidden by default), live values at the cursor, hex/bin/dec, two measurement cursors, failed-check flags on the time axis, zoom and a full-window *Expand* mode.
- **Per-stage routing**: `LLM_MODEL_INTENT` / `_RTL` / `_TESTBENCH` / `_EXPLAIN` / `_FIX` can put a strong model on the verification-critical stages and a cheap one on cosmetic ones. A model chosen in the menu for a run wins.
- **Measured testbench strength**: after every PASS the app injects up to 12 one-token bugs into the passing design (mutation testing, DeMillo, Lipton and Sayward, 1978) and reruns the same testbench; the card shows "caught N of M". Survivors may be equivalent mutants, so the score is evidence about the testbench, not a proof. `STRENGTH_ENABLED=0` skips it. Separately, `python3 backend/tools/mutation_sweep.py` injects 27 hand-picked bugs into the curated designs: **27 / 27 caught**.
- **Measured toggle coverage**: read from the simulator's own VCD for design signals only; each bit must be seen going 0→1 and 1→0. On the deliberately buggy counter it reports that `count[0]` never changed. Line and branch coverage are **not** measured.

## Requirements

- Python 3.11+ and a working `iverilog` / `vvp` 12.0 (`brew install icarus-verilog`, `apt install iverilog`, or use Docker)
- Node 18+ / npm
- Optional, for synthesis: `yosys` (`brew install yosys`)
- Optional, for timing and area: `yosys`, OpenSTA's `sta` on `PATH` (built from source; `backend/tools/build_opensta.sh` is the build script used here), and `backend/pdk/sky130hd_tt.lib` (see [`backend/pdk/README.md`](backend/pdk/README.md))
- For live generation, one of: the OpenCode app installed and signed in (used for the live demo and the evaluation), Cloudflare Workers AI, NVIDIA NIM, or any OpenAI-compatible key. With none of them the app runs the labelled offline demo.

## Setup & run

```bash
# 1. Backend
cd backend
python3 -m venv venv && source venv/bin/activate   # if not already created
pip install -r requirements.txt
cp .env.example .env        # optional provider settings, see "Model providers" below

# 2. Frontend
cd ../frontend
npm install

# 3. Launch both (from repo root)
./run.sh
```

- Backend: http://localhost:8000  (docs at `/docs`)
- Frontend: http://localhost:5173

**Live setup used for the demo and the evaluation** (two terminals; from `viva/DEMO_RUNBOOK.md`):

```bash
# terminal 1: backend, live model through the OpenCode app
cd backend
PATH="$HOME/.local/bin:$PATH" env -u OFFLINE_MODE LLM_PROVIDER=opencode-app \
  LLM_MODEL=deepseek-v4.1-flash-free LLM_TIMEOUT_SECONDS=360 \
  python3 -m uvicorn main:app --host 127.0.0.1 --port 8000

# terminal 2: frontend
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173
```

`$HOME/.local/bin` is where `iverilog`, `yosys` and `sta` are installed on the development machine; drop it if they are already on your `PATH`. The top-right badge shows which model is live, or *Offline demo* / *Demo fallback* when it is not. To force offline mode even with a provider configured: `OFFLINE_MODE=1`.

### Model providers (optional, through `backend/.env`)

Keys and account ids are read only from the environment of the backend process, and the simplest place is `backend/.env` (git-ignored; keep it owner-only with `chmod 600`). The web page never asks for, accepts or stores a key. See `backend/.env.example` for the full list. Variable names only:

| Menu tab | Variables | Without them |
|---|---|---|
| OpenCode | `LLM_PROVIDER=opencode-app`, `LLM_MODEL` (the default the menu starts on), `LLM_TIMEOUT_SECONDS` | tab is not used |
| Cloudflare Workers AI | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` (token with the "Workers AI" permission) | tab says it is not set up |
| NVIDIA NIM | `NVIDIA_NIM_API_KEY` (a key that starts with `nvapi-`) | tab says it is not set up |

The older single-provider variables (`OPENCODE_API_KEY` / `ZEN_API_KEY`, `NVIDIA_API_KEY`, `OPENAI_API_KEY` + `OPENAI_BASE_URL`) still work when `LLM_PROVIDER` is not set; see `backend/.env.example`. Free tiers are slow and quota-limited: a live run took 3 to 13 minutes in the evaluation, and Cloudflare's free allowance is 10,000 "neurons" a day.

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/design/run` | One-shot: generate → simulate → self-correct. Returns code, result, iteration history, waveform, schematic, synthesis, strength, toggle coverage, timing, second opinion. Persists to SQLite. |
| POST | `/api/design/stream` | Same pipeline, streamed as SSE (one event per stage). |
| POST | `/api/spec/parse` | Turn a prompt into a specification and stop, so it can be reviewed and edited before generation. |
| POST | `/api/simulation/run` | Simulate a (possibly hand-edited) RTL/TB pair once. Rate-limited. |
| POST | `/api/synthesis/run` | Synthesize RTL with Yosys (if available) → `{available, cell_count, area_estimate (relative proxy, NOT µm²), liberty_mapped:false, area_units, tech_node:null}`. |
| POST | `/api/timing/run` | Map RTL to sky130 cells and report pre-layout timing and area at the target clock (or the reason it refuses). |
| POST | `/api/uvm/export` | Export UVM bundle (Questa style) from prompt → `{files, file_count, is_sequential, zip_base64}`. Export-only, not Icarus. |
| GET | `/api/projects` | List persisted projects `?limit=20&offset=0` → `{total, projects}`. |
| GET | `/api/projects/{id}` | Get full `RunResponse` for persisted project. |
| DELETE | `/api/projects/{id}` | Delete persisted project. |
| GET | `/api/models` | Models for the menu: OpenCode, Cloudflare Workers AI and NVIDIA NIM (`?include_paid=true` adds non-free models, `?refresh=true` re-reads the catalogues). |
| POST | `/api/admin/cleanup` | Admin: GC workspace `?ttl_hours=24` (1..720). |
| GET | `/`, `/health` | Status & simulator check. |

## Evaluation (live, free model)

15 prompts (7 combinational, 6 sequential, 2 FSM) were run through the real pipeline with DeepSeek V4.1 Flash (free) through the OpenCode app. 14 completed with no offline fallback: **8 PASS on the first attempt, 6 PASS after self-repair, 0 not PASS**. Median 360 s per run (3 to 13 minutes). Testbench strength: **102 of 111 injected bugs caught (92%)**. The 15th prompt (s1, 4-bit counter) did not complete: testbench generation timed out three times, so it is reported as "no result", never as a pass or a failure. All 14 passing designs were also checked against independent hand-written reference testbenches: all correct, no false PASS. One run per prompt, mainly one model, small blocks.

Full table (checks, strength, toggle coverage, timing, area per design): [`backend/evaluation/summary.md`](backend/evaluation/summary.md). Raw records are in `backend/evaluation/results.jsonl`, designs and testbenches in `backend/evaluation/artifacts/`, reference testbenches in `backend/evaluation/independent/`. Re-run with `backend/tools/evaluate_live.py` (`--summary` only rebuilds the table, no model call).

## Documentation

- **Final report (EC486):** [`docs/EC486_Final_Report.pdf`](docs/EC486_Final_Report.pdf): architecture, methodology, live-run results, failure analysis, and limitations.
- **Report source:** [`docs/EC486_Final_Report.tex`](docs/EC486_Final_Report.tex); live screenshots are in [`docs/screenshots/`](docs/screenshots/).
- **Presentation:** [`docs/SiliconScribe_EC486_Presentation.pptx`](docs/SiliconScribe_EC486_Presentation.pptx): 23 slides (21 main, 2 backup) with speaker notes.
- **Live evidence:** [`docs/evidence/`](docs/evidence/) contains the archived RTL, testbench, simulator transcript, and structured diagnosis from the early live runs; [`backend/evaluation/`](backend/evaluation/) holds the live evaluation.
- **Viva notes:** [`viva/QA_SHEET.md`](viva/QA_SHEET.md) and [`viva/DEMO_RUNBOOK.md`](viva/DEMO_RUNBOOK.md).

## Tests and verification

```bash
cd backend
PATH="$HOME/.local/bin:$PATH" OFFLINE_MODE=1 python3 -m pytest tests/ -q   # 453 passed (32 test files)
PATH="$HOME/.local/bin:$PATH" python3 tools/mutation_sweep.py            # 27 of 27 injected bugs caught
PATH="$HOME/.local/bin:$PATH" python3 tools/verify_mapping.py            # 19 of 19 designs equivalent at gate level (about 30 s)
PATH="$HOME/.local/bin:$PATH" python3 tools/preflight.py                 # demo readiness, free checks only
#   add --live to preflight.py for ONE tiny live model call (uses a little quota)
cd ../frontend
npm test                  # 222 passed (vitest)
npm run build             # tsc -b && vite build
```

The backend suite runs with **no API key** (`OFFLINE_MODE=1`); the model catalogue tests use fakes for the OpenCode command and the Cloudflare and NVIDIA servers. `test_orchestrator.py` shows the self-correction loop turning a deliberately buggy counter into a PASS. The newest components were also sabotaged on purpose (each behaviour broken) to check that the tests fail. An automated axe-core audit reports 0 violations in both themes, for passing and failing runs, on every tab. UVM bundles are not simulated with Icarus (Questa).

## Security notes

- The API accepts browser calls from this machine only: CORS allows `localhost` / `127.0.0.1` origins, with no wildcard. Extra exact origins are opt-in through `CORS_ALLOW_ORIGINS` (comma-separated; entries with `*` are ignored).
- Keys live only in `backend/.env` (git-ignored) or the backend's environment, never in the web page, the frontend bundle or the logs. The simulator child process gets a scrubbed environment.
- Path-traversal block (`DESIGN_ID_RE ^[a-zA-Z0-9_-]{1,32}$` + `is_relative_to`), `max_length` (prompt 2K, rtl/tb 50K), generic `500` errors instead of `str(e)`, per-IP rate limit `20/min` on all `POST`, `MAX_CODE_BYTES 200KB`, simulation timeout `1..120 s`, workspace GC. Set `TRUST_PROXY_HEADERS=1` only behind a trusted reverse proxy.
- The sandbox is defence in depth on a developer machine, not a jail. For multi-user use the simulator belongs in a container.

## Limitations

- One model writes both the design and the testbench unless a separate testbench model is chosen; the specification is written by a model unless you review it.
- Testbench strength is a sample of up to 12 syntactic mutants; only toggle coverage is measured (no line or branch coverage); there are no assertions. The formal check covers netlist = RTL only, and FSMs whose state is re-encoded stay "not proven".
- Timing and area are pre-layout on one corner: no wires, setup only, no power. Not sign-off.
- Free models are slow and quota-limited; GitHub Copilot `auto` cannot name the model it used.
- The sandbox is defence in depth, not a jail.
- Evaluated on small blocks (under about 100 lines of RTL), one run each, mainly one model.

## Future work

- Power estimate from the run's own simulation activity (OpenSTA reads the VCD).
- Mutation-guided testbench hardening: bugs the testbench missed go back to the model to add checks.
- Coverage-driven test generation from toggle-coverage gaps.
- Physical layout with OpenROAD place and route, for post-layout timing.
- SVA assertions with formal property checking; a multi-model comparison on the 15 prompts.
- Export to a Tiny Tapeout shuttle: from a prompt to fabricated silicon.

## Design notes / honest scope

- **Two kinds of area**: `/api/synthesis/run` runs `yosys synth` **without a liberty file**, so its area is a **dimensionless relative proxy** (`cells × 5`), flagged by `liberty_mapped:false` / `area_units:"relative_proxy"` / `tech_node:null`. The µm² area shown in *Timing and area* comes from mapping to the sky130 library and is a pre-layout estimate.
- **Independent TB, residual model risk**: the testbench generator is given the **specification only** and the RTL body is withheld, so it cannot simply mirror the implementation. The remaining risk is that the same model misreads the spec in *both* artifacts. Specification review, a separate testbench model and the second opinion reduce this; the app does not decide automatically which side is wrong when they disagree, a person compares the first failing check with the specification.
- **Timing is an estimate**: no SDC beyond the target clock, no place and route, no hold analysis. `backend/openroad.py` is still a stub (`openroad -version` check only) and is not wired into the pipeline.
- **Schematic views**: *Block diagram* (ports, from the spec), *RTL cells* (word-level cells after Yosys `proc; opt`) and *Gate level* (single-bit generic gates after `synth`; generic cells, not sky130 cells), drawn in the browser with [netlistsvg](https://github.com/nturley/netlistsvg) from the Yosys netlist of the run. The netlists are reduced to ports and cells (no server paths), the SVG is shown as an image so signal names cannot run script, and designs over 400 cells are not drawn (use RTL cells). Zoom, fit and SVG download.
- **Coverage**: toggle coverage is measured from the VCD. Any other coverage number (`COV:` bins, `Toggle/Branch/Line/Functional` lines a testbench prints about itself) is parsed from the log and labelled as testbench-reported. Verilator was tried for line and branch coverage and rejected: only 3 of 12 designs built with the pip wheel.
- **UVM is export-only**: the generated bundle needs the UVM class library, which Icarus Verilog does not implement, so it targets Questa/ModelSim and is never simulated by `simulator.py`.
- **Lint is best-effort**: `verilator --lint-only` preferred, `iverilog -g2012 -Wall` fallback, heuristic regex last resort. Non-blocking.
- **Persistence**: SQLite `projects.db` at `backend/workspace/projects.db`, per-connection `check_same_thread=False`, migration for `data` JSON. `cleanup` GC skips the `.db` file.

## Layout

```
backend/
  main.py            FastAPI app + routes (design/stream/spec/simulation/synthesis/timing/uvm/projects/models/cleanup), CORS
  orchestrator.py    generate→lint→simulate→fix loop, then synthesis, strength, timing, second opinion (+ SSE, hash/oscillation guards)
  llm_service.py     providers: OpenCode app, Cloudflare Workers AI, NVIDIA NIM, OpenAI-compatible, offline
  model_catalog.py   live model lists for the menu (OpenCode, Cloudflare, NVIDIA NIM)
  checks.py          CHK| per-check line parser
  mutation.py        testbench strength (mutation testing)
  timing.py          Yosys sky130 mapping + OpenSTA timing, area and the critical path
  equivalence.py     formal proof that the sky130 netlist equals the RTL (Yosys SAT / induction)
  offline_designs.py curated designs (ALU/counter/adder/mux + buggy) + // [offline:key] marker
  simulator.py       Icarus compile/run, sandbox policy, $dumpvars injection, limits
  vcd_parser.py      VCD → waveform JSON (MAX 40/2000), toggle coverage
  cov_metrics.py     testbench-reported coverage parsing
  schematic.py       port-level + synthesize_with_yosys (stat, RTL-cell and gate-level JSON netlists for the schematic)
  synthesis.py       YosysSynthesizer hybrid (available/cell_count/area/json)
  linter.py          VerilogLinter (verilator→iverilog→heuristic, benign filter)
  uvm_templates.py   UVM bundle generator (16 files, Questa style)
  db.py              SQLite persistence
  cleanup.py         workspace GC (ttl 24h, skips .db)
  pdk/               sky130hd_tt.lib goes here (git-ignored, see pdk/README.md)
  tools/             mutation_sweep.py, verify_mapping.py, evaluate_live.py, preflight.py, build_opensta.sh
  evaluation/        live evaluation: summary.md, results.jsonl, artifacts/, independent/
  tests/             pytest suite (453 tests, 32 files; offline, no key)
frontend/
  src/App.tsx        layout + streaming + Projects drawer + UVM export → zip download
  src/components/    PromptPanel, ModelPicker, TestbenchModelSelect, SpecReview, SpecSummary, CodeEditor, AgentChat,
                     ResultsPanel (strength, timing and area, synthesis, toggle coverage), TestCasesView,
                     WaveformViewer, SchematicView
  src/api.ts         REST + SSE (fetch+Reader) + projects/uvm export client
  src/types.ts       RunResponse and related types
```

## Deploy (Free Tier)

**Frontend (Vercel):** `vercel.json` → `build: cd frontend && npm ci --ignore-scripts && npm run build`, `output: frontend/dist`, rewrites `/api/*` → backend (server-side, so the browser stays same-origin).

**Backend (Render):** `render.yaml` → `Dockerfile` (`yosys` + `iverilog` 12.0), `healthCheck: /health`, set `OPENCODE_API_KEY` as a secret env var for a hosted model. The Docker image has no OpenSTA and no sky130 library, so timing and area show "not available" there, and the OpenCode app provider is a local, single-user setup.

```bash
# Push to GitHub then
vercel --prod   # or import via vercel.com/new
# Render: connect repo at render.com, picks render.yaml automatically
```
