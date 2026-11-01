"""Scenario / Config module: every tunable assumption lives here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .driver import DriverProfile
from .paths import EVERSOURCE_CSV
from .vehicle import VehicleSpec, default_vehicle

CUSTOMER_CLASSES = ("residential", "small_commercial", "large_commercial", "last_resort")
HUB_LOCATIONS = ("work", "home")
CHARGER_TYPES = ("AC", "DC")

# Eversource CT rate used for a hub's delivery/demand charges when site_rate is None,
# by the hub's customer class. Large C&I / Last Resort customers are really on Rates
# 41/55-58, which aren't in our rate summary; Rate 35 (Intermediate) is the closest.
DEFAULT_SITE_RATE = {"residential": "7", "small_commercial": "27",
                     "large_commercial": "35", "last_resort": "35"}

# Share of residential charging done on Level 1 vs Level 2 (dataset/home_charging.txt;
# NREL ATB 2024 and Joule 2020), among drivers who have a home charger.
HOME_CHARGER_MIX = {"L1": 0.16, "L2": 0.84}
# Home charger power (grid side): Level 1 = 120 V / 12 A, Level 2 = 240 V / 30 A.
HOME_CHARGER_KW = {"L1": 1.4, "L2": 7.2}
HOME_CHARGER_TYPES = ("L2", "L1", "none")


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
    charger_kw: float = 7.2                            # charger rating (grid side)
    charger_type: str = "AC"                           # "AC" (Level 1/2) or "DC" (fast)
    hub_location: str = "work"                         # where the hub is, for EVs with a driver

    # --- drivers (constant schedule for now; see ev_charging/driver.py) ---
    driver: DriverProfile = field(default_factory=DriverProfile)

    # --- "move your car" rule for EVs with a driver ---
    # Once a car reaches its target charge it must leave the charger within this
    # many minutes; it then parks in a regular spot and can't plug back in until
    # the driver leaves and comes back. None turns the rule off.
    move_window_minutes: Optional[int] = 60
    move_rule_at: tuple[str, ...] = ("work",)          # hub locations where the rule applies

    # --- EVs (spec: all identical; default = Honda Prologue AWD, see vehicle.py) ---
    vehicle: VehicleSpec = field(default_factory=default_vehicle)
    battery_kwh: Optional[float] = None                # None -> vehicle.battery_kwh
    kwh_per_mile: Optional[float] = None               # None -> vehicle.kwh_per_mile
    charging_efficiency: float = 1.0                   # 1.0 = no losses

    # --- pricing ---
    price_csv: Optional[Path] = EVERSOURCE_CSV         # None -> flat TOU rates below
    customer_class: str = "residential"                # see CUSTOMER_CLASSES
    peak: PeakWindow = field(default_factory=PeakWindow)
    fallback_on_peak_price: float = 0.35               # used only when price_csv is None
    fallback_off_peak_price: float = 0.15

    # --- what the site pays beyond energy supply (see tariffs.py) ---
    site_rate: Optional[str] = None                    # "7", "27", "30", "35", "EV-L"; None -> by customer_class
    include_delivery: bool = True                      # add delivery $/kWh to the energy price
    prorate_fixed_charges: bool = True                 # scale monthly charges for partial months

    # --- what drivers pay at the hub ---
    # None: drivers pay the site's utility price (supply + delivery), e.g. home charging.
    # A number: flat $/kWh posted price (work fee, public price).
    driver_price_per_kwh: Optional[float] = None

    def __post_init__(self) -> None:
        if self.step_minutes <= 0 or 60 % self.step_minutes:
            raise ValueError("step_minutes must be a positive divisor of 60")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.num_chargers < 1:
            raise ValueError("num_chargers must be >= 1")
        if self.battery_kwh is None:
            object.__setattr__(self, "battery_kwh", self.vehicle.battery_kwh)
        if self.kwh_per_mile is None:
            object.__setattr__(self, "kwh_per_mile", self.vehicle.kwh_per_mile)
        if self.site_rate is None and self.customer_class in DEFAULT_SITE_RATE:
            object.__setattr__(self, "site_rate", DEFAULT_SITE_RATE[self.customer_class])
        if self.battery_kwh <= 0:
            raise ValueError("battery_kwh must be positive")
        if self.kwh_per_mile <= 0:
            raise ValueError("kwh_per_mile must be positive")
        if self.charger_type not in CHARGER_TYPES:
            raise ValueError(f"charger_type must be one of {CHARGER_TYPES}")
        if self.driver_price_per_kwh is not None and self.driver_price_per_kwh < 0:
            raise ValueError("driver_price_per_kwh must be >= 0")
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


# ====================================================================== home + work
# Settings for CommuteSimulation (ev_charging/commute.py): every driver has their
# own home charger (or none) and shares the chargers at work.

@dataclass(frozen=True)
class WorkHubConfig:
    """The shared chargers at work."""
    num_chargers: int = 2
    charger_kw: float = 7.2
    charger_type: str = "AC"
    customer_class: str = "small_commercial"       # energy supply price class
    site_rate: Optional[str] = None                # None -> DEFAULT_SITE_RATE (Rate 27)
    # What drivers pay at work. A flat fee between home and public prices
    # (decided Nov 2026: $0.25/kWh). None = pass-through of the site's price.
    driver_price_per_kwh: Optional[float] = 0.25
    # Most hours a car may stay plugged in at work per day (plugged-in time counts,
    # charging or not). None = no limit.
    daily_limit_hours: Optional[float] = 4.0
    # Move-your-car rule: once a car stops charging, the driver has this many
    # minutes to unplug it. The car then parks and can't plug back in that day.
    move_window_minutes: Optional[int] = 60

    def __post_init__(self) -> None:
        if self.num_chargers < 0:
            raise ValueError("num_chargers must be >= 0")
        if self.charger_type not in CHARGER_TYPES:
            raise ValueError(f"charger_type must be one of {CHARGER_TYPES}")
        if self.customer_class not in CUSTOMER_CLASSES:
            raise ValueError(f"customer_class must be one of {CUSTOMER_CLASSES}")
        if self.site_rate is None:
            object.__setattr__(self, "site_rate", DEFAULT_SITE_RATE[self.customer_class])
        if self.driver_price_per_kwh is not None and self.driver_price_per_kwh < 0:
            raise ValueError("driver_price_per_kwh must be >= 0")
        if self.daily_limit_hours is not None and self.daily_limit_hours < 0:
            raise ValueError("daily_limit_hours must be >= 0 or None")
        if self.move_window_minutes is not None and self.move_window_minutes < 0:
            raise ValueError("move_window_minutes must be >= 0 or None")


@dataclass(frozen=True)
class HomeChargingConfig:
    """Each driver's own home charger, billed on the household's meter."""
    customer_class: str = "residential"
    site_rate: Optional[str] = None                # None -> Rate 7 (residential time-of-day)
    charger_kw: tuple[tuple[str, float], ...] = tuple(HOME_CHARGER_KW.items())
    # Share of EV drivers with no home charger (renters, street parking).
    # 10%: NREL's 2030 National Charging Network study (Wood et al. 2023) assumes 90% of
    # EVs have reliable overnight home charging (sensitivity runs: 85% and 98%).
    # EV-driver surveys agree: 5.8% without (Plug In America 2025, n~4,500) to 14%
    # (ChargeLab 2024, n=500). Mass-market adoption would push this up: only 33% of
    # all US light-duty vehicles park where home charging exists today (NREL, Ge et al. 2021).
    no_home_share: float = 0.10

    def __post_init__(self) -> None:
        if self.customer_class not in CUSTOMER_CLASSES:
            raise ValueError(f"customer_class must be one of {CUSTOMER_CLASSES}")
        if self.site_rate is None:
            object.__setattr__(self, "site_rate", DEFAULT_SITE_RATE[self.customer_class])
        if not 0 <= self.no_home_share <= 1:
            raise ValueError("no_home_share must be in [0, 1]")

    def kw(self, charger_type: str) -> float:
        return dict(self.charger_kw)[charger_type]

    @property
    def shares(self) -> dict[str, float]:
        """Share of drivers per home charger type (L2 / L1 / none)."""
        has = 1 - self.no_home_share
        return {"L2": HOME_CHARGER_MIX["L2"] * has, "L1": HOME_CHARGER_MIX["L1"] * has,
                "none": self.no_home_share}


# Typical public charging prices, $/kWh, are in dataset/charger_prices_summary.csv.
PUBLIC_KINDS = ("L2", "DCFC")


@dataclass(frozen=True)
class PublicStationConfig:
    """A public charging station drivers can detour to from home.

    Drivers pay the posted price (None -> the dataset's typical price for its kind:
    L2 $0.39, DC fast $0.485). The station pays its own utility bill: Rate 27 for a
    Level 2 lot, Rate EV-L (the EV charging station rate) for DC fast.
    Detour times/distances are placeholders until we place stations on a map (A7).
    """
    name: str = "public-l2"
    kind: str = "L2"                           # "L2" or "DCFC"
    num_chargers: int = 2
    charger_kw: float = 7.2
    detour_minutes: int = 5                    # one way, from home
    detour_miles: float = 1.0                  # one way, from home
    # Longest stay. Public L2: 4 h (84% of Palo Alto public L2 sessions end within 4 h;
    # median 2.3 h). DC fast: 45 min.
    max_dwell_minutes: int = 240
    driver_price_per_kwh: Optional[float] = None
    customer_class: Optional[str] = None       # None -> small_commercial (L2) / large_commercial (DCFC)
    site_rate: Optional[str] = None            # None -> "27" (L2) / "EV-L" (DCFC)

    def __post_init__(self) -> None:
        if self.kind not in PUBLIC_KINDS:
            raise ValueError(f"kind must be one of {PUBLIC_KINDS}")
        if self.num_chargers < 1:
            raise ValueError("num_chargers must be >= 1")
        if self.detour_minutes <= 0 or self.detour_miles < 0:
            raise ValueError("detour_minutes must be > 0 and detour_miles >= 0")
        if self.max_dwell_minutes <= 0:
            raise ValueError("max_dwell_minutes must be > 0")
        if self.customer_class is None:
            object.__setattr__(self, "customer_class",
                               "small_commercial" if self.kind == "L2" else "large_commercial")
        if self.customer_class not in CUSTOMER_CLASSES:
            raise ValueError(f"customer_class must be one of {CUSTOMER_CLASSES}")
        if self.site_rate is None:
            object.__setattr__(self, "site_rate", "27" if self.kind == "L2" else "EV-L")

    @property
    def charger_type(self) -> str:
        return "AC" if self.kind == "L2" else "DC"


def default_public_stations() -> tuple[PublicStationConfig, ...]:
    return (
        PublicStationConfig(),
        PublicStationConfig(name="public-dcfc", kind="DCFC", num_chargers=2, charger_kw=150.0,
                            detour_minutes=10, detour_miles=3.0, max_dwell_minutes=45),
    )


@dataclass(frozen=True)
class CommuteConfig:
    # --- time ---
    start: datetime = datetime(2025, 7, 7, 0, 0)      # a Monday
    end: datetime = datetime(2025, 7, 14, 0, 0)
    step_minutes: int = 15

    # --- sites ---
    work: WorkHubConfig = field(default_factory=WorkHubConfig)
    home: HomeChargingConfig = field(default_factory=HomeChargingConfig)
    public: tuple[PublicStationConfig, ...] = field(default_factory=default_public_stations)
    # Drivers only head out to a public station between these hours (start, end).
    public_visit_hours: tuple[int, int] = (6, 22)

    # --- vehicles (all identical: Honda Prologue) ---
    vehicle: VehicleSpec = field(default_factory=default_vehicle)
    charging_efficiency: float = 1.0

    # --- charge goal (A8): always keep enough for the driving ahead plus this
    # buffer, i.e. the battery should never drop below soc_buffer ---
    soc_buffer: float = 0.20

    # --- pricing ---
    price_csv: Optional[Path] = EVERSOURCE_CSV
    peak: PeakWindow = field(default_factory=PeakWindow)
    include_delivery: bool = True
    prorate_fixed_charges: bool = True
    fallback_on_peak_price: float = 0.35              # used only when price_csv is None
    fallback_off_peak_price: float = 0.15

    def __post_init__(self) -> None:
        if self.step_minutes <= 0 or 60 % self.step_minutes:
            raise ValueError("step_minutes must be a positive divisor of 60")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if not 0 <= self.soc_buffer < 1:
            raise ValueError("soc_buffer must be in [0, 1)")
        if not 0 < self.charging_efficiency <= 1:
            raise ValueError("charging_efficiency must be in (0, 1]")
        a, b = self.public_visit_hours
        if not 0 <= a < b <= 24:
            raise ValueError("public_visit_hours must be (start, end) with 0 <= start < end <= 24")
        names = [p.name for p in self.public]
        if len(set(names)) != len(names) or "work" in names:
            raise ValueError("public station names must be unique and not 'work'")


def assign_home_chargers(n: int, shares: dict[str, float]) -> list[str]:
    """Split n drivers into home charger types matching `shares` as closely as
    possible (largest remainder), spread out so the types alternate."""
    raw = {k: n * v for k, v in shares.items()}
    counts = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[: n - sum(counts.values())]:
        counts[k] += 1
    out: list[str] = []
    while len(out) < n:   # round-robin: L2, L1, none, L2, ...
        for k in HOME_CHARGER_TYPES:
            if counts.get(k, 0) > 0:
                out.append(k)
                counts[k] -= 1
    return out
