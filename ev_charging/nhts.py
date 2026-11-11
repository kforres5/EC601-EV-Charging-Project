"""Driver schedules from the 2022 NHTS (National Household Travel Survey).

dataset/derived/nhts_commuters.csv (built by scripts/build_nhts_commuters.py)
holds one real weekday car commuter per row. Use it to give each simulated
driver a different, realistic schedule:

    profiles = sample_driver_profiles(10, seed=1)            # all of the US
    profiles = sample_driver_profiles(10, seed=1, region=NEW_ENGLAND)

NHTS has one travel day per person, so work days per week are not in the data;
every sampled driver works Monday-Friday.
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .driver import DriverProfile
from .paths import NHTS_COMMUTERS_CSV

NEW_ENGLAND = 1          # NHTS CENSUS_D code (CT, MA, ME, NH, RI, VT)


@dataclass(frozen=True)
class Commuter:
    profile: DriverProfile
    weight: float
    census_division: int


def _time(hhmm: str) -> time:
    h, m = map(int, hhmm.split(":"))
    return time(h, m)


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[Commuter, ...]:
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out.append(Commuter(
                profile=DriverProfile(
                    work_start=_time(r["work_start"]), work_end=_time(r["work_end"]),
                    commute_miles=float(r["commute_miles"]),
                    commute_minutes=int(r["commute_minutes"]),
                ),
                weight=float(r["weight"]),
                census_division=int(r["census_division"]),
            ))
    if not out:
        raise ValueError(f"no commuters in {path}")
    return tuple(out)


def load_commuters(path: Path | str = NHTS_COMMUTERS_CSV,
                   region: Optional[int] = None) -> list[Commuter]:
    rows = _load(str(path))
    return [c for c in rows if region is None or c.census_division == region]


def sample_driver_profiles(n: int, seed: Optional[int] = None, region: Optional[int] = None,
                           path: Path | str = NHTS_COMMUTERS_CSV) -> list[DriverProfile]:
    """n schedules drawn from real commuters, weighted by the NHTS trip weights."""
    commuters = load_commuters(path, region)
    if not commuters:
        raise ValueError(f"no commuters for region {region}")
    rng = random.Random(seed)
    picks = rng.choices(commuters, weights=[c.weight for c in commuters], k=n)
    return [c.profile for c in picks]


def median_profile(path: Path | str = NHTS_COMMUTERS_CSV,
                   region: Optional[int] = None) -> DriverProfile:
    """Weighted median of each schedule field (what DriverProfile's defaults are set to)."""
    commuters = load_commuters(path, region)

    def wmedian(values):
        pairs = sorted(zip(values, (c.weight for c in commuters)))
        half, acc = sum(w for _, w in pairs) / 2, 0.0
        for v, w in pairs:
            acc += w
            if acc >= half:
                return v
        return pairs[-1][0]

    def mins(t: time) -> int:
        return t.hour * 60 + t.minute

    start = wmedian([mins(c.profile.work_start) for c in commuters])
    end = wmedian([mins(c.profile.work_end) for c in commuters])
    return DriverProfile(
        work_start=time(start // 60, start % 60), work_end=time(end // 60, end % 60),
        commute_miles=wmedian([c.profile.commute_miles for c in commuters]),
        commute_minutes=wmedian([c.profile.commute_minutes for c in commuters]),
    )
