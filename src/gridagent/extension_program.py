"""Typed requests for first-party solver extensions."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[float, Field(gt=0, le=1e6, allow_inf_nan=False)]


class Feeder(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kv: float = Field(gt=0.1, le=100)
    length_km: Positive
    r_ohm_km: Positive
    x_ohm_km: Positive
    load_kw: Positive
    load_kvar: float = Field(ge=0, le=1e6)
    source_mvasc: Positive = 1000


class Battery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: Literal["SPM", "DFN"] = "SPM"
    current_a: float = Field(gt=0, le=20)
    duration_s: float = Field(gt=0, le=14400)
    initial_soc: float = Field(gt=0, le=1)


class Solar(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    effective_irradiance_w_m2: float = Field(ge=0, le=2000)
    cell_temperature_c: float = Field(ge=-50, le=110)
    rated_dc_w: Positive
    gamma_pdc_per_c: float = Field(ge=-0.02, le=0)


Coefficient = Annotated[float, Field(ge=-1e6, le=1e6, allow_inf_nan=False)]


class ControlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    numerator: list[Coefficient] = Field(min_length=1, max_length=9)
    denominator: list[Coefficient] = Field(min_length=1, max_length=9)
    duration_s: float = Field(gt=0, le=1000)
    samples: int = Field(default=501, ge=10, le=2001)

    @model_validator(mode="after")
    def proper(self):
        if not self.denominator[0] or not self.numerator[0] or len(self.numerator) > len(self.denominator):
            raise ValueError("Use nonzero leading coefficients and a proper continuous SISO transfer function")
        return self
