"""Demo: several EVs sharing a hub with fewer chargers than cars, so you can
see cars queue, plug in, charge, and leave.

    python run_fleet_demo.py                  # 6 EVs, 2 chargers, saves charts
    python run_fleet_demo.py --evs 10 --chargers 3 --show
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta

from ev_charging.config import ScenarioConfig
from ev_charging.ev import EV
from ev_charging.simulation import Simulation
from run_single_ev import add_viz_args, print_results, render


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evs", type=int, default=6)
    ap.add_argument("--chargers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    add_viz_args(ap, default_name="fleet")
    args = ap.parse_args()

    start = datetime(2025, 7, 1, 16, 0)   # evening arrivals, through on-peak into off-peak
    cfg = ScenarioConfig(start=start, end=start + timedelta(days=2), num_chargers=args.chargers)
    sim = Simulation(cfg)
    rng = random.Random(args.seed)
    arrivals = sorted(start + timedelta(minutes=15 * rng.randint(0, 12)) for _ in range(args.evs))
    for i, t in enumerate(arrivals, 1):   # added in arrival order = first come, first served
        sim.add_ev(EV(f"ev-{i}", cfg.battery_kwh, soc=round(rng.uniform(0.2, 0.6), 2),
                      required_soc=0.8, arrival_time=t))
    result = sim.run()
    print_results(cfg, result)
    render(result, args)


if __name__ == "__main__":
    main()
