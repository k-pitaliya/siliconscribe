"""
Lightweight functional coverage.

This is honestly-scoped: it is NOT synthesis toggle/line coverage (which would
need instrumentation). It summarizes what the self-checking testbench exercised:
  - number of test vectors run (pass + fail)
  - pass rate
  - any explicit coverage bins the TB printed as "COV: <bin> <count>"
"""

import re
from models import SimulationResult


def compute_coverage(result: SimulationResult, log: str = "") -> dict:
    log = log or result.log_excerpt or ""
    total = result.test_count or (result.pass_count + result.fail_count)
    pass_rate = round(100.0 * result.pass_count / total, 1) if total else 0.0

    bins: dict[str, int] = {}
    for m in re.finditer(r"COV:\s*(\w+)\s+(\d+)", log):
        bins[m.group(1)] = int(m.group(2))

    cov = {
        "test_vectors": total,
        "passed": result.pass_count,
        "failed": result.fail_count,
        "pass_rate": pass_rate,
    }
    if bins:
        cov["bins"] = bins
    return cov
