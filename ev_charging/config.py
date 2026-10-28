"""Scenario / Config module: every tunable assumption lives here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .driver import DriverProfile
from .paths import EVERSOURCE_CSV

CUSTOMER_CLASSES = ("residential", "small_commercial", "large_commercial", "last_resort")
HUB_LOCATIONS = ("work", "home")


@dataclass(frozen=True)
class PeakWindow:
    """Which hours are billed at the on-peak rate.

    Default: Eversource Connecticut time-of-use peak, weekdays 12:00-20:00
    (Rate 7 residential and Rate 27 small business; the CSV is Eversource CT
    Variable Peak Pricing). Weekends are off-peak all day. Whether holidays
    count as off-peak is unconfirmed; list them in `holidays` once known.
    """
    start_hour: int = 12         # inclusive
    end_hour: int = 20           # exclusive
    weekdays_only: bool = True
    holidays: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        if not (0 <= self.start_hour < self.end_hour <= 24):
            raise ValueError("need 0 <= start_hour < end_hour <= 24")

    def is_on_peak(self, t: datetime) -> bool:
        if self.weekdays_only and t.weekday() >= 5:
            return False
        if t.date() in self.holidays:
            return False
        return self.start_hour <= t.hour < self.end_hour


@dataclass(frozen=True)
class ScenarioConfig:
    # --- time ---
    start: datetime = datetime(2025, 7, 1, 0, 0)
    end: datetime = datetime(2025, 7, 3, 0, 0)        # hard stop for a run
    step_minutes: int = 15

    # --- hub (spec: 1 hub with M chargers) ---
    num_chargers: int = 1                              # M
    charger_kw: float = 7.2                            # constant rate
    hub_location: str = "work"                         # where the hub is, for EVs with a driver

    # --- drivers (constant schedule for now; see ev_charging/driver.py) ---
    driver: DriverProfile = field(default_factory=DriverProfile)

    # --- "move your car" rule for EVs with a driver ---
    # Once a car reaches its target charge it must leave the charger within this
    # many minutes; it then parks in a regular spot and can't plug back in until
    # the driver leaves and comes back. None turns the rule off.
    move_window_minutes: Optional[int] = 60
    move_rule_at: tuple[str, ...] = ("work",)          # hub locations where the rule applies

    # --- EVs (spec: all identical) ---
    battery_kwh: float = 60.0
    kwh_per_mile: float = 0.30                         # driving efficiency
    charging_efficiency: float = 1.0                   # 1.0 = no losses

    # --- pricing ---
    price_csv: Optional[Path] = EVERSOURCE_CSV         # None -> flat TOU rates below
    customer_class: str = "residential"                # see CUSTOMER_CLASSES
    peak: PeakWindow = field(default_factory=PeakWindow)
    fallback_on_peak_price: float = 0.35               # used only when price_csv is None
    fallback_off_peak_price: float = 0.15

    def __post_init__(self) -> None:
        if self.step_minutes <= 0 or 60 % self.step_minutes:
            raise ValueError("step_minutes must be a positive divisor of 60")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.num_chargers < 1:
            raise ValueError("num_chargers must be >= 1")
        if self.kwh_per_mile <= 0:
            raise ValueError("kwh_per_mile must be positive")
        if not 0 < self.charging_efficiency <= 1:
            raise ValueError("charging_efficiency must be in (0, 1]")
        if self.customer_class not in CUSTOMER_CLASSES:
            raise ValueError(f"customer_class must be one of {CUSTOMER_CLASSES}")
        if self.hub_location not in HUB_LOCATIONS:
            raise ValueError(f"hub_location must be one of {HUB_LOCATIONS}")
        if self.move_window_minutes is not None and self.move_window_minutes < 0:
            raise ValueError("move_window_minutes must be >= 0 or None")
        if not set(self.move_rule_at) <= set(HUB_LOCATIONS):
            raise ValueError(f"move_rule_at entries must be in {HUB_LOCATIONS}")
