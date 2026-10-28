"""EV Model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .driver import DriverProfile
    from .strategies.base import Strategy


@dataclass
class EV:
    ev_id: str
    battery_kwh: float
    soc: float = 0.0                         # fraction 0..1
    required_soc: float = 1.0                # fraction 0..1
    arrival_time: Optional[datetime] = None  # None -> scenario start (ignored with a driver)
    departure_time: Optional[datetime] = None  # not enforced yet
    strategy: Optional["Strategy"] = None    # RL / centralized / random plug in here
    driver: Optional["DriverProfile"] = None  # daily schedule; None = old one-visit behaviour
    kwh_per_mile: float = 0.30               # driving efficiency (energy per mile)

    def __post_init__(self) -> None:
        if self.battery_kwh <= 0:
            raise ValueError("battery_kwh must be positive")
        if self.kwh_per_mile <= 0:
            raise ValueError("kwh_per_mile must be positive")
        for name in ("soc", "required_soc"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        self.start_soc = self.soc
        self.energy_drawn_kwh = 0.0          # grid-side, what gets billed
        self.cost = 0.0
        self.energy_driven_kwh = 0.0         # used by driving
        self.miles_driven = 0.0
        self.shortfall_kwh = 0.0             # driving energy the battery didn't have

    @property
    def energy_needed_kwh(self) -> float:
        return max(0.0, (self.required_soc - self.soc) * self.battery_kwh)

    @property
    def is_done(self) -> bool:
        return self.soc >= self.required_soc - 1e-9

    def add_energy(self, stored_kwh: float) -> None:
        self.soc = min(1.0, self.soc + stored_kwh / self.battery_kwh)

    def use_energy(self, kwh: float) -> float:
        """Drain the battery by driving. Returns the shortfall (kWh the battery
        didn't have); SOC never goes below 0."""
        available = self.soc * self.battery_kwh
        used = min(kwh, available)
        self.soc = max(0.0, self.soc - used / self.battery_kwh)
        self.energy_driven_kwh += used
        short = kwh - used
        self.shortfall_kwh += short
        return short

    def drive(self, miles: float) -> float:
        """Drive `miles`, using miles * kwh_per_mile from the battery.
        Returns the shortfall in kWh (energy the battery didn't have)."""
        self.miles_driven += miles
        return self.use_energy(miles * self.kwh_per_mile)
