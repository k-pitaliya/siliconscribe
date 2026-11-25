"""Send every model in the app's menu one tiny message through the app's own provider code (llm_service).

Run from backend/ with the live environment. Prints one line per model and a summary; writes a JSON report.
Usage: python3 probe_models.py <model_ids.json> <report.json>
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, ".")
import llm_service  # noqa: E402

ids = json.load(open(sys.argv[1]))
out = sys.argv[2]


def probe(mid):
    t0 = time.time()
    try:
        prov = llm_service.get_provider(mid)
        txt = prov._chat(None, "Reply with exactly the word OK and nothing else.", 0.0, model=mid, stage="probe")
        ok = "ok" in txt.strip().lower()[:40]
        return mid, ("OK" if ok else "ODD"), round(time.time() - t0, 1), txt.strip()[:60].replace("\n", " ")
    except Exception as e:  # report every failure kind as text
        return mid, "FAIL", round(time.time() - t0, 1), f"{type(e).__name__}: {str(e)[:160]}".replace("\n", " ")


results = []
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = [ex.submit(probe, m) for m in ids]
    for f in as_completed(futs):
        r = f.result()
        results.append(r)
        print(f"{r[1]:4s} {r[2]:6.1f}s  {r[0]:60s} {r[3]}", flush=True)

json.dump(results, open(out, "w"), indent=1)
by = {}
for mid, st, *_ in results:
    by.setdefault(st, []).append(mid)
print("\nSUMMARY:", {k: len(v) for k, v in by.items()}, "of", len(results))
