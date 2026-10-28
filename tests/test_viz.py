"""Smoke tests: charts render and save without errors."""
import pytest

pytest.importorskip("matplotlib")

from tests.test_timeline import fleet_run, single_run  # noqa: E402
from ev_charging.viz import animate_hub, plot_dashboard  # noqa: E402


def test_dashboard_png(tmp_path):
    out = tmp_path / "dash.png"
    plot_dashboard(single_run(), out)
    assert out.stat().st_size > 10_000


def test_dashboard_fleet(tmp_path):
    out = tmp_path / "fleet.png"
    plot_dashboard(fleet_run(), out)
    assert out.exists()


def test_animation_gif(tmp_path):
    out = tmp_path / "hub.gif"
    animate_hub(fleet_run(), out, every=4, substeps=2, fps=6)
    assert out.stat().st_size > 10_000


def test_animation_rejects_huge_runs():
    from datetime import datetime
    from ev_charging.config import ScenarioConfig
    from ev_charging.ev import EV
    from ev_charging.simulation import Simulation
    cfg = ScenarioConfig(end=datetime(2025, 7, 20), charger_kw=0.2)
    sim = Simulation(cfg)
    sim.add_ev(EV("slow", cfg.battery_kwh))
    with pytest.raises(ValueError):
        animate_hub(sim.run(), None)


def test_empty_timeline_rejected():
    from ev_charging.config import ScenarioConfig
    from ev_charging.ev import EV
    from ev_charging.simulation import Simulation
    cfg = ScenarioConfig()
    sim = Simulation(cfg, record=False)
    sim.add_ev(EV("x", cfg.battery_kwh))
    with pytest.raises(ValueError):
        plot_dashboard(sim.run())
