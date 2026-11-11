"""Vehicle specs: battery size, efficiency, and how fast the car can charge.

Default vehicle is the Honda Prologue AWD (dataset/honda_prologue_specs.csv and
dataset/honda_prologue_dc_curve.csv). The DC curve gives the most power the car
accepts at each state of charge on a DC fast charger; on AC (Level 1/2) the car
is limited by its onboard charger (max_ac_kw).
"""
from __future__ import annotations

import bisect
import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import VEHICLE_DC_CURVE_CSV, VEHICLE_SPECS_CSV


@dataclass(frozen=True)
class VehicleSpec:
    name: str
    battery_kwh: float                              # usable capacity
    kwh_per_mile: float
    max_ac_kw: float                                # onboard charger limit (Level 1/2)
    max_dc_kw: float                                # peak DC fast-charging power
    dc_curve: tuple[tuple[float, float], ...] = ()  # (SOC 0..1, max kW), sorted by SOC

    def __post_init__(self) -> None:
        if min(self.battery_kwh, self.kwh_per_mile, self.max_ac_kw, self.max_dc_kw) <= 0:
            raise ValueError("vehicle battery, efficiency and charge rates must be positive")
        socs = [s for s, _ in self.dc_curve]
        if socs != sorted(socs):
            raise ValueError("dc_curve must be sorted by SOC")

    def dc_power_at(self, soc: float) -> float:
        """Most DC power (kW) the car accepts at this SOC (linear between curve points)."""
        if not self.dc_curve:
            return self.max_dc_kw
        socs = [s for s, _ in self.dc_curve]
        soc = min(max(soc, socs[0]), socs[-1])
        i = bisect.bisect_left(socs, soc)
        if socs[i] == soc:
            return self.dc_curve[i][1]
        (s0, p0), (s1, p1) = self.dc_curve[i - 1], self.dc_curve[i]
        return p0 + (p1 - p0) * (soc - s0) / (s1 - s0)


def load_vehicle_spec(specs_csv: Path | str = VEHICLE_SPECS_CSV,
                      curve_csv: Path | str | None = VEHICLE_DC_CURVE_CSV) -> VehicleSpec:
    """Read a specs CSV (parameter,value,unit,...) and an optional DC curve CSV
    (soc_percent,power_kw,...)."""
    params: dict[str, str] = {}
    with open(specs_csv, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            params[row["parameter"].strip()] = (row.get("value") or "").strip()
    curve: list[tuple[float, float]] = []
    if curve_csv is not None:
        with open(curve_csv, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                curve.append((float(row["soc_percent"]) / 100, float(row["power_kw"])))
        curve.sort()
    try:
        return VehicleSpec(
            name=params.get("vehicle", "vehicle"),
            battery_kwh=float(params["battery_capacity_effective"]),
            kwh_per_mile=float(params["energy_consumption_combined"]),
            max_ac_kw=float(params["max_AC_charge_rate"]),
            max_dc_kw=float(params["max_DC_charge_rate"]),
            dc_curve=tuple(curve),
        )
    except KeyError as e:
        raise ValueError(f"{specs_csv} is missing parameter {e}") from None


@lru_cache(maxsize=1)
def default_vehicle() -> VehicleSpec:
    return load_vehicle_spec()
