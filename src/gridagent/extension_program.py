"""Typed requests for first-party solver extensions."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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
