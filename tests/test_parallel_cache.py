import json
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from gridagent.evidence import AC_FILES, capture_evidence
from gridagent.execution_plan import fixed_plan
from gridagent.parallel_execution import ac_workers, run_batch
from gridagent.store import ResearchStore
from gridagent.verified_cache import VerifiedCache


def test_batch_is_concurrent_but_returns_input_order():
    barrier = Barrier(2)
    guard = Lock()
    running = 0
    peak = 0

    def launch(value):
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
        barrier.wait(timeout=5)
        with guard:
            running -= 1
        return value

    assert run_batch([2, 1], workers=2, launch=launch, cancelled=lambda: False) == [2, 1]
    assert peak == 2


def test_batch_cancellation_and_unknown_exception():
    def launch(value):
        raise RuntimeError("internal payload")

    assert run_batch([1], workers=1, launch=launch, cancelled=lambda: True) == [
        {"launch": "not_started"}]
    assert run_batch([1], workers=1, launch=launch, cancelled=lambda: False) == [
        {"launch": "exception", "launch_error_type": "RuntimeError"}]
    with pytest.raises(ValueError, match="worker limit"):
        run_batch([1, 2], workers=1, launch=launch, cancelled=lambda: False)


def test_worker_configuration(monkeypatch):
    monkeypatch.delenv("GRIDAGENT_AC_WORKERS", raising=False)
    assert ac_workers() == 1
    monkeypatch.setenv("GRIDAGENT_AC_WORKERS", "5")
    with pytest.raises(ValueError, match="between 1 and 4"):
        ac_workers()


def cache_fixture(tmp_path):
    root = tmp_path
    store = ResearchStore(root / "research.sqlite3")
    cache = VerifiedCache(store, root, {"backend_version": "fixture", "schema": 1})
    request = {"backend": "pandapower", "analysis": "power_flow"}
    plan = fixed_plan(family="ac_steady_state", model_sha256="a" * 64, study_sha256="b" * 64,
                      requests=[("base", request)], max_solver_runs=1)
    verdict = {"passed": True, "checks": [{"id": "balance", "passed": True}]}
    origin = "a" * 32
    folder = root / "runs" / origin
    folder.mkdir(parents=True)
    for name in AC_FILES:
        (folder / name).write_text("fixture", encoding="utf-8")
    (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
    result = {"backend": "pandapower", "status": "ok", "run_id": origin, "version": "fixture"}
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    record = capture_evidence(root, plan, "base", origin, request, version="fixture", verdict=verdict)
    assert record.status == "verified"
    key = cache.key(plan, request, {"voltage_min": 0.9})
    cache.publish(key, record, verdict)
    return SimpleNamespace(cache=cache, root=root, plan=plan, request=request, key=key,
                           origin=origin, folder=folder, verdict=verdict, record=record)


def test_cache_rechecks_then_copies_with_new_identity(tmp_path):
    f = cache_fixture(tmp_path)
    calls = []

    def verify(result):
        calls.append(result["run_id"])
        return f.verdict

    new = "b" * 32
    assert f.cache.restore(f.key, f.request, new, recheck=verify, cancelled=lambda: False) == f.origin
    assert calls == [f.origin]
    result = json.loads((f.root / "runs" / new / "result.json").read_text(encoding="utf-8"))
    assert result["run_id"] == new
    assert result["cache_origin_run_id"] == f.origin
    (f.root / "runs" / new / "bus.csv").write_text("changed", encoding="utf-8")
    assert (f.folder / "bus.csv").read_text(encoding="utf-8") == "fixture"


def test_cache_fails_closed_on_changes_or_failed_recheck(tmp_path):
    f = cache_fixture(tmp_path)
    destination = "b" * 32
    assert f.cache.restore(f.key, f.request, destination, recheck=lambda _: {"passed": False},
                           cancelled=lambda: False) is None
    assert not (f.root / "runs" / destination).exists()
    (f.folder / "bus.csv").write_text("changed", encoding="utf-8")
    assert f.cache.restore(f.key, f.request, destination, recheck=lambda _: f.verdict,
                           cancelled=lambda: False) is None
    assert not (f.root / "runs" / destination).exists()


def test_cache_keys_separate_limits_request_and_runtime(tmp_path):
    f = cache_fixture(tmp_path)
    assert f.cache.key(f.plan, f.request, {"voltage_min": 0.95}) != f.key
    assert f.cache.key(f.plan, {**f.request, "load_scale": 1.2}, {"voltage_min": 0.9}) != f.key
    other = VerifiedCache(f.cache.store, f.root, {"backend_version": "different", "schema": 1})
    assert other.key(f.plan, f.request, {"voltage_min": 0.9}) != f.key
    assert other.restore(other.key(f.plan, f.request, {"voltage_min": 0.9}),
                         f.request, "b" * 32, recheck=lambda _: f.verdict, cancelled=lambda: False) is None
