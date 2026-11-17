# Live evaluation

Provider/model: opencode-app / deepseek-v4.1-flash-free
Testbench model: same as design

- Prompts run: **7** (0 fell back to the offline demo and are not counted)
- PASS on the first attempt: **4** of 7
- PASS after self-repair: **3** of 7
- Not PASS: **0** of 7
- Median time per run: **232 s**

| id | type | verdict | repairs | checks | strength | time | notes |
|---|---|---|---|---|---|---|---|
| c1 | combinational | PASS | 1 | 823/823 | 10/12 | 675 s | weak-evidence warning; 2 bug(s) missed |
| c2 | combinational | PASS | 1 | 308/308 | 1/1 | 185 s | weak-evidence warning |
| c3 | combinational | PASS | 0 | 747/747 | 12/12 | 275 s |  |
| c4 | combinational | PASS | 0 | 907/907 | 6/6 | 232 s |  |
| c5 | combinational | PASS | 0 | 484/484 | 12/12 | 202 s |  |
| c6 | combinational | PASS | 1 | 2216/2216 | 3/3 | 408 s | weak-evidence warning |
| c7 | combinational | PASS | 0 | 6909/6909 | 9/12 | 224 s | 3 bug(s) missed |

Strength = injected bugs caught / injected bugs run (mutation testing of the design's own testbench; survivors may be equivalent mutants). Raw records: `evaluation/results.jsonl`; designs and testbenches: `evaluation/artifacts/`.
