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
    AWAY = "away"           # not arrived yet
    WAITING = "waiting"     # at the hub, no free charger
    CHARGING = "charging"   # plugged in and drawing power
    IDLE = "idle"           # plugged in, strategy chose to wait
    DONE = "done"           # reached required SOC and left the charger


@dataclass(frozen=True)
class EVSnapshot:
    ev_id: str
    state: EVState
    charger_id: Optional[int]
    soc: float              # fraction 0..1
    power_kw: float         # grid-side draw during the interval
    cost: float             # cumulative $ at start of the interval


@dataclass(frozen=True)
class StepRecord:
    time: datetime
    price: float            # $/kWh during the interval
    on_peak: bool
    evs: tuple[EVSnapshot, ...]

    @property
    def hub_load_kw(self) -> float:
        return sum(s.power_kw for s in self.evs)

    def snapshot(self, ev_id: str) -> EVSnapshot:
        return next(s for s in self.evs if s.ev_id == ev_id)


class TimelineRecorder:
    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def record(self, time: datetime, price: float, on_peak: bool,
               snapshots: list[EVSnapshot]) -> None:
        self.records.append(StepRecord(time, price, on_peak, tuple(snapshots)))
