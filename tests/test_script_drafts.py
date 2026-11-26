import pytest

from gridagent.script_drafts import draft_script, list_drafts


def test_draft_is_never_executed(tmp_path):
    source = "raise RuntimeError('must not execute')"
    row = draft_script(tmp_path, "test", source)
    assert not row["executed"]
    assert (tmp_path / "drafts" / row["id"] / "script.py").read_text() == source
    assert list_drafts(tmp_path)[0]["status"] == "awaiting_user_review"
    with pytest.raises(SyntaxError):
        draft_script(tmp_path, "invalid", "if")
