"""Build dataset/derived/nhts_commuters.csv from the 2022 NHTS trip file.

One row per weekday commuter who drove a car straight from home to work:
  work_start   = arrival time of that home->work trip
  work_end     = start time of their first trip leaving work afterwards
  commute_*    = distance and duration of the home->work trip (one way)
  weight       = NHTS trip weight (WTTRDFIN), for weighted sampling/medians

Filters: Mon-Fri travel day, 0.5-100 mi, 1-180 min, an average speed of
3-75 mph (drops reporting errors), 2-14 h at work, and both commutes inside
the same calendar day. Run from the repo root:

    python scripts/build_nhts_commuters.py
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ev_charging.paths import NHTS_COMMUTERS_CSV, NHTS_DIR   # noqa: E402

# NHTS 2022 codes used here
HOME, WORK_AWAY = 1, 3         # WHYFROM / WHYTO: 1 = home, 3 = work at a non-home location
CAR_DRIVER = 1                 # TRIPMODE: 1 = private vehicle, as the driver
WEEKDAYS = {2, 3, 4, 5, 6}     # TRAVDAY: 1 = Sunday ... 7 = Saturday


def minutes(hhmm: str) -> int:
    v = int(hhmm)
    return (v // 100) * 60 + v % 100


def build(trip_csv: Path, out_csv: Path) -> int:
    people = defaultdict(list)
    with open(trip_csv, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if int(r["TRAVDAY"]) not in WEEKDAYS:
                continue
            people[(r["HOUSEID"], r["PERSONID"])].append(r)

    rows = []
    for (house, person), trips in people.items():
        trips.sort(key=lambda r: minutes(r["STRTTIME"]))
        to_work = next((r for r in trips if int(r["WHYFROM"]) == HOME and int(r["WHYTO"]) == WORK_AWAY
                        and int(r["TRIPMODE"]) == CAR_DRIVER), None)
        if to_work is None:
            continue
        leave_home, arrive = minutes(to_work["STRTTIME"]), minutes(to_work["ENDTIME"])
        back = next((r for r in trips if int(r["WHYFROM"]) == WORK_AWAY
                     and minutes(r["STRTTIME"]) >= arrive), None)
        if back is None:
            continue
        leave_work = minutes(back["STRTTIME"])
        miles, mins = float(to_work["TRPMILES"]), round(float(to_work["TRVLCMIN"]))
        if not (0.5 <= miles <= 100 and 1 <= mins <= 180 and 120 <= leave_work - arrive <= 14 * 60):
            continue
        if arrive - mins < 0 or leave_work + mins >= 24 * 60 or arrive <= leave_home:
            continue
        if not 3 <= miles / (mins / 60) <= 75:
            continue
        rows.append({
            "houseid": house, "personid": person,
            "census_division": to_work["CENSUS_D"],
            "weight": to_work["WTTRDFIN"],
            "work_start": f"{arrive // 60:02d}:{arrive % 60:02d}",
            "work_end": f"{leave_work // 60:02d}:{leave_work % 60:02d}",
            "commute_miles": f"{miles:.2f}",
            "commute_minutes": mins,
        })

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    n = build(NHTS_DIR / "trip.csv", NHTS_COMMUTERS_CSV)
    print(f"wrote {n} commuters to {NHTS_COMMUTERS_CSV}")
