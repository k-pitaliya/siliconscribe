# SiliconScribe

**AI-driven RTL design & verification — now with zero-budget Zen, hardening, lint, synthesis & UVM export.** Type a hardware design in plain English → the system generates synthesizable Verilog RTL and a self-checking testbench, simulates it with Icarus Verilog, and **runs an autonomous self-correction loop** that feeds simulation failures back to the LLM until the design passes. Results, a real VCD waveform, a schematic, lint + synthesis metrics, and a step-by-step agent trace are shown in the browser. Projects persist in SQLite; UVM bundles export for Questa.

```
Natural language ─▶ Intent parse ─▶ RTL gen ─▶ Testbench gen ─▶ Explain
                                                                   │
                                                                   ▼
                          ┌──────────── Simulate (Icarus) ◀────────┘
                          │                  │
                     PASS │            FAIL / ERROR
                          ▼                  ▼
                        Done   ◀──  Fix (LLM debugger)  ── loop ≤ N
                                 + Lint (verilator→iverilog→heuristic)
                                 + Synth (yosys → netlist)
```

## Highlights

- **Self-correction loop** — compile errors *and* test failures are fed back to the model; it patches RTL (or the testbench) and re-runs until PASS or the iteration cap. Each attempt is recorded and shown as a timeline. Whitespace/comment-insensitive hash + oscillation guard prevents thrash.
- **Opencode Zen (zero-budget, remote)** — primary LLM `opencode/muse-spark-1.2-contributor-free` via `OPENCODE_API_KEY` at `https://api.opencode.ai/v1` (also `ZEN_API_KEY` alias). Falls back to `NVIDIA NIM` → `OpenAI` → `offline`. `OFFLINE_MODE=1` forces offline curated designs.
- **Offline demo mode** — with no API key it serves curated designs (ALU, counter, adder, mux) and still demonstrates the full loop, so it never hard-fails in an interview without internet.
- **Real simulation** — Icarus Verilog (`iverilog`/`vvp`), `-g2012`, `Verilog-2001` (reg/wire/integer, `always @(*)`, `always @(posedge clk)`).
- **Lint** — `backend/linter.py` tries `verilator --lint-only`, falls back to `iverilog -o /dev/null -g2012 -Wall`, then heuristic (missing semicolon, duplicate module, width mismatch). Benign `timescale` warnings filtered. Non-blocking `lint` stage in agent panel.
- **Real waveforms** — `$dumpvars` is auto-injected if missing; the backend parses the VCD (`MAX 40 signals / 2000 changes`) and the UI renders it as SVG (bits + hex buses, zoom/ruler, dark amber truncation).
- **Synthesis** — `yosys` (`read_verilog -sv → synth → stat → write_json`) when available, `Dockerfile` includes `yosys`, graceful fallback to port-level block diagram. `POST /api/synthesis/run` returns `cell_count / area_estimate`.
- **UVM Export (Questa style)** — `POST /api/uvm/export` generates a `16-file` Questa/ModelSim bundle (`logic`/`always_ff`, `uvm_*`, `uvm_config_db#(virtual *_if)`, `run_test()` at 0, `Makefile`/`filelist.f`/`README`). Export-only, never `iverilog` simulated. `Frontend UVM button → zip download`.
- **Projects** — `SQLite` `backend/workspace/projects.db` persists every `design/run`. `GET /api/projects` (paginated), `GET /api/projects/{id}`, `DELETE`. Frontend drawer with `Load/Delete`.
- **Editable code** — CodeMirror with Verilog highlighting, `Copy` per tab, `Ctrl+Enter` to generate; edit and `Re-run` (also `Re-run` uses `POST /api/simulation/run`).
- **Live agent stream** — the pipeline streams over SSE into the agent panel (`lint`/`synthesis` stages included).
- **Security** — path-traversal block (`DESIGN_ID_RE` + `is_relative_to`), `max_length` (prompt 2K, rtl/tb 50K, module regex), `500 generic` not `str(e)`, per-IP rate-limit `20/min` on all `POST`, `MAX_CODE_BYTES 200KB`, `timeout 1..120`, `admin cleanup TTL 1..720`, `workspace GC`.

