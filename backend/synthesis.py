"""
Yosys synthesis wrapper.

Provides :class:`YosysSynthesizer` which delegates to
:func:`schematic.synthesize_with_yosys`, returning metrics when yosys is
installed and a graceful ``available: False`` result when it is not.
"""

import shutil
from pathlib import Path
from typing import Optional, Tuple

from models import RTLDesignSpec, Schematic
from schematic import build_schematic, synthesize_with_yosys


class YosysSynthesizer:
    """High-level wrapper around :func:`schematic.synthesize_with_yosys`.

    The class is intentionally light: it carries a default workspace so callers
    can ``synthesize(rtl, module)`` without threading ``work_dir`` everywhere,
    and it exposes :meth:`build_schematic_hybrid` for the orchestrator.
    """

    def __init__(self, workspace: str | Path = "./workspace"):
        self.workspace = Path(workspace).resolve()
        # Ensure workspace exists so synthesize_with_yosys can create sub-dirs.
        try:
            self.workspace.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def available(self) -> bool:
        """Return True iff ``yosys`` is on $PATH."""
        return shutil.which("yosys") is not None

    def synthesize(
        self, rtl_code: str, module_name: str, work_dir: Optional[Path] = None
    ) -> dict:
        """Run Yosys synthesis and return the metrics dict.

        When ``work_dir`` is None a temporary sub-directory under
        ``self.workspace`` is used (``synth_<module>``).  The returned dict
        always contains ``available`` (bool) and optionally ``cell_count``,
        ``area_estimate``, ``json_netlist``, ``error``.
        """
        if work_dir is None:
            # Use a per-module synth dir to avoid collisions across designs.
            work_dir = self.workspace / f"synth_{module_name}"
        return synthesize_with_yosys(rtl_code, module_name, Path(work_dir))

    def synthesize_and_build(
        self,
        spec: RTLDesignSpec,
        rtl_code: str,
        work_dir: Optional[Path] = None,
    ) -> Tuple[Schematic, dict]:
        """Return both the port-level schematic and synthesis metrics.

        There is deliberately no "hybrid" variant that runs yosys and throws the
        result away: the orchestrator calls :meth:`synthesize` itself and keeps
        the metrics, so a second hidden synthesis run would only waste time.
        """
        wd = Path(work_dir) if work_dir is not None else self.workspace / f"synth_{spec.module_name}"
        synthesis = self.synthesize(rtl_code, spec.module_name, work_dir=wd)
        schematic = build_schematic(spec)
        return schematic, synthesis
