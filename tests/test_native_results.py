import json

import pytest

from gridagent.native_results import read_table


def test_native_tables_are_scoped(tmp_path):
    rid = "a"*32
    folder = tmp_path / "runs" / rid
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps({"backend": "pandapower"}))
    (folder / "res_bus.csv").write_text("index,vm_pu\n0,1\n1,0.95\n")
    result = read_table(tmp_path, rid, "res_bus", limit=1)
    assert result["next_offset"] == 1
    assert result["rows"] == [["0", "1"]]
    with pytest.raises(ValueError):
        read_table(tmp_path, rid, "../secret")
