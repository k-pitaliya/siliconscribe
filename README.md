# SiliconScribe

**AI-driven RTL design & verification.** Type a hardware design in plain English → the system generates synthesizable
Verilog RTL and a self-checking testbench, simulates it with Icarus Verilog,
and **runs an autonomous self-correction loop** that feeds simulation failures
back to the LLM until the design passes. Results, a real VCD waveform, a
schematic, and a step-by-step agent trace are shown in the browser.

```
Natural language ─▶ Intent parse ─▶ RTL gen ─▶ Testbench gen ─▶ Explain
                                                                   │
                                                                   ▼
                          ┌──────────── Simulate (Icarus) ◀────────┘
                          │                  │
                     PASS │            FAIL / ERROR
                          ▼                  ▼
                        Done   ◀──  Fix (LLM debugger)  ── loop ≤ N
```

## Highlights

- **Self-correction loop** — compile errors *and* test failures are fed back to
  the model; it patches RTL (or the testbench) and re-runs until PASS or the
  iteration cap. Each attempt is recorded and shown as a timeline.
- **Real simulation** — Icarus Verilog (`iverilog`/`vvp`), `-g2012`.
- **Real waveforms** — `$dumpvars` is auto-injected if missing; the backend
  parses the VCD and the UI renders it as SVG (bits + hex buses).
- **Editable code** — CodeMirror with Verilog highlighting; edit and "Re-run".
- **Live agent stream** — the pipeline streams over SSE into the agent panel.
- **Offline demo mode** — with no API key it serves curated designs (ALU,
  counter, adder, mux) and still demonstrates the full loop, so it never
  hard-fails in an interview without internet.

## Requirements

- Python 3.11+ and a working `iverilog` / `vvp` (`brew install icarus-verilog`)
- Node 18+ / npm
- (Optional) An `OPENAI_API_KEY` for live AI generation

## Setup & run

```bash
# 1. Backend
cd backend
python3 -m venv venv && source venv/bin/activate   # if not already created
pip install -r requirements.txt
cp .env.example .env        # add OPENAI_API_KEY, or leave blank for offline mode

# 2. Frontend
cd ../frontend
npm install

# 3. Launch both (from repo root)
./run.sh
```

- Backend: http://localhost:8000  (docs at `/docs`)
- Frontend: http://localhost:5173

To force offline mode even with a key: `OFFLINE_MODE=1`.

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/design/run` | One-shot: generate → simulate → self-correct. Returns code, result, iteration history, waveform, schematic. |
| POST | `/api/design/stream` | Same pipeline, streamed as SSE (one event per stage). |
| POST | `/api/design/generate` | Generate RTL + testbench + explanation only. |
| POST | `/api/simulation/run` | Simulate a (possibly hand-edited) RTL/TB pair once. |
| GET | `/api/simulation/{id}/waveform` | Parsed VCD JSON. |
| GET | `/api/artifacts/{id}/{file}` | Download `design.vcd` / `transcript.log` (allowlisted, path-traversal safe). |

## Tests

```bash
cd backend
OFFLINE_MODE=1 ./venv/bin/python -m pytest tests/ -v
```

The suite runs with **no API key**. `test_orchestrator.py` proves the
self-correction loop turns a deliberately-buggy counter into a PASS.

## Design notes / honest scope

- **Coverage is lightweight** — test-vector counts and pass-rate parsed from the
  self-checking testbench, *not* synthesis toggle/line coverage.
- **Schematic is a port-level block diagram** built from the parsed spec.
  Gate-level synthesis rendering (yosys + netlistsvg) is future work.
- **Security** — generated Verilog is executed locally via `vvp`. It runs under
  a per-simulation timeout, confined to `backend/workspace/`. The artifact
  endpoint is allowlisted and path-traversal safe. This is a local dev tool, not
  a hardened multi-tenant sandbox.

## Layout

```
backend/
  main.py            FastAPI app + routes
  orchestrator.py    the agentic generate→simulate→fix loop (+ SSE generator)
  llm_service.py     OpenAI / Offline provider seam + fix_design
  offline_designs.py curated designs (powers offline mode + tests)
  simulator.py       Icarus compile/run, $dumpvars injection, result parsing
  vcd_parser.py      VCD → waveform JSON
  coverage.py        lightweight functional coverage
  schematic.py       port-level schematic data
  tests/             pytest suite (offline, no key needed)
frontend/
  src/App.tsx        layout + streaming state
  src/components/    PromptPanel, CodeEditor, AgentChat, ResultsPanel,
                     WaveformViewer, SchematicView
  src/api.ts         REST + SSE client
```
