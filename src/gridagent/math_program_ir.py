"""Typed, bounded linear and mixed-integer mathematical programs."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .engineering_ir import fingerprint
from .task_contracts import Contract

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Number = Annotated[float, Field(ge=-1e9, le=1e9)]


class DecisionVariable(Contract):
    id: Identifier
    kind: Literal["continuous", "integer", "binary"] = "continuous"
    lower: Number
    upper: Number
    unit: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def bounds(self):
        if self.lower > self.upper:
            raise ValueError("Variable lower bound exceeds upper bound")
        if self.kind != "continuous" and (not self.lower.is_integer() or not self.upper.is_integer()):
            raise ValueError("Integer variables require integer bounds")
        if self.kind == "binary" and not 0 <= self.lower <= self.upper <= 1:
            raise ValueError("Binary bounds must be within [0, 1]")
        return self


class LinearTerm(Contract):
    variable: Identifier
    coefficient: Number


class LinearConstraint(Contract):
    id: Identifier
    terms: tuple[LinearTerm, ...] = Field(min_length=1, max_length=200)
    lower: Number | None = None
    upper: Number | None = None
    unit: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def bounds(self):
        if self.lower is None and self.upper is None:
            raise ValueError("Constraint requires at least one bound")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("Constraint lower bound exceeds upper bound")
        return self


class LinearObjective(Contract):
    sense: Literal["minimize", "maximize"] = "minimize"
    terms: tuple[LinearTerm, ...] = Field(min_length=1, max_length=200)
    constant: Number = 0
    unit: str = Field(min_length=1, max_length=40)


class MathematicalProgram(Contract):
    schema_version: Literal[1] = 1
    family: Literal["linear_program"] = "linear_program"
    description: str = Field(min_length=1, max_length=4000)
    variables: tuple[DecisionVariable, ...] = Field(min_length=1, max_length=200)
    constraints: tuple[LinearConstraint, ...] = Field(default=(), max_length=500)
    objective: LinearObjective
    time_limit_s: int = Field(default=30, ge=1, le=120)
    node_limit: int = Field(default=10000, ge=1, le=100000)

    @model_validator(mode="after")
    def validate_references(self):
        ids = {v.id for v in self.variables}
        if len(ids) != len(self.variables):
            raise ValueError("Duplicate variable ID")
        if len({c.id for c in self.constraints}) != len(self.constraints):
            raise ValueError("Duplicate constraint ID")
        for expression in (self.objective, *self.constraints):
            references = [term.variable for term in expression.terms]
            if len(set(references)) != len(references) or not set(references) <= ids:
                raise ValueError("Duplicate or unknown expression variable")
        return self

    def route(self):
        return "scipy-highs-lp" if all(v.kind == "continuous" for v in self.variables) else "scipy-highs-milp"

    def canonical(self):
        data = self.model_dump(mode="json")
        for group in ("variables", "constraints"):
            data[group].sort(key=lambda row: row["id"])
        for expression in (data["objective"], *data["constraints"]):
            expression["terms"].sort(key=lambda term: term["variable"])
        return data

    def sha256(self):
        return fingerprint(self.canonical())
