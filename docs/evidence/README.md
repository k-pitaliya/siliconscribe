# Live-run evidence

Captured on 6 November 2026 from the running SiliconScribe backend with Icarus
Verilog 12.0, using the OpenRouter model
`nvidia/nemotron-3-ultra-550b-a55b:free`. No API key or secret is stored here.

| File | Evidence |
|------|----------|
| `live_priority_result.json` | Full API response for the live headless 8-to-3 priority-encoder run: **PASS, 116/116 checks, 0 iterations, no fallback**. |
| `livepriority08_design.sv` | Exact RTL generated in that workspace. |
| `livepriority08_testbench.sv` | Exact independent, specification-derived testbench used to check it. |
| `livepriority08_transcript.log` | Icarus simulator transcript (`Passed: 116`, `Failed: 0`, `ALL TESTS PASSED`). |
| `live_seeded_repair.json` | Live fault-injection run on a seeded counter bug: **1/20 FAIL → 20/20 PASS**, including the structured `symptom`, `root_cause`, `fix_location`, and `confidence` returned by the fixer. |

The in-browser live run shown in `docs/screenshots/03_live_pass_results.png`
produced **105/105 checks, PASS, 0 iterations, and no degraded-mode banner** for
the same priority-encoder prompt; the generated random loop bound differs slightly
between runs. Screenshots and the final report are in the parent directory.
