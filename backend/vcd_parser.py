"""
VCD (Value Change Dump) parser.

Turns an Icarus-produced .vcd into a compact JSON-friendly structure the frontend waveform
viewer renders directly:

    {
      "timescale": "1ps", "timescale_ps": 1.0, "end_time": 200000,
      "signals": [
        {"name": "clk", "width": 1, "role": "clock", "path": "testbench.clk",
         "wave": [{"t": 0, "v": "0"}, {"t": 5000, "v": "1"}, ...]},
        {"name": "count", "width": 4, "role": "out", "wave": [{"t": 0, "v": "x"}, ...]},
        ...
      ]
    }

Bus values are hex strings: each hex digit is one nibble, and a nibble containing an unknown
bit is shown as ``x`` (or ``z``), so ``1010xxxx`` becomes ``ax`` instead of collapsing the whole
bus to ``x``. Single bits stay '0'/'1'/'x'/'z'.

Signals are tagged with a ``role`` (clock, reset, DUT input/output, internal, testbench
bookkeeping, task-local, parameter) and ranked by it BEFORE the signal cap is applied, so a
testbench's loop counters and task locals can never push the design's own signals out.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from models import ToggleCoverage, UntoggledSignal, Waveform, WaveformSignal

# Hard cap so a runaway TB can't produce a multi-megabyte payload.
MAX_SIGNALS = 40
MAX_CHANGES_PER_SIGNAL = 2000
# Hard byte cap: read at most this much of a VCD. Without it, a runaway
# testbench could make read_text() allocate hundreds of MB before the
# per-signal caps ever apply.
MAX_VCD_BYTES = 8 * 1024 * 1024

_UNIT_PS = {"fs": 1e-3, "ps": 1.0, "ns": 1e3, "us": 1e6, "ms": 1e9, "s": 1e12}
_CLOCK_RE = re.compile(r"(?i)^(clk|clock)\w*$")
_RESET_RE = re.compile(r"(?i)^(rst|reset)\w*$")
_TB_NAMES = {"pass_count", "fail_count", "expected", "exp", "exp_ovf", "wide", "label", "opn",
             "gray", "cv", "i", "j", "k", "s", "op", "ia", "ib", "idx"}
_RANK = {"clock": 0, "reset": 1, "in": 2, "out": 3, "io": 3, "dut_internal": 4,
         "internal": 5, "tb": 6, "aux": 7, "param": 8}
_HEADER_TOKEN_RE = re.compile(
    r"\$scope\s+(\w+)\s+(\S+)\s+\$end"
    r"|\$(upscope)\s+\$end"
    r"|\$var\s+(\w+)\s+(\d+)\s+(\S+)\s+([^\s$]+(?:\s*\[[^\]]*\])?)\s+\$end"
)


def _bin_to_hex(bits: str) -> str:
    """Convert a binary string (possibly with x/z) to a compact hex string, nibble by nibble."""
    bits = bits.strip().lower()
    if not bits:
        return "0"
    if set(bits) == {"x"}:
        return "x"
    if set(bits) == {"z"}:
        return "z"
    if not set(bits) <= set("01xz"):
        return bits
    bits = bits.zfill((len(bits) + 3) // 4 * 4)
    out = []
    for i in range(0, len(bits), 4):
        nib = bits[i:i + 4]
        if "x" in nib:
            out.append("x")
        elif "z" in nib:
            out.append("z")
        else:
            out.append(format(int(nib, 2), "x"))
    h = "".join(out).lstrip("0")
    return h or "0"


def _role(sig: dict, ports: Optional[Dict[str, str]]) -> str:
    name, depth = sig["name"], sig["depth"]
    if sig["var_type"] in ("parameter", "localparam"):
        return "param"
    if sig["scope_kind"] in ("task", "function", "begin", "fork"):
        return "aux"
    if _CLOCK_RE.match(name):
        return "clock"
    if _RESET_RE.match(name):
        return "reset"
    direction = (ports or {}).get(name)
    if direction in ("input", "output", "inout") and depth <= 2:
        return {"input": "in", "output": "out", "inout": "io"}[direction]
    if depth >= 2:
        return "dut_internal"
    if sig["var_type"] in ("integer", "real", "realtime", "time", "event") or name in _TB_NAMES:
        return "tb"
    return "tb" if ports else "internal"


_NON_NET_TYPES = {"parameter", "localparam", "integer", "real", "realtime", "time", "event", "string"}


def _parse_header(header: str) -> Dict[str, dict]:
    """Walk $scope / $upscope / $var in order so every signal knows where it lives."""
    code_to_sig: Dict[str, dict] = {}
    scopes: List[tuple] = []
    for m in _HEADER_TOKEN_RE.finditer(header):
        if m.group(1):
            scopes.append((m.group(1), m.group(2)))
        elif m.group(3):
            if scopes:
                scopes.pop()
        else:
            code = m.group(6)
            raw = m.group(7).strip()
            name = re.sub(r"\s*\[\d+:\d+\]\s*$", "", raw)   # width is stored separately
            scope_kind, scope_name = scopes[-1] if scopes else ("module", "")
            # A net inside an instantiated module (below the testbench top) belongs to the design.
            # The simulator gives a DUT port and the testbench wire tied to it the SAME code, so
            # remember design membership even when the code was first seen at testbench level.
            in_design = len(scopes) >= 2 and scope_kind == "module" and m.group(4) not in _NON_NET_TYPES
            if code in code_to_sig:      # alias of a signal we already have
                if in_design and not code_to_sig[code]["design_name"]:
                    code_to_sig[code]["design_name"] = name
                continue
            rng = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*$", raw)
            code_to_sig[code] = {
                "design_name": name if in_design else None,
                "name": name, "width": int(m.group(5)), "wave": [], "var_type": m.group(4),
                "scope": scope_name, "scope_kind": scope_kind, "depth": len(scopes),
                "path": ".".join(n for _, n in scopes) + ("." if scopes else "") + name,
                "msb": int(rng.group(1)) if rng else None, "lsb": int(rng.group(2)) if rng else None,
                "truncated_at": None,
            }
    return code_to_sig


# ----------------------------------------------------------------------------- toggle coverage
MAX_UNTOGGLED_LISTED = 12


def _pad_bits(bits: str, width: int) -> str:
    """VCD drops leading bits: pad with 0, or with x/z when the value starts with x/z."""
    bits = bits.lower()
    if len(bits) >= width:
        return bits[-width:]
    fill = bits[0] if bits and bits[0] in "xz" else "0"
    return fill * (width - len(bits)) + bits


def toggle_coverage(vcd_path: str | Path) -> Optional[ToggleCoverage]:
    """Measure toggle coverage of the design under test from a VCD file.

    A bit is covered when the simulator recorded it going 0 -> 1 AND 1 -> 0 (direct transitions;
    a change through x or z does not count). Only nets inside an instantiated module (the design
    hierarchy under the testbench) are counted, so testbench bookkeeping cannot inflate the
    number. Returns None when the file is missing or contains no design signals.
    """
    path = Path(vcd_path)
    if not path.exists():
        return None
    partial = path.stat().st_size > MAX_VCD_BYTES
    with path.open("r", errors="ignore") as fh:
        text = fh.read(MAX_VCD_BYTES)
    body_start = text.find("$enddefinitions")
    if body_start == -1:
        return None
    sigs = _parse_header(text[:body_start])
    # Design signals: nets with a declaration inside an instantiated module (see _parse_header).
    design = {code: s for code, s in sigs.items() if s["design_name"] and 0 < s["width"] <= 4096}
    if not design:
        return None
    state = {code: {"last": None, "rose": [False] * s["width"], "fell": [False] * s["width"]}
             for code, s in design.items()}

    def change(code: str, bits: str) -> None:
        st = state.get(code)
        if st is None:
            return
        width = design[code]["width"]
        new = _pad_bits(bits, width)
        old = st["last"]
        if old is not None and old != new:
            rose, fell = st["rose"], st["fell"]
            for i in range(width):
                o, n = old[i], new[i]
                if o == "0" and n == "1":
                    rose[width - 1 - i] = True          # index = bit position, 0 = LSB
                elif o == "1" and n == "0":
                    fell[width - 1 - i] = True
        st["last"] = new

    for raw in text[body_start:].splitlines():
        line = raw.strip()
        if not line or line[0] in "#$":
            continue
        if line[0] in "01xXzZ":
            change(line[1:], line[0])
        elif line[0] in "bB":
            parts = line[1:].split()
            if len(parts) == 2:
                change(parts[1], parts[0])

    bits_total = bits_toggled = 0
    untoggled: List[UntoggledSignal] = []
    for code, s in design.items():
        st = state[code]
        width = s["width"]
        bits_total += width
        never_rose = [i for i in range(width) if not st["rose"][i]]
        never_fell = [i for i in range(width) if not st["fell"][i]]
        bits_toggled += sum(1 for i in range(width) if st["rose"][i] and st["fell"][i])
        if never_rose or never_fell:
            untoggled.append(UntoggledSignal(signal=s["design_name"], width=width,
                                             never_rose=never_rose[:64], never_fell=never_fell[:64]))
    untoggled.sort(key=lambda u: -(len(set(u.never_rose) | set(u.never_fell))))
    return ToggleCoverage(
        percent=round(100.0 * bits_toggled / bits_total, 1) if bits_total else 0.0,
        bits_total=bits_total, bits_toggled=bits_toggled, signals=len(design),
        untoggled=untoggled[:MAX_UNTOGGLED_LISTED],
        untoggled_more=max(0, len(untoggled) - MAX_UNTOGGLED_LISTED),
        partial=partial,
    )


def parse_vcd(vcd_path: str | Path, max_signals: int = MAX_SIGNALS,
              ports: Optional[Dict[str, str]] = None) -> Optional[Waveform]:
    path = Path(vcd_path)
    if not path.exists():
        return None

    file_size = path.stat().st_size
    file_truncated = file_size > MAX_VCD_BYTES
    with path.open("r", errors="ignore") as fh:
        text = fh.read(MAX_VCD_BYTES)

    timescale = "1ns"
    timescale_ps: Optional[float] = None
    ts_match = re.search(r"\$timescale\s+(.*?)\s+\$end", text, re.DOTALL)
    if ts_match:
        timescale = ts_match.group(1).strip()
        um = re.fullmatch(r"(\d+)\s*(fs|ps|ns|us|ms|s)", timescale)
        if um:
            timescale_ps = int(um.group(1)) * _UNIT_PS[um.group(2)]
    body_start = text.find("$enddefinitions")
    header = text[:body_start] if body_start != -1 else text

    code_to_sig = _parse_header(header)

    if not code_to_sig:
        return Waveform(timescale=timescale, timescale_ps=timescale_ps, end_time=0, signals=[])

    # The same net often appears twice (a testbench wire and the DUT's output reg, with
    # different codes). Keep the shallowest copy.
    first_seen: Dict[tuple, dict] = {}
    for sig in code_to_sig.values():
        key = (sig["name"], sig["width"])
        keep = first_seen.get(key)
        if keep is None or sig["depth"] < keep["depth"]:
            first_seen[key] = sig
    duplicates = {id(s) for s in code_to_sig.values()} - {id(s) for s in first_seen.values()}
    for sig in code_to_sig.values():
        sig["role"] = _role(sig, ports)

    # Walk the value-change section.
    current_time = 0
    end_time = 0
    changes_truncated = False
    body = text[body_start:] if body_start != -1 else text

    def record(code: str, value: str):
        nonlocal changes_truncated
        sig = code_to_sig.get(code)
        if sig is None:
            return
        if len(sig["wave"]) >= MAX_CHANGES_PER_SIGNAL:
            changes_truncated = True
            if sig["truncated_at"] is None:
                sig["truncated_at"] = sig["wave"][-1]["t"]
            return
        sig["wave"].append({"t": current_time, "v": value})

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line[0] == "#":
            try:
                current_time = int(line[1:])
                end_time = max(end_time, current_time)
            except ValueError:
                pass
        elif line[0] in "01xXzZ" and len(line) >= 2:
            record(line[1:], line[0].lower())            # scalar change: <value><code>
        elif line[0] in "bB":
            parts = line[1:].split()                     # vector change: b<bits> <code>
            if len(parts) == 2:
                record(parts[1], _bin_to_hex(parts[0]))
        elif line[0] in "rR":
            parts = line[1:].split()                     # real change: r<value> <code>
            if len(parts) == 2:
                record(parts[1], parts[0])

    candidates = [s for s in code_to_sig.values() if id(s) not in duplicates]
    ranked = sorted(enumerate(candidates), key=lambda p: (_RANK.get(p[1]["role"], 5), p[0]))
    kept = [s for _, s in ranked[:max_signals]]
    dropped_signals = max(0, len(candidates) - max_signals)
    truncated = dropped_signals > 0 or changes_truncated or file_truncated

    return Waveform(
        timescale=timescale, timescale_ps=timescale_ps,
        timescale_defaulted=(timescale == "1s"),
        end_time=end_time,
        signals=[WaveformSignal(
            name=s["name"], width=s["width"], wave=s["wave"], path=s["path"], scope=s["scope"],
            var_type=s["var_type"], role=s["role"], msb=s["msb"], lsb=s["lsb"],
            truncated_at=s["truncated_at"]) for s in kept],
        truncated=truncated, dropped_signals=dropped_signals, changes_truncated=changes_truncated,
    )


def ports_from_rtl(rtl: str) -> Dict[str, str]:
    """Best-effort ``{port name: direction}`` from a module header (used when no spec exists).

    Only used for waveform grouping on Re-run, where the user may have edited the RTL, so a
    wrong guess merely changes how signals are grouped; it never affects a verdict.
    """
    m = re.search(r"\bmodule\s+\w+\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;", rtl or "", re.DOTALL)
    if not m:
        return {}
    pieces, depth, cur = [], 0, ""
    for ch in m.group(1):
        depth += ch in "[(" 
        depth -= ch in "])"
        if ch == "," and depth == 0:
            pieces.append(cur)
            cur = ""
        else:
            cur += ch
    pieces.append(cur)
    out: Dict[str, str] = {}
    direction = None
    for piece in pieces:
        dm = re.search(r"\b(input|output|inout)\b", piece)
        if dm:
            direction = dm.group(1)
        names = re.findall(r"[A-Za-z_]\w*", re.sub(r"\[[^\]]*\]|\b(?:input|output|inout|wire|reg|logic|signed)\b", " ", piece))
        if names and direction:
            out[names[-1]] = direction
    return out
