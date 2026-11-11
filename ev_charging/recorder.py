"""Timeline recorder: a snapshot of every EV at every timestep.

The simulation fills this in as it runs; charts and animations read it
afterwards, so plotting never has to re-run or reach into the simulation.

Each StepRecord describes the interval [time, time + step):
  - soc and cost are the values at the START of the interval
  - state, charger_id and power_kw describe what happened DURING it
The last record is a closing snapshot (power 0) with final SOC and cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class EVState(str, Enum):
    AWAY = "away"           # not at the hub (not arrived yet, or at home/work elsewhere;
                            # CommuteSimulation: at home, not plugged in)
    DRIVING = "driving"     # on a commute (only EVs with a driver)
    WAITING = "waiting"     # at the hub, no free charger
    CHARGING = "charging"   # plugged in and drawing power
    IDLE = "idle"           # plugged in but not drawing power (full, or strategy waited)
    PARKED = "parked"       # at the hub but moved off the charger (move-your-car rule);
                            # CommuteSimulation: at work, not using a charger
    DONE = "done"           # reached required SOC and left for good (EVs without a driver)


@dataclass(frozen=True)
class EVSnapshot:
    ev_id: str
    state: EVState
    charger_id: Optional[int]
    soc: float              # fraction 0..1
    power_kw: float         # grid-side draw during the interval
    cost: float             # cumulative $ at start of the interval
    location: Optional[str] = None   # driver's location ("home"/"work"/"driving"/"public"); None without a driver
    site: Optional[str] = None       # CommuteSimulation: site the car is at ("work", a public station's name)


@dataclass(frozen=True)
class StepRecord:
    time: datetime
    price: float            # $/kWh drivers pay during the interval
    on_peak: bool
    evs: tuple[EVSnapshot, ...]
    supply_price: Optional[float] = None    # energy supply $/kWh (the price CSV)
    utility_price: Optional[float] = None   # supply + delivery $/kWh the site pays
    prices: Optional[dict] = None           # driver $/kWh per site, e.g. {"home": .., "work": ..}

    @property
    def hub_load_kw(self) -> float:
        return sum(s.power_kw for s in self.evs)

    def load_kw_at(self, location: str) -> float:
        """Power drawn by cars at one location ("home" or "work")."""
        return sum(s.power_kw for s in self.evs if s.location == location)

    def snapshot(self, ev_id: str) -> EVSnapshot:
        return next(s for s in self.evs if s.ev_id == ev_id)


class TimelineRecorder:
    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def record(self, time: datetime, price: float, on_peak: bool,
               snapshots: list[EVSnapshot], supply_price: Optional[float] = None,
               utility_price: Optional[float] = None, prices: Optional[dict] = None) -> None:
        self.records.append(StepRecord(time, price, on_peak, tuple(snapshots),
                                       supply_price, utility_price, prices))
