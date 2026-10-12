"""Base scenario: 1 EV at 0% SOC, 1 charger, cost to charge to 100%
using Eversource pricing. Edit assumptions in ev_charging/config.py.

    python run_single_ev.py
"""
from ev_charging.config import ScenarioConfig
from ev_charging.ev import EV
from ev_charging.simulation import Simulation


def main() -> None:
    cfg = ScenarioConfig()
    sim = Simulation(cfg)
    sim.add_ev(EV("ev-1", battery_kwh=cfg.battery_kwh, soc=0.0, required_soc=1.0))
    r = sim.run().ev_results[0]

    print(f"Scenario: {cfg.customer_class}, start {cfg.start}, "
          f"{cfg.charger_kw} kW charger, {cfg.battery_kwh} kWh battery")
    print(f"Peak window: {cfg.peak.start_hour}:00-{cfg.peak.end_hour}:00"
          f"{' weekdays' if cfg.peak.weekdays_only else ' every day'}")
    print(f"EV {r.ev_id}: SOC {r.start_soc:.0%} -> {r.final_soc:.0%}")
    print(f"  Charged {r.charge_started} -> {r.charge_finished}")
    print(f"  Energy: {r.energy_kwh:.2f} kWh "
          f"(off-peak {r.off_peak_kwh:.2f}, on-peak {r.on_peak_kwh:.2f})")
    print(f"  Cost: ${r.cost:.2f}  (avg ${r.avg_price_per_kwh:.4f}/kWh)")


if __name__ == "__main__":
    main()
