"""Explicitly authorized mixed-variable AC simulation optimization contracts."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .engineering_ir import DeviceId, EngineeringStudy, ModelIR, StudySpec, fingerprint
from .task_contracts import Contract

Parameter = Literal["voltage_pu", "active_mw", "reactive_mvar"]
Value = Annotated[float, Field(ge=-1e6, le=1e6)]
ALLOWED = {"slack": {"voltage_pu"}, "generator": {"voltage_pu", "active_mw"},
           "storage": {"reactive_mvar"}}


class ContinuousVariable(Contract):
    kind: Literal["continuous"]
    device_id: DeviceId
    parameter: Parameter
    minimum: Value
    maximum: Value

    @model_validator(mode="after")
    def validate_interval(self):
        if self.minimum >= self.maximum:
            raise ValueError("Continuous variable requires a nonempty interval")
        return self


class DiscreteVariable(Contract):
    kind: Literal["discrete"]
    device_id: DeviceId
    parameter: Parameter
    choices: tuple[Value, ...] = Field(min_length=2, max_length=24)

    @model_validator(mode="after")
    def validate_choices(self):
        if tuple(sorted(set(self.choices))) != self.choices:
            raise ValueError("Discrete choices must be unique and increasing")
        return self


Variable = Annotated[ContinuousVariable | DiscreteVariable, Field(discriminator="kind")]


class ACOptimizationSpec(Contract):
    schema_version: Literal[1] = 1
    source: EngineeringStudy
    variables: tuple[Variable, ...] = Field(min_length=1, max_length=8)
    objective: Literal["minimize_worst_voltage_deviation", "minimize_mean_active_loss"]
    max_solver_runs: int = Field(ge=3, le=60)

    @model_validator(mode="after")
    def validate_authorization(self):
        if self.max_solver_runs < 3 * len(self.source.study.scenarios):
            raise ValueError("Budget must cover baseline, at least one candidate and fresh verification")
        keys = [(v.device_id, v.parameter) for v in self.variables]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate optimization variable")
        devices = {row["id"]: row for row in self.source.model.canonical()["devices"]}
        for variable in self.variables:
            row = devices.get(variable.device_id)
            if row is None or variable.parameter not in ALLOWED.get(row["kind"], set()):
                raise ValueError("Only authorized operating setpoints may be optimized")
            baseline = row[variable.parameter]
            if isinstance(variable, ContinuousVariable):
                values = (variable.minimum, variable.maximum)
                if not values[0] <= baseline <= values[1]:
                    raise ValueError("Baseline outside authorized interval")
            else:
                values = variable.choices
                if baseline not in values:
                    raise ValueError("Baseline must be an authorized discrete choice")
            for value in values:
                type(next(d for d in self.source.model.devices if d.id == variable.device_id)).model_validate(
                    {**row, variable.parameter: value})
        return self

    def baseline(self):
        devices = {row.id: row for row in self.source.model.devices}
        return tuple(float(getattr(devices[v.device_id], v.parameter)) for v in self.variables)

    def candidate(self, values):
        if len(values) != len(self.variables):
            raise ValueError("Incorrect candidate dimension")
        data = self.source.model.canonical()
        devices = {row["id"]: row for row in data["devices"]}
        for variable, value in zip(self.variables, values, strict=True):
            if isinstance(variable, ContinuousVariable):
                valid = variable.minimum <= value <= variable.maximum
            else:
                valid = value in variable.choices
            if not valid:
                raise ValueError("Candidate outside authorized domain")
            devices[variable.device_id][variable.parameter] = value
        # Candidate revisions all branch from the immutable baseline; content hashes identify them.
        if tuple(values) != self.baseline():
            data["revision"] += 1
        model = ModelIR.model_validate(data)
        study = StudySpec.model_validate({
            **self.source.study.model_dump(mode="json"),
            "model_sha256": model.sha256(),
            "max_runs": len(self.source.study.scenarios),
        })
        return EngineeringStudy(model=model, study=study)

    def sha256(self):
        return fingerprint(self.model_dump(mode="json"))


def next_candidate(spec: ACOptimizationSpec, observations):
    """Deterministic mixed coordinate/pattern search; no claim of global optimality."""
    baseline = spec.baseline()
    if not observations:
        return baseline
    visited = {tuple(row["values"]) for row in observations}
    feasible = [row for row in observations if row["status"] == "feasible"]
    best = min(feasible, key=lambda row: (row["objective"], tuple(row["values"])), default=None)
    anchor = tuple(best["values"]) if best is not None else baseline
    # Coarse-to-fine normalized steps, interleaved with neighboring discrete choices.
    for fraction in (0.5, 0.25, 0.125, 0.0625, 0.03125):
        for index, variable in enumerate(spec.variables):
            current = anchor[index]
            if isinstance(variable, ContinuousVariable):
                step = fraction * (variable.maximum - variable.minimum)
                choices = (max(variable.minimum, current - step), min(variable.maximum, current + step))
            else:
                choices = sorted(variable.choices, key=lambda value, current=current: (abs(value-current), value))
            for value in choices:
                candidate = (*anchor[:index], float(value), *anchor[index+1:])
                if candidate not in visited:
                    return candidate
    return None
