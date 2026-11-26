import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path


def load_sync():
    script = Path(__file__).resolve().parents[1] / "scripts" / "sync_benchmark.py"
    spec = importlib.util.spec_from_file_location("sync_benchmark", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_asset_cache_is_verified_and_repairs_corruption(tmp_path, monkeypatch):
    sync = load_sync()
    payload = b"public benchmark data"
    digest = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    manifest = tmp_path / "src" / "gridagent" / "paper_assets.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "repository": "example/public",
        "commit": "pinned",
        "files": {"case.txt": digest},
    }), encoding="utf-8")
    monkeypatch.setattr(sync, "__file__", str(tmp_path / "scripts" / "sync_benchmark.py"))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "case.txt").write_bytes(payload)
    (cache / "unlisted.txt").write_bytes(b"do not copy")
    output = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["sync_benchmark", str(output), "--cache-dir", str(cache)])
    requests = []

    def download(url, timeout):
        requests.append(url)
        return io.BytesIO(payload)

    monkeypatch.setattr(sync, "urlopen", download)
    sync.main()
    assert (output / "case.txt").read_bytes() == payload
    assert not (output / "unlisted.txt").exists()
    assert not requests

    (cache / "case.txt").write_bytes(b"invalid")
    sync.main()
    assert not requests  # Valid destination wins even when the source cache is corrupt.

    (output / "case.txt").write_bytes(b"invalid")
    sync.main()
    assert len(requests) == 1
    assert (output / "case.txt").read_bytes() == payload
