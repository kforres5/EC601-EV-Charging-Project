"""Base scenario: 1 EV at 0% SOC, 1 charger, cost to charge to 100%
using Eversource pricing. Edit assumptions in ev_charging/config.py.

    python run_single_ev.py                 # print results only
    python run_single_ev.py --plot          # + outputs/single_ev_dashboard.png
    python run_single_ev.py --animate       # + outputs/single_ev_hub.gif
    python run_single_ev.py --plot --animate --show   # also open live windows
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ev_charging.config import ScenarioConfig
from ev_charging.ev import EV
from ev_charging.metrics import SimulationResult
from ev_charging.paths import REPO_ROOT
from ev_charging.simulation import Simulation


def add_viz_args(ap: argparse.ArgumentParser, default_name: str) -> None:
    ap.add_argument("--plot", action="store_true", help="save a dashboard PNG")
    ap.add_argument("--animate", action="store_true", help="save an animated GIF of the hub")
    ap.add_argument("--show", action="store_true", help="open the charts in a window")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "outputs", help="output folder")
    ap.add_argument("--name", default=default_name, help="file name prefix")
    ap.add_argument("--every", type=int, default=1,
                    help="animate every Nth timestep (use for long runs)")


def print_results(cfg: ScenarioConfig, result: SimulationResult) -> None:
    print(f"Scenario: {cfg.customer_class}, start {cfg.start}, {cfg.num_chargers} x "
          f"{cfg.charger_kw} kW charger(s), {cfg.battery_kwh} kWh batteries")
    print(f"Peak window: {cfg.peak.start_hour}:00-{cfg.peak.end_hour}:00"
          f"{' weekdays' if cfg.peak.weekdays_only else ' every day'}")
    for r in result.ev_results:
        print(f"EV {r.ev_id}: SOC {r.start_soc:.0%} -> {r.final_soc:.0%}")
        print(f"  Charged {r.charge_started} -> {r.charge_finished}")
        print(f"  Energy: {r.energy_kwh:.2f} kWh "
              f"(off-peak {r.off_peak_kwh:.2f}, on-peak {r.on_peak_kwh:.2f})")
        print(f"  Cost: ${r.cost:.2f}  (avg ${r.avg_price_per_kwh:.4f}/kWh)")
    if len(result.ev_results) > 1:
        print(f"Total cost: ${result.total_cost:.2f}")


def render(result: SimulationResult, args: argparse.Namespace) -> None:
    if not (args.plot or args.animate or args.show):
        return
    from ev_charging.viz import animate_hub, plot_dashboard   # needs matplotlib

    if args.plot:
        path = args.out / f"{args.name}_dashboard.png"
        plot_dashboard(result, path)
        print(f"Saved {path}")
    if args.animate:
        path = args.out / f"{args.name}_hub.gif"
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
    add_viz_args(ap, default_name="single_ev")
    args = ap.parse_args()

    cfg = ScenarioConfig()
    sim = Simulation(cfg)
    sim.add_ev(EV("ev-1", battery_kwh=cfg.battery_kwh, soc=0.0, required_soc=1.0))
    result = sim.run()
    print_results(cfg, result)
    render(result, args)


if __name__ == "__main__":
    main()
