from types import SimpleNamespace as NS

from gridagent.topology import shortest_path, topology_summary


def test_disconnected_and_parallel_branches():
    ss = NS(Bus=NS(idx=NS(v=[1,2,3,4])),
            Line=NS(idx=NS(v=["a","b","c","d"]), bus1=NS(v=[1,1,2,3]),
                    bus2=NS(v=[2,2,3,4]), u=NS(v=[1,1,1,0])))
    topology = topology_summary(ss)
    assert topology["component_count"] == 2
    assert topology["active_branch_count"] == 3
    assert shortest_path(topology, "1", "3")["hops"] == 2
    assert shortest_path(topology, "1", "4")["path"] is None
