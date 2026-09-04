"""
Lightweight functional coverage.

This is honestly-scoped: it is NOT synthesis toggle/line coverage (which would
need instrumentation). It summarizes what the self-checking testbench exercised:
  - number of test vectors run (pass + fail)
  - pass rate
  - any explicit coverage bins the TB printed as "COV: <bin> <count>"
  - optional Toggle/Branch/Line/Functional coverage if the TB prints it
    (e.g. "Toggle coverage: 85%" or "Branch coverage = 72.5%")

Backward compatible: existing keys (test_vectors, passed, failed, pass_rate,
bins) are always present; new keys are only added when the log contains them.
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

    # --- Extended coverage parsing (toggle / branch / line / functional) ---
    # Accepts variants:
    #   "Toggle coverage: 85%"      "Toggle coverage 85"   "Toggle coverage=85.5 %"
    #   "Branch coverage: 72%" etc.  Case-insensitive.
    # Only adds the key when a match is found to keep backward compat.
    for label, key in [
        ("Toggle", "toggle_coverage"),
        ("Branch", "branch_coverage"),
        ("Line", "line_coverage"),
        ("Functional", "functional_coverage"),
        ("Statement", "statement_coverage"),
        ("Block", "block_coverage"),
    ]:
        # Use word boundary and allow optional colon/equals and percent sign
        pat = rf"{label}\s+coverage\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%?"
        m = re.search(pat, log, re.IGNORECASE)
        if m:
            try:
                cov[key] = float(m.group(1))
                # Keep integer-looking values as int-like float? Always float for consistency
                # but round to 1 decimal if needed
                if cov[key].is_integer():
                    # preserve as float to indicate percentage; callers can handle either
                    pass
            except ValueError:
                pass

    # Generic fallback: if TB prints "Coverage: 90%" without qualifier, surface as functional_coverage
    # Only if no more specific coverage was found to avoid overwriting.
    if "functional_coverage" not in cov and "toggle_coverage" not in cov and "branch_coverage" not in cov:
        m = re.search(r"(?:^|\n)\s*Coverage\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%", log, re.IGNORECASE)
        if m:
            try:
                cov["functional_coverage"] = float(m.group(1))
            except ValueError:
                pass

    return cov
