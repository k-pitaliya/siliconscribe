"""Per-check results parsed from the testbench transcript.

The testbench prints one machine-readable line per comparison::

    CHK|<PASS|FAIL>|<category>|<name>|<time>|<expected hex>|<actual hex>|<detail>

(see ``CHK_TASK`` in offline_designs.py for the Verilog task that prints it). This module
turns those lines into rows and exact per-category counters for the UI.

Important: these rows NEVER decide the verdict. PASS/FAIL still comes only from the
validated ``Passed:`` / ``Failed:`` summary (simulator._decide_verdict). A testbench could
print any CHK lines it likes, so they are treated as display data, size-capped, and
cross-checked against the summary (``checks_consistent``).
"""

import re
from typing import List

from models import CheckGroup, CheckResult

CHECK_PREFIX = "CHK|"
MAX_ROWS = 1000          # rows returned to the UI
MAX_FAIL_ROWS = 200      # every failure is kept first, up to this many
MAX_CATEGORIES = 12      # extra categories are folded into "other"
_SYNONYMS = {
    "rand": "random", "rnd": "random", "randomized": "random", "randomised": "random", "stress": "random",
    "constrained_random": "random",
    "edge": "corner", "corners": "corner", "boundary": "corner", "boundaries": "corner", "limit": "corner",
    "enable": "hold", "phase": "protocol", "exhaust": "exhaustive", "full": "exhaustive",
    "full_sweep": "exhaustive", "all_combinations": "exhaustive", "sweep": "exhaustive",
    "basic": "directed", "sanity": "directed", "smoke": "directed", "functional": "directed",
    "rst": "reset", "reset_behavior": "reset", "reset_behaviour": "reset", "power_up": "reset",
    "walking": "toggle", "walking_ones": "toggle", "walking_zeros": "toggle",
    "undefined": "invalid_input", "illegal": "invalid_input", "invalid": "invalid_input",
}
# "boundary_cases", "random_tests", "reset_checks" -> "boundary", "random", "reset": models pad the
# type with a generic word that would otherwise give every phrasing its own chip.
_GENERIC_SUFFIX_RE = re.compile(r"_(?:tests?|cases?|checks?|vectors?|phase)$")
_LEGACY_RE = re.compile(r"^[ \t]*FAIL\w*[ \t]*:?[ \t]*(.*)$", re.MULTILINE)
_KV_RE = re.compile(r"(\w+)=([^\s,;]+)")
_EXP_KEYS = ("expected", "exp", "golden", "want")
_ACT_KEYS = ("got", "actual", "result", "res")


def _category(raw: str, seen: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")[:24] or "other"
    stripped = _GENERIC_SUFFIX_RE.sub("", slug)
    if stripped:
        slug = stripped
    slug = _SYNONYMS.get(slug, slug)
    if slug not in seen and len(seen) >= MAX_CATEGORIES:
        slug = "other"
    seen.setdefault(slug, True)
    return slug


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n]


def parse_checks(log: str, pass_count: int, fail_count: int) -> dict:
    """Return the check-related SimulationResult fields for this transcript."""
    structured: List[tuple] = []
    seen: dict = {}
    for line in log.splitlines():
        if not line.startswith(CHECK_PREFIX):
            continue
        parts = line.split("|", 7)
        if len(parts) < 5 or parts[1] not in ("PASS", "FAIL"):
            continue  # malformed or forged: ignored, never an error
        t = int(parts[4]) if parts[4].strip().isdigit() else None
        structured.append((
            parts[1], _category(parts[2], seen), _clip(parts[3], 60), t,
            _clip(parts[5], 40) if len(parts) > 5 else None,
            _clip(parts[6], 40) if len(parts) > 6 else None,
            _clip(parts[7], 120) if len(parts) > 7 else "",
        ))

    if structured:
        groups: dict = {}
        for status, cat, *_ in structured:
            g = groups.setdefault(cat, [0, 0])
            g[0 if status == "PASS" else 1] += 1
        logged_pass = sum(g[0] for g in groups.values())
        logged_fail = sum(g[1] for g in groups.values())
        fail_rows_budget = MAX_FAIL_ROWS
        pass_rows_budget = MAX_ROWS - min(logged_fail, MAX_FAIL_ROWS)
        rows: List[CheckResult] = []
        for idx, (status, cat, name, t, exp, act, detail) in enumerate(structured, start=1):
            if status == "FAIL":
                if fail_rows_budget <= 0:
                    continue
                fail_rows_budget -= 1
            else:
                if pass_rows_budget <= 0:
                    continue
                pass_rows_budget -= 1
            rows.append(CheckResult(idx=idx, status=status, category=cat, name=name, t=t,
                                    expected=exp, actual=act, detail=detail, source="chk"))
        return {
            "checks": rows,
            "check_groups": [CheckGroup(category=c, total=p + f, passed=p, failed=f)
                             for c, (p, f) in groups.items()],
            "checks_source": "structured",
            "checks_total_logged": len(structured),
            "checks_truncated": len(rows) < len(structured),
            "checks_consistent": logged_pass == pass_count and logged_fail == fail_count,
        }

    # Fallback: a testbench that predates the CHK format. Only failures are visible.
    rows = []
    for m in _LEGACY_RE.finditer(log):
        if len(rows) >= MAX_FAIL_ROWS:
            break
        text = m.group(1).strip()
        kv = dict(_KV_RE.findall(text))
        exp = next((kv[k] for k in _EXP_KEYS if k in kv), None)
        act = next((kv[k] for k in _ACT_KEYS if k in kv), None)
        rows.append(CheckResult(idx=len(rows) + 1, status="FAIL", category="unclassified",
                                name=_clip(text, 60), expected=_clip(exp, 40) if exp else None,
                                actual=_clip(act, 40) if act else None, source="legacy_fail"))
    total = pass_count + fail_count
    if not rows and total == 0:
        return {"checks_source": "none"}
    return {
        "checks": rows,
        "check_groups": [CheckGroup(category="all checks (not logged individually)",
                                    total=total, passed=pass_count, failed=fail_count)],
        "checks_source": "legacy",
        "checks_total_logged": len(rows),
        "checks_truncated": False,
        "checks_consistent": True,
    }
