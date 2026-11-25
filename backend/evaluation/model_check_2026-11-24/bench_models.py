"""Benchmark every model in the app's menu on real SiliconScribe tasks, judged by Icarus (not by the model).

T1  generate_rtl(counter spec)          -> simulated with the 57-check reference testbench      -> PASS 57/57?
T2  generate_rtl(8-bit ALU, exact spec) -> simulated with the built-in ALU reference testbench   -> PASS?
T3  generate_testbench(counter)         -> must PASS the correct counter with >= 10 checks and FAIL two buggy ones
Uses the app's own prompts (llm_service.generate_rtl / generate_testbench). Run from backend/ with the live env.
Usage: python3 bench_models.py <model_ids.json> <report.json> <demo_files_dir>
"""
import json
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, ".")
import llm_service  # noqa: E402
import offline_designs as od  # noqa: E402
from models import RTLDesignSpec  # noqa: E402
from simulator import IcarusSimulator  # noqa: E402

import threading
ids = json.load(open(sys.argv[1]))
out = sys.argv[2]
demo = sys.argv[3].rstrip("/") + "/"
PHASE = sys.argv[4]                      # "A" = T1+T2 for every model, "B" = T3 for the models in the list
# OpenCode-app calls (opencode/ and openrouter/) share one local app and slow each other down: allow 2 at once.
LIMIT = {"opencode": threading.Semaphore(2), "cf": threading.Semaphore(4), "nim": threading.Semaphore(4)}
def family(mid):
    return "cf" if mid.startswith("@cf/") else "nim" if mid.startswith("nim/") else "opencode"
TB57 = open(demo + "counter_tb_57_checks.v").read()
GOOD = open(demo + "counter_rtl_correct.v").read()
HIDDEN = open(demo + "counter_rtl_hidden_enable_bug.v").read()
ADDS2 = od.get_design("counter")["rtl_buggy"]
COUNTER = RTLDesignSpec(**od.get_design("counter")["spec"])
ALU = od.get_design("alu8")
alu_spec = dict(ALU["spec"])
alu_spec["behavior"] = ("Combinational 8-bit ALU. opcode 3'b000: result = a + b, overflow = carry out (bit 8 of the 9-bit sum). "
                        "3'b001: result = a - b, overflow = borrow (bit 8 of the 9-bit difference, 1 when a < b). "
                        "3'b010: result = a & b. 3'b011: result = a | b. 3'b100: result = a ^ b. For AND, OR and XOR "
                        "overflow = 0. Any other opcode: result = 0 and overflow = 0.")
ALU_SPEC = RTLDesignSpec(**alu_spec)
sim = IcarusSimulator(workspace=tempfile.mkdtemp(prefix="bench_"))


def sid(mid, tag):
    return (re.sub(r"[^A-Za-z0-9_-]", "_", mid)[-24:] + "_" + tag)[-32:]


def run(mid, tag, rtl, tb):
    try:
        r = sim.simulate(sid(mid, tag), rtl, tb, timeout=30)
        return r.status, r.pass_count, r.test_count
    except Exception:
        return "ERROR", 0, 0


def timed(fn, *a, **k):
    t0 = time.time()
    try:
        return fn(*a, **k), None, round(time.time() - t0)
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}".replace("\n", " "), round(time.time() - t0)


def bench(mid):
    with LIMIT[family(mid)]:
        return bench_a(mid) if PHASE == "A" else bench_b(mid)


def bench_a(mid):
    res = {"model": mid}
    rtl, err, t = timed(llm_service.generate_rtl, COUNTER, None, model=mid)
    res["t1"] = {"time": t, "err": err, "sim": run(mid, "t1", rtl, TB57) if rtl else None}
    rtl, err, t = timed(llm_service.generate_rtl, ALU_SPEC, None, model=mid)
    res["t2"] = {"time": t, "err": err, "sim": run(mid, "t2", rtl, ALU["tb"]) if rtl else None}
    return res


def bench_b(mid):
    res = {"model": mid}
    tb, err, t = timed(llm_service.generate_testbench, GOOD, COUNTER, model=mid)
    t3 = {"time": t, "err": err}
    if tb:
        t3["good"] = run(mid, "t3g", GOOD, tb)
        t3["adds2"] = run(mid, "t3a", ADDS2, tb)
        t3["hidden"] = run(mid, "t3h", HIDDEN, tb)
    res["t3"] = t3
    return res


results = []
with ThreadPoolExecutor(max_workers=10) as ex:
    for f in as_completed([ex.submit(bench, m) for m in ids]):
        r = f.result()
        results.append(r)
        json.dump(results, open(out, "w"), indent=1)
        if PHASE == "A":
            a, b = r["t1"]["sim"], r["t2"]["sim"]
            print(f"{r['model']:58s} T1 {a[0] if a else 'ERR'} {r['t1']['time']}s  T2 {b[0] if b else 'ERR'} {r['t2']['time']}s", flush=True)
        else:
            t3 = r["t3"]
            print(f"{r['model']:58s} T3 {t3.get('time')}s good={t3.get('good')} adds2={t3.get('adds2')} hidden={t3.get('hidden')} {t3.get('err') or ''}", flush=True)
print("done", len(results))
