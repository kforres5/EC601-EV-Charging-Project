"""Strategy interface. The decentralized RL, centralized, random and greedy
strategies each implement it; the simulations never special-case them.

Two simulations use strategies:
  - Simulation (one hub) calls decide(): charge this step or wait.
  - CommuteSimulation (home + work + public) calls wants_charger() when the car
    is at work without a charger, charge_limit_kwh() every step it is plugged in
    at home or work, and public_visit() while the car is at home (go to a public
    station now?). The first two default to decide(), so a decide()-only
    strategy works in both simulations; public_visit() defaults to never.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..sites import Site


@dataclass(frozen=True)
class ChargeContext:
    """What a driver can see when deciding, in CommuteSimulation."""
    now: datetime
    step: timedelta
    site: Optional["Site"]  # the site the car is at (home charger, work hub, public station)
    price: float            # $/kWh the driver pays there this step
    is_on_peak: bool
    view: Any = None        # PlanningView (commute.py): schedule, prices ahead, work limits


class Strategy(ABC):
    name = "strategy"

    @abstractmethod
    def decide(self, ev, now: datetime, price: float, is_on_peak: bool) -> bool:
        """True = charge during this timestep, False = wait."""

    def wants_charger(self, ev, ctx: ChargeContext) -> bool:
        """At work without a charger: plug in now if one is free?"""
        return not ev.is_done and self.decide(ev, ctx.now, ctx.price, ctx.is_on_peak)

    def charge_limit_kwh(self, ev, ctx: ChargeContext) -> float:
        """Plugged in: most battery-side kWh to add this step (0 = wait, inf = as
        much as the charger and car allow, up to the car's required_soc)."""
        return math.inf if self.decide(ev, ctx.now, ctx.price, ctx.is_on_peak) else 0.0

    def public_visit(self, ev, view) -> Optional[tuple[str, float]]:
        """At home: drive to a public station now? Return (station name, battery-side
        kWh to add) or None. `view` is a PlanningView (commute.py)."""
        return None


class AlwaysCharge(Strategy):
    """Uncontrolled charging: plug in whenever possible and charge at full power
    until required_soc. Public charging: if home charging before the next trip
    can't cover the next 24 hours of driving plus the buffer, go to the fastest
    station that fits (DC fast first) and fill up to required_soc."""
    name = "always-charge"

    def decide(self, ev, now, price, is_on_peak) -> bool:
        return True

    def public_visit(self, ev, view):
        if not view.public_stations:
            return None
        itin, now = view.itinerary, view.now
        have = ev.soc * ev.battery_kwh
        if view.home is not None:   # home charging it will get before leaving
            hours = (itin.next_home_departure(now) - now).total_seconds() / 3600
            have += view.power_kw(view.home) * hours
        need = view.drive_kwh(now, now + timedelta(hours=24)) + view.buffer_kwh
        if have >= need:
            return None
        fastest = sorted(view.public_stations, key=lambda st: -view.power_kw(st))
        for st in fastest:
            if view.visit_window(st) is not None:
                return st.name, max(0.0, view.cap_kwh - ev.soc * ev.battery_kwh)
        return None
