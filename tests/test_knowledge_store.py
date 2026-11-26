import json

from gridagent.knowledge import KnowledgeIndex
from gridagent.knowledge_store import import_pack, list_packs, reference_rows


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
