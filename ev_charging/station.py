"""Charging station (hub) and its chargers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .ev import EV


@dataclass
class Charger:
    charger_id: int
    rate_kw: float
    occupied_by: Optional[EV] = None

    @property
    def is_free(self) -> bool:
        return self.occupied_by is None


class ChargingStation:
    def __init__(self, num_chargers: int, rate_kw: float) -> None:
        self.chargers = [Charger(i, rate_kw) for i in range(num_chargers)]

    @property
    def num_chargers(self) -> int:
        return len(self.chargers)

    @property
    def num_available(self) -> int:
        return sum(c.is_free for c in self.chargers)

    def charger_of(self, ev: EV) -> Optional[Charger]:
        return next((c for c in self.chargers if c.occupied_by is ev), None)

    def plug_in(self, ev: EV) -> Optional[Charger]:
        """First free charger, or None if the hub is full (ChargingQueue comes later)."""
        for c in self.chargers:
            if c.is_free:
                c.occupied_by = ev
                return c
        return None

    def unplug(self, ev: EV) -> None:
        c = self.charger_of(ev)
        if c:
            c.occupied_by = None

    def active_sessions(self) -> list[Charger]:
        return [c for c in self.chargers if not c.is_free]
