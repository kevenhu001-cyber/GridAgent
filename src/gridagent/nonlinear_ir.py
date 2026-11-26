"""Bounded polynomial NLP contracts; no executable expression strings."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .engineering_ir import fingerprint
from .math_program_ir import DecisionVariable, Identifier, Number
from .task_contracts import Contract


class Power(Contract):
    variable: Identifier
    exponent: int = Field(ge=1, le=4)


class Monomial(Contract):
    coefficient: Annotated[float, Field(ge=-1e6, le=1e6)]
    powers: tuple[Power, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def validate_degree(self):
        if sum(p.exponent for p in self.powers) > 4 or len({p.variable for p in self.powers}) != len(self.powers):
            raise ValueError("Monomial degree exceeds four or repeats a variable")
        return self


class PolynomialObjective(Contract):
    sense: Literal["minimize", "maximize"] = "minimize"
    terms: tuple[Monomial, ...] = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=40)


class PolynomialConstraint(Contract):
    id: Identifier
    terms: tuple[Monomial, ...] = Field(min_length=1, max_length=128)
    lower: Number | None = None
    upper: Number | None = None
    unit: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def bounds(self):
        if self.lower is None and self.upper is None:
            raise ValueError("Constraint requires a bound")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("Invalid constraint interval")
        return self


class NonlinearProgram(Contract):
    schema_version: Literal[1] = 1
    family: Literal["polynomial_nlp"] = "polynomial_nlp"
    description: str = Field(min_length=1, max_length=4000)
    variables: tuple[DecisionVariable, ...] = Field(min_length=1, max_length=32)
    initial: dict[Identifier, Number]
    constraints: tuple[PolynomialConstraint, ...] = Field(default=(), max_length=64)
    objective: PolynomialObjective
    max_iterations: int = Field(default=100, ge=1, le=500)
    max_evaluations: int = Field(default=2000, ge=1, le=10000)
    time_limit_s: int = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def validate_program(self):
        ids = {v.id for v in self.variables}
        if len(ids) != len(self.variables) or set(self.initial) != ids:
            raise ValueError("Unique variable IDs and a complete initial point required")
        if len({c.id for c in self.constraints}) != len(self.constraints):
            raise ValueError("Duplicate constraint ID")
        for variable in self.variables:
            if (variable.kind != "continuous" or variable.lower == variable.upper
                    or max(abs(variable.lower), abs(variable.upper)) > 1000):
                raise ValueError("NLP requires continuous nonfixed variables with bounds within [-1000, 1000]")
            if not variable.lower <= self.initial[variable.id] <= variable.upper:
                raise ValueError("Initial point outside bounds")
        for expression in (self.objective, *self.constraints):
            signatures = set()
            for term in expression.terms:
                signature = tuple(sorted((p.variable, p.exponent) for p in term.powers))
                if signature in signatures or not {p.variable for p in term.powers} <= ids:
                    raise ValueError("Duplicate monomial or unknown variable")
                signatures.add(signature)
        return self

    def route(self):
        return "scipy-slsqp-polynomial"

    def canonical(self):
        data = self.model_dump(mode="json")
        for group in ("variables", "constraints"):
            data[group].sort(key=lambda row: row["id"])
        for expression in (data["objective"], *data["constraints"]):
            for term in expression["terms"]:
                term["powers"].sort(key=lambda p: p["variable"])
            expression["terms"].sort(key=lambda term: tuple(
                (p["variable"], p["exponent"]) for p in term["powers"]))
        return data

    def sha256(self):
        return fingerprint(self.canonical())
