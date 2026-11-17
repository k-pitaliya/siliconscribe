# Live evaluation

Provider/model: opencode-app / deepseek-v4.1-flash-free
Testbench model: same as design

- Prompts run: **7** (0 fell back to the offline demo and are not counted)
- PASS on the first attempt: **4** of 7
- PASS after self-repair: **3** of 7
- Not PASS: **0** of 7
- Median time per run: **232 s**

| id | type | verdict | repairs | checks | strength | toggle | max MHz | area um2 | time | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| c1 | combinational | PASS | 1 | 823/823 | 10/12 | 100% | 2777.8 | 58.806 | 675 s | testbench changed during repair; 2 bug(s) missed |
| c2 | combinational | PASS | 1 | 308/308 | 1/1 | 100% | 8333.3 | 26.275 | 185 s | testbench changed during repair |
| c3 | combinational | PASS | 0 | 747/747 | 12/12 | 100% | 675.7 | 110.106 | 275 s |  |
| c4 | combinational | PASS | 0 | 907/907 | 6/6 | 100% | 1587.3 | 205.197 | 232 s |  |
| c5 | combinational | PASS | 0 | 484/484 | 12/12 | 100% | 5263.2 | 77.574 | 202 s |  |
| c6 | combinational | PASS | 1 | 2216/2216 | 3/3 | 100% | 2272.7 | 95.091 | 408 s | testbench changed during repair |
| c7 | combinational | PASS | 0 | 6909/6909 | 9/12 | 100% | 819.7 | 336.573 | 224 s | 3 bug(s) missed |

Strength = injected bugs caught / injected bugs run (mutation testing of the design's own testbench; survivors may be equivalent mutants). Toggle = measured toggle coverage of design signals. Max MHz and area = pre-layout estimate on sky130 (typical corner, no wire delay, not sign-off). Raw records: `evaluation/results.jsonl`; designs and testbenches: `evaluation/artifacts/`.
