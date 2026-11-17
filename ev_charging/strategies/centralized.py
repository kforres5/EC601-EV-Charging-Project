"""CentralizedStrategy: each car follows the CentralController's plan.

A thin adapter so the simulation treats the centralized baseline like any other
strategy (team_notes/Centralized_Controller_Plan.md). Every car gets one, and they
all share the same CentralController:

    controller = CentralController(sim.fleet_view())
    strategy = CentralizedStrategy(controller)
    sim.add_driver(EV.from_vehicle(..., strategy=strategy), "L2")   # for every car

Each call asks the controller for the current plan (it re-plans at most once per
step, see CentralController.ensure_plan) and reads this car's line of it:
  - wants_charger():    plan has the car on a work charger now
  - charge_limit_kwh(): planned kWh this slot, at this site
  - public_visit():     planned trip to a station leaving now, with its kWh target
  - release_charger():  its planned work session is over, so free the charger
If the controller has no plan (the solver failed), the car falls back to Greedy.
"""
from __future__ import annotations

from typing import Optional

from .base import ChargeContext, Strategy
from .greedy import Greedy


class CentralizedStrategy(Strategy):
    name = "central"

    def __init__(self, controller, fallback: Optional[Strategy] = None) -> None:
        self.controller = controller
        self.fallback = fallback or Greedy()
        self.fallback_calls = 0

    def decide(self, ev, now, price, is_on_peak) -> bool:
        raise TypeError("CentralizedStrategy plans across home, work and public; "
                        "use it with CommuteSimulation")

    def wants_charger(self, ev, ctx: ChargeContext) -> bool:
        on = self.controller.work_on(ev.ev_id, ctx.now)
        if on is None:
            self.fallback_calls += 1
            return self.fallback.wants_charger(ev, ctx)
        return on

    def charge_limit_kwh(self, ev, ctx: ChargeContext) -> float:
        kwh = self.controller.kwh(ev.ev_id, ctx.now, ctx.site.location)
        if kwh is None:
            self.fallback_calls += 1
            return self.fallback.charge_limit_kwh(ev, ctx)
        return kwh if kwh > 1e-6 else 0.0

    def public_visit(self, ev, view):
        if self.controller.ensure_plan() is None:
            self.fallback_calls += 1
            return self.fallback.public_visit(ev, view)
        return self.controller.visit_now(ev.ev_id, view.now)

    def release_charger(self, ev, ctx: ChargeContext) -> bool:
        on = self.controller.work_on(ev.ev_id, ctx.now)
        return on is False
