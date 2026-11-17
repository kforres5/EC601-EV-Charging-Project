"""CentralController: one planner that schedules every car together.

The centralized baseline (team_notes/Centralized_Controller_Plan.md). It builds one
mixed-integer linear program (MILP) for the whole fleet over the next
`horizon_hours` and solves it with SciPy's HiGHS solver (scipy.optimize.milp).
Each car follows the plan through a CentralizedStrategy
(strategies/centralized.py); every car in the simulation must use one that
points at the same controller.

Decisions (see the plan doc for why):
  1. Objective: what drivers pay (kWh x the price at that site), plus a penalty
     for each kWh below the charge-goal buffer, plus small per-session costs.
  2. Prices: only what's posted. Same day-ahead rule as greedy
     (PlanningView.price_forecast): on-peak known through tomorrow, off-peak for
     the month, flat work / public prices.
  3. Public stations are planned too.

What it sees (FleetView, commute.py): every car's charge, schedule, home charger,
work-charging use today and visits under way; every site's chargers.

Model, per car i and 15-minute slot k (k = 0 is the current step):
  E[i,k]        battery kWh at the start of slot k (E[i,0] = current charge)
  h[i,k]        kWh added at home        (only if the driver is home at the slot start)
  w[i,k]        kWh added at work        (only if at work); on[i,k] = holds a work
                charger, start[i,k] = a work session starts
  p[i,j,k]      kWh added at public station j; occ[i,j,k] = charging there,
                go[i,j,k] = leaves home for j in slot k-1 and plugs in at slot k
  slack[i,k]    kWh below the buffer (heavily penalized)
  E[k+1] = E[k] + h + w + sum p + (visit already under way) - driving - detours
  E[k] + charge in slot k <= target;  E[k+1] + slack >= buffer
  work: sum_i on <= chargers; one session per day; plugged hours <= daily limit
  public: sum_i occ <= chargers; one visit per stretch at home; at most the
          station's longest stay; only from home, leaving within visit hours,
          back before the next commute; no home charging while away
How a planned visit maps onto the simulation: the car leaves home at slot k-1,
plugs in at slot k (the simulation's _plug_time), charges in slots k..e, and
drives home in slot e+1. Both detour legs are counted at slot k-1.

When it plans: the first time a car asks in a step, if there is no plan, a new
day has started (new day-ahead prices), the plan has run out, or any car's
charge has drifted from the plan (DC taper, partial slots, a blocked plug).

Keeping it fast (yes/no variables are what make a MILP slow):
  - public="as_needed" (default): solve first without public stations; only if
    some car can't keep the buffer, solve again offering stations to those cars.
    public="always" offers them to every car (same answer, slower).
  - binary_hours (default 48): yes/no choices are exact for the first 48 hours;
    after that they're relaxed to fractions, since the plan is redone daily anyway.
"""
from __future__ import annotations

import math
import time as _time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from .driver import Location

_INF = math.inf


# ------------------------------------------------------------------ model builder
class _Model:
    """A tiny sparse MILP builder on top of scipy.optimize.milp."""

    def __init__(self) -> None:
        self.c: list[float] = []
        self.lb: list[float] = []
        self.ub: list[float] = []
        self.integer: list[int] = []
        self._r: list[int] = []
        self._c: list[int] = []
        self._v: list[float] = []
        self.row_lb: list[float] = []
        self.row_ub: list[float] = []

    def var(self, lb: float = 0.0, ub: float = _INF, cost: float = 0.0, integer: bool = False) -> int:
        self.c.append(cost)
        self.lb.append(lb)
        self.ub.append(ub)
        self.integer.append(1 if integer else 0)
        return len(self.c) - 1

    def binary(self, cost: float = 0.0) -> int:
        return self.var(0.0, 1.0, cost, integer=True)

    def row(self, terms, lb: float = -_INF, ub: float = _INF) -> None:
        r = len(self.row_lb)
        for idx, coef in terms:
            if coef:
                self._r.append(r)
                self._c.append(idx)
                self._v.append(coef)
        self.row_lb.append(lb)
        self.row_ub.append(ub)

    @property
    def size(self) -> tuple[int, int, int]:
        return len(self.c), sum(self.integer), len(self.row_lb)

    def solve(self, time_limit: float, mip_gap: float):
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix
        n = len(self.c)
        cons = []
        if self.row_lb:
            a = coo_matrix((self._v, (self._r, self._c)), shape=(len(self.row_lb), n)).tocsr()
            cons = [LinearConstraint(a, np.array(self.row_lb), np.array(self.row_ub))]
        return milp(np.array(self.c), constraints=cons, integrality=np.array(self.integer),
                    bounds=Bounds(np.array(self.lb), np.array(self.ub)),
                    options={"time_limit": time_limit, "mip_rel_gap": mip_gap, "disp": False})


