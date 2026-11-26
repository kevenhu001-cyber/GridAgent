import pytest

from gridagent.workspace import artifact_folder, waveform, waveform_text


def test_waveform_envelope(tmp_path):
    identifier = "a" * 32
    folder = tmp_path / "runs" / identifier
    folder.mkdir(parents=True)
    (folder / "voltage.csv").write_text("time_s,B5\n0,1\n0.01,0.1\n1,1\n")
    data = waveform(tmp_path, identifier, "B5")
    text = waveform_text(data)
    assert "min 0.1" in text
    assert "3 samples" in text
    with pytest.raises(ValueError):
        waveform(tmp_path, identifier, "not-found")
    with pytest.raises(ValueError):
        artifact_folder(tmp_path, "runs", "../secret")


def test_study_waveform_cannot_escape(tmp_path):
    identifier = "b" * 32
    folder = tmp_path / "studies" / identifier
    folder.mkdir(parents=True)
    with pytest.raises(ValueError):
        waveform(tmp_path, identifier, relative="../../outside.csv")
