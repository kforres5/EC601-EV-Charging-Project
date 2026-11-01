"""Eversource Connecticut delivery tariffs and the monthly site bill.

The price CSV (pricing.py) is only the energy *supply* part of a bill. This
module adds the rest, from:
  - dataset/eversource_summary_of_electric_rates.csv: Rates 7, 27, 30, 35
    (customer charge, demand charge, on/off-peak delivery per kWh)
  - dataset/eversource_rate_ev-l.csv: Rate EV-L, the EV charging station rate,
    whose demand and delivery charges depend on the site's monthly load factor

Assumptions (change here if the tariff text says otherwise):
  - Demand is the site's highest 15-minute average load in the month.
  - Demand_Threshold_kW: demand up to the threshold is not billed.
  - EV-L demand charges are per kVA; we take kVA = kW (power factor 1).
  - EV-L load factor = month's kWh / (peak kW x hours the run covered that month).
  - Runs that cover part of a month get the customer and demand charges scaled
    by the share of the month covered (prorate=True), so short runs stay comparable.
"""
from __future__ import annotations

import calendar
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .paths import PUBLIC_PRICES_CSV, RATE_EVL_CSV, RATE_SUMMARY_CSV

EVL = "EV-L"


@dataclass(frozen=True)
class DeliveryRate:
    """One Eversource rate from the summary table (Rate 7, 27, 30, 35)."""
    rate: str
    name: str
    customer_charge: float          # $/month
    demand_charge: float            # $/kW-month
    demand_threshold_kw: float
    on_peak_delivery: float         # $/kWh
    off_peak_delivery: float        # $/kWh

    def delivery(self, on_peak: bool) -> float:
        return self.on_peak_delivery if on_peak else self.off_peak_delivery


@dataclass(frozen=True)
class EVLTier:
    tier: int
    lf_low: float                   # load factor range [lf_low, lf_high), as fractions
    lf_high: float
    customer_charge: float          # $/month
    demand_charge: float            # $/kVA-month (distribution + production/transmission)
    on_peak_delivery: float
    off_peak_delivery: float


@dataclass(frozen=True)
class EVLRate:
    rate: str
    tiers: tuple[EVLTier, ...]

    def tier_for(self, load_factor: float) -> EVLTier:
        for t in self.tiers:
            if t.lf_low <= load_factor < t.lf_high:
                return t
        return self.tiers[-1] if load_factor >= self.tiers[-1].lf_low else self.tiers[0]


def _num(x: str) -> float:
    return float(x.replace("$", "").replace(",", "").strip())


def load_rate_summary(path: Path | str = RATE_SUMMARY_CSV) -> dict[str, DeliveryRate]:
    rates = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            r = row["Rate"].strip()
            rates[r] = DeliveryRate(
                rate=r, name=row["Rate_Name"].strip(),
                customer_charge=_num(row["Customer_Charge_$/month"]),
                demand_charge=_num(row["Demand_Charge_$/kW"]),
                demand_threshold_kw=_num(row["Demand_Threshold_kW"]),
                on_peak_delivery=_num(row["OnPeak_Delivery_$/kWh"]),
                off_peak_delivery=_num(row["OffPeak_Delivery_$/kWh"]),
            )
    return rates


def _lf_range(text: str) -> tuple[float, float]:
    """'0% to <5%' -> (0.00, 0.05); '>=35%' -> (0.35, inf)."""
    nums = [float(n) / 100 for n in re.findall(r"[\d.]+", text)]
    if text.strip().startswith(">="):
        return nums[0], float("inf")
    return nums[0], nums[1]


def load_evl_rate(path: Path | str = RATE_EVL_CSV) -> EVLRate:
    tiers = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lo, hi = _lf_range(row["Load_Factor_Range"])
            tiers.append(EVLTier(
                tier=int(row["Tier"]), lf_low=lo, lf_high=hi,
                customer_charge=_num(row["Customer_Charge_$/month"]),
                demand_charge=_num(row["Dist_Demand_$/kVA"]) + _num(row["ProdTrans_Demand_$/kVA"]),
                on_peak_delivery=_num(row["OnPeak_Delivery_$/kWh"]),
                off_peak_delivery=_num(row["OffPeak_Delivery_$/kWh"]),
            ))
    tiers.sort(key=lambda t: t.lf_low)
    return EVLRate(rate=EVL, tiers=tuple(tiers))


