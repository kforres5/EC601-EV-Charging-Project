"""Commuting drivers: each EV follows the same constant driver schedule
(ev_charging/driver.py, defaults in ev_charging/config.py) and can only charge
while it is at the hub's location.

    python run_commute.py                          # 4 drivers, 2 work chargers, Mon-Wed
    python run_commute.py --hub home --days 7      # shared home garage, one week
    python run_commute.py --evs 6 --chargers 3 --plot --animate --every 2
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from ev_charging.config import ScenarioConfig
from ev_charging.ev import EV
from ev_charging.simulation import Simulation
from run_single_ev import add_viz_args, print_results, render


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evs", type=int, default=4)
    ap.add_argument("--chargers", type=int, default=2)
    ap.add_argument("--hub", choices=["work", "home"], default="work",
                    help="where the charging hub is")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--start", default="2025-07-07", help="start date (YYYY-MM-DD), 00:00")
    ap.add_argument("--soc", type=float, default=0.5, help="starting state of charge (0-1)")
    ap.add_argument("--target", type=float, default=0.8, help="charge up to this SOC (0-1)")
    add_viz_args(ap, default_name="commute")
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start)
    cfg = ScenarioConfig(
        start=start, end=start + timedelta(days=args.days),
        num_chargers=args.chargers, hub_location=args.hub,
        # energy price for the hub's customer class (driver-facing prices come later)
        customer_class="small_commercial" if args.hub == "work" else "residential",
    )
    d = cfg.driver
    print(f"Driver schedule: work {d.work_start:%H:%M}-{d.work_end:%H:%M} on weekdays "
          f"{list(d.work_days)}, commute {d.commute_miles:g} mi / {d.commute_minutes} min each way "
          f"({d.trip_kwh:.2f} kWh per trip)")

    sim = Simulation(cfg)
    for i in range(1, args.evs + 1):
        sim.add_ev(EV(f"ev-{i}", cfg.battery_kwh, soc=args.soc, required_soc=args.target,
                      driver=cfg.driver))
    result = sim.run()
    print_results(cfg, result)
    render(result, args)


if __name__ == "__main__":
    main()
