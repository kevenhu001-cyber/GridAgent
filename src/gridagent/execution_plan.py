"""Immutable, versioned execution DAG for fixed engineering studies."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .engineering_ir import fingerprint
from .task_contracts import Contract

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
NodeId = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")]


class PlanNode(Contract):
    id: NodeId
    kind: Literal["solve", "verify", "aggregate"]
    depends_on: tuple[NodeId, ...] = Field(default=(), max_length=60)
    scenario: NodeId | None = None
    request_sha256: Hash | None = None

    @model_validator(mode="after")
    def check_shape(self):
        if len(set(self.depends_on)) != len(self.depends_on) or self.id in self.depends_on:
            raise ValueError("Duplicate or self dependency")
        if self.kind == "aggregate":
            if self.scenario is not None or self.request_sha256 is not None or not self.depends_on:
                raise ValueError("Aggregation requires verification dependencies only")
        elif self.scenario is None or self.request_sha256 is None:
            raise ValueError("Solve and verification nodes must identify their input")
        elif self.kind == "solve" and self.depends_on:
            raise ValueError("Fixed-study solve nodes cannot depend on other nodes")
        elif self.kind == "verify" and len(self.depends_on) != 1:
            raise ValueError("Verification requires exactly one solve dependency")
        return self


class ExecutionPlan(Contract):
    schema_version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    family: Literal["ac_steady_state", "hourly_linear_dispatch"]
    model_sha256: Hash
    study_sha256: Hash
    evaluator: Literal["ac-research-v1", "native-dispatch-v1"]
    max_solver_runs: int = Field(ge=1, le=60)
    nodes: tuple[PlanNode, ...] = Field(min_length=3, max_length=121)

    @model_validator(mode="after")
    def check_graph(self):
        by_id = {node.id: node for node in self.nodes}
        if len(by_id) != len(self.nodes):
            raise ValueError("Duplicate plan node ID")
        if (self.family == "ac_steady_state") != (self.evaluator == "ac-research-v1"):
            raise ValueError("Evaluator does not match model family")
        solves = [node for node in self.nodes if node.kind == "solve"]
        verifies = [node for node in self.nodes if node.kind == "verify"]
        aggregates = [node for node in self.nodes if node.kind == "aggregate"]
        if not solves or len(solves) > self.max_solver_runs:
            raise ValueError("Plan exceeds solver budget")
        if len({node.scenario for node in solves}) != len(solves):
            raise ValueError("Duplicate solve scenario")
        for node in self.nodes:
            if any(dep not in by_id for dep in node.depends_on):
                raise ValueError("Unknown dependency")
        if len(aggregates) != 1 or set(aggregates[0].depends_on) != {node.id for node in verifies}:
            raise ValueError("Aggregate must depend on every verification")
        if len(verifies) != len(solves) or {node.depends_on[0] for node in verifies} != {node.id for node in solves}:
            raise ValueError("Every solve requires exactly one verification")
        for node in verifies:
            parent = by_id[node.depends_on[0]]
            if parent.kind != "solve" or (node.scenario, node.request_sha256) != (
                    parent.scenario, parent.request_sha256):
                raise ValueError("Verification must match the exact solve input")
        self.topological_order()
        return self

    def topological_order(self):
        remaining = {node.id: node for node in self.nodes}
        ordered = []
        done = set()
        while remaining:
            ready = sorted(key for key, node in remaining.items() if set(node.depends_on) <= done)
            if not ready:
                raise ValueError("Cyclic execution plan")
            for key in ready:
                ordered.append(remaining.pop(key))
                done.add(key)
        return tuple(ordered)

    def ready(self, completed=()):
        """Dependencies are satisfied by completed nodes, not merely reserved nodes."""
        done = set(completed)
        nodes = {node.id: node for node in self.nodes}
        if not done <= nodes.keys() or any(not set(nodes[key].depends_on) <= done for key in done):
            raise ValueError("Inconsistent completed node set")
        return tuple(node for node in self.topological_order()
                     if node.id not in done and set(node.depends_on) <= done)

    def sha256(self):
        return fingerprint(self.model_dump(mode="json"))

    def solve_for(self, scenario, request):
        node = next((n for n in self.nodes if n.kind == "solve" and n.scenario == scenario), None)
        if node is None or node.request_sha256 != fingerprint(request):
            raise ValueError("Native request does not match frozen execution plan")
        return node


def fixed_plan(*, family, model_sha256, study_sha256, requests, max_solver_runs):
    """Plan one independent solve and one verification for each ordered scenario."""
    nodes = []
    verify_ids = []
    for index, (scenario, request) in enumerate(requests, 1):
        solve_id, verify_id = f"solve-{index:03}", f"verify-{index:03}"
        fields = {"scenario": scenario, "request_sha256": fingerprint(request)}
        nodes.extend((PlanNode(id=solve_id, kind="solve", **fields),
                      PlanNode(id=verify_id, kind="verify", depends_on=(solve_id,), **fields)))
        verify_ids.append(verify_id)
    nodes.append(PlanNode(id="aggregate", kind="aggregate", depends_on=tuple(verify_ids)))
    return ExecutionPlan(
        family=family, model_sha256=model_sha256, study_sha256=study_sha256,
        evaluator="ac-research-v1" if family == "ac_steady_state" else "native-dispatch-v1",
        max_solver_runs=max_solver_runs, nodes=tuple(nodes),
    )


def ac_plan(manifest, provenance):
    program = manifest.program.model_dump(mode="json")
    return fixed_plan(family="ac_steady_state", model_sha256=provenance["model_sha256"],
                      study_sha256=provenance["study_sha256"], max_solver_runs=manifest.max_runs,
                      requests=[(scenario.name, scenario.materialize(program)) for scenario in manifest.scenarios])


def dispatch_plan(program, provenance):
    return fixed_plan(family="hourly_linear_dispatch", model_sha256=provenance["model_sha256"],
                      study_sha256=provenance["study_sha256"], max_solver_runs=1,
                      requests=[("dispatch", program)])
