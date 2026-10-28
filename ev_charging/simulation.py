"""Simulation: ties config, clock, station, pricing, EVs, and strategies together."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .clock import SimClock
from .config import ScenarioConfig
from .ev import EV
from .metrics import EVResult, SimulationResult
from .pricing import PriceSchedule, build_price_schedule
from .recorder import EVSnapshot, EVState, TimelineRecorder
from .station import ChargingStation
from .strategies.base import AlwaysCharge, Strategy


class Simulation:
    def __init__(self, cfg: ScenarioConfig, prices: Optional[PriceSchedule] = None,
                 record: bool = True) -> None:
        self.cfg = cfg
        self.clock = SimClock(cfg.start, cfg.end, cfg.step_minutes)
        self.prices = prices or build_price_schedule(cfg)
        self.station = ChargingStation(cfg.num_chargers, cfg.charger_kw)
        self.evs: list[EV] = []
        self.default_strategy: Strategy = AlwaysCharge()
        self.recorder: Optional[TimelineRecorder] = TimelineRecorder() if record else None
        self._first_charge: dict[str, datetime] = {}
        self._finished_at: dict[str, datetime] = {}
        self._on_peak_kwh: dict[str, float] = {}
        self._off_peak_kwh: dict[str, float] = {}

    def add_ev(self, ev: EV) -> None:
        if any(e.ev_id == ev.ev_id for e in self.evs):
            raise ValueError(f"duplicate ev_id {ev.ev_id!r}")
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
        self._record_closing_snapshot()
        return self._collect(steps)

    # ------------------------------------------------------------ internals
    def _all_finished(self) -> bool:
        return bool(self.evs) and all(ev.ev_id in self._finished_at for ev in self.evs)

    def _step(self) -> None:
        now = self.clock.now
        price = self.prices.price_at(now)
        on_peak = self.prices.is_on_peak(now)
        before = {ev.ev_id: (ev.soc, ev.cost) for ev in self.evs}
        was_done = set(self._finished_at)

        for ev in self.evs:   # arrivals
            if (ev.arrival_time <= now and ev.ev_id not in self._finished_at
                    and self.station.charger_of(ev) is None):
                self.station.plug_in(ev)

        plugged = {c.occupied_by.ev_id: c.charger_id for c in self.station.active_sessions()}
        drawn_kwh: dict[str, float] = {}

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
            drawn_kwh[ev.ev_id] = drawn
            (self._on_peak_kwh if on_peak else self._off_peak_kwh)[ev.ev_id] += drawn
            self._first_charge.setdefault(ev.ev_id, now)
            if ev.is_done:
                self._finished_at[ev.ev_id] = now + self.clock.step
                self.station.unplug(ev)

        if self.recorder is not None:
            snaps = []
            for ev in self.evs:
                soc, cost = before[ev.ev_id]
                if ev.ev_id in drawn_kwh:
                    state = EVState.CHARGING
                elif ev.ev_id in plugged:
                    state = EVState.IDLE
                elif ev.ev_id in was_done:
                    state = EVState.DONE
                elif ev.arrival_time <= now:
                    state = EVState.WAITING
                else:
                    state = EVState.AWAY
                snaps.append(EVSnapshot(
                    ev_id=ev.ev_id, state=state, charger_id=plugged.get(ev.ev_id),
                    soc=soc, power_kw=drawn_kwh.get(ev.ev_id, 0.0) / self.clock.step_hours,
                    cost=cost,
                ))
            self.recorder.record(now, price, on_peak, snaps)

    def _record_closing_snapshot(self) -> None:
        if self.recorder is None or not self.evs:
            return
        now = self.clock.now
        snaps = []
        for ev in self.evs:
            charger = self.station.charger_of(ev)
            if ev.ev_id in self._finished_at:
                state = EVState.DONE
            elif charger is not None:
                state = EVState.IDLE
            elif ev.arrival_time <= now:
                state = EVState.WAITING
            else:
                state = EVState.AWAY
            snaps.append(EVSnapshot(ev.ev_id, state, charger.charger_id if charger else None,
                                    ev.soc, 0.0, ev.cost))
        # Price lookup can fail past the dataset's last day; the closing row only needs a label.
        try:
            price, on_peak = self.prices.price_at(now), self.prices.is_on_peak(now)
        except KeyError:
            last = self.recorder.records[-1] if self.recorder.records else None
            price, on_peak = (last.price, last.on_peak) if last else (0.0, False)
        self.recorder.record(now, price, on_peak, snaps)

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
            config=self.cfg,
            timeline=list(self.recorder.records) if self.recorder else [],
        )
