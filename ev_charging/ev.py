"""EV Model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .strategies.base import Strategy


@dataclass
class EV:
    ev_id: str
    battery_kwh: float
    soc: float = 0.0                         # fraction 0..1
    required_soc: float = 1.0                # fraction 0..1
    arrival_time: Optional[datetime] = None  # None -> scenario start
    departure_time: Optional[datetime] = None  # not enforced yet
    strategy: Optional["Strategy"] = None    # RL / centralized / random plug in here

    def __post_init__(self) -> None:
        if self.battery_kwh <= 0:
            raise ValueError("battery_kwh must be positive")
        for name in ("soc", "required_soc"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        self.start_soc = self.soc
        self.energy_drawn_kwh = 0.0          # grid-side, what gets billed
        self.cost = 0.0

    @property
    def energy_needed_kwh(self) -> float:
        return max(0.0, (self.required_soc - self.soc) * self.battery_kwh)

    @property
    def is_done(self) -> bool:
        return self.soc >= self.required_soc - 1e-9

    def add_energy(self, stored_kwh: float) -> None:
        self.soc = min(1.0, self.soc + stored_kwh / self.battery_kwh)
