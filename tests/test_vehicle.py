from datetime import datetime, timedelta

import pytest

from ev_charging.ev import EV
from ev_charging.simulation import Simulation
from ev_charging.vehicle import VehicleSpec, default_vehicle
from tests.helpers import simple_cfg

V = default_vehicle()


def test_prologue_specs_loaded():
    assert V.name == "Honda Prologue"
    assert (V.battery_kwh, V.kwh_per_mile, V.max_ac_kw, V.max_dc_kw) == (91, 0.34, 11.5, 155)
    assert len(V.dc_curve) == 101


def test_dc_curve_interpolates_and_clamps():
    assert V.dc_power_at(0.10) == 153
    assert V.dc_power_at(0.805) == pytest.approx((66 + 60) / 2)
    assert V.dc_power_at(-1) == 50 and V.dc_power_at(2) == 9


def test_from_vehicle_takes_battery_and_efficiency():
    ev = EV.from_vehicle("x", V)
    assert (ev.battery_kwh, ev.kwh_per_mile, ev.vehicle) == (91, 0.34, V)


def test_ac_power_capped_by_onboard_charger():
    ev = EV.from_vehicle("x", V, soc=0.0)
    assert ev.charge_capacity_kwh(19.2, "AC", 1.0) == pytest.approx(11.5)   # car limit
    assert ev.charge_capacity_kwh(7.2, "AC", 1.0) == pytest.approx(7.2)     # charger limit
    assert EV("y", 60).charge_capacity_kwh(19.2, "AC", 1.0) == pytest.approx(19.2)  # no vehicle


def test_dc_10_to_80_percent_matches_spec_time():
    ev = EV.from_vehicle("x", V, soc=0.10, required_soc=0.80)
    minutes = 0
    while not ev.is_done:
        ev.add_energy(ev.charge_capacity_kwh(350, "DC", 1 / 60))
        minutes += 1
    assert minutes == pytest.approx(33.9, abs=3)      # spec sheet: 33.9 min


def test_dc_power_capped_by_charger():
    ev = EV.from_vehicle("x", V, soc=0.10, required_soc=1.0)
    assert ev.charge_capacity_kwh(50, "DC", 0.25) == pytest.approx(12.5)


def test_capacity_stops_at_target_and_does_not_change_car():
    ev = EV.from_vehicle("x", V, soc=0.78, required_soc=0.80)
    assert ev.charge_capacity_kwh(150, "DC", 1.0) == pytest.approx(0.02 * 91)
    assert ev.soc == 0.78


def test_bad_vehicle_and_charger_kind_rejected():
    with pytest.raises(ValueError):
        VehicleSpec("bad", 0, 0.3, 7, 50)
    with pytest.raises(ValueError):
        EV("x", 60).charge_capacity_kwh(7, "XYZ", 1)


def test_dc_hub_in_simulation():
    start = datetime(2025, 7, 1)
    cfg = simple_cfg(start=start, end=start + timedelta(hours=2), charger_type="DC",
                     charger_kw=150, battery_kwh=91)
    sim = Simulation(cfg)
    sim.add_ev(EV.from_vehicle("x", V, soc=0.1, required_soc=0.8))
    r = sim.run().ev_results[0]
    assert r.reached_required_soc
    assert r.charge_finished <= start + timedelta(minutes=45)
