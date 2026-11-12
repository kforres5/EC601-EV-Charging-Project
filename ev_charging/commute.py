"""CommuteSimulation: commuting drivers who can charge at home, at work, and at
public charging stations.

Every EV has a driver (driver.py) who lives this weekday schedule:

    home --(commute)--> work [work hours] --(commute)--> home

and can add detours to public stations from home (itinerary.py):

    home --(detour)--> public station [charge] --(detour)--> home

Sites (sites.py):
  - Home: each driver's own charger: Level 2 (7.2 kW), Level 1 (1.4 kW) or none.
    The car is plugged in whenever it is home. The household pays the
    residential supply price + Rate 7 delivery (pass-through).
  - Work: one hub with M shared chargers, first come, first served. Drivers pay
    a flat price (default $0.25/kWh). The hub pays its own utility bill
    (small C&I supply + Rate 27: delivery, demand and customer charges).
    Rules at work:
      * daily limit: at most cfg.work.daily_limit_hours plugged in per day
      * move your car: once a car stops charging, it must be unplugged within
        cfg.work.move_window_minutes
      Either rule moves the car to a regular spot; it can't plug back in that day.
  - Public stations (cfg.public): Level 2 and DC fast, first come, first served.
    Drivers pay the posted price (dataset/charger_prices_summary.csv); each
    station pays its own utility bill (Rate 27 for L2, Rate EV-L for DC fast).
    A visit is booked by the driver's strategy while the car is at home. It
    must start within cfg.public_visit_hours and end back home before the
    driver's next departure. The car charges at full power until it has added
    the visit's target, or until it must leave (max dwell, or time to get home).

Charge goal (assumption A8): keep enough charge for the driving ahead plus a
buffer, i.e. never let the battery drop below cfg.soc_buffer. Metrics count
trips that end below the buffer, hours spent below it, and energy the battery
didn't have (shortfall).

Strategies decide when and where to charge (strategies/base.py): AlwaysCharge
plugs in whenever it can and tops up at a public station when it can't cover
tomorrow; Greedy (strategies/greedy.py) buys the cheapest slots it needs. A
strategy only sees what a real driver could: its own SOC and schedule, posted
prices (via PlanningView), and its own work limits.

Step order (15 minutes by default):
  0. cars at a public station leave once done; cars at home may head out to one
  1. cars whose driver left a site unplug
  2. work rules (move-your-car, daily limit) move cars off work chargers
  3. cars at home plug into their own charger; cars at work ask their strategy
     whether to plug in; cars at a station plug in; no charger free = wait
  4. plugged-in cars charge (strategy picks how much; at a station, the visit's target)
  5. driving drains the battery; trip and buffer metrics update
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Optional

from .clock import SimClock
from .config import CommuteConfig, HOME_CHARGER_TYPES
from .driver import Location
from .ev import EV
from .itinerary import Itinerary, Visit
from .recorder import EVSnapshot, EVState, TimelineRecorder, StepRecord
from .sites import HomeSiteFactory, Site, build_public_site, build_work_site
from .strategies.base import AlwaysCharge, ChargeContext, Strategy
from .tariffs import MonthlyBill

_EPS = 1e-9


# ------------------------------------------------------------------ results
@dataclass
class CommuteEVResult:
    ev_id: str
    home_charger: str               # "L2", "L1" or "none"
    strategy: str
    start_soc: float
    final_soc: float
    min_soc: float
    home_kwh: float                 # drawn from the grid at home
    work_kwh: float                 # drawn from the grid at work
    home_cost: float
    work_cost: float
    on_peak_kwh: float
    off_peak_kwh: float
    miles_driven: float
    energy_driven_kwh: float
    shortfall_kwh: float            # driving energy the battery didn't have
    trips: int
    trips_below_buffer: int         # trips that ended with SOC under the buffer (missed goal)
    hours_below_buffer: float
    work_waiting_hours: float       # at work, wanted a charger, none free
    work_plugged_hours: float
    moves: int                      # moved off a work charger by the move-your-car rule
    limit_moves: int                # moved off a work charger by the daily limit
    public_kwh: float = 0.0
    public_cost: float = 0.0
    public_visits: int = 0
    public_hours: float = 0.0       # time spent on public visits, detours included
    public_waiting_hours: float = 0.0
    public_kwh_by_kind: dict = field(default_factory=dict)   # {"L2": .., "DCFC": ..}
    public_fixed_cost: float = 0.0  # this driver's share of public stations' network + maintenance
    home_fixed_cost: float = 0.0    # network + maintenance fee for the home L2 charger

    @property
    def energy_kwh(self) -> float:
        return self.home_kwh + self.work_kwh + self.public_kwh

    @property
    def energy_cost(self) -> float:
        return self.home_cost + self.work_cost + self.public_cost

    @property
    def cost(self) -> float:
        return self.energy_cost + self.home_fixed_cost + self.public_fixed_cost

    @property
    def avg_price_per_kwh(self) -> float:
        """$/kWh of energy only; fixed fees are excluded."""
        return self.energy_cost / self.energy_kwh if self.energy_kwh else 0.0


@dataclass
class StationResult:
    """One public station over the run."""
    name: str
    kind: str
    price: float
    revenue: float
    energy_kwh: float
    peak_kw: float
    bills: list[MonthlyBill]
    fixed_cost: float = 0.0         # network + maintenance over the run
    fee_revenue: float = 0.0        # collected from drivers as per-user shares

    @property
    def margin(self) -> float:
        return self.revenue + self.fee_revenue - self.site_cost

    @property
    def site_cost(self) -> float:
        return sum(b.total for b in self.bills) + self.fixed_cost


@dataclass
class CommuteResult:
    ev_results: list[CommuteEVResult]
    config: CommuteConfig
    steps_run: int
    ended_at: datetime
    timeline: list[StepRecord] = field(default_factory=list)
    work_bills: list[MonthlyBill] = field(default_factory=list)
    peak_home_kw: float = 0.0       # all home chargers together
    peak_work_kw: float = 0.0
    peak_home_at: Optional[datetime] = None
    strategy: str = ""
    stations: list[StationResult] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        """What all drivers paid (home bills + work fees + public charging)."""
        return sum(r.cost for r in self.ev_results)

    @property
    def work_revenue(self) -> float:
        return sum(r.work_cost for r in self.ev_results)

    @property
    def work_site_cost(self) -> float:
        return sum(b.total for b in self.work_bills)

    @property
    def work_margin(self) -> float:
        """Work hub: fees collected minus its utility bill."""
        return self.work_revenue - self.work_site_cost

@dataclass
class _Draw:
    ev: EV
    site: Site
    visit: Optional[Visit]
    ctx: ChargeContext
    stored: float            # battery-side kWh this car would add this step


# ------------------------------------------------------------ what a driver sees
class PlanningView:
    """Read-only window on the simulation for one driver's strategy."""

    def __init__(self, sim: "CommuteSimulation", ev: EV) -> None:
        self._sim = sim
        self.ev = ev
        self.now = sim.clock.now
        self.step = sim.clock.step
        self.step_hours = sim.clock.step_hours
        self.efficiency = sim.cfg.charging_efficiency
        self.buffer_kwh = sim.cfg.soc_buffer * ev.battery_kwh
        self.cap_kwh = ev.required_soc * ev.battery_kwh
        self.home: Optional[Site] = sim.homes.get(ev.ev_id)
        self.work: Site = sim.work
        self.public_stations: list[Site] = list(sim.public.values())
        self.itinerary: Itinerary = sim.itinerary[ev.ev_id]

    def site_for(self, location: Location, t: Optional[datetime] = None) -> Optional[Site]:
        if location is Location.HOME:
            return self.home
        if location is Location.WORK and self.work.station.num_chargers:
            return self.work
        if location is Location.PUBLIC:
            v = self.itinerary.active_visit(t or self.now)
            return v.station if v else None
        return None

    def power_kw(self, site: Site) -> float:
        """Battery-side kW this car gets on the site's charger (DC: the car's peak)."""
        v = self.ev.vehicle
        car = (v.max_ac_kw if site.kind == "AC" else v.max_dc_kw) if v else math.inf
        return min(site.charger_kw, car) * self.efficiency

    def work_hours_left(self, day: date) -> float:
        """Hours this car may still be plugged in at work on `day`."""
        sim = self._sim
        if day == self.now.date() and self.ev.ev_id in sim._parked:
            return 0.0      # already moved off a work charger today
        limit = self.work.daily_limit
        if limit is None:
            return math.inf
        used = sim._work_plugged_day[self.ev.ev_id].get(day, 0.0) if day == self.now.date() else 0.0
        return max(0.0, limit.total_seconds() / 3600 - used)

    def visit_window(self, station: Site) -> Optional[tuple[datetime, datetime]]:
        """(plug-in time, latest_depart) if the driver can leave home for `station`
        now, else None (not at home, outside visit hours, or no time before the next trip)."""
        return self._sim._visit_window(self.ev, station, self.now)

    def drive_kwh(self, start: datetime, end: datetime) -> float:
        return self.itinerary.driving_miles(start, end) * self.ev.kwh_per_mile

    def known_until(self) -> date:
        """Last day with posted prices: on-peak prices are set the day before."""
        return self.now.date() + timedelta(days=1)

    def price_forecast(self, site: Site, t: datetime) -> float:
        """Driver price at t, as known now. Flat prices and off-peak prices (set
        monthly) are known ahead; on-peak prices past tomorrow are guessed as the
        latest posted on-peak price."""
        try:
            if site.flat_price is not None or t.date() <= self.known_until():
                return site.driver_price(t)
            if not site.is_on_peak(t):
                return site.driver_price(t)
            d = self.known_until()
            for _ in range(7):
                ref = datetime.combine(d, time(site_peak_hour(site)))
                if site.is_on_peak(ref):
                    return site.driver_price(ref)
                d -= timedelta(days=1)
            return site.driver_price(t)
        except KeyError:     # past the end of the price data
            return site.driver_price(self.now)


