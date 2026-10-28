from datetime import datetime, timedelta

import pytest

from ev_charging.config import ScenarioConfig
from ev_charging.ev import EV
from ev_charging.recorder import EVState
from ev_charging.simulation import Simulation


def single_run(**cfg_kwargs):
    cfg = ScenarioConfig(**cfg_kwargs)
    sim = Simulation(cfg)
    sim.add_ev(EV("ev-1", cfg.battery_kwh, soc=0.0, required_soc=1.0))
    return sim.run()


def fleet_run():
    start = datetime(2025, 7, 1, 16)
    cfg = ScenarioConfig(start=start, end=start + timedelta(days=2), num_chargers=1)
    sim = Simulation(cfg)
    sim.add_ev(EV("a", cfg.battery_kwh, soc=0.5, required_soc=0.8, arrival_time=start))
    sim.add_ev(EV("b", cfg.battery_kwh, soc=0.5, required_soc=0.8,
                  arrival_time=start + timedelta(hours=1)))
    return sim.run()


def test_one_record_per_step_plus_closing():
    r = single_run()
    assert len(r.timeline) == r.steps_run + 1
    assert r.timeline[-1].time == r.ended_at


def test_states_for_single_car():
    tl = single_run().timeline
    assert all(rec.snapshot("ev-1").state is EVState.CHARGING for rec in tl[:-1])
    assert tl[-1].snapshot("ev-1").state is EVState.DONE
    assert tl[0].snapshot("ev-1").charger_id == 0


def test_recorded_power_matches_energy_and_cost():
    r = single_run()
    dt_h = 0.25
    energy = sum(rec.hub_load_kw * dt_h for rec in r.timeline[:-1])
    cost = sum(rec.hub_load_kw * dt_h * rec.price for rec in r.timeline[:-1])
    assert energy == pytest.approx(r.ev_results[0].energy_kwh)
    assert cost == pytest.approx(r.total_cost)
    assert r.timeline[-1].snapshot("ev-1").cost == pytest.approx(r.total_cost)


def test_soc_is_start_of_interval():
    tl = single_run().timeline
    assert tl[0].snapshot("ev-1").soc == 0.0
    assert tl[1].snapshot("ev-1").soc == pytest.approx(1.8 / 60)
    assert tl[-1].snapshot("ev-1").soc == pytest.approx(1.0)


def test_queue_states_with_one_charger():
    tl = fleet_run().timeline
    states_b = [rec.snapshot("b").state for rec in tl]
    assert states_b[0] is EVState.AWAY                      # not arrived yet
    assert EVState.WAITING in states_b                      # 'a' holds the only charger
    first_wait = states_b.index(EVState.WAITING)
    first_charge = states_b.index(EVState.CHARGING)
    assert first_wait < first_charge
    assert states_b[-1] is EVState.DONE


def test_recording_can_be_turned_off():
    cfg = ScenarioConfig()
    sim = Simulation(cfg, record=False)
    sim.add_ev(EV("ev-1", cfg.battery_kwh))
    r = sim.run()
    assert r.timeline == []
    assert r.total_cost > 0


def test_duplicate_ev_id_rejected():
    cfg = ScenarioConfig()
    sim = Simulation(cfg)
    sim.add_ev(EV("x", cfg.battery_kwh))
    with pytest.raises(ValueError):
        sim.add_ev(EV("x", cfg.battery_kwh))