def load_public_prices(path: Path | str = PUBLIC_PRICES_CSV) -> dict[str, float]:
    """Typical public charging prices, $/kWh: {'L2': ..., 'DCFC': ...}."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row["level"].strip(): _num(row["price_usd_kwh"]) for row in csv.DictReader(f)}


def get_rate(rate: str) -> DeliveryRate | EVLRate:
    if rate == EVL:
        return load_evl_rate()
    rates = load_rate_summary()
    if rate not in rates:
        raise ValueError(f"unknown rate {rate!r}; available: {sorted(rates) + [EVL]}")
    return rates[rate]


# --------------------------------------------------------------- site bill
@dataclass
class MonthlyBill:
    month: str                      # "YYYY-MM"
    rate: str
    hours_covered: float
    hours_in_month: float
    energy_kwh: float
    on_peak_kwh: float
    peak_kw: float                  # highest 15-minute demand
    load_factor: float
    tier: Optional[int]             # EV-L tier, else None
    supply_cost: float
    delivery_cost: float
    demand_cost: float
    customer_cost: float

    @property
    def total(self) -> float:
        return self.supply_cost + self.delivery_cost + self.demand_cost + self.customer_cost


class SiteMeter:
    """Accumulates a site's load every step; turns it into monthly bills."""

    DEMAND_MINUTES = 15

    def __init__(self) -> None:
        self._month = defaultdict(lambda: {"kwh": 0.0, "on_kwh": 0.0, "supply": 0.0,
                                           "hours": 0.0})
        self._blocks: dict[datetime, float] = defaultdict(float)   # 15-min block -> kWh
        self._block_hours: dict[datetime, float] = defaultdict(float)
        self._steps: list[tuple[datetime, float, bool]] = []       # (time, kWh, on_peak)

    def record(self, t: datetime, step: timedelta, kwh: float, on_peak: bool,
               supply_price: float) -> None:
        key = f"{t.year:04d}-{t.month:02d}"
        m = self._month[key]
        m["kwh"] += kwh
        m["supply"] += kwh * supply_price
        m["hours"] += step.total_seconds() / 3600
        if on_peak:
            m["on_kwh"] += kwh
        block = t.replace(minute=t.minute - t.minute % self.DEMAND_MINUTES, second=0, microsecond=0)
        self._blocks[block] += kwh
        self._block_hours[block] += step.total_seconds() / 3600
        self._steps.append((t, kwh, on_peak))

    def _peak_kw(self, key: str) -> float:
        best = 0.0
        for block, kwh in self._blocks.items():
            if f"{block.year:04d}-{block.month:02d}" == key:
                hours = max(self._block_hours[block], self.DEMAND_MINUTES / 60)
                best = max(best, kwh / hours)
        return best

    def bills(self, rate: DeliveryRate | EVLRate, prorate: bool = True) -> list[MonthlyBill]:
        out = []
        for key in sorted(self._month):
            m = self._month[key]
            year, month = map(int, key.split("-"))
            month_hours = calendar.monthrange(year, month)[1] * 24.0
            share = min(1.0, m["hours"] / month_hours) if prorate else 1.0
            peak = self._peak_kw(key)
            lf = m["kwh"] / (peak * m["hours"]) if peak > 0 and m["hours"] > 0 else 0.0
            off_kwh = m["kwh"] - m["on_kwh"]
            if isinstance(rate, EVLRate):
                t = rate.tier_for(lf)
                tier, cust, demand = t.tier, t.customer_charge, t.demand_charge * peak
                delivery = t.on_peak_delivery * m["on_kwh"] + t.off_peak_delivery * off_kwh
            else:
                tier, cust = None, rate.customer_charge
                demand = rate.demand_charge * max(0.0, peak - rate.demand_threshold_kw)
                delivery = rate.on_peak_delivery * m["on_kwh"] + rate.off_peak_delivery * off_kwh
            out.append(MonthlyBill(
                month=key, rate=rate.rate, hours_covered=m["hours"], hours_in_month=month_hours,
                energy_kwh=m["kwh"], on_peak_kwh=m["on_kwh"], peak_kw=peak, load_factor=lf,
                tier=tier, supply_cost=m["supply"], delivery_cost=delivery,
                demand_cost=demand * share, customer_cost=cust * share,
            ))
        return out
