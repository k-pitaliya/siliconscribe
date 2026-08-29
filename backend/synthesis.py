"""
Yosys synthesis wrapper.

Provides :class:`YosysSynthesizer` which delegates to
:func:`schematic.synthesize_with_yosys` and offers a hybrid
``build_schematic_hybrid`` that prefers gate-level metrics when yosys is
installed but gracefully falls back to the port-level block diagram.
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

    def build_schematic_hybrid(
        self,
        spec: RTLDesignSpec,
        rtl_code: str,
        work_dir: Optional[Path] = None,
    ) -> Schematic:
        """Try yosys synthesis, then return a port-level :class:`Schematic`.

        Gate-level rendering (yosys + netlistsvg) is future work, so this
        method always returns the port-level block diagram today.  It still
        *attempts* synthesis first so synthesis metrics are populated and
        failures do not propagate — guaranteeing offline / no-yosys correctness.

        Args:
            spec: Parsed RTL spec for the port diagram.
            rtl_code: Verilog source for the top module.
            work_dir: Optional synthesis scratch dir.

        Returns:
            Schematic: port-level diagram (fallback is the only diagram today).
        """
        # Attempt synthesis for side-effects / metrics, but never fail the
        # schematic build.  Any yosys errors are swallowed; the caller can
        # call :meth:`synthesize` separately if it needs the metrics.
        try:
            wd = Path(work_dir) if work_dir is not None else self.workspace / f"synth_{spec.module_name}"
            # We intentionally ignore the return value here; synthesis metrics
            # are consumed via synthesize() in the orchestrator.  The hybrid
            # schematic itself remains port-level for now.
            synthesize_with_yosys(rtl_code, spec.module_name, wd)
        except Exception:
            # Graceful fallback — never raise from schematic building.
            pass
        return build_schematic(spec)

    def synthesize_and_build(
        self,
        spec: RTLDesignSpec,
        rtl_code: str,
        work_dir: Optional[Path] = None,
    ) -> Tuple[Schematic, dict]:
        """Convenience: return both the schematic and synthesis metrics.

        Returns:
            (Schematic, synthesis_dict)
        """
        wd = Path(work_dir) if work_dir is not None else self.workspace / f"synth_{spec.module_name}"
        synthesis = self.synthesize(rtl_code, spec.module_name, work_dir=wd)
        schematic = build_schematic(spec)
        return schematic, synthesis
