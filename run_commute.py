"""Commuting drivers charging at a hub (work by default). Each EV is a Honda
Prologue; by default every driver follows the NHTS median weekday schedule
(ev_charging/driver.py), or --sample-drivers gives each a real NHTS commuter's.

    python run_commute.py                          # 4 drivers, 2 work chargers, Mon-Wed
    python run_commute.py --sample-drivers --region new-england --seed 3
    python run_commute.py --hub home --days 7      # shared home garage, one week
    python run_commute.py --driver-price public-l2 # drivers pay the public L2 price
    python run_commute.py --charger-type DC --charger-kw 150 --site-rate EV-L --driver-price public-dcfc
    python run_commute.py --evs 6 --chargers 3 --plot --animate --every 2

Each run gets its own folder: outputs/runX_[parameters]/ (see ev_charging/run_output.py).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from ev_charging.config import ScenarioConfig
from ev_charging.ev import EV
from ev_charging.nhts import NEW_ENGLAND, sample_driver_profiles
from ev_charging.simulation import Simulation
from ev_charging.tariffs import load_public_prices
from ev_charging.run_output import run_folder
from run_single_ev import add_viz_args, print_results, render


def parse_driver_price(text: str):
    """'passthrough' -> None, 'public-l2' / 'public-dcfc' -> data price, else a number."""
    if text == "passthrough":
        return None
    public = load_public_prices()
    if text == "public-l2":
        return public["L2"]
    if text == "public-dcfc":
        return public["DCFC"]
    return float(text)


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
    ap.add_argument("--move-window", type=int, default=60,
                    help="minutes to move a full car off a work charger; -1 turns the rule off")
    ap.add_argument("--sample-drivers", action="store_true",
                    help="give each driver a real NHTS commuter's schedule")
    ap.add_argument("--region", choices=["us", "new-england"], default="us",
                    help="NHTS commuters to sample from")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--charger-type", choices=["AC", "DC"], default="AC")
    ap.add_argument("--charger-kw", type=float, default=7.2)
    ap.add_argument("--site-rate", choices=["7", "27", "30", "35", "EV-L"], default=None,
                    help="Eversource CT rate the hub is billed on (default: 27 at work, 7 at home)")
    ap.add_argument("--driver-price", default="passthrough",
                    help="passthrough, public-l2, public-dcfc, or a $/kWh number")
    add_viz_args(ap)
    args = ap.parse_args()
    with run_folder(args, ap, "commute", always=("hub", "evs", "chargers", "days", "start")):
        run(args)


def run(args) -> None:

    start = datetime.fromisoformat(args.start)
    cfg = ScenarioConfig(
        start=start, end=start + timedelta(days=args.days),
        num_chargers=args.chargers, hub_location=args.hub,
        move_window_minutes=None if args.move_window < 0 else args.move_window,
        # energy supply price for the hub's customer class
        customer_class="small_commercial" if args.hub == "work" else "residential",
        charger_type=args.charger_type, charger_kw=args.charger_kw,
        site_rate=args.site_rate, driver_price_per_kwh=parse_driver_price(args.driver_price),
    )
    if args.sample_drivers:
        region = NEW_ENGLAND if args.region == "new-england" else None
        profiles = sample_driver_profiles(args.evs, seed=args.seed, region=region)
        print(f"Driver schedules: sampled from NHTS 2022 commuters ({args.region}, seed {args.seed})")
    else:
        profiles = [cfg.driver] * args.evs
        print("Driver schedules: NHTS 2022 median for every driver")
    for i, d in enumerate(profiles, 1):
        print(f"  ev-{i}: work {d.work_start:%H:%M}-{d.work_end:%H:%M} weekdays, commute "
              f"{d.commute_miles:g} mi / {d.commute_minutes} min each way "
              f"({d.trip_miles * cfg.kwh_per_mile:.2f} kWh per trip)")
    rule_on = cfg.move_window_minutes is not None and cfg.hub_location in cfg.move_rule_at
    print("Move-your-car rule: " + (f"move within {cfg.move_window_minutes} min of reaching target"
                                    if rule_on else "off"))

    sim = Simulation(cfg)
    for i, profile in enumerate(profiles, 1):
        sim.add_ev(EV.from_vehicle(f"ev-{i}", cfg.vehicle, battery_kwh=cfg.battery_kwh,
                                   kwh_per_mile=cfg.kwh_per_mile, soc=args.soc,
                                   required_soc=args.target, driver=profile))
    result = sim.run()
    print_results(cfg, result)
    render(result, args)


if __name__ == "__main__":
    main()
