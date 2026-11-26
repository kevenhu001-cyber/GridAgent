import json

import pytest

from gridagent.research_tools import analyze_voltage, compare_faults


def create_run(root, identifier, sha="a", duration=0.1, severity=0.2):
    folder = root / "runs" / identifier
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps({
        "status": "ok", "operation": "fault", "model_sha256": sha,
        "fault": {"duration_s": duration, "end_s": 3, "bus": 5},
        "metrics": {"v_min_pu": 0.8, "v_max_pu": 1.1, "voltage_severity_proxy": severity,
                    "window_s": [1+duration, 3]}}))
    (folder / "voltage.csv").write_text("time_s,B5\n0,1\n1.2,0.8\n2,1.1\n3,1\n")


def test_waveform_and_matching_comparison(tmp_path):
    a, b, c = "a"*32, "b"*32, "c"*32
    create_run(tmp_path, a)
    create_run(tmp_path, b, duration=0.2, severity=0.3)
    create_run(tmp_path, c, sha="different")
    data = analyze_voltage(tmp_path, a, "B5")
    assert data["min_pu"] == 0.8
    assert data["max_time_s"] == 2
    assert compare_faults(tmp_path, a, b)["metrics"]["voltage_severity_proxy"]["delta"] == pytest.approx(0.1)
    with pytest.raises(ValueError, match="snapshot"):
        compare_faults(tmp_path, a, c)


def test_flow_comparison(tmp_path):
    from gridagent.research_tools import compare_power_flows

    a, b = "a"*32, "b"*32
    for rid, voltages in ((a, {"1": 1.0, "2": 1.0}), (b, {"1": 0.98, "2": 0.95})):
        folder = tmp_path / "runs" / rid
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({"status": "ok", "operation": "power_flow",
            "model_sha256": "same", "voltages_pu": voltages}))
    result = compare_power_flows(tmp_path, a, b)
    assert result["largest_voltage_changes"][0]["bus"] == "2"
    assert result["candidate_voltage_min_pu"] == 0.95


def test_branch_lookup_is_paged_and_filtered(tmp_path):
    from gridagent.research_tools import network_branches

    identifier = "c"*32
    folder = tmp_path / "runs" / identifier
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps({"status": "ok", "operation": "inspect",
                                                   "model_sha256": "same"}))
    (folder / "topology.json").write_text(json.dumps({"buses": ["1", "2", "3"], "branches": [
        {"id": "L1", "from": "1", "to": "2", "in_service": True},
        {"id": "L2", "from": "2", "to": "3", "in_service": True}]}))
    page = network_branches(tmp_path, identifier, "2", limit=1)
    assert page["total"] == 2 and page["next_offset"] == 1
    assert page["branches"][0]["id"] == "L1"
    assert network_branches(tmp_path, identifier, "1")["total"] == 1
