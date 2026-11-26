import zipfile

import pytest

from gridagent.models import list_models, register_model, resolve_model


def workbook(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")


def test_explicit_registration_and_hash(tmp_path):
    src = tmp_path / "input.xlsx"
    workbook(src)
    root = tmp_path / "workspace"
    identifier = register_model(root, src)
    assert identifier == register_model(root, src)
    assert any(r["id"] == identifier for r in list_models(root))
    path = resolve_model(root, identifier)
    src.unlink()
    assert resolve_model(root, identifier) == path
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash"):
        resolve_model(root, identifier)
    with pytest.raises(ValueError):
        resolve_model(root, "../input")


def test_reject_external_links(tmp_path):
    src = tmp_path / "input.xlsx"
    workbook(src)
    with zipfile.ZipFile(src, "a") as archive:
        archive.writestr("xl/externalLinks/externalLink1.xml", "bad")
    with pytest.raises(ValueError, match="external"):
        register_model(tmp_path / "workspace", src)
