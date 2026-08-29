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

    work_dir = Path(work_dir)
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"available": True, "error": f"Could not create work_dir: {e}"}

    rtl_file = work_dir / f"{module_name}.sv"
    json_out = work_dir / f"{module_name}_netlist.json"

    try:
        rtl_file.write_text(rtl_code)
    except Exception as e:
        return {"available": True, "error": f"Failed to write RTL: {e}"}

    # Build the yosys script.  Keep it single-string for ``yosys -p``.
    # read_verilog -sv -> SystemVerilog, hierarchy check, proc/opt, synth, stat, write_json
    yosys_script = (
        f"read_verilog -sv {rtl_file}; "
        f"hierarchy -check -top {module_name}; "
        f"proc; opt; synth -top {module_name}; "
        f"stat; write_json {json_out}"
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

        # Heuristic area estimate: no liberty file, so approximate.
        # ~5 um^2 per generic cell is a plausible order-of-magnitude for demo.
        area_estimate = float(cell_count * 5.0) if cell_count is not None else None

        # Try to read JSON netlist if yosys produced it.
        json_netlist = None
        if json_out.exists():
            try:
                json_netlist = json.loads(json_out.read_text())
            except Exception:
                json_netlist = None

        ret: dict = {"available": True}
        if cell_count is not None:
            ret["cell_count"] = cell_count
        if area_estimate is not None:
            ret["area_estimate"] = area_estimate
        if json_netlist is not None:
            ret["json_netlist"] = json_netlist

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
    except Exception as e:
        return {"available": True, "error": str(e)}
