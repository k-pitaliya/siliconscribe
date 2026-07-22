"""
Minimal VCD (Value Change Dump) parser.

Turns an Icarus-produced .vcd into a compact JSON-friendly structure the
frontend waveform viewer can render directly:

    {
      "timescale": "1ns",
      "end_time": 200,
      "signals": [
        {"name": "clk", "width": 1, "wave": [{"t": 0, "v": "0"}, {"t": 5, "v": "1"}, ...]},
        {"name": "a",   "width": 4, "wave": [{"t": 0, "v": "x"}, {"t": 10, "v": "a"}, ...]},
        ...
      ]
    }

Bus values are normalized to hex strings; single bits stay as '0'/'1'/'x'/'z'.
Only top-level testbench signals are kept (depth-limited) to avoid noise.
"""

import re
from pathlib import Path
from typing import Optional

from models import Waveform, WaveformSignal

# Hard cap so a runaway TB can't produce a multi-megabyte payload.
MAX_SIGNALS = 40
MAX_CHANGES_PER_SIGNAL = 2000


def _bin_to_hex(bits: str) -> str:
    """Convert a binary string (possibly with x/z) to a compact hex string."""
    bits = bits.strip()
    if not bits:
        return "0"
    if any(c in "xz" for c in bits.lower()):
        # If any bit is unknown, represent the whole bus symbolically.
        return "x" if "x" in bits.lower() else "z"
    try:
        return format(int(bits, 2), "x")
    except ValueError:
        return bits


def parse_vcd(vcd_path: str | Path, max_signals: int = MAX_SIGNALS) -> Optional[Waveform]:
    path = Path(vcd_path)
    if not path.exists():
        return None

    text = path.read_text(errors="ignore")

    timescale = "1ns"
    ts_match = re.search(r"\$timescale\s+(.*?)\s+\$end", text, re.DOTALL)
    if ts_match:
        timescale = ts_match.group(1).strip()

    # Map identifier-code -> signal metadata. VCD aliases multiple names to one
    # code; we keep the first (shortest-scope) name we see.
    code_to_sig: dict[str, dict] = {}
    for m in re.finditer(r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+([^\s$]+(?:\s*\[[^\]]*\])?)\s+\$end", text):
        width = int(m.group(1))
        code = m.group(2)
        name = m.group(3).strip()
        if code not in code_to_sig:
            code_to_sig[code] = {"name": name, "width": width, "wave": []}

    if not code_to_sig:
        return Waveform(timescale=timescale, end_time=0, signals=[])

    # Walk the value-change section.
    current_time = 0
    end_time = 0
    body_start = text.find("$enddefinitions")
    body = text[body_start:] if body_start != -1 else text

    def record(code: str, value: str):
        sig = code_to_sig.get(code)
        if sig is None:
            return
        if len(sig["wave"]) >= MAX_CHANGES_PER_SIGNAL:
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
            # Scalar change: <value><code>, e.g. "1!"
            value = line[0].lower()
            code = line[1:]
            record(code, value)
        elif line[0] in "bB":
            # Vector change: b<bits> <code>
            parts = line[1:].split()
            if len(parts) == 2:
                record(parts[1], _bin_to_hex(parts[0]))
        elif line[0] in "rR":
            # Real change: r<value> <code>
            parts = line[1:].split()
            if len(parts) == 2:
                record(parts[1], parts[0])

    signals = []
    for sig in code_to_sig.values():
        signals.append(WaveformSignal(name=sig["name"], width=sig["width"], wave=sig["wave"]))
        if len(signals) >= max_signals:
            break

    return Waveform(timescale=timescale, end_time=end_time, signals=signals)
