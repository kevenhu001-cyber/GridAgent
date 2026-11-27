"""Explicit authorization for single-contingency diagnostic counterfactuals."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .commitment_ir import UnitCommitment
from .engineering_ir import fingerprint
from .math_program_ir import Identifier
from .task_contracts import Contract


class ContingencyProbe(Contract):
    kind: Literal["line", "unit"]
    component: Identifier


class DiagnosticExperiment(Contract):
    schema_version: Literal[1] = 1
    source_study_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    source_report_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    probes: tuple[ContingencyProbe, ...] = Field(min_length=1, max_length=8)
    max_solver_calls: int = Field(ge=2, le=9)

    @model_validator(mode="after")
    def validate_budget(self):
        if len({(p.kind, p.component) for p in self.probes}) != len(self.probes):
            raise ValueError("Duplicate diagnostic probe")
        if 1 + len(self.probes) > self.max_solver_calls:
            raise ValueError("Diagnostic budget must include base and all authorized probes")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        data["probes"].sort(key=lambda row: (row["kind"], row["component"]))
        return data

    def sha256(self):
        return fingerprint(self.canonical())


def compile_probes(spec, original):
    """Only remove selected contingency rows; preserve all base operating assumptions."""
    spec = DiagnosticExperiment.model_validate(spec.canonical())
    original = UnitCommitment.model_validate(original)
    if original.network is None or original.network.security is None:
        raise ValueError("Diagnostic probes require a security-constrained commitment")
    security = original.network.security
    allowed = {("line", key) for key in security.outage_lines} | {
        ("unit", key) for key in security.outage_units}
    if any((p.kind, p.component) not in allowed for p in spec.probes):
        raise ValueError("Probe must refer to an originally authorized contingency")
    cases = []
    for index, probe in enumerate((None, *spec.probes)):
        data = original.canonical()
        if probe is None:
            data["network"].pop("security")
        else:
            field = "outage_lines" if probe.kind == "line" else "outage_units"
            data["network"]["security"] = {field: [probe.component]}
        variant = UnitCommitment.model_validate(data)
        cases.append(({"index": index, "probe": probe.model_dump(mode="json") if probe else None,
                       "program_sha256": variant.sha256()}, variant))
    return cases
