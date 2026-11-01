"""Greedy baseline: buy the cheapest charging slots that keep the charge goal.

Each driver plans on its own (decentralized), using only what a real driver
could know (PlanningView): its SOC and schedule, its home charger, posted prices
(on-peak prices one day ahead, see PlanningView.price_forecast), and its own
work limits. It does not know what other drivers will do.

Plan (re-made every day, and whenever things didn't go as planned):
  1. Cut the next `horizon_hours` into timesteps. For each one: where the car
     is, how much energy driving uses, and how much it could charge there
     (home charger, work charger within the daily limit, nothing while driving;
     at a public station already booked, the visit's target is fixed).
  2. Walk forward in time. When the battery would drop below the buffer
     (cfg.soc_buffer), pick the cheapest earlier slot with room left and buy
     just enough energy there; repeat until the dip is covered. Ties go to the
     earliest slot (tie_break="earliest") or the latest ("latest").
     The battery never goes above the car's required_soc.
  3. Charge what the plan says for the current step.
  4. Public charging: if home + work can't keep the buffer and the first dip is
     within `public_lookahead_hours`, book a public visit now (only possible from
     home). Pick the cheapest station that can deliver what's missing over the
     next `public_lookahead_hours` (plus the detour) before the driver must be
     home again, and fill up there toward everything the horizon is missing; if
     no station can, the one that delivers the most. Public L2 ($0.39) beats DC
     fast ($0.485) when there's time.

Replanning: if the car's actual charge differs from the plan (e.g. every work
charger was taken, the car was moved, or a DC charger tapered), the next step
builds a new plan from the actual state. This is the "replan when blocked"
rule from Rate et al.: future work slots are assumed available until the car
finds them taken.

This is a myopic, price-only baseline: it has no value of time, ignores
congestion it can't see yet, and buys the minimum (so it runs near the buffer).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from ..driver import Location
from .base import ChargeContext, Strategy

_EPS = 1e-6


@dataclass
class _Slot:
    t: datetime
    location: Location
    drive_kwh: float
    capacity_kwh: float          # battery-side kWh this slot can add
    price: float                 # $/kWh (grid side), inf if no charger
    hours: float                 # time at the charger in this slot
    alloc_kwh: float = 0.0


@dataclass
class Plan:
    made_at: datetime
    slots: list[_Slot]
    start_kwh: float             # battery energy when the plan was made
    unmet_kwh: float = 0.0       # energy home + work can't supply within the horizon
    first_unmet: Optional[datetime] = None   # when the battery first dips below the buffer
    shortfalls: tuple = ()       # (time, kWh) for every dip home + work can't cover

    def unmet_before(self, t: datetime) -> float:
        return sum(kwh for when, kwh in self.shortfalls if when < t)

    def index_of(self, t: datetime) -> int | None:
        if not self.slots:
            return None
        k = round((t - self.slots[0].t) / (self.slots[1].t - self.slots[0].t)) if len(self.slots) > 1 else 0
        return k if 0 <= k < len(self.slots) and self.slots[k].t == t else None

    def expected_kwh_at(self, k: int) -> float:
        """Battery energy at the start of slot k if the plan runs as planned."""
        return self.start_kwh + sum(s.alloc_kwh - s.drive_kwh for s in self.slots[:k])

    @property
    def cost(self) -> float:
        return sum(s.alloc_kwh * s.price for s in self.slots if s.alloc_kwh > 0)


class Greedy(Strategy):
    name = "greedy"

    def __init__(self, horizon_hours: float = 96.0, tie_break: str = "earliest",
                 public_lookahead_hours: float = 24.0) -> None:
        if tie_break not in ("earliest", "latest"):
            raise ValueError("tie_break must be 'earliest' or 'latest'")
        self.horizon = timedelta(hours=horizon_hours)
        self.public_lookahead = timedelta(hours=public_lookahead_hours)
        self.tie_break = tie_break
        self.plans: dict[str, Plan] = {}
        self.replans = 0

    # -------------------------------------------------------- Strategy API
    def decide(self, ev, now, price, is_on_peak) -> bool:
        raise TypeError("Greedy plans across home and work; use it with CommuteSimulation")

    def wants_charger(self, ev, ctx: ChargeContext) -> bool:
        return self._planned_kwh(ev, ctx) > _EPS

    def charge_limit_kwh(self, ev, ctx: ChargeContext) -> float:
        return self._planned_kwh(ev, ctx)

    def public_visit(self, ev, view):
        if not view.public_stations:
            return None
        plan = self._current_plan(ev, view)
        if plan.unmet_kwh <= _EPS or plan.first_unmet is None:
            return None
        if plan.first_unmet - view.now > self.public_lookahead:
            return None          # not urgent yet; work or a later visit may cover it
        room = max(0.0, view.cap_kwh - ev.soc * ev.battery_kwh)
        urgent = plan.unmet_before(plan.first_unmet + self.public_lookahead)
        best = None              # (covers the urgent need?, -price or deliverable), station, target
        for st in view.public_stations:
            window = view.visit_window(st)
            if window is None:
                continue
            arrive, latest = window
            detour_kwh = 2 * st.detour_miles * ev.kwh_per_mile
            deliverable = view.power_kw(st) * (latest - arrive).total_seconds() / 3600
            target = min(room, plan.unmet_kwh + detour_kwh, deliverable)
            enough = deliverable >= min(room, urgent + detour_kwh) - _EPS
            key = (True, -st.flat_price) if enough else (False, deliverable)
            if best is None or key > best[0]:
                best = (key, st, target)
        if best is None or best[2] <= _EPS:
            return None
        self.plans.pop(ev.ev_id, None)       # the visit changes the day: plan again
        return best[1].name, best[2]

    # -------------------------------------------------------- planning
    def _current_plan(self, ev, view) -> Plan:
        plan = self.plans.get(ev.ev_id)
        k = plan.index_of(view.now) if plan else None
        stale = (plan is None or k is None or plan.made_at.date() != view.now.date()
                 or abs(plan.expected_kwh_at(k) - ev.soc * ev.battery_kwh) > 1e-3)
        if stale:
            plan = self.plan(ev, view)
            self.plans[ev.ev_id] = plan
            self.replans += 1
        return plan

    def _planned_kwh(self, ev, ctx: ChargeContext) -> float:
        plan = self._current_plan(ev, ctx.view)
        slot = plan.slots[plan.index_of(ctx.now)]
        return slot.alloc_kwh if slot.location is ctx.site.location else 0.0

    def plan(self, ev, view) -> Plan:
        slots = self._slots(ev, view)
        start = ev.soc * ev.battery_kwh
        short = self._allocate(slots, start, view.buffer_kwh, view.cap_kwh)
        if short and view.public_stations:
            # It will need a public visit: keep enough above the buffer to drive
            # to the station, so the trip there doesn't dip below the buffer.
            reserve = max(st.detour_miles for st in view.public_stations) * ev.kwh_per_mile
            slots = self._slots(ev, view)
            short = self._allocate(slots, start, view.buffer_kwh + reserve, view.cap_kwh)
        return Plan(made_at=view.now, slots=slots, start_kwh=start,
                    unmet_kwh=sum(kwh for _, kwh in short),
                    first_unmet=slots[short[0][0]].t if short else None,
                    shortfalls=tuple((slots[k].t, kwh) for k, kwh in short))

    def _slots(self, ev, view) -> list[_Slot]:
        itin, step, step_h = view.itinerary, view.step, view.step_hours
        n = max(1, int(self.horizon / step))
        work_left: dict = {}
        committed: dict = {}     # public visit -> battery kWh still to add
        out = []
        for i in range(n):
            t = view.now + i * step
            loc = itin.location_at(t)
            site = view.site_for(loc, t)
            drive = itin.driving_miles(t, t + step) * ev.kwh_per_mile
            cap, price, hours, fixed = 0.0, math.inf, 0.0, False
            if site is not None:
                hours = step_h * itin.fraction_at(loc, t, t + step)
                if loc is Location.WORK:
                    day = t.date()
                    left = work_left.setdefault(day, view.work_hours_left(day))
                    hours = min(hours, left)
                    work_left[day] = left - hours
                cap = view.power_kw(site) * hours
                price = view.price_forecast(site, t)
                if loc is Location.PUBLIC:       # booked visit: charges its target, no more
                    v = itin.active_visit(t)
                    left = committed.setdefault(id(v), max(0.0, v.target_kwh - v.charged_kwh))
                    cap = min(cap, left)
                    committed[id(v)] = left - cap
                    fixed = True
            slot = _Slot(t, loc, drive, cap, price, hours)
            if fixed:
                slot.alloc_kwh = cap
            out.append(slot)
        return out

    def _allocate(self, slots: list[_Slot], start: float, floor: float,
                  cap: float) -> list[tuple[int, float]]:
        """Greedy fill: cover every dip below `floor` with the cheapest earlier slots.
        Returns the dips it couldn't cover: [(slot index, kWh missing)]."""
        n = len(slots)
        after = [0.0] * n        # battery after each slot's charging (before its driving)
        sign = 1 if self.tie_break == "earliest" else -1
        forgiven = 0.0           # energy the plan can't find; don't chase it again
        short: list[tuple[int, float]] = []
        e = start
        for k in range(n):
            after[k] = e + slots[k].alloc_kwh
            e_end = after[k] - slots[k].drive_kwh
            deficit = floor - (e_end + forgiven)
            if deficit > _EPS:
                order = sorted((j for j in range(k + 1) if slots[j].capacity_kwh - slots[j].alloc_kwh > _EPS),
                               key=lambda j: (round(slots[j].price, 6), sign * j))
                for j in order:
                    headroom = cap - max(after[j:k + 1])
                    x = min(deficit, slots[j].capacity_kwh - slots[j].alloc_kwh, headroom)
                    if x <= _EPS:
                        continue
                    slots[j].alloc_kwh += x
                    for i in range(j, k + 1):
                        after[i] += x
                    deficit -= x
                    if deficit <= _EPS:
                        break
                e_end = after[k] - slots[k].drive_kwh
                if deficit > _EPS:
                    forgiven += deficit
                    short.append((k, deficit))
            e = e_end
        return short
