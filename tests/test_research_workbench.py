import pytest

from gridagent.research_workbench import workbench_command


def test_plan_does_not_run_solver(tmp_path, monkeypatch):
    from gridagent import ac_decision_train, ac_native_collection

    monkeypatch.setattr(ac_decision_train, "read_json", lambda path: {"input": path})
    monkeypatch.setattr(ac_native_collection, "start_collection", lambda root, auth: "frozen-id")
    monkeypatch.setattr(ac_native_collection, "resume_collection",
                        lambda *args: pytest.fail("Planning must not execute"))
    result = list(workbench_command(tmp_path, "ac-collection-plan", ["reviewed.json"]))
    assert "frozen-id" in result[0] and "No solver" in result[0]


def test_training_requires_completed_collection(tmp_path):
    from gridagent.dsr import Study

    study = Study(tmp_path / "studies")
    with pytest.raises(ValueError, match="Finish the collection"):
        list(workbench_command(tmp_path, "ac-train-collection", [study.id]))


@pytest.mark.parametrize("command,args", [("ac-collection-plan", []), ("ac-standard-screening", ["unexpected"]),
                                          ("unknown", [])])
def test_invalid_operation(tmp_path, command, args):
    with pytest.raises(ValueError, match="Invalid research workbench"):
        list(workbench_command(tmp_path, command, args))