# ------------------------------------------------------------------ plan
@dataclass
class CarPlan:
    """One car's schedule, slot by slot (battery-side kWh)."""
    home: np.ndarray
    work: np.ndarray
    work_on: np.ndarray                     # bool
    public: np.ndarray                      # kWh at any public station
    energy: np.ndarray                      # battery kWh at the start of each slot (n + 1)
    visits: dict[int, tuple[str, float]] = field(default_factory=dict)   # leave slot -> (station, kWh)
    slack: float = 0.0                      # kWh-slots below the buffer the plan accepts


@dataclass
class FleetPlan:
    made_at: datetime
    step: timedelta
    slots: int
    cars: dict[str, CarPlan]
    objective: float
    status: str
    gap: Optional[float]
    seconds: float

    def index(self, t: datetime) -> Optional[int]:
        k, rem = divmod(t - self.made_at, self.step)
        return int(k) if not rem and 0 <= k < self.slots else None


# ------------------------------------------------------------------ controller
class CentralController:
    def __init__(self, fleet, horizon_hours: float = 96.0, time_limit: float = 60.0,
                 mip_gap: float = 0.01, goal_penalty: float = 2.0, work_session_cost: float = 0.01,
                 work_slot_cost: float = 0.001, visit_cost: float = 0.05, drift_kwh: float = 0.05,
                 public: str = "as_needed", binary_hours: float = 48.0) -> None:
        """fleet: CommuteSimulation.fleet_view(). goal_penalty is $ per kWh below the
        buffer per 15-minute slot (far above any price, so the goal wins when it can).
        Session / slot / visit costs are small tie-breakers that stop pointless
        plug-ins, charger hogging and trips."""
        self.fleet = fleet
        self.horizon = timedelta(hours=horizon_hours)
        self.time_limit = time_limit
        self.mip_gap = mip_gap
        self.goal_penalty = goal_penalty
        self.work_session_cost = work_session_cost
        self.work_slot_cost = work_slot_cost
        self.visit_cost = visit_cost
        self.drift_kwh = drift_kwh
        if public not in ("as_needed", "always"):
            raise ValueError("public must be 'as_needed' or 'always'")
        self.public = public
        self.binary_hours = binary_hours
        self.plan: Optional[FleetPlan] = None
        self._checked_at: Optional[datetime] = None
        # stats for summaries
        self.solves = 0
        self.failures = 0
        self.solve_seconds = 0.0
        self.max_solve_seconds = 0.0
        self.last_size: tuple[int, int, int] = (0, 0, 0)
        self.reasons: dict[str, int] = defaultdict(int)

    # ---------------------------------------------------------- lookups
    def ensure_plan(self) -> Optional[FleetPlan]:
        """Plan (again) if needed; at most once per simulation step."""
        now = self.fleet.now
        if self._checked_at == now:
            return self.plan
        self._checked_at = now
        reason = self._replan_reason(now)
        if reason:
            self.reasons[reason] += 1
            self.plan = self._plan(now) or self.plan
        return self.plan

    def _plan(self, now: datetime) -> Optional[FleetPlan]:
        everyone = {ev.ev_id for ev in self.fleet.evs}
        if self.public == "always" or not self.fleet.public_stations:
            return self._solve(now, public_for=everyone)
        first = self._solve(now, public_for=set())
        if first is None:
            return self._solve(now, public_for=everyone)
        short = {i for i, car in first.cars.items() if car.slack > 1e-3}
        if not short:
            return first
        self.reasons["public stations offered"] += 1
        return self._solve(now, public_for=short) or first

    def _replan_reason(self, now: datetime) -> Optional[str]:
        p = self.plan
        if p is None:
            return "first plan"
        k = p.index(now)
        if k is None or k >= p.slots - 1:
            return "plan ran out"
        if p.made_at.date() != now.date():
            return "new day"
        for ev in self.fleet.evs:
            car = p.cars.get(ev.ev_id)
            if car is None or abs(car.energy[k] - ev.soc * ev.battery_kwh) > self.drift_kwh:
                return "off plan"
        return None

    def _slot(self, ev_id: str, now: datetime) -> tuple[Optional[CarPlan], Optional[int]]:
        p = self.ensure_plan()
        if p is None:
            return None, None
        k = p.index(now)
        car = p.cars.get(ev_id)
        return (car, k) if (car is not None and k is not None) else (None, None)

    def work_on(self, ev_id: str, now: datetime) -> Optional[bool]:
        car, k = self._slot(ev_id, now)
        return None if car is None else bool(car.work_on[k])

    def kwh(self, ev_id: str, now: datetime, location: Location) -> Optional[float]:
        car, k = self._slot(ev_id, now)
        if car is None:
            return None
        if location is Location.HOME:
            return float(car.home[k])
        if location is Location.WORK:
            return float(car.work[k])
        return float(car.public[k])

    def visit_now(self, ev_id: str, now: datetime) -> Optional[tuple[str, float]]:
        car, k = self._slot(ev_id, now)
        return None if car is None else car.visits.get(k)

    def summary(self) -> str:
        why = ", ".join(f"{r}: {n}" for r, n in sorted(self.reasons.items()))
        n, b, r = self.last_size
        p = self.plan
        gap = f", gap {p.gap:.1%}" if p and p.gap is not None else ""
        return (f"central controller: {self.solves} solves ({why}), {self.failures} failed; "
                f"{self.solve_seconds:.1f} s total, slowest {self.max_solve_seconds:.1f} s; "
                f"last model {n} variables ({b} yes/no), {r} constraints{gap}")

    # ---------------------------------------------------------- the MILP
    def _solve(self, now: datetime, public_for: set[str]) -> Optional[FleetPlan]:
        fv = self.fleet
        step, sh = fv.step, fv.step_hours
        n = max(2, int(self.horizon / step))
        n_exact = max(1, int(timedelta(hours=self.binary_hours) / step))
        times = [now + k * step for k in range(n)]
        choice = lambda k, cost=0.0: m.var(0.0, 1.0, cost, integer=k < n_exact)   # yes/no (or relaxed)
        cfg = fv.cfg
        eff = cfg.charging_efficiency
        visit_from, visit_to = cfg.public_visit_hours
        work = fv.work
        n_work = work.station.num_chargers
        stations = fv.public_stations
        m = _Model()

        work_on_at = defaultdict(list)          # k -> [on vars]
        occ_at = defaultdict(list)              # (station, k) -> [occ vars]
        busy = defaultdict(int)                 # (station, k) -> cars already on a visit there
        keys = {}                               # ev_id -> variable indices

        for ev in fv.evs:
            view = fv.view(ev)
            itin = fv.itinerary(ev)
            floor, cap = view.buffer_kwh, view.cap_kwh
            loc = [itin.location_at(t) for t in times]
            home_hours = [sh * itin.fraction_at(Location.HOME, t, t + step) if loc[k] is Location.HOME else 0.0
                          for k, t in enumerate(times)]
            drive = [view.drive_kwh(t, t + step) for t in times]
            home = view.home
            p_home = view.power_kw(home) if home else 0.0

            # visits already under way: the simulation charges their target, whatever we say
            fixed = [0.0] * n
            left = {}
            for k, t in enumerate(times):
                if loc[k] is Location.PUBLIC:
                    v = itin.active_visit(t)
                    if v is None:
                        continue
                    busy[(v.station.name, k)] += 1
                    remaining = left.setdefault(id(v), max(0.0, v.target_kwh - v.charged_kwh))
                    hours = sh * itin.fraction_at(Location.PUBLIC, t, t + step)
                    q = min(view.power_kw(v.station) * hours, remaining)
                    fixed[k] = q
                    left[id(v)] = remaining - q

            E = [m.var(lb=-_INF, ub=_INF) for _ in range(n + 1)]
            m.row([(E[0], 1.0)], ev.soc * ev.battery_kwh, ev.soc * ev.battery_kwh)
            slack = [None] + [m.var(cost=self.goal_penalty) for _ in range(n)]

            # ---- home
            h = [None] * n
            if home is not None:
                for k, t in enumerate(times):
                    if home_hours[k] > 0:
                        price = view.price_forecast(home, t) / eff
                        h[k] = m.var(ub=p_home * home_hours[k], cost=price + 1e-6 * k)

            # ---- work
            w, on = [None] * n, [None] * n
            if n_work:
                p_work = view.power_kw(work)
                prev_on = None
                plugged_now = fv.plugged_at(ev) is work
                day_starts = defaultdict(list)
                day_hours = defaultdict(list)
                for k, t in enumerate(times):
                    hours = sh * itin.fraction_at(Location.WORK, t, t + step) if loc[k] is Location.WORK else 0.0
                    today = t.date() == now.date()
                    allowed = hours > 0 and view.work_hours_left(t.date()) > 0 and (
                        not today or fv.can_use_work_today(ev))
                    if not allowed:
                        prev_on = None
                        continue
                    on[k] = choice(k, self.work_slot_cost)
                    w[k] = m.var(ub=p_work * hours, cost=view.price_forecast(work, t) / eff + 1e-6 * k)
                    m.row([(w[k], 1.0), (on[k], -p_work * hours)], ub=0.0)
                    start = choice(k, self.work_session_cost)
                    terms = [(on[k], 1.0), (start, -1.0)]
                    if prev_on is not None:
                        terms.append((prev_on, -1.0))
                        m.row(terms, ub=0.0)
                    elif k == 0 and plugged_now:
                        m.row(terms, ub=1.0)            # continuing the session already under way
                    else:
                        m.row(terms, ub=0.0)
                    day_starts[t.date()].append(start)
                    day_hours[t.date()].append((on[k], hours))
                    work_on_at[k].append(on[k])
                    prev_on = on[k]
                for d, starts in day_starts.items():
                    allowed_starts = 0 if (d == now.date() and fv.worked_today(ev)) else 1
                    m.row([(s, 1.0) for s in starts], ub=allowed_starts)
                for d, terms in day_hours.items():
                    limit = view.work_hours_left(d)
                    if limit < _INF:
                        m.row(terms, ub=limit)

            # ---- public stations (new visits)
            full_home = [home_hours[k] >= sh - 1e-9 for k in range(n)]
            stretch = [None] * n                # id of the stretch at home each slot belongs to
            sid = 0
            for k in range(n):
                if full_home[k]:
                    if k == 0 or not full_home[k - 1]:
                        sid += 1
                    stretch[k] = sid
            p_pub = [[None] * n for _ in stations]
            occ = [[None] * n for _ in stations]
            go = [[None] * n for _ in stations]
            stretch_go = defaultdict(list)
            for j, st in enumerate(stations if ev.ev_id in public_for else []):
                power = view.power_kw(st) * sh
                longest = max(1, int(st.max_dwell / step))
                detour_kwh = 2 * st.detour_miles * ev.kwh_per_mile
                stretch_occ = defaultdict(list)
                for k in range(1, n - 1):
                    # charge at k; slot k+1 home (drive back); same stretch at home throughout
                    if not (full_home[k] and full_home[k + 1] and stretch[k] == stretch[k + 1]):
                        continue
                    can_leave = (full_home[k - 1] and stretch[k - 1] == stretch[k]
                                 and visit_from <= times[k - 1].hour < visit_to)
                    if not can_leave and occ[j][k - 1] is None:
                        continue
                    occ[j][k] = choice(k)
                    p_pub[j][k] = m.var(ub=power, cost=st.flat_price / eff if st.flat_price is not None
                                        else view.price_forecast(st, times[k]) / eff)
                    m.row([(p_pub[j][k], 1.0), (occ[j][k], -power)], ub=0.0)
                    terms = [(occ[j][k], 1.0)]
                    if occ[j][k - 1] is not None:
                        terms.append((occ[j][k - 1], -1.0))
                    if can_leave:
                        go[j][k] = choice(k, self.visit_cost)
                        terms.append((go[j][k], -1.0))
                        stretch_go[stretch[k]].append(go[j][k])
                    m.row(terms, ub=0.0)
                    stretch_occ[stretch[k]].append(occ[j][k])
                    occ_at[(st.name, k)].append(occ[j][k])
                for vars_ in stretch_occ.values():
                    m.row([(v, 1.0) for v in vars_], ub=longest)
            for vars_ in stretch_go.values():
                m.row([(v, 1.0) for v in vars_], ub=1.0)       # one visit per stretch at home
            for k in range(n):
                here = [occ[j][k] for j in range(len(stations)) if occ[j][k] is not None]
                if len(here) > 1:
                    m.row([(v, 1.0) for v in here], ub=1.0)
                # no home charging while charging at a station, or driving there / back
                if h[k] is not None:
                    hk = p_home * home_hours[k]
                    if here:
                        m.row([(h[k], 1.0)] + [(v, hk) for v in here], ub=hk)
                    before = [occ[j][k - 1] for j in range(len(stations)) if k > 0 and occ[j][k - 1] is not None]
                    if before:   # returning in slot k: occ[k-1] = 1 and occ[k] = 0
                        m.row([(h[k], 1.0)] + [(v, hk) for v in before] + [(v, -hk) for v in here], ub=hk)
                    leaving = [go[j][k + 1] for j in range(len(stations)) if k + 1 < n and go[j][k + 1] is not None]
                    if leaving:
                        m.row([(h[k], 1.0)] + [(v, hk) for v in leaving], ub=hk)

            # ---- battery
            for k in range(n):
                charge = [(x, 1.0) for x in (h[k], w[k]) if x is not None]
                charge += [(p_pub[j][k], 1.0) for j in range(len(stations)) if p_pub[j][k] is not None]
                detours = [(go[j][k + 1], 2 * st.detour_miles * ev.kwh_per_mile)
                           for j, st in enumerate(stations) if k + 1 < n and go[j][k + 1] is not None]
                m.row([(E[k + 1], 1.0), (E[k], -1.0)] + [(x, -c) for x, c in charge] + detours,
                      lb=fixed[k] - drive[k], ub=fixed[k] - drive[k])
                m.row([(E[k], 1.0)] + charge, ub=max(cap - fixed[k], 0.0) if charge else _INF)
                m.row([(E[k + 1], 1.0), (slack[k + 1], 1.0)], lb=floor)
            keys[ev.ev_id] = dict(E=E, h=h, w=w, on=on, p=p_pub, occ=occ, go=go, slack=slack)

        for k, vars_ in work_on_at.items():
            if len(vars_) > n_work:
                m.row([(v, 1.0) for v in vars_], ub=n_work)
        for st in stations:
            n_ch = st.station.num_chargers
            for k in range(n):
                vars_ = occ_at.get((st.name, k), [])
                if vars_:
                    m.row([(v, 1.0) for v in vars_], ub=max(0, n_ch - busy[(st.name, k)]))

        self.last_size = m.size
        t0 = _time.perf_counter()
        res = m.solve(self.time_limit, self.mip_gap)
        secs = _time.perf_counter() - t0
        self.solves += 1
        self.solve_seconds += secs
        self.max_solve_seconds = max(self.max_solve_seconds, secs)
        if res.x is None:
            self.failures += 1
            return None
        x = res.x
        val = lambda i: 0.0 if i is None else float(x[i])
        cars = {}
        for ev in fv.evs:
            kv = keys[ev.ev_id]
            visits = {}
            pub = np.zeros(n)
            for j, st in enumerate(stations):
                for k in range(n):
                    pub[k] += max(0.0, val(kv["p"][j][k]))
                    g = kv["go"][j][k]
                    if g is not None and x[g] > 0.5:
                        # leave at k-1; target = what the plan charges in this block
                        kwh, e = 0.0, k
                        while e < n and kv["occ"][j][e] is not None and x[kv["occ"][j][e]] > 0.5:
                            kwh += max(0.0, val(kv["p"][j][e]))
                            e += 1
                        if kwh > 1e-6:
                            visits[k - 1] = (st.name, kwh)
            cars[ev.ev_id] = CarPlan(
                home=np.array([max(0.0, val(i)) for i in kv["h"]]),
                work=np.array([max(0.0, val(i)) for i in kv["w"]]),
                work_on=np.array([i is not None and x[i] > 0.5 for i in kv["on"]]),
                public=pub,
                energy=np.array([val(i) for i in kv["E"]]),
                visits=visits,
                slack=sum(val(i) for i in kv["slack"][1:]),
            )
        gap = getattr(res, "mip_gap", None)
        return FleetPlan(made_at=now, step=step, slots=n, cars=cars, objective=float(res.fun),
                         status=str(res.message), gap=None if gap is None else float(gap), seconds=secs)
