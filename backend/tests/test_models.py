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
