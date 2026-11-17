# Viva questions and honest answers

`[EVAL]` = fill in from `backend/evaluation/summary.md` once the live evaluation has finished.

**1. Why should anyone trust a PASS?**
The simulator, not the model, decides. A PASS needs a whole-line `Passed: N` / `Failed: 0` summary with N above zero, no `FAIL` or `ERROR` line contradicting it, and a clean simulator exit. The design under test is not allowed to print the summary or end the run, so it cannot write its own verdict. Zero executed checks is never a PASS. It is still *evidence*, not a proof.

**2. Who checks the checker?** (the strongest question to expect)
After a PASS the app injects up to 12 small bugs into the design (`+` to `-`, `&` to `|`, `==` to `!=`, a flipped constant or case label, a negated `if`, ...) and reruns the same testbench on each one. The card shows "caught N of M". On the five built-in designs the testbenches catch every injected bug except two that are provably equivalent (for example replacing the XOR in a full adder's carry term by OR gives the majority function). A deliberately weak testbench scores below half and triggers a warning. *Limit:* a survivor may be an equivalent mutant, so the score is evidence about the testbench, not a proof.

**3. Does one model write both the design and the testbench?**
Yes, in the live demo. The testbench is generated from the specification only, never from the RTL, and the repair loop is forbidden from weakening it. A different model for the testbench is a supported setting, and I tried it: on a counter whose correctness I knew, the free models either timed out, produced a testbench that never connected the design (it was reported as FAIL, not a false PASS) or did not compile. So independence is supported but not reliable on the free tier.

**4. What stops the repair loop from cheating by deleting checks?**
A minimum count of real check sites in the testbench, a check that it still instantiates the design, validation of the model's replacement design and testbench, and, after a repair, a re-run of the original testbench on the final design with an explicit warning if it still fails.

**5. Is this safe to run on untrusted input?**
It is defence in depth on a developer machine, not a jail. System tasks are an allow-list (file and process access is rejected before compile and before lint), the environment is scrubbed so API keys never reach the simulator, CPU, file-size and memory limits apply (the memory limit is enforced on Linux, not macOS), and at most two simulations run at once. For multi-user use the simulator belongs in a container.

**6. Does it give area, timing or power?**
No. Yosys runs without a technology library, so it reports generic cell counts, flip-flop and latch counts and a warning when a latch is inferred. The "area" figure is labelled a relative proxy. Real timing would need a liberty file and a timing tool such as OpenSTA, which is future work.

**7. Why Icarus Verilog? What about UVM?**
It is free and scriptable. Icarus 12.0 accepts most synthesizable SystemVerilog (`logic`, `always_ff`, `return`, `enum`) and rejects a specific set (`break`/`continue`, `disable` of a function, `inside`, streaming operators, concurrent assertions, class constraints). UVM needs the UVM class library, which Icarus does not implement, so UVM is export-only and never simulated.

**8. Is the coverage real coverage?**
No. It is testbench-reported (pass rate and bins the testbench prints). Instrumented line and toggle coverage would need a tool like Verilator, which is future work. The Test cases tab shows the executed checks by type, which is a different and honest measure.

**9. What did your evaluation show?**
`[EVAL]` prompts across combinational, sequential and FSM designs with the free DeepSeek model: PASS on the first attempt `[N]`, PASS after repair `[N]`, not PASS `[N]`, median time `[N s]`, and the testbench-strength scores. Runs that fell back to the offline demo are excluded. The raw records are in `backend/evaluation/`.

**10. How is this different from AutoBench, CorrectBench or VerilogEval?**
AutoBench and CorrectBench generate (and in CorrectBench self-correct) testbenches for HDL designs; VerilogEval is a benchmark of design generation against golden references. SiliconScribe is an end-to-end tool on a single open-source simulator that generates the testbench independently from the specification, forbids the repair loop from weakening it, reports every executed check, and measures the testbench's strength by mutation. It does not reproduce their evaluation protocols, so I make no performance comparison.

**11. What happens when the model or the network fails?**
The app says so. Before any live call has succeeded it may fall back to a scripted demo, but that is labelled "Demo fallback". After a live success, a later outage fails loudly instead of swapping in an unrelated design.

**12. Why do live runs take minutes?**
Free-tier models are slow: generating the testbench alone has taken 2-3 minutes, and one evaluation run took 11 minutes. The UI shows seconds since the last update so slow looks different from stuck. A paid or local model would be much faster.

**13. Is the interface accessible?**
An automated axe-core audit of every tab, for a passing and a failing run, reports zero violations (structure, names, heading order and colour contrast), and the structural rules run in the test suite. That is an automated audit, not a user study.

**14. What are the main limitations?**
One model for both stages; free-tier speed and quota; the strength score is a sample of 12 syntactic mutants; no timing or power; testbench-reported coverage; sandbox is not a jail; evaluated on small designs, not full SoC blocks.

**15. What would you do next?**
A stronger or local second model for the testbench, Verilator coverage, OpenSTA timing with a technology library, a golden reference model check, and container isolation with a job queue for multi-user deployment.
