from models import RTLDesignSpec, PortSpec, SimulationResult


def test_rtl_spec_roundtrip():
    spec = RTLDesignSpec(
        module_name="full_adder",
        ports=[PortSpec(name="a", direction="input"), PortSpec(name="sum", direction="output")],
        behavior="adds bits",
    )
    assert spec.module_name == "full_adder"
    assert len(spec.ports) == 2
    assert spec.model_dump()["ports"][0]["width"] == 1


def test_simulation_result_defaults():
    r = SimulationResult(status="PASS", module_name="x")
    assert r.coverage == {}
    assert r.errors == []
    assert r.pass_count == 0


import pytest as _pytest  # noqa: E402
from models import PortSpec as _PortSpec  # noqa: E402


@_pytest.mark.parametrize("raw,expected", [
    (8, 8), ("8", 8), ("[7:0]", 8), ("7:0", 8), ("[0:7]", 8), ("8 bits", 8), ("8-bit", 8),
    ("16 Bits", 16), (8.0, 8), ("8.0", 8), ("WIDTH", 1), (True, 1),
])
def test_width_spellings_models_actually_use_are_understood(raw, expected):
    assert _PortSpec(name="a", direction="input", width=raw).width == expected
