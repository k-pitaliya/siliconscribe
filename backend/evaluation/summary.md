# Live evaluation

Provider/model: opencode-app / deepseek-v4.1-flash-free
Testbench model: same as design

- Prompts run: **14** (0 fell back to the offline demo and are not counted)
- No result yet for: **s1** (not run, or the model did not answer in time on every attempt; never counted as a pass or as a design failure)
- PASS on the first attempt: **8** of 14
- PASS after self-repair: **6** of 14
- Not PASS: **0** of 14
- Median time per run: **360 s**

| id | type | verdict | repairs | checks | strength | toggle | max MHz | area um2 | time | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| c1 | combinational | PASS | 1 | 823/823 | 10/12 | 100% | 2808.2 | 58.806 | 675 s | testbench changed during repair; 2 bug(s) missed |
| c2 | combinational | PASS | 1 | 308/308 | 1/1 | 100% | 8382.2 | 26.275 | 185 s | testbench changed during repair |
| c3 | combinational | PASS | 0 | 747/747 | 12/12 | 100% | 675.2 | 110.106 | 275 s |  |
| c4 | combinational | PASS | 0 | 907/907 | 6/6 | 100% | 1592.6 | 205.197 | 232 s |  |
| c5 | combinational | PASS | 0 | 484/484 | 12/12 | 100% | 5399.6 | 77.574 | 202 s |  |
| c6 | combinational | PASS | 1 | 2216/2216 | 3/3 | 100% | 2252.3 | 95.091 | 408 s | testbench changed during repair |
| c7 | combinational | PASS | 0 | 6909/6909 | 9/12 | 100% | 817.9 | 336.573 | 224 s | 3 bug(s) missed |
| s2 | sequential | PASS | 0 | 2427/2427 | 9/9 | 100% | 499.1 | 490.47 | 266 s |  |
| s3 | sequential | PASS | 0 | 2313/2313 | 5/5 | 100% | 1329.1 | 212.704 | 408 s |  |
| s4 | sequential | PASS | 1 | 2518/2518 | 3/3 | 100% | 2042.9 | 210.202 | 462 s | testbench changed during repair |
| s5 | sequential | PASS | 0 | 275/275 | 7/7 | 100% | 1567.9 | 62.56 | 332 s |  |
| s6 | sequential | PASS | 0 | 2610/2610 | 12/12 | 100% | 542.1 | 1830.51 | 388 s |  |
| f1 | fsm | PASS | 1 | 1287/1287 | 6/6 | 100% | 1354.6 | 163.907 | 791 s | testbench changed during repair |
| f2 | fsm | PASS | 1 | 3797/3797 | 7/11 | 85% | 800.6 | 466.698 | 661 s | testbench changed during repair; 4 bug(s) missed |

Strength = injected bugs caught / injected bugs run (mutation testing of the design's own testbench; survivors may be equivalent mutants). Toggle = measured toggle coverage of design signals. Max MHz and area = pre-layout estimate on sky130 (typical corner, no wire delay, not sign-off). Raw records: `evaluation/results.jsonl`; designs and testbenches: `evaluation/artifacts/`.
