"""Charging sites for CommuteSimulation: each driver's home charger, the shared
work hub, and public stations. A site bundles its chargers, its prices and its
utility meter.

Prices at a site:
  - supply: Eversource CT energy price for the site's customer class (price CSV)
  - utility: supply + the site rate's delivery $/kWh (when include_delivery)
  - driver: the flat posted price if the site has one (work fee, public posted
    price), else the utility price (home: the household pays its own bill, so
    it's a pass-through)
"""
from __future__ import annotations
from typing import Hashable, Optional

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import CommuteConfig, PublicStationConfig
from .driver import Location
from .pricing import (DeliveredPriceSchedule, EversourcePriceSchedule, FlatTOUPriceSchedule,
                      PriceSchedule)
from .station import ChargingStation
from .tariffs import DeliveryRate, EVLRate, SiteMeter, get_rate, load_public_prices


@dataclass
class Site:
    name: str                               # "work", "home:<ev_id>" or the public station's name
    location: Location
    station: ChargingStation
    supply: PriceSchedule
    utility: PriceSchedule
    rate: DeliveryRate | EVLRate
    flat_price: Optional[float] = None      # None -> drivers pay the utility price
    owner: Optional[str] = None             # ev_id, for a private home charger
    move_window: Optional[timedelta] = None
    daily_limit: Optional[timedelta] = None
    # public stations only
    public_kind: Optional[str] = None       # "L2" or "DCFC"
    detour: timedelta = timedelta(0)        # one-way drive from home
    detour_miles: float = 0.0               # one-way distance from home
    max_dwell: Optional[timedelta] = None
    meter: SiteMeter = field(default_factory=SiteMeter)   # billed for work and public sites
    p_max_kw: Optional[float] = None        # grid connection limit (grid-side kW); None = uncapped
    fixed_cost_per_day: float = 0.0         # network + maintenance: home L2 owner pays it daily;
                                            # public: station owes it, drivers split it (commute.py)

    def allocate_power(self, requests_kw: dict[Hashable, float]) -> dict[Hashable, float]:
        """Grid-side kW each request may draw. Over the cap, every request is scaled
        by the same factor (proportional sharing); under it, requests pass through."""
        total = sum(requests_kw.values())
        if self.p_max_kw is None or total <= self.p_max_kw or total <= 0:
            return dict(requests_kw)
        scale = self.p_max_kw / total
        return {k: kw * scale for k, kw in requests_kw.items()}

    @property
    def charger_kw(self) -> float:
        return self.station.chargers[0].rate_kw if self.station.chargers else 0.0

    @property
    def kind(self) -> str:
        return self.station.chargers[0].kind if self.station.chargers else "AC"

    def is_on_peak(self, t: datetime) -> bool:
        return self.supply.is_on_peak(t)

    def driver_price(self, t: datetime) -> float:
        return self.flat_price if self.flat_price is not None else self.utility.price_at(t)


def supply_schedule(cfg: CommuteConfig, customer_class: str) -> PriceSchedule:
    if cfg.price_csv is not None:
        return EversourcePriceSchedule(cfg.price_csv, customer_class, cfg.peak)
    return FlatTOUPriceSchedule(cfg.fallback_on_peak_price, cfg.fallback_off_peak_price, cfg.peak)


def _utility(supply: PriceSchedule, rate, include_delivery: bool) -> PriceSchedule:
    if include_delivery and isinstance(rate, DeliveryRate):
        return DeliveredPriceSchedule(supply, rate.on_peak_delivery, rate.off_peak_delivery)
    return supply


def build_work_site(cfg: CommuteConfig) -> Site:
    w = cfg.work
    supply = supply_schedule(cfg, w.customer_class)
    rate = get_rate(w.site_rate)
    if w.driver_price_per_kwh is None and cfg.include_delivery and isinstance(rate, EVLRate):
        raise ValueError("Rate EV-L delivery depends on the monthly load factor, so drivers "
                         "can't pay a pass-through price; set work.driver_price_per_kwh")
    return Site(
        name="work", location=Location.WORK,
        station=ChargingStation(w.num_chargers, w.charger_kw, w.charger_type),
        supply=supply, utility=_utility(supply, rate, cfg.include_delivery), rate=rate,
        flat_price=w.driver_price_per_kwh,
        move_window=None if w.move_window_minutes is None else timedelta(minutes=w.move_window_minutes),
        daily_limit=None if w.daily_limit_hours is None else timedelta(hours=w.daily_limit_hours),
        p_max_kw=w.p_max_kw,
    )


class HomeSiteFactory:
    """Makes one private home charger per driver; all homes share one price schedule."""

    def __init__(self, cfg: CommuteConfig) -> None:
        self.cfg = cfg
        self.supply = supply_schedule(cfg, cfg.home.customer_class)
        self.rate = get_rate(cfg.home.site_rate)
        if isinstance(self.rate, EVLRate):
            raise ValueError("Rate EV-L is for charging stations, not homes")
        self.utility = _utility(self.supply, self.rate, cfg.include_delivery)

    def make(self, ev_id: str, charger_type: str) -> Optional[Site]:
        if charger_type == "none":
            return None
        return Site(
            name=f"home:{ev_id}", location=Location.HOME,
            station=ChargingStation(1, self.cfg.home.kw(charger_type), "AC"),
            supply=self.supply, utility=self.utility, rate=self.rate, owner=ev_id,
            fixed_cost_per_day=self.cfg.home.fixed_cost_per_day(charger_type),
        )


def build_public_site(cfg: CommuteConfig, p: PublicStationConfig) -> Site:
    supply = supply_schedule(cfg, p.customer_class)
    rate = get_rate(p.site_rate)
    price = p.driver_price_per_kwh
    if price is None:
        price = load_public_prices()[p.kind]     # dataset/charger_prices_summary.csv
    return Site(
        name=p.name, location=Location.PUBLIC,
        station=ChargingStation(p.num_chargers, p.charger_kw, p.charger_type),
        supply=supply, utility=_utility(supply, rate, cfg.include_delivery), rate=rate,
        flat_price=price, public_kind=p.kind,
        detour=timedelta(minutes=p.detour_minutes), detour_miles=p.detour_miles,
        max_dwell=timedelta(minutes=p.max_dwell_minutes),
        p_max_kw=p.p_max_kw,
        fixed_cost_per_day=p.num_chargers * p.fixed_cost_per_charger_year / 365,
    )
