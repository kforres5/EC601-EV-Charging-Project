"""Price sources. Anything with price_at(t) and is_on_peak(t) plugs into Simulation."""
from __future__ import annotations

import bisect
import csv
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from .config import PeakWindow, ScenarioConfig

# customer_class key -> column label prefix in the Eversource CSV
EVERSOURCE_COLUMNS = {
    "last_resort": "Last Resort Service",
    "residential": "Residential",
    "small_commercial": "Small Commercial & Industrial",
    "large_commercial": "Large Commercial & Industrial",
}


class PriceSchedule(Protocol):
    def price_at(self, t: datetime) -> float: ...
    def is_on_peak(self, t: datetime) -> bool: ...


class FlatTOUPriceSchedule:
    """Two constant rates split by a PeakWindow. Handy for tests / no-data runs."""

    def __init__(self, on_peak_price: float, off_peak_price: float, peak: PeakWindow) -> None:
        self.on_peak_price = on_peak_price
        self.off_peak_price = off_peak_price
        self.peak = peak

    def is_on_peak(self, t: datetime) -> bool:
        return self.peak.is_on_peak(t)

    def price_at(self, t: datetime) -> float:
        return self.on_peak_price if self.is_on_peak(t) else self.off_peak_price


class EversourcePriceSchedule:
    """Daily on/off-peak rates from dataset/Eversource_Peak_Pricing_History.csv.

    The CSV has one row per weekday (MM/DD/YYYY) with on- and off-peak $/kWh for
    four customer classes. Dates without a row (weekends, a few missing
    weekdays) borrow the closest row in the same month, so the monthly
    off-peak rate stays correct; with no row that month, the closest earlier row.
    """

    def __init__(self, path: Path | str, customer_class: str, peak: PeakWindow) -> None:
        if customer_class not in EVERSOURCE_COLUMNS:
            raise ValueError(f"unknown customer_class {customer_class!r}")
        label = EVERSOURCE_COLUMNS[customer_class]
        on_col, off_col = f"{label} On-Peak [$/kWh]", f"{label} Off-Peak [$/kWh]"
        self.peak = peak
        self._rates: dict[date, tuple[float, float]] = {}

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = {on_col, off_col} - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSV missing columns: {sorted(missing)}")
            for row in reader:
                raw = (row.get("Date") or "").strip()
                if not raw:
                    continue
                d = datetime.strptime(raw, "%m/%d/%Y").date()
                self._rates[d] = (float(row[on_col]), float(row[off_col]))

        if not self._rates:
            raise ValueError(f"no price rows found in {path}")
        self._dates = sorted(self._rates)
        self.first_date, self.last_date = self._dates[0], self._dates[-1]

    def rates_for(self, d: date) -> tuple[float, float]:
        """(on_peak, off_peak) $/kWh that apply on date d."""
        if d in self._rates:
            return self._rates[d]
        if not (self.first_date <= d <= self.last_date):
            raise KeyError(f"{d} is outside the price data ({self.first_date} to {self.last_date})")
        i = bisect.bisect_left(self._dates, d)
        prev_d, next_d = self._dates[i - 1], self._dates[i]
        same_month = [x for x in (prev_d, next_d) if (x.year, x.month) == (d.year, d.month)]
        chosen = min(same_month, key=lambda x: abs((x - d).days)) if same_month else prev_d
        return self._rates[chosen]

    def is_on_peak(self, t: datetime) -> bool:
        return self.peak.is_on_peak(t)

    def price_at(self, t: datetime) -> float:
        on, off = self.rates_for(t.date())
        return on if self.is_on_peak(t) else off


def build_price_schedule(cfg: ScenarioConfig) -> PriceSchedule:
    if cfg.price_csv is not None:
        return EversourcePriceSchedule(cfg.price_csv, cfg.customer_class, cfg.peak)
    return FlatTOUPriceSchedule(cfg.fallback_on_peak_price, cfg.fallback_off_peak_price, cfg.peak)
