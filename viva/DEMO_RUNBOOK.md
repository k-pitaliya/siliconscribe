# SiliconScribe: viva demo runbook (23 Nov 2026)

Everything here was checked against the real app. Where a number depends on the final evaluation it says so.

## The day before (22 Nov)
1. **After 05:30 IST** (free-quota reset), run the preflight with one tiny live call:
   ```
   cd ~/Kushal_Master/Projects/VLSI/ai-eda-playground/backend
   PATH="$HOME/.local/bin:$PATH" env -u OFFLINE_MODE LLM_PROVIDER=opencode-app \
     LLM_MODEL=deepseek-v4.1-flash-free LLM_TIMEOUT_SECONDS=360 python3 tools/preflight.py --live
   ```
   You want: no FAIL lines, "live model: READY", and the offline demo and saved results READY.
2. Open the OpenCode app once so you are signed in.
3. Do **not** run other long model jobs the same day (they share the free quota).
4. Pre-generate one good live result in the app (a counter or FIFO) so it is in the **Projects** drawer.
5. Laptop: charger in, notifications off, browser zoom 100%, window at least 1500 px wide, one browser tab.

## Start the app (two terminals)
```
# terminal 1: backend, live model
cd ~/Kushal_Master/Projects/VLSI/ai-eda-playground/backend
PATH="$HOME/.local/bin:$PATH" env -u OFFLINE_MODE LLM_PROVIDER=opencode-app \
  LLM_MODEL=deepseek-v4.1-flash-free LLM_TIMEOUT_SECONDS=360 python3 -m uvicorn main:app --host 127.0.0.1 --port 8000

# terminal 2: frontend
cd ~/Kushal_Master/Projects/VLSI/ai-eda-playground/frontend && npm run dev -- --host 127.0.0.1 --port 5173
```
Open http://127.0.0.1:5173. The top-right badge must say **Live · deepseek-v4.1-flash-free**. If it says *Offline demo* or *Demo fallback*, the live model is not in use.

## Demo flow (about 8 minutes)
1. **One sentence.** "SiliconScribe turns plain English into Verilog plus an independent self-checking testbench, runs both in a real simulator, and repairs failures. The simulator decides PASS or FAIL, never the model."
2. **Show a finished live result first** (Projects, Load): it appears instantly, so the audience sees the product before any waiting.
3. **Start a live run** (type the prompt, Generate). A live run takes about 2-11 minutes. Talk over the agent timeline: specification, RTL, testbench, simulation, synthesis, testbench strength. The clock under "Working…" proves it is not stuck.
4. **While it runs, tour the loaded result:**
   - *Test cases tab*: every executed check with its type; filter to a type; click a row.
   - *Waveform tab*: grouped signals, value at the cursor, radix, Expand.
   - *Results tab*: Yosys cell/flip-flop/latch counts and the **Testbench strength** card ("caught N of M injected bugs").
5. **Show a failure on purpose (instant, no model needed).** With a loaded counter in the editor, change the increment in the RTL (for example `count + 1'b1` to `count + 2'd2`) and press **Re-run**. It fails immediately: open **Test cases**, press *Failed*, click a row to see the differing bits, then open **Waveform** (the red flags mark the failed checks; `[` and `]` jump between them). Change the line back and **Re-run** again to return to PASS. This is a real simulation of your edit, not a recording.
   (Do **not** use the "buggy 4-bit counter" example chip with the live model: it is only scripted in offline mode, so with a live model it is just another prompt.)
6. **Close with limits** (see "Say this / never say this").

## If something goes wrong (fallback ladder)
| Problem | What to do | What to say |
|---|---|---|
| Live run is slow | Keep talking over the timeline; switch to the loaded result | "Free models can take minutes; the timer shows it is working." |
| Live run errors or quota is out | Projects, Load the saved result | "This is a saved live run from earlier." |
| Backend will not start with the live model | `OFFLINE_MODE=1` with the same uvicorn command (then the "buggy 4-bit counter" chip is scripted and shows a failure and a repair) | "This is the scripted offline demo; the badge says so." |
| Everything fails | Open `backend/evaluation/summary.md` and `artifacts/` | "These are the recorded live results." |

Never pretend an offline or saved result is a fresh live one. The app labels them, and so should you.

## Say this / never say this
**Say:** the simulator decides; PASS needs a validated summary and at least one executed check; the testbench is written from the specification, never from the RTL; the strength card measures whether the testbench could have caught bugs; the sandbox is defence in depth on a developer machine.

**Never say:** "proven correct" (PASS is evidence, not proof); "real area or timing" (Yosys without a technology file gives generic cell counts only); "UVM was simulated" (UVM is export-only); "secure sandbox or jail"; "two independent models" (one model writes both stages; the separate-model setting exists but the free models tried were not reliable).
