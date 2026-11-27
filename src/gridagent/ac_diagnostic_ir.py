"""Single-factor AC diagnostic experiments with explicit counterfactual authorization."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .ac_check_ir import ACCheckSpec, Snapshot
from .engineering_ir import fingerprint
from .math_program_ir import Identifier
from .task_contracts import Contract


class VoltageProbe(Contract):
    kind: Literal["voltage_setpoint"]
    device: Identifier
    value_pu: float = Field(ge=0.8, le=1.2)


class ReactiveProbe(Contract):
    kind: Literal["storage_reactive"]
    device: Identifier
    value_mvar: float = Field(ge=-1e6, le=1e6)
    minimum_mvar: float = Field(ge=-1e6, le=1e6)
    maximum_mvar: float = Field(ge=-1e6, le=1e6)

    @model_validator(mode="after")
    def authorized_range(self):
        if not self.minimum_mvar <= self.value_mvar <= self.maximum_mvar:
            raise ValueError("Storage Q outside explicitly authorized range")
        return self


Probe = Annotated[VoltageProbe | ReactiveProbe, Field(discriminator="kind")]


class ACDiagnosticExperiment(Contract):
    schema_version: Literal[1] = 1
    source_study_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    source_report_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    snapshot: Snapshot
    target_scope: Literal["ac_native", "ac_physical"]
    target_check: str = Field(min_length=1, max_length=150)
    probes: tuple[Probe, ...] = Field(min_length=1, max_length=8)
    max_solver_runs: int = Field(ge=2, le=9)

    @model_validator(mode="after")
    def budget(self):
        if len(self.probes)+1 > self.max_solver_runs:
            raise ValueError("Budget must include fresh baseline and every probe")
        keys = [(p.kind, p.device, p.value_pu if isinstance(p, VoltageProbe) else p.value_mvar)
                for p in self.probes]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate AC diagnostic probe")
        if self.target_scope == "ac_native":
            if self.target_check not in {"voltage_operating_range", "res_line_loading"}:
                raise ValueError("Unsupported native diagnostic target")
        elif not self.target_check.startswith(("reactive:", "active-limit:")):
            raise ValueError("Unsupported supplementary diagnostic target")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        data["probes"].sort(key=lambda p: (p["kind"], p["device"], p.get("value_pu", p.get("value_mvar"))))
        return data

    def sha256(self):
        return fingerprint(self.canonical())


def compile_probes(spec, original):
    spec = ACDiagnosticExperiment.model_validate(spec.canonical())
    original = ACCheckSpec.model_validate(original)
    if spec.snapshot not in original.snapshots:
        raise ValueError("Snapshot not in original AC study")
    cases = []
    for index, probe in enumerate((None, *spec.probes)):
        data = original.canonical()
        data["snapshots"] = [spec.snapshot.model_dump(mode="json")]
        change = None
        if probe is not None:
            row = next((r for r in data["model"]["devices"] if r["id"] == probe.device), None)
            if row is None:
                raise ValueError("Unknown AC diagnostic device")
            if isinstance(probe, VoltageProbe):
                if row["kind"] not in {"slack", "generator"}:
                    raise ValueError("Voltage probe requires an existing regulating unit")
                field, value = "voltage_pu", probe.value_pu
            else:
                if row["kind"] != "storage":
                    raise ValueError("Reactive probe requires an existing storage device")
                field, value = "reactive_mvar", probe.value_mvar
                if not probe.minimum_mvar <= row[field] <= probe.maximum_mvar:
                    raise ValueError("Original storage Q outside declared probe range")
            if row[field] == value:
                raise ValueError("Diagnostic probe makes no change")
            change = {"device": probe.device, "field": field, "before": row[field], "after": value}
            row[field] = value
            data["model"]["revision"] += 1
        variant = ACCheckSpec.model_validate(data)
        cases.append(({"index": index, "probe": probe.model_dump(mode="json") if probe else None,
                       "change": change, "ac_spec_sha256": variant.sha256()}, variant))
    return cases
