"""Base scenario: 1 EV (Honda Prologue) at 0% SOC on 1 home Level 2 charger,
cost to charge to 100% with Eversource CT residential supply + Rate 7 delivery.
Edit assumptions in ev_charging/config.py.

    python run_single_ev.py                 # print results (also saved to the run folder)
    python run_single_ev.py --plot          # + dashboard.png
    python run_single_ev.py --animate       # + hub.gif
    python run_single_ev.py --plot --animate --show   # also open live windows

Each run gets its own folder: outputs/runX_[parameters]/ (see ev_charging/run_output.py).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ev_charging.config import ScenarioConfig
from ev_charging.ev import EV
from ev_charging.metrics import SimulationResult
from ev_charging.paths import REPO_ROOT
from ev_charging.run_output import run_folder
from ev_charging.simulation import Simulation


def add_viz_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--plot", action="store_true", help="save a dashboard PNG")
    ap.add_argument("--animate", action="store_true", help="save an animated GIF of the hub")
    ap.add_argument("--show", action="store_true", help="open the charts in a window")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "outputs",
                    help="where run folders go (each run: <out>/runX_[parameters]/)")
    ap.add_argument("--every", type=int, default=1,
                    help="animate every Nth timestep (use for long runs)")


def print_results(cfg: ScenarioConfig, result: SimulationResult) -> None:
    v = cfg.vehicle
    print(f"Scenario: {cfg.customer_class} supply, Eversource CT Rate {cfg.site_rate}, start {cfg.start}, "
          f"{cfg.num_chargers} x {cfg.charger_kw:g} kW {cfg.charger_type} charger(s)")
    print(f"Vehicle: {v.name}, {cfg.battery_kwh:g} kWh, {cfg.kwh_per_mile:g} kWh/mi, "
          f"max {v.max_ac_kw:g} kW AC / {v.max_dc_kw:g} kW DC")
    print(f"Peak window: {cfg.peak.start_hour}:00-{cfg.peak.end_hour}:00"
          f"{' weekdays' if cfg.peak.weekdays_only else ' every day'}")
    if cfg.driver_price_per_kwh is not None:
        print(f"Driver price: flat ${cfg.driver_price_per_kwh:.3f}/kWh")
    else:
        print("Driver price: pass-through of the utility price (supply"
              + (" + delivery)" if cfg.include_delivery else ", no delivery)"))
    for r in result.ev_results:
        print(f"EV {r.ev_id}: SOC {r.start_soc:.0%} -> {r.final_soc:.0%}")
        if r.charge_finished is not None or not (r.energy_driven_kwh or r.hub_departures):
            print(f"  Charged {r.charge_started} -> {r.charge_finished}")
        else:
            print(f"  First charge: {r.charge_started or 'never'}")
        print(f"  Energy: {r.energy_kwh:.2f} kWh "
              f"(off-peak {r.off_peak_kwh:.2f}, on-peak {r.on_peak_kwh:.2f})")
        print(f"  Cost: ${r.cost:.2f}  (avg ${r.avg_price_per_kwh:.4f}/kWh)")
        if r.energy_driven_kwh or r.hub_departures:
            print(f"  Driving: {r.energy_driven_kwh:.2f} kWh used, {r.shortfall_kwh:.2f} kWh short; "
                  f"left the hub {r.hub_departures}x, {r.departures_below_target}x below target")
            print(f"  Charger use: {r.idle_plugged_hours:.2f} h plugged in but idle, "
                  f"moved off the charger {r.moves}x")
    if len(result.ev_results) > 1:
        print(f"Total cost: ${result.total_cost:.2f}")
    print_site_bill(result)


def print_site_bill(result: SimulationResult) -> None:
    if not result.site_bills:
        return
    print("Site utility bill (what the hub pays Eversource):")
    for b in result.site_bills:
        days = b.hours_covered / 24
        tier = f", EV-L tier {b.tier} (load factor {b.load_factor:.0%})" if b.tier else ""
        print(f"  {b.month} ({days:.1f} of {b.hours_in_month / 24:.0f} days{tier}): "
              f"{b.energy_kwh:.1f} kWh, peak {b.peak_kw:.1f} kW | supply ${b.supply_cost:.2f}, "
              f"delivery ${b.delivery_cost:.2f}, demand ${b.demand_cost:.2f}, "
              f"customer ${b.customer_cost:.2f} -> ${b.total:.2f}")
    print(f"  Drivers paid ${result.total_cost:.2f}, site paid ${result.site_cost:.2f}, "
          f"margin ${result.site_margin:.2f}")


def render(result: SimulationResult, args: argparse.Namespace) -> None:
    if not (args.plot or args.animate or args.show):
        return
    from ev_charging.viz import animate_hub, plot_dashboard   # needs matplotlib

    if args.plot:
        path = args.run_dir / "dashboard.png"
        plot_dashboard(result, path)
        print(f"Saved {path}")
    if args.animate:
        path = args.run_dir / "hub.gif"
        print("Rendering animation...")
        animate_hub(result, path, every=args.every)
        print(f"Saved {path}")
    if args.show:   # open the dashboard (and the animation, if asked) in windows
        import matplotlib.pyplot as plt
        plot_dashboard(result, interactive=True)
        anim = animate_hub(result, interactive=True, every=args.every) if args.animate else None
        plt.show()
        del anim


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_viz_args(ap)
    args = ap.parse_args()

    with run_folder(args, ap, "single-ev"):
        cfg = ScenarioConfig(hub_location="home")      # one car on a home charger (Rate 7)
        sim = Simulation(cfg)
        sim.add_ev(EV.from_vehicle("ev-1", cfg.vehicle, battery_kwh=cfg.battery_kwh, soc=0.0,
                                   required_soc=1.0))
        result = sim.run()
        print_results(cfg, result)
        render(result, args)


if __name__ == "__main__":
    main()
