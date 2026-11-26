"""Bounded engineering inputs for optional solver extensions."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Nonnegative = Annotated[float, Field(ge=0, le=1e8, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, le=1e8, allow_inf_nan=False)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Wind(Strict):
    wind_speed_m_s: list[Nonnegative] = Field(min_length=1, max_length=168)
    curve_speed_m_s: list[Nonnegative] = Field(min_length=2, max_length=100)
    curve_power_w: list[Nonnegative] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def validate_curve(self):
        if len(self.curve_speed_m_s) != len(self.curve_power_w):
            raise ValueError("Power curve arrays must have equal length")
        if any(a >= b for a, b in zip(self.curve_speed_m_s, self.curve_speed_m_s[1:])):
            raise ValueError("Curve speeds must be strictly increasing")
        if max(self.wind_speed_m_s + self.curve_speed_m_s) > 100:
            raise ValueError("Wind speed exceeds 100 m/s")
        return self


class Unit(Strict):
    maximum_mw: Positive
    minimum_mw: Nonnegative = 0
    linear_cost_per_mwh: Nonnegative
    quadratic_cost: Nonnegative = 0
    startup_cost: Nonnegative = 0
    online_cost_per_hour: Nonnegative = 0

    @model_validator(mode="after")
    def limits(self):
        if self.minimum_mw > self.maximum_mw:
            raise ValueError("Minimum power exceeds maximum")
        return self


class EconomicDispatch(Strict):
    demand_mw: Nonnegative
    units: list[Unit] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def cost_model(self):
        if any(u.startup_cost or u.online_cost_per_hour for u in self.units):
            raise ValueError("Economic dispatch does not model startup or online costs")
        return self


class Commitment(Strict):
    demand_mw: list[Nonnegative] = Field(min_length=1, max_length=48)
    units: list[Unit] = Field(min_length=1, max_length=15)

    @model_validator(mode="after")
    def cost_model(self):
        if any(u.quadratic_cost for u in self.units):
            raise ValueError("Commitment supports linear generation costs only")
        return self


class EquivalentCell(Strict):
    ocv_v: float = Field(gt=0, le=10)
    ohmic_resistance_ohm: float = Field(gt=0, le=10)
    polarization_resistance_ohm: float = Field(gt=0, le=10)
    polarization_capacitance_f: float = Field(gt=0, le=1e7)
    current_a: float = Field(ge=0, le=100)
    duration_s: float = Field(gt=0, le=14400)
    samples: int = Field(default=101, ge=2, le=1001)
