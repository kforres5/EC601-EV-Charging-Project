"""Metrics. Deadline-miss rate, queue wait, and peak load get added here later."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .config import ScenarioConfig
    from .recorder import StepRecord


@dataclass
class EVResult:
    ev_id: str
    start_soc: float
    final_soc: float
    energy_kwh: float               # drawn from the grid
    cost: float
    on_peak_kwh: float
    off_peak_kwh: float
    charge_started: Optional[datetime]
    charge_finished: Optional[datetime]
    reached_required_soc: bool

    @property
    def avg_price_per_kwh(self) -> float:
        return self.cost / self.energy_kwh if self.energy_kwh else 0.0


@dataclass
class SimulationResult:
    ev_results: list[EVResult]
    steps_run: int
    ended_at: datetime
    config: Optional["ScenarioConfig"] = None
    timeline: list["StepRecord"] = field(default_factory=list)   # empty if recording is off

    @property
    def total_cost(self) -> float:
        return sum(r.cost for r in self.ev_results)
