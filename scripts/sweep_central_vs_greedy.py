"""When does the centralized controller beat greedy on price? A parameter sweep.

Runs greedy and central on the same NHTS-sampled commuters for every combination
of season x work fee x work chargers x share without a home charger, and writes
one row per (scenario, strategy) to sweep.csv in a new run folder
(outputs/runX_sweep-central-vs-greedy_.../), plus a side-by-side table in
summary.txt. Results and what they mean: team_notes/Centralized_Controller_Plan.md.

    python scripts/sweep_central_vs_greedy.py                 # the Nov 16 sweep (~10 min)
    python scripts/sweep_central_vs_greedy.py --work-prices 0,0.10 --chargers 1 --evs 12
"""
from __future__ import annotations

import argparse
import csv
import itertools
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ev_charging.central_controller import CentralController  # noqa: E402
from ev_charging.commute import CommuteSimulation  # noqa: E402
from ev_charging.config import (CommuteConfig, HomeChargingConfig, WorkHubConfig,  # noqa: E402
                                assign_home_chargers)
from ev_charging.ev import EV  # noqa: E402
from ev_charging.nhts import sample_driver_profiles  # noqa: E402
from ev_charging.paths import REPO_ROOT  # noqa: E402
from ev_charging.run_output import run_folder  # noqa: E402
from ev_charging.strategies import Greedy  # noqa: E402
from ev_charging.strategies.centralized import CentralizedStrategy  # noqa: E402

FIELDS = ["start", "work_price", "chargers", "no_home", "strategy", "cost", "kwh", "per_kwh",
          "home_kwh", "work_kwh", "public_kwh", "on_peak_kwh", "wait_h", "missed", "seconds"]


def floats(text: str) -> list[float]:
    return [float(x) for x in text.split(",") if x.strip()]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starts", default="2025-07-07,2026-01-05", help="comma list of start dates (Mondays)")
    ap.add_argument("--work-prices", default="0.10,0.25", help="comma list of work fees, $/kWh")
    ap.add_argument("--chargers", default="1,2,3", help="comma list of work charger counts")
    ap.add_argument("--no-home-shares", default="0.1,0.5", help="comma list of shares without a home charger")
    ap.add_argument("--evs", type=int, default=10)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--soc", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=3, help="NHTS driver sample")
    ap.add_argument("--solver-time-limit", type=float, default=30)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "outputs")
    return ap


def run_pair(start, work_price, chargers, no_home, a):
    s = datetime.fromisoformat(start)
    cfg = CommuteConfig(start=s, end=s + timedelta(days=a.days),
                        work=WorkHubConfig(num_chargers=chargers, driver_price_per_kwh=work_price),
                        home=HomeChargingConfig(no_home_share=no_home))
    profiles = sample_driver_profiles(a.evs, seed=a.seed)
    types = assign_home_chargers(a.evs, cfg.home.shares)
    rows = {}
    for name in ("greedy", "central"):
        sim = CommuteSimulation(cfg, record=False)
        strat = Greedy() if name == "greedy" else CentralizedStrategy(
            CentralController(sim.fleet_view(), time_limit=a.solver_time_limit))
        for i, (p, t) in enumerate(zip(profiles, types), 1):
            sim.add_driver(EV.from_vehicle(f"ev-{i}", cfg.vehicle, soc=a.soc, required_soc=0.8,
                                           driver=p, strategy=strat), t)
        t0 = time.time()
        r = sim.run()
        e = r.ev_results
        kwh = sum(x.energy_kwh for x in e)
        rows[name] = dict(
            start=start, work_price=work_price, chargers=chargers, no_home=no_home, strategy=name,
            cost=round(r.total_cost, 2), kwh=round(kwh, 1),
            per_kwh=round(r.total_cost / kwh, 4) if kwh else 0.0,
            home_kwh=round(sum(x.home_kwh for x in e), 1), work_kwh=round(sum(x.work_kwh for x in e), 1),
            public_kwh=round(sum(x.public_kwh for x in e), 1),
            on_peak_kwh=round(sum(x.on_peak_kwh for x in e), 1),
            wait_h=round(sum(x.work_waiting_hours + x.public_waiting_hours for x in e), 1),
            missed=sum(x.missed_goal for x in e), seconds=round(time.time() - t0, 1))
    return rows


def main() -> None:
    ap = build_parser()
    a = ap.parse_args()
    grid = list(itertools.product(a.starts.split(","), floats(a.work_prices),
                                  [int(c) for c in floats(a.chargers)], floats(a.no_home_shares)))
    with run_folder(a, ap, "sweep-central-vs-greedy", always=("evs", "days", "seed")) as folder:
        print(f"{len(grid)} scenarios x 2 strategies, {a.evs} drivers, {a.days} days\n")
        print(f"{'start':10} {'work $':>6} {'ch':>2} {'no home':>7} | {'greedy':>7} {'central':>7} "
              f"{'diff':>6} | {'waiting h g/c':>13} | {'public kWh g/c':>14} | {'missed g/c':>10}")
        with open(folder / "sweep.csv", "w", newline="") as f:
            out = csv.DictWriter(f, fieldnames=FIELDS)
            out.writeheader()
            for scenario in grid:
                rows = run_pair(*scenario, a)
                out.writerows(rows.values())
                f.flush()
                g, c = rows["greedy"], rows["central"]
                diff = (c["per_kwh"] / g["per_kwh"] - 1) if g["per_kwh"] else 0.0
                print(f"{scenario[0]:10} {scenario[1]:6.2f} {scenario[2]:2d} {scenario[3]:7.0%} | "
                      f"{g['per_kwh']:7.3f} {c['per_kwh']:7.3f} {diff:+6.1%} | "
                      f"{g['wait_h']:6.1f}/{c['wait_h']:<6.1f} | {g['public_kwh']:6.1f}/{c['public_kwh']:<7.1f} | "
                      f"{g['missed']:>4}/{c['missed']:<5}")
        print(f"\nSaved {folder / 'sweep.csv'}")


if __name__ == "__main__":
    main()
