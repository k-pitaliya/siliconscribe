"""
Port-level schematic data.

Builds a simple block-diagram description (module box + grouped I/O ports) from
the RTL spec. The frontend renders it as SVG.

Yosys synthesis (gate-level) is now supported via :func:`synthesize_with_yosys`
with graceful fallback to the port-level diagram when yosys is unavailable.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from models import RTLDesignSpec, Schematic, SchematicPort


def build_schematic(spec: RTLDesignSpec) -> Schematic:
    inputs, outputs, inouts = [], [], []
    for p in spec.ports:
        port = SchematicPort(name=p.name, direction=p.direction, width=p.width)
        if p.direction == "input":
            inputs.append(port)
        elif p.direction == "output":
            outputs.append(port)
        else:
            inouts.append(port)
    return Schematic(
        module_name=spec.module_name,
        inputs=inputs,
        outputs=outputs,
        inouts=inouts,
    )


def summarize_netlist(netlist: dict, module_name: str) -> dict | None:
    """Count what Yosys produced, from the JSON netlist (stable across Yosys versions).

    The printed ``stat`` text changed format between releases ("Number of cells: N" became
    "N cells"), which silently dropped the count. The netlist is the machine-readable source.
    Returns ``cell_count``, ``cell_types`` (most common first), ``flip_flops`` and ``latches``,
    or None when the module is not in the netlist.
    """
    modules = (netlist or {}).get("modules") or {}
    mod = modules.get(module_name) or next(iter(modules.values()), None)
    if not isinstance(mod, dict):
        return None
    counts: dict[str, int] = {}
    for cell in (mod.get("cells") or {}).values():
        ctype = str(cell.get("type", "?"))
        counts[ctype] = counts.get(ctype, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "cell_count": sum(counts.values()),
        # "$_DFF_PN0_" -> "DFF_PN0", "$_XOR_" -> "XOR"
        "cell_types": [[ctype.strip("$_"), n] for ctype, n in ordered[:10]],
        "flip_flops": sum(n for c, n in counts.items() if "DFF" in c),
        "latches": sum(n for c, n in counts.items() if "LATCH" in c),
    }


def _yosys_warnings(output: str, limit: int = 5) -> list[str]:
    """Yosys' own `Warning:` lines (multiple drivers, combinational loops, ...), de-duplicated."""
    seen: list[str] = []
    for line in output.splitlines():
        if line.startswith("Warning:"):
            # Keep only file names: the server's temporary directories are noise to the user and should not be shown.
            msg = re.sub(r"(?:/[^\s/:]+)+/([^\s/:]+)", r"\1", line[len("Warning:"):].strip())[:200]
            if msg and msg not in seen:
                seen.append(msg)
    return seen[:limit]


