"""Simulation: ties config, clock, station, pricing, EVs, and strategies together."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .clock import SimClock
from .config import ScenarioConfig
from .ev import EV
from .metrics import EVResult, SimulationResult
from .pricing import PriceSchedule, build_price_schedule
from .station import ChargingStation
from .strategies.base import AlwaysCharge, Strategy


class Simulation:
    def __init__(self, cfg: ScenarioConfig, prices: Optional[PriceSchedule] = None) -> None:
        self.cfg = cfg
        self.clock = SimClock(cfg.start, cfg.end, cfg.step_minutes)
        self.prices = prices or build_price_schedule(cfg)
        self.station = ChargingStation(cfg.num_chargers, cfg.charger_kw)
        self.evs: list[EV] = []
        self.default_strategy: Strategy = AlwaysCharge()
        self._first_charge: dict[str, datetime] = {}
        self._finished_at: dict[str, datetime] = {}
        self._on_peak_kwh: dict[str, float] = {}
        self._off_peak_kwh: dict[str, float] = {}

    def add_ev(self, ev: EV) -> None:
        if ev.arrival_time is None:
            ev.arrival_time = self.cfg.start
        if ev.strategy is None:
            ev.strategy = self.default_strategy
        self._on_peak_kwh[ev.ev_id] = self._off_peak_kwh[ev.ev_id] = 0.0
        self.evs.append(ev)

    def run(self) -> SimulationResult:
        steps = 0
        while not self.clock.done and not self._all_finished():
            self._step()
            self.clock.advance()
            steps += 1
        return self._collect(steps)

    # ------------------------------------------------------------ internals
    def _all_finished(self) -> bool:
        return bool(self.evs) and all(ev.ev_id in self._finished_at for ev in self.evs)

    def _step(self) -> None:
        now = self.clock.now
        price = self.prices.price_at(now)
        on_peak = self.prices.is_on_peak(now)

        for ev in self.evs:   # arrivals
            if (ev.arrival_time <= now and ev.ev_id not in self._finished_at
                    and self.station.charger_of(ev) is None):
                self.station.plug_in(ev)

        for charger in self.station.active_sessions():   # charging
            ev = charger.occupied_by
            if not ev.strategy.decide(ev, now, price, on_peak):
                continue
            eff = self.cfg.charging_efficiency
            stored = min(charger.rate_kw * self.clock.step_hours * eff, ev.energy_needed_kwh)
            drawn = stored / eff
            ev.add_energy(stored)
            ev.energy_drawn_kwh += drawn
            ev.cost += drawn * price
            (self._on_peak_kwh if on_peak else self._off_peak_kwh)[ev.ev_id] += drawn
            self._first_charge.setdefault(ev.ev_id, now)
            if ev.is_done:
                self._finished_at[ev.ev_id] = now + self.clock.step
                self.station.unplug(ev)

    def _collect(self, steps: int) -> SimulationResult:
        return SimulationResult(
            ev_results=[
                EVResult(
                    ev_id=ev.ev_id,
                    start_soc=ev.start_soc,
                    final_soc=ev.soc,
                    energy_kwh=ev.energy_drawn_kwh,
                    cost=ev.cost,
                    on_peak_kwh=self._on_peak_kwh[ev.ev_id],
                    off_peak_kwh=self._off_peak_kwh[ev.ev_id],
                    charge_started=self._first_charge.get(ev.ev_id),
                    charge_finished=self._finished_at.get(ev.ev_id),
                    reached_required_soc=ev.is_done,
                )
                for ev in self.evs
            ],
            steps_run=steps,
            ended_at=self.clock.now,
        )