## Requirements

- Python 3.11+ and a working `iverilog` / `vvp` (`brew install icarus-verilog`, `apt install iverilog`, or use `Docker`), `yosys` optional (`brew install yosys`) for synthesis
- Node 18+ / npm
- (Optional) `OPENCODE_API_KEY` (Zen) or `NVIDIA_API_KEY` or `OPENAI_API_KEY` for live AI generation — or leave blank for offline mode

## Setup & run

```bash
# 1. Backend
cd backend
python3 -m venv venv && source venv/bin/activate   # if not already created
pip install -r requirements.txt
cp .env.example .env        # add OPENCODE_API_KEY (Zen, free) or leave blank for offline

# 2. Frontend
cd ../frontend
npm install

# 3. Launch both (from repo root)
./run.sh
```

- Backend: http://localhost:8000  (docs at `/docs`)
- Frontend: http://localhost:5173

To force offline mode even with a key: `OFFLINE_MODE=1`.
To use Zen: `OPENCODE_API_KEY=sk-...` (or `ZEN_API_KEY`) — remote, not local, defaults to `opencode/muse-spark-1.2-contributor-free` at `https://api.opencode.ai/v1`.

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/design/run` | One-shot: generate → simulate → self-correct. Returns code, result, iteration history, waveform, schematic, synthesis. Persists to SQLite. |
| POST | `/api/design/stream` | Same pipeline, streamed as SSE (one event per stage: `start/intent/rtl/lint/testbench/lint/explanation/simulate/fixing/fix/synthesis/done`). |
| POST | `/api/design/generate` | Generate RTL + testbench + explanation only (if wired). |
| POST | `/api/simulation/run` | Simulate a (possibly hand-edited) RTL/TB pair once. Rate-limited. |
| POST | `/api/synthesis/run` | Synthesize RTL with Yosys (if available) → `{available, cell_count, area_estimate}`. |
| POST | `/api/uvm/export` | Export UVM bundle (Questa style) from prompt → `{files, file_count, is_sequential, zip_base64}`. Export-only, not Icarus. |
| GET | `/api/projects` | List persisted projects `?limit=20&offset=0` → `{total, projects}`. |
| GET | `/api/projects/{id}` | Get full `RunResponse` for persisted project. |
| DELETE | `/api/projects/{id}` | Delete persisted project. |
| GET | `/api/models` | List available LLM models (Zen/NVIDIA/OpenAI or offline). |
| POST | `/api/admin/cleanup` | Admin: GC workspace `?ttl_hours=24` (1..720). |
| GET | `/`, `/health` | Status & simulator check. |

## Tests

```bash
cd backend
OFFLINE_MODE=1 ./venv/bin/python -m pytest tests/ -v   # 42 passed (real iverilog when on PATH)
cd ../frontend
npm test                  # 36 passed (vitest)
npm run build             # tsc -b && vite 586KB
```

The suite runs with **no API key**. `test_orchestrator.py` proves the self-correction loop turns a deliberately-buggy counter into a PASS. `test_linter.py` covers heuristic + `iverilog` parsing. UVM bundle not `iverilog` simulated (Questa).

## Design notes / honest scope

- **Coverage is lightweight + extended** — `pass_rate` + `COV:` bins + optional `Toggle/Branch/Line/Functional` parsed from log if TB prints `Toggle coverage: 85%`. *Not* synthesis toggle/line coverage.
- **Schematic is hybrid** — port-level block diagram via `spec` when `yosys` absent; gate-level `write_json` metrics (`cell_count`, `area_estimate`) when `yosys` available. `Docker` includes `yosys`; local without `yosys` falls back gracefully.
- **UVM is export-only** — generated SV uses `logic`/`always_ff`/`logic` and `uvm_*` (Questa), **not** `iverilog -g2012` compatible. Bundle is `zip` download for `vlog`/`vsim` (`QUESTA_HOME/uvm-1.2`), never auto-simulated via `simulator.py`.
- **Lint is best-effort** — `verilator --lint-only` preferred, `iverilog -g2012 -Wall` fallback, heuristic regex last resort. `timescale` warnings benign-filtered. Non-blocking.
- **Security** — generated Verilog is executed locally via `vvp`. It runs under a per-simulation timeout `1..120s`, confined to `backend/workspace/<id>/`, `DESIGN_ID_RE ^[a-zA-Z0-9_-]{1,32}$` + `is_relative_to`, `MAX_CODE_BYTES 200KB`, allowlisted artifact paths, per-IP sliding window `20/min`. This is a local dev tool, not a hardened multi-tenant sandbox.
- **Persistence** — `SQLite` `projects.db` at `backend/workspace/projects.db`, per-connection `check_same_thread=False`, migration for `data` JSON. `cleanup GC` skips `.db` file. Foreground `workspace/` at repo root also ignored.

## Layout

```
backend/
  main.py            FastAPI app + routes (design/stream/simulation/synthesis/uvm/projects/cleanup)
  orchestrator.py    agentic generate→lint→simulate→fix→lint→synthesis loop (+ SSE, hash/oscillation guards)
  llm_service.py     Zen > NVIDIA > OpenAI > Offline seam + fix_design (OPENCODE_API_KEY/ZEN_API_KEY)
  offline_designs.py curated designs (ALU/counter/adder/mux + buggy) + // [offline:key] marker
  simulator.py       Icarus compile/run, $dumpvars injection, harden (DESIGN_ID_RE, 200KB, is_relative_to, timeout clamp)
  vcd_parser.py      VCD → waveform JSON (MAX 40/2000, x/z → x/z, hex)
  coverage.py        lightweight + Toggle/Branch/Line/Functional parsing
  schematic.py       port-level + synthesize_with_yosys (yosys -p synth -top, stat, write_json)
  synthesis.py       YosysSynthesizer hybrid (available/cell_count/area/json)
  linter.py          VerilogLinter (verilator→iverilog→heuristic, benign filter)
  uvm_templates.py   UVM bundle generator (16 files, Questa style, no Jinja, f-strings)
  db.py              SQLite persistence (projects table, init/save/get/list/count/delete)
  cleanup.py         workspace GC (ttl 24h, skips .db)
  tests/             pytest suite (offline, no key, real iverilog when PATH has ~/iverilog12/bin)
