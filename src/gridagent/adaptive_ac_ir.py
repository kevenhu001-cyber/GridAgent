"""Authorization for bounded adaptive search over an existing AC probe pool."""

from typing import Literal

from pydantic import Field, model_validator

from .ac_diagnostic_ir import ACDiagnosticExperiment
from .engineering_ir import fingerprint
from .task_contracts import Contract


class AdaptiveACExperiment(Contract):
    schema_version: Literal[1] = 1
    experiment: ACDiagnosticExperiment
    run_budget: int = Field(ge=2, le=9)
    use_history: bool = False

    @model_validator(mode="after")
    def budget_within_pool(self):
        if self.run_budget > len(self.experiment.probes)+1:
            raise ValueError("Adaptive budget exceeds baseline plus authorized probe pool")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        data["experiment"] = self.experiment.canonical()
        return data

    def sha256(self):
        return fingerprint(self.canonical())
