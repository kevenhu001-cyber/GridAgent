import json

import pytest

from gridagent.knowledge import KnowledgeIndex
from gridagent.knowledge_store import import_pack, list_packs, pack_page, reference_rows


def test_reference_import_is_deduplicated_and_separate(tmp_path):
    source = tmp_path / "pack.json"
    source.write_text(json.dumps({"title": "Notes", "entries": [{
        "kind": "option", "function": "scenario_power_flow", "option": "load_scale",
        "description": "load_scale controls load multiplier", "source": "Manual p. 10", "version": "1"
    }]}))
    root = tmp_path / "workspace"
    first = import_pack(root, source)
    assert import_pack(root, source) == first
    assert len(list_packs(root)) == 1
    index = KnowledgeIndex(reference_rows(root))
    result = index.retrieve({"options": [{"description": "load_scale", "function": "scenario_power_flow"}]})
    assert not result["options"]
    assert result["references"][0]["source"] == "Manual p. 10"
    assert not index.feedback("scenario_power_flow", ["load_scale"])["contracts"]


def test_reference_pack_pages_preserve_sources_and_reject_invalid_requests(tmp_path):
    source = tmp_path / "pack.json"
    entries = [{"kind": "concept", "function": f"f{i}", "description": "Notes",
                "source": "Manual", "version": "2"} for i in range(21)]
    source.write_text(json.dumps({"title": "Notes", "entries": entries}), encoding="utf-8")
    root = tmp_path / "workspace"
    identifier, _ = import_pack(root, source)
    first = pack_page(root, identifier)
    last = pack_page(root, identifier, 20)
    assert first["total"] == 21 and len(first["entries"]) == 10
    assert last["entries"][0]["function"] == "f20"
    assert last["entries"][0]["source"] == "Manual"
    assert last["entries"][0]["version"] == "2"
    for invalid in (-10, 1, 30, 1000, True, "10"):
        with pytest.raises(ValueError):
            pack_page(root, identifier, invalid)
    with pytest.raises(ValueError):
        pack_page(root, "../pack.json")
    with pytest.raises(ValueError):
        pack_page(root, "0" * 64)
