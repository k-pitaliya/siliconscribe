"""
Port-level schematic data.

Builds a simple block-diagram description (module box + grouped I/O ports) from
the RTL spec. The frontend renders it as SVG. A full gate-level schematic via
yosys + netlistsvg is intentionally out of scope (noted as future work).
"""

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