def synthesize_with_yosys(rtl_code: str, module_name: str, work_dir: Path) -> dict:
    """
    Try to synthesize ``rtl_code`` with Yosys.

    Returns a dict with at least ``available`` (bool).  When yosys is present
    and the flow succeeds the dict also contains ``cell_count`` (int),
    ``area_estimate`` (float, heuristic), and ``json_netlist`` (dict) when
    the JSON backend produced output.  On failure ``error`` is populated.

    Graceful fallback: when ``yosys`` is not on ``$PATH`` the function
    immediately returns ``{"available": False}`` and callers should fall back
    to :func:`build_schematic`.
    """
    # Check availability first — offline / CI without yosys must not fail.
    if shutil.which("yosys") is None:
        return {"available": False}

    # Basic module_name sanitisation to avoid shell injection via the yosys -p string.
    # Yosys identifiers must start with letter/underscore; we allow alphanumeric + underscore.
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", module_name):
        return {"available": True, "error": f"Invalid module_name: {module_name!r}"}

    # Guard against unreasonably large RTL (200 KB mirrors simulator.py limit).
    if len(rtl_code.encode("utf-8")) > 200 * 1024:
        return {"available": True, "error": "rtl_code exceeds 200 KB limit"}

    # Same sandbox policy as simulation, lint and timing: Yosys itself evaluates `include and
    # $readmemh while reading, so a design must not reach local files through synthesis either.
    from simulator import sandbox_violations  # local import: simulator is the policy owner
    blocked = sandbox_violations(rtl_code)
    if blocked:
        return {"available": True, "error": "Source not synthesized: " + "; ".join(blocked[:3])}

    work_dir = Path(work_dir)
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Generic to avoid leaking internal path / OS error details
        import logging as _logging
        _logging.getLogger("siliconscribe.synthesis").exception("work_dir create failed")
        return {"available": True, "error": "Could not create work_dir"}

    rtl_file = work_dir / f"{module_name}.sv"
    json_out = work_dir / f"{module_name}_netlist.json"

    try:
        rtl_file.write_text(rtl_code)
    except Exception:
        import logging as _logging
        _logging.getLogger("siliconscribe.synthesis").exception("write RTL failed")
        return {"available": True, "error": "Failed to write RTL"}

    # Build the yosys script.  Keep it single-string for ``yosys -p``.
    # read_verilog -sv -> SystemVerilog, hierarchy check, proc/opt, synth, stat, write_json
    yosys_script = (
        f"read_verilog -sv {rtl_file}; "
        f"hierarchy -check -top {module_name}; "
        f"proc; opt; synth -top {module_name}; "
        f"check; stat; write_json {json_out}"
    )

    try:
        result = subprocess.run(
            ["yosys", "-p", yosys_script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(work_dir),
        )
        output = (result.stdout or "") + (result.stderr or "")

        # Parse cell count: Yosys prints "Number of cells:  N"
        cell_count = None
        m = re.search(r"Number of cells:\s+(\d+)", output)
        if m:
            try:
                cell_count = int(m.group(1))
            except ValueError:
                cell_count = None

        # RELATIVE AREA PROXY — NOT a physical area in um^2.
        # We run `synth` with NO liberty file, so Yosys maps to its generic gate
        # library ($__NOT_CELL__, $_AND_, ...). No technology mapping => no real
        # transistor area, no node/corner, no die area. Reporting "cell_count * 5"
        # as um^2 would be fabricated. We keep a dimensionless, monotonic proxy so
        # designs can still be ranked against each other, and we label it
        # explicitly so no consumer can mistake it for silicon area.
        # Real um^2 requires: read_liberty <pdk>.lib + abc -D <delay> + stat -tech.
        RELATIVE_AREA_PER_CELL = 5.0
        area_estimate = (float(cell_count * RELATIVE_AREA_PER_CELL)
                         if cell_count is not None else None)

        # Try to read JSON netlist if yosys produced it.
        json_netlist = None
        if json_out.exists():
            try:
                json_netlist = json.loads(json_out.read_text())
            except Exception:
                json_netlist = None

        ret: dict = {
            "available": True,
            # Honesty flags: consumers MUST check these before quoting numbers.
            "liberty_mapped": False,        # no .lib => no real tech mapping
            "area_units": "relative_proxy", # dimensionless; NOT um^2
            "tech_node": None,              # unknown until a PDK liberty is supplied
        }
        if cell_count is not None:
            ret["cell_count"] = cell_count
        if area_estimate is not None:
            ret["area_estimate"] = area_estimate
            ret["area_estimate_note"] = (
                "Relative proxy = cell_count x "
                f"{RELATIVE_AREA_PER_CELL:g} (generic cells, no liberty/tech map). "
                "NOT a physical area in um^2."
            )
        if json_netlist is not None:
            ret["json_netlist"] = json_netlist
            summary = summarize_netlist(json_netlist, module_name)
            if summary:
                # The netlist is authoritative; the text regex above is only a fallback.
                ret.update(summary)
                ret["cell_count"] = summary["cell_count"]
                ret["area_estimate"] = float(summary["cell_count"] * RELATIVE_AREA_PER_CELL)
                ret["area_estimate_note"] = (
                    "Relative proxy = cell_count x "
                    f"{RELATIVE_AREA_PER_CELL:g} (generic cells, no liberty/tech map). "
                    "NOT a physical area in um^2."
                )
                if summary["latches"]:
                    ret["latch_warning"] = (
                        f"{summary['latches']} latch(es) inferred: usually an if/case in combinational "
                        "logic that does not assign every output on every path."
                    )
        warnings = _yosys_warnings(output)
        if warnings:
            ret["warnings"] = warnings

        if result.returncode != 0:
            # Include error excerpt; if we also have cell_count we still surface it.
            ret["error"] = output.strip()[-2500:] if output.strip() else f"yosys exited {result.returncode}"
            # If we have no cell_count and no json, this is a hard synthesis failure.
            if cell_count is None and json_netlist is None and "error" not in ret:
                ret["error"] = output.strip()[-2500:]

        # Edge: successful run but nothing parsed — still return available True.
        if "error" not in ret and cell_count is None and json_netlist is None:
            # No cell count found but yosys exited 0 — treat as available but empty.
            # Keep ret as is; callers check existence of cell_count.
            pass

        return ret

    except subprocess.TimeoutExpired:
        return {"available": True, "error": "yosys timeout after 30s"}
    except FileNotFoundError:
        # yosys disappeared between shutil.which and run
        return {"available": False}
    except Exception:
        import logging as _logging
        _logging.getLogger("siliconscribe.synthesis").exception("yosys synthesis failed")
        return {"available": True, "error": "synthesis failed"}
