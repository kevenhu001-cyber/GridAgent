"""Unweighted network topology; not electrical impedance distance."""
from collections import deque


def topology_summary(ss):
    buses = [str(x) for x in ss.Bus.idx.v]
    known = set(buses)
    branches = []
    neighbors = {b: set() for b in buses}
    for idx, a, b, active in zip(ss.Line.idx.v, ss.Line.bus1.v, ss.Line.bus2.v, ss.Line.u.v):
        a, b = str(a), str(b)
        if a not in known or b not in known:
            raise ValueError("Branch references unknown bus")
        branches.append({"id": str(idx), "from": a, "to": b, "in_service": bool(active)})
        if active:
            neighbors[a].add(b)
            neighbors[b].add(a)
    remaining = set(buses)
    components = []
    while remaining:
        start = min(remaining)
        seen = {start}
        queue = deque([start])
        while queue:
            for node in neighbors[queue.popleft()] - seen:
                seen.add(node)
                queue.append(node)
        remaining -= seen
        components.append(sorted(seen))
    return {"buses": buses, "branches": branches, "bus_count": len(buses),
            "branch_count": len(branches), "active_branch_count": sum(b["in_service"] for b in branches),
            "component_count": len(components), "components": components,
            "degree": {b: len(neighbors[b]) for b in buses}}


def shortest_path(topology, origin, destination):
    neighbors = {b: set() for b in topology["buses"]}
    if origin not in neighbors or destination not in neighbors:
        raise ValueError("Unknown bus")
    for branch in topology["branches"]:
        if branch["in_service"]:
            a, b = branch["from"], branch["to"]
            neighbors[a].add(b)
            neighbors[b].add(a)
    queue = deque([[origin]])
    seen = {origin}
    while queue:
        path = queue.popleft()
        if path[-1] == destination:
            return {"path": path, "hops": len(path)-1, "distance_type": "unweighted_branch_hops"}
        for node in sorted(neighbors[path[-1]] - seen):
            seen.add(node)
            queue.append([*path, node])
    return {"path": None, "hops": None, "distance_type": "unweighted_branch_hops"}
