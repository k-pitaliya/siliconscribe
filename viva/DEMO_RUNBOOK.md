# SiliconScribe: viva demo runbook (25 Nov 2026)

Everything here was checked against the real app. Where a number depends on the final evaluation it says so.

**Code version:** the demo runs from branch `agent-debug` (it adds "Ask about this run", 24 Nov). Check with `git branch --show-current` in the repo before starting the servers.

## The day before (24 Nov)
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
6. Optional: tick **Review the specification before generating** to show the audience the specification the model wrote before it builds anything, and pick a second model under **Testbench written by** to show independent verification (it costs one extra model call and can make the run end FAIL if the two disagree: that is the feature working, say so).
7. Do not run `pip install -U` or `npm update` before the demo: the tested versions are the ones installed now.
8. Back up `backend/workspace/projects.db` (your saved live runs) to a USB stick or cloud folder.
9. Optional, free and offline (about 30 s): `PATH="$HOME/.local/bin:$PATH" python3 tools/verify_mapping.py`. Every design should say OK or REFUSED (with a reason); this is the evidence behind the timing numbers if you are asked.

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

For **Ask about this run** use a fast model: in the sidebar **Model** menu pick the **NVIDIA NIM** tab, then `nvidia/nemotron-3-ultra-550b-a55b` (it needs the NIM key that is already in `backend/.env`). It answered in 31-219 s on 24 Nov; DeepSeek through OpenCode also works but is slower. The chat uses whatever model is selected in this menu.

On the morning of the 25th: run the preflight **without** `--live` once more after starting both servers (it now checks that the running backend is live and can see the simulator), keep the Mac awake during long runs with `caffeinate -dims` in a third terminal, and if `npm run dev` says port 5173 is in use, stop the old server first (otherwise you would be looking at an old build). If the badge says **Server not reachable**, the backend is not running: start it and press Retry.

What looks different since the 19 Nov self-review: a PASS whose original testbench (or a fresh second-opinion testbench) still fails is shown as **PASS, disputed** in amber, which is intended, so explain it. The verdict card says "Checks", the attribution says "Design written by", and saved demo runs carry a **demo** label in Projects.

## Demo flow (about 8 minutes)
1. **One sentence.** "SiliconScribe turns plain English into Verilog plus an independent self-checking testbench, runs both in a real simulator, and repairs failures. The simulator decides PASS or FAIL, never the model."
2. **Show a finished live result first** (Projects, Load): it appears instantly, so the audience sees the product before any waiting.
3. **Start a live run** (type the prompt, Generate). A live run takes about 2-11 minutes. Talk over the run timeline in the sidebar: specification, RTL, testbench, simulation, synthesis, testbench strength, timing. The clock under "Working…" proves it is not stuck.
   Good moment for the Target clock slider: set 500 MHz before generating and show whether timing is met.
   Pick a clocked or plain combinational block (counter, ALU, FIFO, FSM, shift register). **Avoid gate-level latches and ring oscillators** (for example "SR latch"): with zero gate delay a testbench that releases the forbidden input on both pins at once oscillates forever at one simulated time and ends in TIMEOUT (viva Q26). If it happens anyway, it is a good teaching moment: the Results tab shows how many checks ran before the stop and names the likely cause.
4. **While it runs, tour the loaded result:**
   - *Results tab*: the verdict band, then four sections: **Testbench strength** ("caught N of M injected bugs"), **Timing and area** ("meets 100 MHz with +X ns slack", real area in µm² on sky130; a design with no clock, like the ALU, shows its longest input-to-output path instead), **Synthesis**, and **Toggle coverage (measured)**.
   - *Test cases tab*: every executed check with its type; filter to a type; click a row.
   - *Waveform tab*: grouped signals, value at the cursor, radix. Every tab is full height.
   - The theme switch (top right) follows the system; pick whichever reads best on the projector.
5. **Show a failure on purpose (instant, no model needed).** With a loaded counter in the editor, change the increment in the RTL (for example `count + 1'b1` to `count + 2'd2`) and press **Re-run**. It fails immediately: open **Test cases**, press *Failed*, click a row to see the differing bits, then open **Waveform** (the red flags mark the failed checks; `[` and `]` jump between them). Change the line back and **Re-run** again to return to PASS. This is a real simulation of your edit, not a recording.
   (Do **not** use the "buggy 4-bit counter" example chip with the live model: it is only scripted in offline mode, so with a live model it is just another prompt.)
