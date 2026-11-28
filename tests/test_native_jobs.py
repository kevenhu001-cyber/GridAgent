import pytest

from gridagent import native_jobs as jobs
from gridagent import scientific_workspace as ws
from gridagent.native_service import dispatch


def test_job_identity_and_cancellation(tmp_path):
    ws.set_enabled(tmp_path, True)
    launches = []
    first = "a" * 32
    second = "b" * 32

    def launch(root, identifier):
        launches.append(identifier)

    def submit(identifier, entry="study.py"):
        return jobs.submit(tmp_path, identifier, entry, [], [], launch=launch)

    assert dispatch(tmp_path, "job.latest", {}) == {"job": None}
    assert not (tmp_path / "native-jobs").exists()
    assert submit(first)["status"] == "queued"
    assert dispatch(tmp_path, "job.latest", {})["job"] == {
        "job_id": first, "status": "queued", "outcome": "unconfirmed",
        "run_id": None, "cancellation_requested": False,
    }
    assert submit(first)["status"] == "queued"
    assert launches == [first]
    with pytest.raises(ValueError, match="another request"):
        submit(first, "another.py")
    with pytest.raises(ValueError, match="active"):
        submit(second)
    assert jobs.cancel(tmp_path, first)["cancellation_requested"]
    jobs.run_worker(tmp_path, first, execute=lambda *a, **k: pytest.fail("Cancelled job executed"))
    assert jobs.status(tmp_path, first)["status"] == "cancelled"
    assert submit(second)["status"] == "queued"

    def fake_execute(root, entry, arguments, plugin_ids, run_id, cancelled):
        assert run_id == second
        assert not cancelled()
        return {"status": "ok", "run_id": run_id, "verification": "unverified_script_output"}

    jobs.run_worker(tmp_path, second, execute=fake_execute)
    jobs.run_worker(tmp_path, second, execute=lambda *a, **k: pytest.fail("Duplicate execution"))
    assert jobs.status(tmp_path, second)["run_id"] == second
    assert jobs.status(tmp_path, second)["status"] == "ok"
    recorded = dispatch(tmp_path, "job.latest", {})["job"]
    assert (recorded["job_id"], recorded["run_id"], recorded["outcome"]) == (second, second, "recorded_terminal")
    assert launches == [first, second]
    ws.set_enabled(tmp_path, False)
    with pytest.raises(ValueError, match="disabled"):
        dispatch(tmp_path, "job.latest", {})


def test_mutations_default_disabled_and_hash_guarded(tmp_path):
    payload = {"path": "study.py", "text": "print(1)"}
    ws.set_enabled(tmp_path, True)
    with pytest.raises(ValueError, match="Unknown native method"):
        dispatch(tmp_path, "workspace.write", payload)
    saved = dispatch(tmp_path, "workspace.write", payload, allow_tasks=True)
    with pytest.raises(ValueError, match="SHA-256"):
        dispatch(tmp_path, "workspace.write", payload, allow_tasks=True)
    updated = dispatch(tmp_path, "workspace.write",
                       {**payload, "text": "print(2)", "expected_sha256": saved["sha256"]}, allow_tasks=True)
    assert updated["sha256"] != saved["sha256"]
    ws.set_enabled(tmp_path, False)
    with pytest.raises(ValueError, match="disabled"):
        dispatch(tmp_path, "workspace.write", payload, allow_tasks=True)


def test_worker_revoked_grant(tmp_path):
    ws.set_enabled(tmp_path, True)
    identifier = "c" * 32
    jobs.submit(tmp_path, identifier, "study.py", [], [], launch=lambda *args: None)
    ws.set_enabled(tmp_path, False)
    jobs.run_worker(tmp_path, identifier, execute=lambda *a, **k: pytest.fail("Revoked grant executed"))
    assert jobs.status(tmp_path, identifier)["status"] == "cancelled"


def test_shell_guest_launcher_validates_and_compiles():
    from gridagent.scientific_runtime import isolated_shell_source

    source = isolated_shell_source("powershell", "Write-Output '42'")
    compile(source, "guest-launcher.py", "exec")
    assert b"subprocess.run" in source
    assert b"shell=True" not in source
    with pytest.raises(ValueError):
        isolated_shell_source("unknown", "echo 42")
    with pytest.raises(ValueError):
        isolated_shell_source("bash", "x" * 8001)


def test_kernel_batch_uses_existing_durable_job(tmp_path):
    ws.set_enabled(tmp_path, True)
    identifier = "d" * 32
    cells = ["x = 2", "print(x)"]
    jobs.submit(tmp_path, identifier, "internal-kernel.py", [], [],
                kernel_cells=cells, launch=lambda *args: None)

    def fake_execute(root, **request):
        assert request["kernel_cells"] == cells
        assert request["run_id"] == identifier
        return {"status": "ok", "run_id": identifier}

    jobs.run_worker(tmp_path, identifier, execute=fake_execute)
    assert jobs.status(tmp_path, identifier)["status"] == "ok"
    with pytest.raises(ValueError, match="another request"):
        jobs.submit(tmp_path, identifier, "internal-kernel.py", [], [],
                    kernel_cells=["x = 3"], launch=lambda *args: None)
    with pytest.raises(ValueError, match="Unknown"):
        dispatch(tmp_path, "job.submit", {"job_id": "e" * 32, "entry": "internal-kernel.py",
                                         "kernel_cells": cells})
