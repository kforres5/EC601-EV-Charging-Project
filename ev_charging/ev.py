"""EV Model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .driver import DriverProfile
    from .strategies.base import Strategy
    from .vehicle import VehicleSpec

CHARGER_KINDS = ("AC", "DC")
_DC_SLICE_HOURS = 1 / 60      # DC charging is integrated minute by minute (power follows SOC)


@dataclass
class EV:
    """One electric vehicle. Use EV.from_vehicle() to take battery size,
    efficiency and charging limits from a VehicleSpec."""
    ev_id: str
    battery_kwh: float
    soc: float = 0.0                         # fraction 0..1
    required_soc: float = 1.0                # fraction 0..1
    arrival_time: Optional[datetime] = None  # None -> scenario start (ignored with a driver)
    departure_time: Optional[datetime] = None  # not enforced yet
    strategy: Optional["Strategy"] = None    # RL / centralized / random plug in here
    driver: Optional["DriverProfile"] = None  # daily schedule; None = old one-visit behaviour
    kwh_per_mile: float = 0.30               # driving efficiency (energy per mile)
    vehicle: Optional["VehicleSpec"] = None  # charging limits (max AC kW, DC curve); None = no car limit

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

    @classmethod
    def from_vehicle(cls, ev_id: str, vehicle: "VehicleSpec", **kwargs) -> "EV":
        kwargs.setdefault("battery_kwh", vehicle.battery_kwh)
        kwargs.setdefault("kwh_per_mile", vehicle.kwh_per_mile)
        return cls(ev_id=ev_id, vehicle=vehicle, **kwargs)

    def charge_capacity_kwh(self, charger_kw: float, kind: str, hours: float,
                            efficiency: float = 1.0) -> float:
        """Battery-side kWh this car can take in `hours` on a charger of
        `charger_kw` (grid side), stopping at required_soc. Doesn't change the car.

        AC: power = min(charger, car's onboard charger limit).
        DC: power = min(charger, car's DC curve at the current SOC), re-checked
            every minute as the battery fills."""
        if kind not in CHARGER_KINDS:
            raise ValueError(f"charger kind must be one of {CHARGER_KINDS}")
        need = self.energy_needed_kwh
        if need <= 0 or hours <= 0:
            return 0.0
        if kind == "AC":
            kw = min(charger_kw, self.vehicle.max_ac_kw) if self.vehicle else charger_kw
            return min(kw * hours * efficiency, need)
        stored, soc, left = 0.0, self.soc, hours
        while left > 1e-12 and stored < need - 1e-12:
            h = min(_DC_SLICE_HOURS, left)
            kw = min(charger_kw, self.vehicle.dc_power_at(soc)) if self.vehicle else charger_kw
            e = min(kw * h * efficiency, need - stored)
            stored += e
            soc += e / self.battery_kwh
            left -= h
        return stored