frontend/
  src/App.tsx        layout + streaming + Projects drawer + UVM export → zip download
  src/components/    PromptPanel (Ctrl+Enter, freq clamp), CodeEditor (Copy), AgentChat (lint/synthesis icons),
                     ResultsPanel (synthesis/lint sections, pass-rate colors, waveform/schematic tabs),
                     WaveformViewer (zoom/ruler/hex 0x, dark amber), SchematicView (port+inout responsive)
  src/api.ts         REST + SSE (fetch+Reader) + projects/uvm export client
  src/types.ts       RunResponse + ProjectSummary + UVMExportResponse + StreamEvent lint/synthesis
```

## Deploy (Free Tier)

**Frontend (Vercel):** `vercel.json` → `build: cd frontend && npm ci && npm run build`, `output: frontend/dist`, rewrites `/api/*` → backend.

**Backend (Render):** `render.yaml` → `Dockerfile` (`yosys+iverilog`, `OFFLINE_MODE=1`), `healthCheck: /health`, set `OPENCODE_API_KEY` as secret env for Zen.

```bash
# Push to GitHub then
vercel --prod   # or import via vercel.com/new
# Render: connect repo at render.com, picks render.yaml auto
```

Live demo after deploy: `https://siliconscribe.vercel.app` (frontend) + `https://siliconscribe-backend.onrender.com` (backend `/docs`).

