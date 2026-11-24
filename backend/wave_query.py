"""
wave_query.py: a queryable view of one simulation's VCD, for the debugging agent.

The waveform viewer gets a compact, capped copy of the VCD (vcd_parser.parse_vcd). The agent needs something
different: exact values at exact times, for ANY signal in the dump, without the whole file ever entering a prompt.
WaveDB keeps every value change (binary, padded to the signal width) and answers small questions:

    value_at(signal, t)          what was the value at time t
    changes(signal, t0, t1)      every change in a window
    edges(clock, t0, t1)         rising / falling edges of a 1-bit signal
    find_value(signal, v, ...)   when did the signal hold value v

Times in this module are VCD ticks (the file's own unit). The agent tools convert to and from nanoseconds.

All values are returned as text the model can read: hex, plus decimal when the value has no x / z bits.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from vcd_parser import MAX_VCD_BYTES, _UNIT_PS, _bin_to_hex, _pad_bits, _parse_header

MAX_SIGNALS = 2000                 # a design bigger than this is not what the playground is for
MAX_CHANGES_PER_SIGNAL = 200_000   # per signal; the 8 MB read cap bounds the total anyway


@dataclass
class Signal:
    path: str              # testbench.dut.count
    name: str              # count
    width: int
    var_type: str
    in_design: bool        # declared inside the design under test (not testbench bookkeeping)
    depth: int
    times: List[int] = field(default_factory=list)
    values: List[str] = field(default_factory=list)   # binary, MSB first, padded to width ('x'/'z' kept)
    truncated: bool = False

    def value_at(self, t: int) -> Optional[str]:
        """The value at time t, AFTER every change at t has been applied. None before the first change."""
        i = bisect.bisect_right(self.times, t) - 1
        return self.values[i] if i >= 0 else None

    def value_before(self, t: int) -> Optional[str]:
        """The value just before time t: what a flip-flop clocked at t samples."""
        i = bisect.bisect_left(self.times, t) - 1
        return self.values[i] if i >= 0 else None


def fmt_value(bits: Optional[str], width: int) -> str:
    """'4'h9 (9)' style text: hex for everything, decimal too when every bit is known."""
    if bits is None:
        return "no value yet"
    if width == 1:
        return bits
    hx = _bin_to_hex(bits)
    if set(bits) <= {"0", "1"}:
        return f"{width}'h{hx} ({int(bits, 2)})"
    return f"{width}'h{hx}"


def parse_value(text: str, width: int) -> Optional[str]:
    """A value the model wrote ('9', "4'h9", '0x9', "4'b1001", 'x', '1') as a padded binary string, or None."""
    s = str(text).strip().lower().replace("_", "")
    if not s:
        return None
    if s in ("x", "z") or (set(s) <= {"x"} or set(s) <= {"z"}):
        return s[0] * width
    m = re.fullmatch(r"(?:\d+)?'s?([bhdo])([0-9a-fxz]+)", s)
    try:
        if m:
            base, digits = m.group(1), m.group(2)
            if base == "b":
                return _pad_bits(digits, width) if set(digits) <= set("01xz") else None
            if base == "h":
                if set(digits) - set("0123456789abcdef"):
                    return None
                return format(int(digits, 16) & ((1 << width) - 1), f"0{width}b")
            if base == "o":
                return format(int(digits, 8) & ((1 << width) - 1), f"0{width}b")
            return format(int(digits, 10) & ((1 << width) - 1), f"0{width}b")
        if s.startswith("0x"):
            return format(int(s[2:], 16) & ((1 << width) - 1), f"0{width}b")
        if s.startswith("0b"):
            return _pad_bits(s[2:], width) if set(s[2:]) <= set("01xz") else None
        if s.lstrip("-").isdigit():
            v = int(s)
            if v < 0:
                v &= (1 << width) - 1
            return format(v & ((1 << width) - 1), f"0{width}b")
    except ValueError:
        return None
    return None


