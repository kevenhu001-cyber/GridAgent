"""Small, typed native solver studies. No arbitrary expressions or files."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .extra_programs import Strict

Positive = Annotated[float, Field(gt=0, le=1e9, allow_inf_nan=False)]
Value = Annotated[float, Field(ge=-1e7, le=1e7, allow_inf_nan=False)]


class PowerFlowCase(Strict):
    case: Literal["ieee14", "ieee30", "ieee118"] = "ieee14"


class PowSyBlCase(Strict):
    case: Literal["ieee14"] = "ieee14"


class TrackingQP(Strict):
    target_mw: list[Value] = Field(min_length=1, max_length=168)
    lower_mw: float = Field(ge=-1e7, le=1e7)
    upper_mw: float = Field(ge=-1e7, le=1e7)
    ramp_mw_per_hour: Positive

    @model_validator(mode="after")
    def bounds(self):
        if self.lower_mw > self.upper_mw:
            raise ValueError("Lower bound exceeds upper bound")
        return self


class TransmissionLine(Strict):
    frequency_hz: float = Field(gt=0, le=1e10)
    length_m: float = Field(gt=0, le=1e6)
    characteristic_ohm: float = Field(gt=0, le=1e5)
    port_ohm: float = Field(gt=0, le=1e5)
    attenuation_np_per_m: float = Field(ge=0, le=100)
    velocity_m_s: float = Field(gt=0, le=299792458)


class FluidState(Strict):
    fluid: Literal["Water", "Air", "CO2", "R134a", "Ammonia", "Hydrogen"]
    temperature_k: float = Field(gt=50, le=1500)
    pressure_pa: float = Field(gt=0, le=1e8)


class RainflowSeries(Strict):
    samples: list[Value] = Field(min_length=3, max_length=10000)