6. **Ask the AI about a failure (new, 2-4 minutes, needs the live model).** Use the ready files in `viva/demo_files/`
   (open each in a text editor, Cmd+A, Cmd+C, then click into the app's editor tab, Cmd+A, Cmd+V):
   - **Design bug:** RTL tab = `counter_rtl_hidden_enable_bug.v`, Testbench tab = `counter_tb_57_checks.v`. In
     **Ask about this run** type *Some hold checks fail. Why?* (verified: FAIL 12/57 before the question). Expected on
     24 Nov: evidence steps (read the testbench, a cycle table, test a fix), "Suspect: Design", line 13
     `enable || count[0]`, and a fix card "the server re-simulated it, PASS (57 of 57 checks passed)". Click a time
     such as **@30ns**: the Waveform tab opens with the cursor where `enable=0` but `count` is already 2.
   - **Testbench bug (the strongest moment):** RTL = `counter_rtl_correct.v`, Testbench =
     `counter_tb_wrong_expectation.v` (FAIL 56/57). Ask *The last check fails. Is my counter wrong?* Expected:
     "Suspect: Testbench" (the check at 560 ns expects 3 before the third clock edge), and a testbench fix with the
     warning that it changes the checker. This took 219 s on 24 Nov, so start it and keep talking.
   - Say while it works: "It re-simulates the code on screen, then queries the waveform; every fix it proposes is
     simulated again by the server, and only that verdict is shown."
   - Do NOT use a saved counter project's own testbench for this: the older saved ones have 20 checks and never drop
     `enable`, so the hidden bug is not exposed (the agent then correctly says nothing failed).
   - If it is slow or the quota is out: show deck slides 14-15 (real runs from 24 Nov). If no model answers, the panel
     shows **Rule-based evidence (no AI)** (the first failing check, the signal values, the cycles before it): say that
     is the labelled fallback, not an AI answer.
7. **Close with limits** (see "Say this / never say this").

## If something goes wrong (fallback ladder)
| Problem | What to do | What to say |
|---|---|---|
| Live run is slow | Keep talking over the timeline; switch to the loaded result | "Free models can take minutes; the timer shows it is working." |
| The model stalls or says it could not be used | Pick another free model in the **Model** menu (for example `hy4-flash-free` or `beam-free`) and run again; Cloudflare is the second tab if it is set up | "Free models vary; the menu lists every one the OpenCode app offers." |
| Live run errors or quota is out | Projects, Load the saved result | "This is a saved live run from earlier." |
| Backend will not start with the live model | `cd backend && PATH="$HOME/.local/bin:$PATH" OFFLINE_MODE=1 python3 -m uvicorn main:app --host 127.0.0.1 --port 8000` (do NOT keep `env -u OFFLINE_MODE` in front, it would undo the setting) (then the "buggy 4-bit counter" chip is scripted and shows a failure and a repair) | "This is the scripted offline demo; the badge says so." |
| Ask about this run is slow | Keep talking; it shows each evidence step as it happens. After 5 minutes press Stop | "Each step is a model call on a free model; the answer will rest on these steps." |
| Ask about this run fails | The panel shows labelled rule-based evidence; or show deck slides 14-15 | "No AI answered, so it shows evidence collected by fixed rules, and says so." |
| Everything fails | Open `backend/evaluation/summary.md` and `artifacts/` | "These are the recorded live results." |

Never pretend an offline or saved result is a fresh live one. The app labels them, and so should you.

## Say this / never say this
**Say:** the simulator decides; the agent's fix is re-simulated by the server, its explanation is model text; PASS needs a validated summary and at least one executed check; the testbench is written from the specification, never from the RTL; the strength card measures whether the testbench could have caught bugs; the sandbox is defence in depth on a developer machine.

**Never say:** "proven correct" (PASS is evidence, not proof); "the AI's explanation is verified" (only its fix is: the SR-latch fix passed 558/558 with a partly wrong explanation); "sign-off timing" or "silicon area" (the timing and area are a pre-layout estimate on one sky130 corner: no wire delay, ideal clock, setup only); "UVM was simulated" (UVM is export-only); "secure sandbox or jail"; "two independent models" (one model writes both stages; the separate-model setting exists but the free models tried were not reliable).