class WaveDB:
    def __init__(self, timescale_ps: float, end_time: int, signals: List[Signal], partial: bool):
        self.timescale_ps = timescale_ps
        self.end_time = end_time
        self.signals = signals
        self.partial = partial               # the VCD was larger than the read cap: late changes are missing
        self._by_path = {s.path: s for s in signals}

    # ------------------------------------------------------------------ time units
    def to_ns(self, ticks: int) -> float:
        return round(ticks * self.timescale_ps / 1000.0, 3)

    def to_ticks(self, ns: float) -> int:
        return int(round(float(ns) * 1000.0 / self.timescale_ps))

    # ------------------------------------------------------------------ lookup
    def resolve(self, name: str) -> Tuple[Optional[Signal], List[str]]:
        """Find a signal by full path, path suffix ('dut.count') or bare name ('count').

        Returns (signal, other_candidates). With several matches the design's own copy wins, then the shallowest.
        """
        n = str(name or "").strip().strip("`").replace("/", ".")
        n = re.sub(r"\s*\[\s*\d+\s*:\s*\d+\s*\]\s*$", "", n)
        if not n:
            return None, []
        if n in self._by_path:
            return self._by_path[n], []
        low = n.lower()
        hits = [s for s in self.signals if s.path.lower() == low or s.path.lower().endswith("." + low)]
        if not hits:
            return None, []
        hits.sort(key=lambda s: (not s.in_design, s.depth, s.path))
        return hits[0], [s.path for s in hits[1:6]]

    def clocks(self) -> List[Signal]:
        return [s for s in self.signals if s.width == 1 and re.match(r"(?i)^(clk|clock)\w*$", s.name)]

    def edges(self, sig: Signal, t0: int, t1: int, kind: str = "posedge", limit: int = 64) -> List[int]:
        out: List[int] = []
        start = max(0, bisect.bisect_left(sig.times, t0))
        for i in range(start, len(sig.times)):
            t = sig.times[i]
            if t > t1:
                break
            prev = sig.values[i - 1] if i > 0 else None
            cur = sig.values[i]
            rising = cur == "1" and prev in ("0", "x", "z", None)
            falling = cur == "0" and prev in ("1", "x", "z")
            if (kind == "posedge" and rising) or (kind == "negedge" and falling) or (kind == "any" and (rising or falling)):
                out.append(t)
                if len(out) >= limit:
                    break
        return out

    def changes(self, sig: Signal, t0: int, t1: int, limit: int = 40) -> Tuple[List[Tuple[int, str]], bool]:
        start = bisect.bisect_left(sig.times, t0)
        stop = bisect.bisect_right(sig.times, t1)
        rows = list(zip(sig.times[start:stop], sig.values[start:stop]))
        return rows[:limit], len(rows) > limit

    def find_value(self, sig: Signal, bits: str, t0: int, t1: int, limit: int = 5) -> List[Tuple[int, Optional[int]]]:
        """Intervals [start, end) where the signal held exactly `bits` (end None = until the end of the dump)."""
        out: List[Tuple[int, Optional[int]]] = []
        first = max(0, bisect.bisect_right(sig.times, t0) - 1)
        for i in range(first, len(sig.times)):
            start = sig.times[i]
            if start > t1:
                break
            if sig.values[i] != bits:
                continue
            end = sig.times[i + 1] if i + 1 < len(sig.times) else None
            if end is not None and end <= t0:
                continue
            out.append((max(start, t0), end))
            if len(out) >= limit:
                break
        return out


def load(vcd_path: str | Path) -> Optional[WaveDB]:
    """Parse a VCD into a WaveDB. None when the file is missing or has no signals."""
    path = Path(vcd_path)
    if not path.exists():
        return None
    partial = path.stat().st_size > MAX_VCD_BYTES
    with path.open("r", errors="ignore") as fh:
        text = fh.read(MAX_VCD_BYTES)
    timescale_ps = 1000.0
    ts = re.search(r"\$timescale\s+(.*?)\s+\$end", text, re.DOTALL)
    if ts:
        um = re.fullmatch(r"(\d+)\s*(fs|ps|ns|us|ms|s)", ts.group(1).strip())
        if um:
            timescale_ps = int(um.group(1)) * _UNIT_PS[um.group(2)]
    body_start = text.find("$enddefinitions")
    if body_start == -1:
        return None
    raw = _parse_header(text[:body_start])
    if not raw:
        return None
    sigs: Dict[str, Signal] = {}
    for code, s in list(raw.items())[:MAX_SIGNALS]:
        if s["var_type"] in ("parameter", "localparam", "event", "string") or s["width"] <= 0 or s["width"] > 4096:
            continue
        sigs[code] = Signal(path=s["path"], name=s["name"], width=s["width"], var_type=s["var_type"],
                            in_design=bool(s["design_name"]), depth=s["depth"])

    now = end = 0

    def record(code: str, bits: str) -> None:
        sig = sigs.get(code)
        if sig is None:
            return
        val = _pad_bits(bits, sig.width)
        if sig.values and sig.values[-1] == val:
            return                                   # a re-dump of the same value is not a change
        if len(sig.times) >= MAX_CHANGES_PER_SIGNAL:
            sig.truncated = True
            return
        if sig.times and sig.times[-1] == now:       # several updates in one time step: keep the settled one
            sig.values[-1] = val
            if len(sig.values) >= 2 and sig.values[-2] == val:
                sig.times.pop()
                sig.values.pop()
            return
        sig.times.append(now)
        sig.values.append(val)

    for line in text[body_start:].splitlines():
        line = line.strip()
        if not line:
            continue
        c = line[0]
        if c == "#":
            try:
                now = int(line[1:])
                end = max(end, now)
            except ValueError:
                pass
        elif c in "01xXzZ" and len(line) >= 2:
            record(line[1:], c.lower())
        elif c in "bB":
            parts = line[1:].split()
            if len(parts) == 2:
                record(parts[1], parts[0].lower())
    return WaveDB(timescale_ps=timescale_ps, end_time=end, signals=list(sigs.values()), partial=partial)