def site_peak_hour(site: Site) -> int:
    peak = getattr(site.supply, "peak", None)
    return peak.start_hour if peak is not None else 12


# ------------------------------------------------------------------ simulation
class CommuteSimulation:
    def __init__(self, cfg: CommuteConfig, record: bool = True) -> None:
        self.cfg = cfg
        self.clock = SimClock(cfg.start, cfg.end, cfg.step_minutes)
        self.work = build_work_site(cfg)
        self.public: dict[str, Site] = {p.name: build_public_site(cfg, p) for p in cfg.public}
        self._home_factory = HomeSiteFactory(cfg)
        self.homes: dict[str, Site] = {}
        self.home_type: dict[str, str] = {}
        self.itinerary: dict[str, Itinerary] = {}
        self.evs: list[EV] = []
        self.default_strategy: Strategy = AlwaysCharge()
        self.recorder: Optional[TimelineRecorder] = TimelineRecorder() if record else None

        self._plugged: dict[str, Site] = {}            # ev_id -> site it's plugged into
        self._parked: set[str] = set()                 # moved off a work charger today
        self._idle_since: dict[str, datetime] = {}     # plugged in at work, stopped charging at
        self._waiting: set[str] = set()                # at work or a station, no charger free
        self._work_plugged_day: dict[str, dict[date, float]] = defaultdict(dict)
        self._stats: dict[str, dict[str, float]] = {}
        self._peak_home = (0.0, None)
        self._peak_work = 0.0
        self._station_kwh = defaultdict(float)
        self._station_revenue = defaultdict(float)
        self._station_peak = defaultdict(float)
        self._days_seen: set[date] = set()             # calendar days the run touched (daily fees)
        self._station_users: dict[tuple[str, date], set[str]] = defaultdict(set)   # (station, day) -> ev_ids that charged
        self._fee_revenue = defaultdict(float)                                     # station -> per-user fees collected
        self._fixed_billed: dict[str, date] = {}       # ev_id -> last day its home-charger fee was billed

    # ------------------------------------------------------------ setup
    def add_driver(self, ev: EV, home_charger: str = "L2") -> None:
        if ev.driver is None:
            raise ValueError("CommuteSimulation needs EVs with a driver")
        if home_charger not in HOME_CHARGER_TYPES:
            raise ValueError(f"home_charger must be one of {HOME_CHARGER_TYPES}")
        if any(e.ev_id == ev.ev_id for e in self.evs):
            raise ValueError(f"duplicate ev_id {ev.ev_id!r}")
        if ev.strategy is None:
            ev.strategy = self.default_strategy
        site = self._home_factory.make(ev.ev_id, home_charger)
        if site is not None:
            self.homes[ev.ev_id] = site
        self.home_type[ev.ev_id] = home_charger
        self.itinerary[ev.ev_id] = Itinerary(ev.driver)
        self.evs.append(ev)
        self._stats[ev.ev_id] = defaultdict(float, min_soc=ev.soc)

    def run(self) -> CommuteResult:
        steps = 0
        while not self.clock.done:
            self._step()
            self.clock.advance()
            steps += 1
        self._settle_public_fees()
        self._record(self.clock.now, {}, closing=True)
        return self._collect(steps)

    # ------------------------------------------------------------ helpers
    def _ctx(self, ev: EV, site: Optional[Site], now: datetime) -> ChargeContext:
        return ChargeContext(now=now, step=self.clock.step, site=site,
                             price=site.driver_price(now) if site else 0.0,
                             is_on_peak=(site or self.work).is_on_peak(now),
                             view=PlanningView(self, ev))

    def _loc(self, ev: EV, t: datetime) -> Location:
        return self.itinerary[ev.ev_id].location_at(t)

    def _unplug(self, ev: EV) -> None:
        site = self._plugged.pop(ev.ev_id, None)
        if site is not None:
            site.station.unplug(ev)
        self._idle_since.pop(ev.ev_id, None)

    def _visit_window(self, ev: EV, station: Site, now: datetime):
        itin = self.itinerary[ev.ev_id]
        a, b = self.cfg.public_visit_hours
        if (itin.location_at(now) is not Location.HOME or itin.active_visit(now) is not None
                or not a <= now.hour < b):
            return None
        arrive = self._plug_time(now + station.detour)
        latest = min(arrive + station.max_dwell, itin.next_home_departure(now) - station.detour)
        latest = self._floor_step(latest)
        if latest - arrive < self.clock.step:
            return None
        return arrive, latest

    def _floor_step(self, t: datetime) -> datetime:
        steps = (t - self.cfg.start) // self.clock.step
        return self.cfg.start + steps * self.clock.step

    def _plug_time(self, t: datetime) -> datetime:
        """First step start at or after t: when a car arriving at t can plug in."""
        floor = self._floor_step(t)
        return floor if floor == t else floor + self.clock.step

    def _book_visit(self, ev: EV, station_name: str, target_kwh: float, now: datetime) -> bool:
        station = self.public.get(station_name)
        if station is None or target_kwh <= _EPS:
            return False
        window = self._visit_window(ev, station, now)
        if window is None:
            return False
        plug, latest = window
        view = PlanningView(self, ev)
        steps = math.ceil(target_kwh / max(view.power_kw(station) * self.clock.step_hours, _EPS) - 1e-9)
        planned = min(latest, plug + max(1, steps) * self.clock.step)
        self.itinerary[ev.ev_id].visits.append(Visit(station, now, target_kwh, latest, planned))
        self._stats[ev.ev_id]["public_visits"] += 1
        return True

    # ------------------------------------------------------------ one step
    def _step(self) -> None:
        now = self.clock.now
        step_end = now + self.clock.step
        step_h = self.clock.step_hours
        today = now.date()
        self._days_seen.add(today)
        self._settle_public_fees(before=today)
        
        # daily home-charger fee (network + maintenance), once per calendar day
        for ev in self.evs:
            home = self.homes.get(ev.ev_id)
            if home is not None and home.fixed_cost_per_day > 0 and self._fixed_billed.get(ev.ev_id) != today:
                self._fixed_billed[ev.ev_id] = today
                ev.cost += home.fixed_cost_per_day
                self._stats[ev.ev_id]["home_fixed_cost"] += home.fixed_cost_per_day

        # 0. public visits: leave the station when done; maybe head out to one
        for ev in self.evs:
            itin = self.itinerary[ev.ev_id]
            visit = itin.active_visit(now)
            if visit is not None and visit.depart is None and visit.arrive <= now:
                if visit.charged_kwh >= visit.target_kwh - 1e-6 or ev.is_done or now >= visit.latest_depart:
                    visit.depart = now
                    stay = (visit.back - visit.leave).total_seconds() / 3600
                    self._stats[ev.ev_id]["public_hours"] += stay
                elif now >= visit.planned_depart:
                    visit.planned_depart = min(visit.latest_depart, now + self.clock.step)
            elif visit is None and self.public and itin.location_at(now) is Location.HOME:
                req = ev.strategy.public_visit(ev, PlanningView(self, ev))
                if req is not None:
                    self._book_visit(ev, req[0], req[1], now)
            if now.hour == 0 and now.minute == 0:
                itin.prune(now - timedelta(days=1))

        # 1. leaving a site
        for ev in self.evs:
            loc = self._loc(ev, now)
            site = self._plugged.get(ev.ev_id)
            if site is not None and site.location is not loc:
                self._unplug(ev)
            if loc is not Location.WORK:
                self._parked.discard(ev.ev_id)
            if loc not in (Location.WORK, Location.PUBLIC):
                self._waiting.discard(ev.ev_id)

        # 2. work rules
        w = self.work
        for ev in self.evs:
            if self._plugged.get(ev.ev_id) is not w:
                continue
            idle = self._idle_since.get(ev.ev_id)
            used = self._work_plugged_day[ev.ev_id].get(today, 0.0)
            if w.move_window is not None and idle is not None and now >= idle + w.move_window:
                self._unplug(ev)
                self._parked.add(ev.ev_id)
                self._stats[ev.ev_id]["moves"] += 1
            elif w.daily_limit is not None and used >= w.daily_limit.total_seconds() / 3600 - _EPS:
                self._unplug(ev)
                self._parked.add(ev.ev_id)
                self._stats[ev.ev_id]["limit_moves"] += 1

        # 3. plug in
        for ev in self.evs:
            if ev.ev_id in self._plugged:
                continue
            loc = self._loc(ev, now)
            if loc is Location.HOME and ev.ev_id in self.homes:
                home = self.homes[ev.ev_id]
                home.station.plug_in(ev)
                self._plugged[ev.ev_id] = home
            elif loc is Location.PUBLIC:
                station = self.itinerary[ev.ev_id].active_visit(now).station
                if station.station.plug_in(ev) is not None:
                    self._plugged[ev.ev_id] = station
                    self._waiting.discard(ev.ev_id)
                else:
                    self._waiting.add(ev.ev_id)
            elif (loc is Location.WORK and w.station.num_chargers
                  and ev.ev_id not in self._parked and self._work_hours_left(ev, today) > _EPS):
                if ev.strategy.wants_charger(ev, self._ctx(ev, w, now)):
                    if w.station.plug_in(ev) is not None:
                        self._plugged[ev.ev_id] = w
                        self._waiting.discard(ev.ev_id)
                    else:
                        self._waiting.add(ev.ev_id)
                else:
                    self._waiting.discard(ev.ev_id)

        # 4. charge
        "sites with a grid cap (p_max_kw) share power proportionally."
        before = {ev.ev_id: (ev.soc, ev.cost) for ev in self.evs}
        eff = self.cfg.charging_efficiency

        # 4a. what each plugged-in car would take this step
        draws: list[_Draw] = []
        for ev in self.evs:
            site = self._plugged.get(ev.ev_id)
            if site is None:
                continue
            itin = self.itinerary[ev.ev_id]
            hours = step_h * itin.fraction_at(site.location, now, step_end)
            visit = itin.active_visit(now) if site.location is Location.PUBLIC else None
            if site is w:
                hours = min(hours, self._work_hours_left(ev, today))   # daily limit
                self._work_plugged_day[ev.ev_id][today] = (
                    self._work_plugged_day[ev.ev_id].get(today, 0.0) + hours)
                self._stats[ev.ev_id]["work_plugged_hours"] += hours
            ctx = self._ctx(ev, site, now)
            if ev.is_done:
                limit = 0.0
            elif visit is not None:
                limit = max(0.0, visit.target_kwh - visit.charged_kwh)
            else:
                limit = ev.strategy.charge_limit_kwh(ev, ctx)
            stored = min(ev.charge_capacity_kwh(site.charger_kw, site.kind, hours, eff), limit)
            draws.append(_Draw(ev, site, visit, ctx, stored))

        # 4b. sites over their grid cap share power
        self._apply_grid_caps(draws, step_h)

        # 4c. deliver the energy
        drawn: dict[str, float] = {}
        home_kw = work_kw = 0.0
        station_kw = defaultdict(float)
        for d in draws:
            ev, site, visit, ctx, stored = d.ev, d.site, d.visit, d.ctx, d.stored
            if stored <= _EPS:
                if site is w:
                    self._idle_since.setdefault(ev.ev_id, now)
                continue
            self._idle_since.pop(ev.ev_id, None)
            kwh = stored / eff
            ev.add_energy(stored)
            ev.energy_drawn_kwh += kwh
            ev.cost += kwh * ctx.price
            drawn[ev.ev_id] = kwh
            s = self._stats[ev.ev_id]
            s["on_peak_kwh" if ctx.is_on_peak else "off_peak_kwh"] += kwh
            if site is w:
                where = "work"
                work_kw += kwh / step_h
            elif visit is not None:
                where = "public"
                self._station_users[(site.name, today)].add(ev.ev_id)
                visit.charged_kwh += stored
                s[f"public_kwh_{site.public_kind}"] += kwh
                station_kw[site.name] += kwh / step_h
                self._station_revenue[site.name] += kwh * ctx.price
            else:
                where = "home"
                home_kw += kwh / step_h
            s[f"{where}_kwh"] += kwh
            s[f"{where}_cost"] += kwh * ctx.price
        # Work and public meters see every step, even with no load, so each bill's
        # prorated customer charge covers the whole run. Home bills aren't modelled:
        # the household pays them anyway; EV cost at home = kWh x pass-through price.
        w.meter.record(now, self.clock.step, work_kw * step_h, w.is_on_peak(now),
                       w.supply.price_at(now))
        for name, st in self.public.items():
            kw = station_kw.get(name, 0.0)
            st.meter.record(now, self.clock.step, kw * step_h, st.is_on_peak(now), st.supply.price_at(now))
            self._station_kwh[name] += kw * step_h
            self._station_peak[name] = max(self._station_peak[name], kw)
        if home_kw > self._peak_home[0]:
            self._peak_home = (home_kw, now)
        self._peak_work = max(self._peak_work, work_kw)

        # recorder snapshot uses the state during the step, before driving
        if self.recorder is not None:
            self._record(now, drawn, before)

        # 5. drive
        buffer = self.cfg.soc_buffer
        for ev in self.evs:
            s = self._stats[ev.ev_id]
            itin = self.itinerary[ev.ev_id]
            if ev.soc < buffer - _EPS:
                s["hours_below_buffer"] += step_h
            if ev.ev_id in self._waiting:
                key = "public_waiting_hours" if self._loc(ev, now) is Location.PUBLIC else "work_waiting_hours"
                s[key] += step_h
            miles = itin.driving_miles(now, step_end)
            if miles > 0:
                ev.drive(miles)
                if itin.location_at(step_end) is not Location.DRIVING:   # trip ended
                    s["trips"] += 1
                    if ev.soc < buffer - _EPS:
                        s["trips_below_buffer"] += 1
            s["min_soc"] = min(s["min_soc"], ev.soc)

    def _work_hours_left(self, ev: EV, day: date) -> float:
        return PlanningView(self, ev).work_hours_left(day)

    def _apply_grid_caps(self, draws: list[_Draw], step_h: float) -> None:
        """Scale down the cars at any site whose total grid draw exceeds p_max_kw."""
        eff = self.cfg.charging_efficiency
        by_site: dict[str, list[_Draw]] = defaultdict(list)
        for d in draws:
            if d.site.p_max_kw is not None:
                by_site[d.site.name].append(d)
        for group in by_site.values():
            requests = {d.ev.ev_id: d.stored / eff / step_h for d in group}   # grid-side kW
            granted = group[0].site.allocate_power(requests)
            for d in group:
                asked = requests[d.ev.ev_id]
                if asked > _EPS:
                    d.stored *= granted[d.ev.ev_id] / asked

    def _settle_public_fees(self, before: Optional[date] = None) -> None:
        """Split each finished day's station fixed cost equally among that day's users.
        before=None settles everything (end of run)."""
        ev_by_id = {e.ev_id: e for e in self.evs}
        for key in sorted(k for k in self._station_users if before is None or k[1] < before):
            users = self._station_users.pop(key)
            fee = self.public[key[0]].fixed_cost_per_day
            if fee <= 0 or not users:
                continue
            share = fee / len(users)
            for ev_id in sorted(users):
                ev_by_id[ev_id].cost += share
                self._stats[ev_id]["public_fixed_cost"] += share
            self._fee_revenue[key[0]] += fee

    # ------------------------------------------------------------ recording
    def _state(self, ev: EV, now: datetime, drawn: dict[str, float]) -> EVState:
        loc = self._loc(ev, now)
        if ev.ev_id in drawn:
            return EVState.CHARGING
        if ev.ev_id in self._plugged:
            return EVState.IDLE
        if loc is Location.DRIVING:
            return EVState.DRIVING
        if loc in (Location.WORK, Location.PUBLIC):
            return EVState.WAITING if ev.ev_id in self._waiting else EVState.PARKED
        return EVState.AWAY

    def _record(self, now: datetime, drawn: dict[str, float],
                before: Optional[dict[str, tuple[float, float]]] = None,
                closing: bool = False) -> None:
        """Snapshot of every car. SOC and cost are taken at the start of the step
        (`before`), like Simulation; the closing row has the final values."""
        if self.recorder is None or not self.evs:
            return
        step_h = self.clock.step_hours
        snaps = []
        for ev in self.evs:
            site = self._plugged.get(ev.ev_id)
            soc, cost = before[ev.ev_id] if before else (ev.soc, ev.cost)
            shared = site is not None and site.owner is None and not closing
            loc = self._loc(ev, now)
            where = site.name if site is not None else None
            if loc is Location.WORK:
                where = self.work.name
            elif loc is Location.PUBLIC:
                visit = self.itinerary[ev.ev_id].active_visit(now)
                where = visit.station.name if visit else where
            snaps.append(EVSnapshot(
                ev_id=ev.ev_id, state=self._state(ev, now, drawn),
                charger_id=site.station.charger_of(ev).charger_id if shared else None,
                soc=soc, power_kw=drawn.get(ev.ev_id, 0.0) / step_h, cost=cost,
                location=loc.value, site=where,
            ))
        try:
            prices = {"home": self._home_factory.utility.price_at(now),
                      "work": self.work.driver_price(now)}
            prices.update({name: st.driver_price(now) for name, st in self.public.items()})
            on_peak = self.work.is_on_peak(now)
            supply, utility = self.work.supply.price_at(now), self.work.utility.price_at(now)
        except KeyError:            # closing row past the end of the price data
            last = self.recorder.records[-1]
            prices, on_peak = dict(last.prices), last.on_peak
            supply, utility = last.supply_price, last.utility_price
        self.recorder.record(now, prices["work"], on_peak, snaps, supply, utility, prices=prices)

    # ------------------------------------------------------------ results
    def _collect(self, steps: int) -> CommuteResult:
        results = []
        for ev in self.evs:
            s = self._stats[ev.ev_id]
            results.append(CommuteEVResult(
                ev_id=ev.ev_id, home_charger=self.home_type[ev.ev_id],
                strategy=getattr(ev.strategy, "name", type(ev.strategy).__name__),
                start_soc=ev.start_soc, final_soc=ev.soc, min_soc=s["min_soc"],
                home_kwh=s["home_kwh"], work_kwh=s["work_kwh"],
                home_cost=s["home_cost"], work_cost=s["work_cost"],
                on_peak_kwh=s["on_peak_kwh"], off_peak_kwh=s["off_peak_kwh"],
                miles_driven=ev.miles_driven, energy_driven_kwh=ev.energy_driven_kwh,
                shortfall_kwh=ev.shortfall_kwh, trips=int(s["trips"]),
                trips_below_buffer=int(s["trips_below_buffer"]),
                hours_below_buffer=s["hours_below_buffer"],
                work_waiting_hours=s["work_waiting_hours"],
                work_plugged_hours=s["work_plugged_hours"],
                moves=int(s["moves"]), limit_moves=int(s["limit_moves"]),
                public_kwh=s["public_kwh"], public_cost=s["public_cost"],
                public_visits=int(s["public_visits"]), public_hours=s["public_hours"],
                public_waiting_hours=s["public_waiting_hours"],
                public_kwh_by_kind={k: s[f"public_kwh_{k}"] for k in ("L2", "DCFC")
                                    if s[f"public_kwh_{k}"] > 0},
                public_fixed_cost=s["public_fixed_cost"],
                home_fixed_cost=s["home_fixed_cost"],
            ))
        names = sorted({r.strategy for r in results})
        prorate = self.cfg.prorate_fixed_charges
        stations = [StationResult(name=n, kind=st.public_kind, price=st.flat_price,
                                  revenue=self._station_revenue[n], energy_kwh=self._station_kwh[n],
                                  peak_kw=self._station_peak[n], bills=st.meter.bills(st.rate, prorate),
                                  fixed_cost=st.fixed_cost_per_day * len(self._days_seen),
                                  fee_revenue=self._fee_revenue[n])
                    for n, st in self.public.items()]
        return CommuteResult(
            ev_results=results, config=self.cfg, steps_run=steps, ended_at=self.clock.now,
            timeline=list(self.recorder.records) if self.recorder else [],
            work_bills=self.work.meter.bills(self.work.rate, prorate),
            peak_home_kw=self._peak_home[0], peak_home_at=self._peak_home[1],
            peak_work_kw=self._peak_work, strategy=" + ".join(names), stations=stations,
        )
