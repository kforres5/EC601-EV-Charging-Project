"""Greedy vs always-charge: commuting drivers who charge at home, at work, and at
public stations.

Each driver has a home charger (Level 2, Level 1 or none; 10% have none, from
NREL) and shares the work hub. Home: Eversource CT residential supply + Rate 7
delivery, paid by the household. Work: flat $0.25/kWh fee, 4 h/day limit,
move-your-car rule; the hub pays small C&I supply + Rate 27. Public: a Level 2
lot ($0.39/kWh) and a DC fast station ($0.485/kWh), prices from
dataset/charger_prices_summary.csv; each pays its own bill (Rate 27 / Rate EV-L).
Both strategies run on the same drivers and prices:
  - always-charge: plug in whenever possible, charge at full power to --target;
    if home can't cover tomorrow, fill up at the fastest public station
  - greedy: buy the cheapest home/work slots that keep the battery above the
    buffer (next driving + 20%), replanning when blocked; book the cheapest
    public station that fits when home + work fall short

    python run_greedy.py                               # 10 drivers, 3 work chargers, 1 week of July 2025
    python run_greedy.py --start 2026-01-05            # winter: work fee cheaper than home off-peak
    python run_greedy.py --sample-drivers --evs 10 --chargers 3 --seed 3
    python run_greedy.py --home-types none,none,L1,L2 # pick each driver's home charger
    python run_greedy.py --no-home-share 0.4 --chargers 2   # more renters, fewer work chargers
    python run_greedy.py --no-public                   # home + work only
    python run_greedy.py --plot                        # dashboards in outputs/
    python run_greedy.py --animate --anim-days 2       # animated GIF of the first 2 days, per strategy
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from ev_charging.commute import CommuteResult, CommuteSimulation
from ev_charging.config import (HOME_CHARGER_TYPES, CommuteConfig, HomeChargingConfig, WorkHubConfig,
                                assign_home_chargers, default_public_stations)
from ev_charging.ev import EV
from ev_charging.nhts import NEW_ENGLAND, sample_driver_profiles
from ev_charging.paths import REPO_ROOT
from ev_charging.strategies import AlwaysCharge, Greedy
from ev_charging.tariffs import load_public_prices

STRATEGIES = {"always": lambda a: AlwaysCharge(),
              "greedy": lambda a: Greedy(horizon_hours=a.horizon, tie_break=a.tie_break)}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evs", type=int, default=10)
    ap.add_argument("--chargers", type=int, default=3, help="work hub chargers")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--start", default="2025-07-07", help="start date (YYYY-MM-DD), 00:00")
    ap.add_argument("--soc", type=float, default=0.5, help="starting state of charge (0-1)")
    ap.add_argument("--target", type=float, default=0.8,
                    help="most a driver charges to (0-1); always-charge charges up to it")
    ap.add_argument("--buffer", type=float, default=0.2, help="charge goal: never below this SOC")
    ap.add_argument("--work-price", type=float, default=0.25, help="flat $/kWh at work")
    ap.add_argument("--work-limit", type=float, default=4.0,
                    help="hours per day a car may be plugged in at work; -1 = no limit")
    ap.add_argument("--move-window", type=int, default=60,
                    help="minutes to unplug after charging stops at work; -1 = rule off")
    ap.add_argument("--work-kw", type=float, default=7.2)
    ap.add_argument("--no-home-share", type=float, default=0.1,
                    help="share of drivers without a home charger (NREL 2030 study: 10%%)")
    ap.add_argument("--home-types", default=None,
                    help="comma list of L2/L1/none per driver (overrides the mix)")
    ap.add_argument("--no-public", action="store_true", help="no public stations")
    ap.add_argument("--public-l2", type=int, default=2, help="chargers at the public L2 lot (0 = none)")
    ap.add_argument("--public-dcfc", type=int, default=2, help="chargers at the DC fast station (0 = none)")
    ap.add_argument("--l2-price", type=float, default=None, help="public L2 $/kWh (default: dataset)")
    ap.add_argument("--dcfc-price", type=float, default=None, help="DC fast $/kWh (default: dataset)")
    ap.add_argument("--sample-drivers", action="store_true",
                    help="give each driver a real NHTS 2022 commuter's schedule")
    ap.add_argument("--region", choices=["us", "new-england"], default="us")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--strategy", choices=["both", *STRATEGIES], default="both")
    ap.add_argument("--horizon", type=float, default=96,
                    help="greedy planning horizon (hours); 96 h lets a Friday plan see Monday")
    ap.add_argument("--tie-break", choices=["earliest", "latest"], default="earliest",
                    help="greedy: among equally cheap slots, charge earliest or latest")
    ap.add_argument("--plot", action="store_true", help="save a dashboard PNG per strategy")
    ap.add_argument("--animate", action="store_true", help="save an animated GIF per strategy")
    ap.add_argument("--anim-days", type=float, default=None,
                    help="animate only the first N days (default: the whole run)")
    ap.add_argument("--every", type=int, default=0,
                    help="animate every Nth timestep (0 = pick one that keeps it under a minute)")
    ap.add_argument("--show", action="store_true", help="open the dashboards in windows")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "outputs")
    ap.add_argument("--name", default="greedy")
    return ap


def build_config(a) -> CommuteConfig:
    start = datetime.fromisoformat(a.start)
    return CommuteConfig(
        start=start, end=start + timedelta(days=a.days), soc_buffer=a.buffer,
        work=WorkHubConfig(
            num_chargers=a.chargers, charger_kw=a.work_kw, driver_price_per_kwh=a.work_price,
            daily_limit_hours=None if a.work_limit < 0 else a.work_limit,
            move_window_minutes=None if a.move_window < 0 else a.move_window),
        home=HomeChargingConfig(no_home_share=a.no_home_share),
        public=public_stations(a),
    )


def public_stations(a) -> tuple:
    if a.no_public:
        return ()
    l2, dc = default_public_stations()
    out = []
    if a.public_l2 > 0:
        out.append(replace(l2, num_chargers=a.public_l2, driver_price_per_kwh=a.l2_price))
    if a.public_dcfc > 0:
        out.append(replace(dc, num_chargers=a.public_dcfc, driver_price_per_kwh=a.dcfc_price))
    return tuple(out)


def drivers_for(a, cfg: CommuteConfig):
    if a.home_types:
        types = [t.strip() for t in a.home_types.split(",")]
        bad = set(types) - set(HOME_CHARGER_TYPES)
        if bad:
            raise SystemExit(f"--home-types: unknown {sorted(bad)}; use {HOME_CHARGER_TYPES}")
        a.evs = len(types)
    else:
        types = assign_home_chargers(a.evs, cfg.home.shares)
    if a.sample_drivers:
        region = NEW_ENGLAND if a.region == "new-england" else None
        profiles = sample_driver_profiles(a.evs, seed=a.seed, region=region)
    else:
        from ev_charging.driver import DriverProfile
        profiles = [DriverProfile()] * a.evs
    return list(zip(profiles, types))


def run_one(cfg: CommuteConfig, drivers, strategy, a, record: bool) -> CommuteResult:
    sim = CommuteSimulation(cfg, record=record)
    for i, (profile, home) in enumerate(drivers, 1):
        sim.add_driver(EV.from_vehicle(f"ev-{i}", cfg.vehicle, soc=a.soc, required_soc=a.target,
                                       driver=profile, strategy=strategy), home)
    return sim.run()


def print_setup(cfg: CommuteConfig, drivers, a) -> None:
    v, w = cfg.vehicle, cfg.work
    print(f"{cfg.start:%a %Y-%m-%d} to {cfg.end:%a %Y-%m-%d}, {v.name} "
          f"({v.battery_kwh:g} kWh, {v.kwh_per_mile:g} kWh/mi), start SOC {a.soc:.0%}, "
          f"max {a.target:.0%}, buffer {cfg.soc_buffer:.0%}")
    lim = f"{w.daily_limit_hours:g} h/day" if w.daily_limit_hours is not None else "no daily limit"
    mv = f"move within {w.move_window_minutes} min" if w.move_window_minutes is not None else "no move rule"
    price = f"${w.driver_price_per_kwh:.2f}/kWh flat" if w.driver_price_per_kwh is not None else "pass-through"
    print(f"Work hub: {w.num_chargers} x {w.charger_kw:g} kW {w.charger_type}, drivers pay {price}, "
          f"{lim}, {mv}; site billed on Rate {w.site_rate} ({w.customer_class} supply)")
    print(f"Home: own charger (L2 {cfg.home.kw('L2'):g} kW / L1 {cfg.home.kw('L1'):g} kW / none), "
          f"{cfg.home.customer_class} supply + Rate {cfg.home.site_rate} delivery, pass-through")
    for p in cfg.public:
        price = p.driver_price_per_kwh
        price = f"${price:.3f}" if price is not None else f"${load_public_prices()[p.kind]:.3f} (dataset)"
        print(f"Public {p.name}: {p.num_chargers} x {p.charger_kw:g} kW {p.kind}, drivers pay {price}/kWh, "
              f"{p.detour_minutes} min / {p.detour_miles:g} mi from home, stay up to "
              f"{p.max_dwell_minutes} min; site billed on Rate {p.site_rate} ({p.customer_class} supply)")
    if not cfg.public:
        print("Public stations: none")
    print("Drivers:")
    for i, (d, home) in enumerate(drivers, 1):
        print(f"  ev-{i}: {home:>4} home charger | work {d.work_start:%H:%M}-{d.work_end:%H:%M}, "
              f"{d.commute_miles:g} mi / {d.commute_minutes} min each way "
              f"({2 * d.trip_miles * v.kwh_per_mile:.1f} kWh/workday)")


def print_result(r: CommuteResult) -> None:
    print(f"\n=== {r.strategy} ===")
    print(f"  {'EV':6} {'home':5} {'SOC start>end (min)':20} {'home kWh/$':>13} {'work kWh/$':>13} "
          f"{'public kWh/$':>13} {'visits':>6} {'$/kWh':>6} {'on-peak':>7} {'trips<buf':>9} "
          f"{'short kWh':>9} {'wait h':>6}")
    for e in r.ev_results:
        print(f"  {e.ev_id:6} {e.home_charger:5} "
              f"{f'{e.start_soc:.0%}>{e.final_soc:.0%} ({e.min_soc:.0%})':20} "
              f"{e.home_kwh:6.1f}/{e.home_cost:6.2f} {e.work_kwh:6.1f}/{e.work_cost:6.2f} "
              f"{e.public_kwh:6.1f}/{e.public_cost:6.2f} {e.public_visits:6d} "
              f"{e.avg_price_per_kwh:6.3f} {e.on_peak_kwh / e.energy_kwh if e.energy_kwh else 0:7.0%} "
              f"{e.trips_below_buffer:>4}/{e.trips:<4} {e.shortfall_kwh:9.1f} "
              f"{e.work_waiting_hours + e.public_waiting_hours:6.1f}")
    by_type = defaultdict(list)
    for e in r.ev_results:
        by_type[e.home_charger].append(e)
    print("  By home charger type:")
    for t in HOME_CHARGER_TYPES:
        es = by_type.get(t)
        if not es:
            continue
        kwh = sum(e.energy_kwh for e in es)
        cost = sum(e.cost for e in es)
        work = sum(e.work_kwh for e in es)
        public = sum(e.public_kwh for e in es)
        hours = sum(e.public_hours for e in es)
        missed = sum(e.missed_goal for e in es)
        share = lambda x: f"{x / kwh if kwh else 0:.0%}"
        print(f"    {t:>4} ({len(es)}): ${cost:.2f} for {kwh:.1f} kWh "
              f"(${cost / kwh if kwh else 0:.3f}/kWh; {share(work)} at work, {share(public)} public, "
              f"{hours:.1f} h on public trips), {missed}/{len(es)} missed the goal")
    at = f" at {r.peak_home_at:%a %H:%M}" if r.peak_home_at else ""
    print(f"  Drivers paid ${r.total_cost:.2f}. Peak load: all homes {r.peak_home_kw:.1f} kW{at}, "
          f"work hub {r.peak_work_kw:.1f} kW")
    for b in r.work_bills:
        print(f"  Work hub bill {b.month} ({b.hours_covered / 24:.0f} days): {b.energy_kwh:.1f} kWh, "
              f"peak {b.peak_kw:.1f} kW | supply ${b.supply_cost:.2f}, delivery ${b.delivery_cost:.2f}, "
              f"demand ${b.demand_cost:.2f}, customer ${b.customer_cost:.2f} -> ${b.total:.2f}")
    print(f"  Work hub: fees ${r.work_revenue:.2f} - bill ${r.work_site_cost:.2f} = margin ${r.work_margin:.2f}")
    for st in r.stations:
        demand = sum(b.demand_cost for b in st.bills)
        tiers = ", ".join(f"EV-L tier {b.tier}" for b in st.bills if b.tier)
        print(f"  Public {st.name}: {st.energy_kwh:.1f} kWh at ${st.price:.3f}, peak {st.peak_kw:.0f} kW | "
              f"revenue ${st.revenue:.2f} - bill ${st.site_cost:.2f} (demand ${demand:.2f}"
              f"{', ' + tiers if tiers else ''}) = margin ${st.margin:.2f}")


def main() -> None:
    a = build_parser().parse_args()
    cfg = build_config(a)
    drivers = drivers_for(a, cfg)
    print_setup(cfg, drivers, a)
    names = list(STRATEGIES) if a.strategy == "both" else [a.strategy]
    results = {}
    for name in names:
        results[name] = run_one(cfg, drivers, STRATEGIES[name](a), a,
                                record=a.plot or a.show or a.animate)
        print_result(results[name])
    if len(results) == 2:
        al, gr = results["always"], results["greedy"]
        kwh = lambda r: sum(e.energy_kwh for e in r.ev_results)
        print(f"\nGreedy vs always-charge: avg price ${gr.total_cost / kwh(gr):.3f} vs "
              f"${al.total_cost / kwh(al):.3f} per kWh; greedy charges only what the goal needs "
              f"({kwh(gr):.0f} vs {kwh(al):.0f} kWh), so compare $/kWh, not totals.")
    if a.plot or a.show:
        from ev_charging.viz import plot_commute_dashboard
        for name, r in results.items():
            path = a.out / f"{a.name}_{name}_dashboard.png" if a.plot else None
            plot_commute_dashboard(r, path, interactive=a.show)
            if path:
                print(f"Saved {path}")
    if a.animate:
        from ev_charging.viz import animate_commute
        end = cfg.start + timedelta(days=a.anim_days) if a.anim_days else None
        for name, r in results.items():
            path = a.out / f"{a.name}_{name}_commute.gif"
            print(f"Rendering {name} animation...")
            animate_commute(r, path, end=end, every=a.every)
            print(f"Saved {path}")
    if a.show:
        import matplotlib.pyplot as plt
        plt.show()


if __name__ == "__main__":
    main()
