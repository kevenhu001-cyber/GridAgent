import json
import math

import pytest

from gridagent import external_runtime, verified_python


def test_sandbox_configuration_and_timeout_cleanup(tmp_path, monkeypatch):
    commands = []
    original_dir = tmp_path / "runtime"
    monkeypatch.setattr(verified_python, "require_runtime", lambda: ("wsb", original_dir))
    with pytest.raises(ValueError, match="disabled"):
        verified_python.sandbox_run(tmp_path, tmp_path / "denied", "pass", {})
    verified_python.set_sandbox_enabled(tmp_path, True)
    monkeypatch.setattr(verified_python, "TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(verified_python.subprocess, "run", lambda args, **kwargs: commands.append(args))

    with pytest.raises(TimeoutError):
        verified_python.sandbox_run(tmp_path, tmp_path / "timed-out", "pass", {})
    assert [entry[1] for entry in commands] == ["start", "stop"]
    assert commands[0][3] == commands[1][3]
    config = commands[0][-1]
    assert "<Networking>Disable</Networking>" in config
    assert config.count("<ReadOnly>true</ReadOnly>") == 2
    assert config.count("<ReadOnly>false</ReadOnly>") == 1


def test_sandbox_imports_only_the_bounded_numeric_contract(tmp_path, monkeypatch):
    folder = tmp_path / "valid"
    monkeypatch.setattr(verified_python, "require_runtime", lambda: ("wsb", tmp_path / "runtime"))

    def run(args, **kwargs):
        if args[1] == "start":
            output = folder / "output"
            (output / "exit-code.txt").write_text("0", encoding="ascii")
            (output / "result.json").write_text(json.dumps({"buses": {"0": {
                "vm_pu": 1.0, "va_degree": 0, "p_mw": -5, "q_mvar": -2}}}), encoding="utf-8")

    monkeypatch.setattr(verified_python.subprocess, "run", run)
    verified_python.set_sandbox_enabled(tmp_path, True)
    evidence = verified_python.sandbox_run(tmp_path, folder, "pass", {})
    assert evidence.buses[0].p_mw == -5


def test_external_spice_import_and_analytic_ac_check(tmp_path, monkeypatch):
    executable = tmp_path / "ngspice.exe"
    executable.write_bytes(b"mock-binary")
    (tmp_path / "ngspice-runtime.json").write_text(json.dumps({
        "path": str(executable), "version": "47", "sha256": external_runtime.file_digest(executable)
    }), encoding="utf-8")

    def solver(args, **kwargs):
        assert args[1:4] == ["-n", "-b", "-r"]
        corner = 1/(2*math.pi*0.001)
        lines = ["No. Variables: 2", "Values:"]
        for idx in range(11):
            freq = corner * 10**(-2 + idx*0.4)
            value = 1/(1+2j*math.pi*freq*0.001)
            lines.extend([f"{idx} {freq},0", f"  {value.real},{value.imag}"])
        (kwargs["cwd"] / "response.raw").write_text("\n".join(lines), encoding="ascii")

    monkeypatch.setattr(external_runtime.subprocess, "run", solver)
    result = external_runtime.run_rc(tmp_path, {"analysis": "ac", "resistance_ohm": 1000, "capacitance_f": 1e-6})
    assert result["quality"]["passed"], result
