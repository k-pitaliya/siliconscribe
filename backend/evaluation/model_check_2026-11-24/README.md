# Model check, 24 November 2026

Every model in the app's menu was tested through the app's own provider code (`llm_service`), and every answer was
judged by Icarus Verilog, not by the model. One attempt per model and task, no repair loop, free tiers only.

| Step | File | Result |
|---|---|---|
| One-message probe ("Reply with exactly the word OK") of all 69 menu models | `probe_69_models.json` | 40 answered; 28 failed and 1 is not a chat model (these 29 are hidden by `backend/model_hidden.json`) |
| T1 counter RTL (judged by the 57-check reference testbench) and T2 8-bit ALU RTL (judged by the 1222-check reference testbench), the 40 working models | `rtl_tasks_40_models.json` | 18 wrote both correctly |
| T3 testbench for the counter: must PASS the correct counter with at least 10 checks and FAIL two buggy counters (adds 2; hidden `enable \|\| count[0]`), the 18 models that passed T1 and T2, 600 s limit | `testbench_task_18_models.json` | 1 passed: `opencode/deepseek-v4.1-flash-free` (173/173, caught both bugs, 148 s) |

Scripts: `probe_models.py` (the probe) and `bench_models.py` (phase `A` = T1 + T2, phase `B` = T3). Run from `backend/`
with the live environment; the task inputs are the files in `viva/demo_files/` and the built-in designs.

Caveats: a single run per model; OpenRouter's free daily allowance ran out during the test, so its models were not
really tested on T3; the first T3 attempt hit a race in the app (fixed in commit `dd84377`) and was repeated for the
eight Cloudflare / NVIDIA models. The app's repair loop was not used, so this measures first-try quality only.
