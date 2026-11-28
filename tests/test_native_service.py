import json
import subprocess
import sys

from gridagent.scientific_workspace import set_enabled


def test_native_service_real_process(tmp_path):
    def frame(number, method, params=None):
        return json.dumps({"version": 1, "id": f"{number:032x}",
                           "method": method, "params": params or {}})

    def invoke(*frames):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "gridagent.native_service", str(tmp_path)],
            input="\n".join(frames) + "\n", capture_output=True, text=True, timeout=30, check=True,
        )
        return [json.loads(row) for row in result.stdout.splitlines()]

    hello, denied, unknown, invalid = invoke(
        frame(1, "hello"), frame(2, "workspace.files"),
        frame(3, "execute_python"), frame(4, "hello", {"root": "/other"}),
    )
    assert hello["ok"] and hello["result"]["mode"] == "read-only"
    assert hello["id"] == f"{1:032x}"
    assert not denied["ok"] and not unknown["ok"] and not invalid["ok"]
    set_enabled(tmp_path, True)
    files, runs = invoke(frame(5, "workspace.files"), frame(6, "scientific.runs"))
    assert files["ok"] and files["result"]["files"] == []
    assert runs["ok"]


def test_native_project_browser_is_scoped_and_preserves_revisions(tmp_path):
    import pytest

    from gridagent.native_service import dispatch
    from gridagent.scientific_workspace import write_bytes, write_project

    for method, args in [("workspace.tree", {}), ("workspace.search", {"query": "py"}),
                         ("workspace.inspect", {"path": "study.py"})]:
        with pytest.raises(ValueError, match="disabled"):
            dispatch(tmp_path, method, args)
    set_enabled(tmp_path, True)
    original = write_project(tmp_path, "models/study.py", "x = 1")
    write_bytes(tmp_path, "model.bin", b"\x00\xff")
    (tmp_path / "scientific-project" / "empty").mkdir()
    (tmp_path / "outside.py").write_text("not in the scientific project")
    root = dispatch(tmp_path, "workspace.tree", {})
    assert [row["name"] for row in root["entries"]] == ["empty", "models", "model.bin"]
    assert root["entries"][0]["hasChildren"] is False
    folder = dispatch(tmp_path, "workspace.tree", {"path": "models"})
    assert folder["entries"] == [{"path": "models/study.py", "name": "study.py",
                                  "kind": "file", "sizeBytes": 5}]
    found = dispatch(tmp_path, "workspace.search", {"query": "STUDY"})
    assert found["results"] == [{"path": "models/study.py", "name": "study.py"}]
    assert dispatch(tmp_path, "workspace.search", {"query": "outside"})["results"] == []
    metadata = dispatch(tmp_path, "workspace.inspect", {"path": "models/study.py"})
    assert metadata["sha256"] == original["sha256"] and metadata["text_readable"]
    assert not dispatch(tmp_path, "workspace.inspect", {"path": "model.bin"})["text_readable"]
    for path in ("../", "/outside.py", "C:/outside.py", "models/../outside.py"):
        with pytest.raises(ValueError):
            dispatch(tmp_path, "workspace.tree", {"path": path})
    with pytest.raises(ValueError):
        dispatch(tmp_path, "workspace.tree", {"root": str(tmp_path.parent)})
    with pytest.raises(ValueError):
        dispatch(tmp_path, "workspace.write", {"path": "new.py", "text": "x"})
    assert not (tmp_path / "scientific-project/new.py").exists()


def test_native_project_browser_refuses_links(tmp_path):
    import pytest

    from gridagent.native_service import dispatch
    from gridagent.scientific_workspace import write_project

    set_enabled(tmp_path, True)
    write_project(tmp_path, "study.py", "x = 1")
    external = tmp_path / "private.txt"
    external.write_text("outside")
    try:
        (tmp_path / "scientific-project" / "link.txt").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Platform does not allow test symlinks")
    for method, args in [("workspace.tree", {}), ("workspace.search", {"query": "link"}),
                         ("workspace.inspect", {"path": "link.txt"})]:
        with pytest.raises(ValueError):
            dispatch(tmp_path, method, args)


def test_native_project_mutations_are_granted_and_revision_checked(tmp_path):
    import pytest

    from gridagent.native_service import dispatch

    def call(method, **params):
        return dispatch(tmp_path, method, params, allow_tasks=True)

    with pytest.raises(ValueError, match="disabled"):
        call("workspace.create", path="study.py", kind="file")
    set_enabled(tmp_path, True)
    with pytest.raises(ValueError, match="Unknown"):
        dispatch(tmp_path, "workspace.create", {"path": "study.py", "kind": "file"})
    call("workspace.create", path="models", kind="directory")
    created = call("workspace.create", path="models/study.py", kind="file", text="x = 1")
    revision = created["file"]["versionToken"]
    assert created["entry"]["sizeBytes"] == 5
    with pytest.raises(ValueError, match="exists"):
        call("workspace.create", path="models/STUDY.py", kind="file")
    with pytest.raises(ValueError, match="changed"):
        call("workspace.rename", path="models/study.py", new_path="new.py",
             kind="file", expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="empty"):
        call("workspace.delete", path="models", kind="directory")
    with pytest.raises(ValueError, match="empty"):
        call("workspace.rename", path="models", new_path="other", kind="directory")
    call("workspace.create", path="occupied.py", kind="file")
    with pytest.raises(ValueError, match="exists"):
        call("workspace.rename", path="models/study.py", new_path="occupied.py",
             kind="file", expected_sha256=revision)
    with pytest.raises(ValueError):
        call("workspace.rename", path="models/study.py", new_path="../outside.py",
             kind="file", expected_sha256=revision)
    renamed = call("workspace.rename", path="models/study.py", new_path="new.py",
                   kind="file", expected_sha256=revision)
    assert renamed["entry"]["path"] == "new.py"
    assert call("workspace.inspect", path="new.py")["sha256"] == revision
    with pytest.raises(ValueError, match="changed"):
        call("workspace.delete", path="new.py", kind="file", expected_sha256="0" * 64)
    call("workspace.delete", path="new.py", kind="file", expected_sha256=revision)
    call("workspace.rename", path="models", new_path="empty", kind="directory")
    call("workspace.delete", path="empty", kind="directory")
    assert [row["path"] for row in call("workspace.tree")["entries"]] == ["occupied.py"]
    set_enabled(tmp_path, False)
    with pytest.raises(ValueError, match="disabled"):
        call("workspace.delete", path="occupied.py", kind="file", expected_sha256=revision)
