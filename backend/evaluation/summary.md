# Live evaluation

Provider/model: opencode-app / deepseek-v4.1-flash-free
Testbench model: same as design

- Prompts run: **14** (0 fell back to the offline demo and are not counted)
- No result yet for: **s1** (not run, or the model did not answer in time on every attempt; never counted as a pass or as a design failure)
- PASS on the first attempt: **8** of 14
- PASS after self-repair: **6** of 14
- Not PASS: **0** of 14
- Median time per run: **360 s**

| id | type | verdict | repairs | checks | strength | toggle | timing | area um2 | time | notes |
|---|---|---|---|---|---|---|---|---|---|---|
| c1 | combinational | PASS | 1 | 823/823 | 10/12 | 100% | path 0.36 ns | 58.806 | 675 s | testbench changed during repair; 2 bug(s) missed |
| c2 | combinational | PASS | 1 | 308/308 | 1/1 | 100% | path 0.12 ns | 26.275 | 185 s | testbench changed during repair |
| c3 | combinational | PASS | 0 | 747/747 | 12/12 | 100% | path 1.48 ns | 110.106 | 275 s |  |
| c4 | combinational | PASS | 0 | 907/907 | 6/6 | 100% | path 0.63 ns | 205.197 | 232 s |  |
| c5 | combinational | PASS | 0 | 484/484 | 12/12 | 100% | path 0.18 ns | 77.574 | 202 s |  |
| c6 | combinational | PASS | 1 | 2216/2216 | 3/3 | 100% | path 0.44 ns | 95.091 | 408 s | testbench changed during repair |
| c7 | combinational | PASS | 0 | 6909/6909 | 9/12 | 100% | path 1.22 ns | 336.573 | 224 s | 3 bug(s) missed |
| s2 | sequential | PASS | 0 | 2427/2427 | 9/9 | 100% | min period 2.00 ns | 490.47 | 266 s |  |
| s3 | sequential | PASS | 0 | 2313/2313 | 5/5 | 100% | min period 0.75 ns | 212.704 | 408 s |  |
| s4 | sequential | PASS | 1 | 2518/2518 | 3/3 | 100% | min period 0.49 ns | 210.202 | 462 s | testbench changed during repair |
| s5 | sequential | PASS | 0 | 275/275 | 7/7 | 100% | min period 0.64 ns | 62.56 | 332 s |  |
| s6 | sequential | PASS | 0 | 2610/2610 | 12/12 | 100% | min period 1.84 ns | 1830.51 | 388 s |  |
| f1 | fsm | PASS | 1 | 1287/1287 | 6/6 | 100% | min period 0.74 ns | 163.907 | 791 s | testbench changed during repair |
| f2 | fsm | PASS | 1 | 3797/3797 | 7/11 | 85% | min period 1.25 ns | 466.698 | 661 s | testbench changed during repair; 4 bug(s) missed |

Strength = injected bugs caught / injected bugs run (mutation testing of the design's own testbench; survivors may be equivalent mutants). Toggle = measured toggle coverage of design signals. Timing = shortest clock period for a design with a clock, longest input-to-output path for one without (a combinational block has no clock rate), and area = pre-layout estimate on sky130 (typical corner, no wire delay, not sign-off). Raw records: `evaluation/results.jsonl`; designs and testbenches: `evaluation/artifacts/`.
