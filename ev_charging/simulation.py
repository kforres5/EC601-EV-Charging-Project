"""Simulation: ties config, clock, station, pricing, EVs, and strategies together.

Two kinds of EV can share a run:
  - EVs with a driver follow the driver's daily schedule. They are at the hub
    only while the driver is at the hub's location (cfg.hub_location), drain
    the battery while commuting, charge up to required_soc while plugged in,
    and unplug when the driver leaves.
    Move-your-car rule (cfg.move_window_minutes, at hubs in cfg.move_rule_at):
    once a car reaches its target it stays plugged in (idle) for at most the
    move window, then parks in a regular spot and can't plug back in until
    the driver leaves and returns. A car that arrives already at its target
    parks straight away. Without the rule, full cars stay plugged in until
    the driver leaves.
  - EVs without a driver keep the original behaviour: arrive once at
    arrival_time, charge to required_soc, then leave for good.
A run stops at cfg.end, or earlier once every driverless EV is done and there
are no EVs with drivers.

Locations are sampled at the start of each timestep: a car that arrives
mid-step plugs in at the next step. Charging is scaled by the share of the
step the car is actually at the hub, so a car leaving mid-step only charges
for the time it was there.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .clock import SimClock
from .config import ScenarioConfig
from .driver import Location
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
        self.hub_location = Location(cfg.hub_location)
        self.evs: list[EV] = []
        self.default_strategy: Strategy = AlwaysCharge()
        self.recorder: Optional[TimelineRecorder] = TimelineRecorder() if record else None
        self._first_charge: dict[str, datetime] = {}
        self._finished_at: dict[str, datetime] = {}
        self._on_peak_kwh: dict[str, float] = {}
        self._off_peak_kwh: dict[str, float] = {}
        self._at_hub: set[str] = set()          # driver EVs currently at the hub (plugged or waiting)
        self._departures: dict[str, int] = {}
        self._departures_low: dict[str, int] = {}
        self._parked: set[str] = set()          # moved off the charger, still at the hub
        self._full_since: dict[str, datetime] = {}
        self._moves: dict[str, int] = {}
        self._idle_hours: dict[str, float] = {}
        self.move_window: Optional[timedelta] = (
            timedelta(minutes=cfg.move_window_minutes)
            if cfg.move_window_minutes is not None and cfg.hub_location in cfg.move_rule_at
            else None)

    def add_ev(self, ev: EV) -> None:
        if any(e.ev_id == ev.ev_id for e in self.evs):
            raise ValueError(f"duplicate ev_id {ev.ev_id!r}")
        if ev.arrival_time is None:
            ev.arrival_time = self.cfg.start
        if ev.strategy is None:
            ev.strategy = self.default_strategy
        self._on_peak_kwh[ev.ev_id] = self._off_peak_kwh[ev.ev_id] = 0.0
        self._departures[ev.ev_id] = self._departures_low[ev.ev_id] = 0
        self._moves[ev.ev_id] = 0
        self._idle_hours[ev.ev_id] = 0.0
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
        if not self.evs or any(ev.driver for ev in self.evs):
            return False   # EVs with drivers keep living their schedule until cfg.end
        return all(ev.ev_id in self._finished_at for ev in self.evs)

    def _driver_at_hub(self, ev: EV, t: datetime) -> bool:
        return ev.driver.location_at(t) is self.hub_location

    def _step(self) -> None:
        now = self.clock.now
        step_end = now + self.clock.step
        price = self.prices.price_at(now)
        on_peak = self.prices.is_on_peak(now)
        before = {ev.ev_id: (ev.soc, ev.cost) for ev in self.evs}
        was_done = set(self._finished_at)

        # 1. departures: drivers who have left the hub's location unplug
        for ev in self.evs:
            if ev.driver and ev.ev_id in self._at_hub and not self._driver_at_hub(ev, now):
                self.station.unplug(ev)
                self._at_hub.discard(ev.ev_id)
                self._parked.discard(ev.ev_id)
                self._full_since.pop(ev.ev_id, None)
                self._departures[ev.ev_id] += 1
                if not ev.is_done:
                    self._departures_low[ev.ev_id] += 1

        # 2. move-your-car: full cars past the move window leave the charger
        if self.move_window is not None:
            for ev in self.evs:
                full_at = self._full_since.get(ev.ev_id)
                if full_at is not None and now >= full_at + self.move_window:
                    self.station.unplug(ev)
                    self._parked.add(ev.ev_id)
                    del self._full_since[ev.ev_id]
                    self._moves[ev.ev_id] += 1

        # 3. arrivals: plug in if a charger is free, otherwise wait (first come, first served)
        for ev in self.evs:
            if ev.driver:
                here = self._driver_at_hub(ev, now)
                if here:
                    self._at_hub.add(ev.ev_id)
                    if ev.ev_id in self._parked:
                        continue
                    if self.move_window is not None and ev.is_done:
                        self._parked.add(ev.ev_id)    # already full: park, don't take a charger
                        continue
            else:
                here = ev.arrival_time <= now and ev.ev_id not in self._finished_at
            if here and self.station.charger_of(ev) is None:
                self.station.plug_in(ev)

        plugged = {c.occupied_by.ev_id: c.charger_id for c in self.station.active_sessions()}
        drawn_kwh: dict[str, float] = {}

        # 4. charging
        for charger in self.station.active_sessions():
            ev = charger.occupied_by
            if ev.is_done or not ev.strategy.decide(ev, now, price, on_peak):
                continue
            share = ev.driver.fraction_at(self.hub_location, now, step_end) if ev.driver else 1.0
            eff = self.cfg.charging_efficiency
            stored = min(charger.rate_kw * self.clock.step_hours * share * eff, ev.energy_needed_kwh)
            if stored <= 0:
                continue
            drawn = stored / eff
            ev.add_energy(stored)
            ev.energy_drawn_kwh += drawn
            ev.cost += drawn * price
            drawn_kwh[ev.ev_id] = drawn
            (self._on_peak_kwh if on_peak else self._off_peak_kwh)[ev.ev_id] += drawn
            self._first_charge.setdefault(ev.ev_id, now)
            if ev.is_done and not ev.driver:     # driverless EVs leave once full
                self._finished_at[ev.ev_id] = now + self.clock.step
                self.station.unplug(ev)
            elif ev.is_done and self.move_window is not None:
                self._full_since.setdefault(ev.ev_id, now + self.clock.step)

        # a car that was full before this step started still counts as full
        if self.move_window is not None:
            for c in self.station.active_sessions():
                ev = c.occupied_by
                if ev.driver and ev.is_done:
                    self._full_since.setdefault(ev.ev_id, now)

        for ev_id in plugged:
            if ev_id not in drawn_kwh:
                self._idle_hours[ev_id] += self.clock.step_hours

        # 5. driving drains the battery
        for ev in self.evs:
            if ev.driver:
                ev.drive(ev.driver.driving_miles(now, step_end))

        if self.recorder is not None:
            snaps = []
            for ev in self.evs:
                soc, cost = before[ev.ev_id]
                location = ev.driver.location_at(now).value if ev.driver else None
                if ev.ev_id in drawn_kwh:
                    state = EVState.CHARGING
                elif ev.ev_id in plugged:
                    state = EVState.IDLE
                elif ev.ev_id in was_done:
                    state = EVState.DONE
                elif ev.driver:
                    if ev.ev_id in self._parked:
                        state = EVState.PARKED
                    elif ev.ev_id in self._at_hub:
                        state = EVState.WAITING
                    elif location == Location.DRIVING.value:
                        state = EVState.DRIVING
                    else:
                        state = EVState.AWAY
                elif ev.arrival_time <= now:
                    state = EVState.WAITING
                else:
                    state = EVState.AWAY
                snaps.append(EVSnapshot(
                    ev_id=ev.ev_id, state=state, charger_id=plugged.get(ev.ev_id),
                    soc=soc, power_kw=drawn_kwh.get(ev.ev_id, 0.0) / self.clock.step_hours,
                    cost=cost, location=location,
                ))
            self.recorder.record(now, price, on_peak, snaps)

    def _record_closing_snapshot(self) -> None:
        if self.recorder is None or not self.evs:
            return
        now = self.clock.now
        snaps = []
        for ev in self.evs:
            charger = self.station.charger_of(ev)
            location = ev.driver.location_at(now).value if ev.driver else None
            if ev.ev_id in self._finished_at:
                state = EVState.DONE
            elif charger is not None:
                state = EVState.IDLE
            elif ev.driver:
                state = (EVState.PARKED if ev.ev_id in self._parked
                         else EVState.WAITING if ev.ev_id in self._at_hub
                         else EVState.DRIVING if location == Location.DRIVING.value
                         else EVState.AWAY)
            elif ev.arrival_time <= now:
                state = EVState.WAITING
            else:
                state = EVState.AWAY
            snaps.append(EVSnapshot(ev.ev_id, state, charger.charger_id if charger else None,
                                    ev.soc, 0.0, ev.cost, location))
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
                    energy_driven_kwh=ev.energy_driven_kwh,
                    shortfall_kwh=ev.shortfall_kwh,
                    hub_departures=self._departures[ev.ev_id],
                    departures_below_target=self._departures_low[ev.ev_id],
                    idle_plugged_hours=self._idle_hours[ev.ev_id],
                    moves=self._moves[ev.ev_id],
                )
                for ev in self.evs
            ],
            steps_run=steps,
            ended_at=self.clock.now,
            config=self.cfg,
            timeline=list(self.recorder.records) if self.recorder else [],
        )
