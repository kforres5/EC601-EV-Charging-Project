from datetime import date, datetime, time, timedelta

import pytest

from ev_charging.config import ScenarioConfig
from ev_charging.driver import DriverProfile, Location
from ev_charging.ev import EV
from ev_charging.recorder import EVState
from ev_charging.simulation import Simulation

MON = datetime(2025, 7, 7)          # a Monday
SAT = datetime(2025, 7, 12)
D = DriverProfile()                 # 9-17, 15 mi / 30 min each way


# ------------------------------------------------------------ driver profile
@pytest.mark.parametrize("hhmm, loc", [
    ("08:29", Location.HOME), ("08:30", Location.DRIVING), ("08:59", Location.DRIVING),
    ("09:00", Location.WORK), ("16:59", Location.WORK), ("17:00", Location.DRIVING),
    ("17:30", Location.HOME), ("23:59", Location.HOME),
])
def test_weekday_locations(hhmm, loc):
    h, m = map(int, hhmm.split(":"))
    assert D.location_at(MON.replace(hour=h, minute=m)) is loc


def test_weekend_at_home_all_day():
    assert all(D.location_at(SAT + timedelta(hours=h)) is Location.HOME for h in range(24))
    assert D.daily_miles(SAT.date()) == 0


def test_driving_miles():
    assert D.trip_miles == pytest.approx(15)
    assert D.daily_miles(MON.date()) == pytest.approx(30)
    assert D.driving_miles(MON, MON + timedelta(days=1)) == pytest.approx(30)
    # one 15-minute step is half of a 30-minute trip
    assert D.driving_miles(MON.replace(hour=8, minute=30), MON.replace(hour=8, minute=45)) \
        == pytest.approx(7.5)
    assert D.driving_miles(SAT, SAT + timedelta(days=1)) == 0


def test_ev_turns_miles_into_energy():
    ev = EV("x", 60, soc=0.5, kwh_per_mile=0.25)
    assert ev.drive(10) == 0
    assert ev.energy_driven_kwh == pytest.approx(2.5)
    assert ev.miles_driven == pytest.approx(10)
    assert ev.soc == pytest.approx(0.5 - 2.5 / 60)


def test_bad_kwh_per_mile_rejected():
    with pytest.raises(ValueError):
        EV("x", 60, kwh_per_mile=0)
    with pytest.raises(ValueError):
        ScenarioConfig(kwh_per_mile=-1)


def test_fraction_at_partial_step():
    p = DriverProfile(work_end=time(17, 10))
    f = p.fraction_at(Location.WORK, MON.replace(hour=17), MON.replace(hour=17, minute=15))
    assert f == pytest.approx(10 / 15)


@pytest.mark.parametrize("kwargs", [
    dict(work_start=time(17), work_end=time(9)),
    dict(commute_minutes=0),
    dict(commute_miles=-1),
    dict(work_days=(7,)),
    dict(work_start=time(0, 10), commute_minutes=30),     # would leave the day before
])
def test_bad_profiles_rejected(kwargs):
    with pytest.raises(ValueError):
        DriverProfile(**kwargs)


# ------------------------------------------------------------ in the simulation
def run(n_evs=1, chargers=1, hub="work", days=1, soc=0.5, target=0.8, start=MON,
        move_window=None, kwh_per_mile=0.30):
    """Move-your-car rule is OFF unless move_window (minutes) is given."""
    cfg = ScenarioConfig(start=start, end=start + timedelta(days=days),
                         num_chargers=chargers, hub_location=hub, price_csv=None,
                         move_window_minutes=move_window)
    sim = Simulation(cfg)
    for i in range(n_evs):
        sim.add_ev(EV(f"ev-{i}", cfg.battery_kwh, soc=soc, required_soc=target, driver=cfg.driver,
                      kwh_per_mile=kwh_per_mile))
    return sim.run()


def state_at(result, ev_id, hhmm):
    h, m = map(int, hhmm.split(":"))
    t = result.timeline[0].time.replace(hour=h, minute=m)
    return next(r for r in result.timeline if r.time == t).snapshot(ev_id)


def test_one_commuting_day_at_work_hub():
    r = run()
    e = r.ev_results[0]
    assert state_at(r, "ev-0", "08:00").state is EVState.AWAY
    assert state_at(r, "ev-0", "08:00").location == "home"
    assert state_at(r, "ev-0", "08:30").state is EVState.DRIVING
    assert state_at(r, "ev-0", "09:00").state is EVState.CHARGING
    assert state_at(r, "ev-0", "15:00").state is EVState.IDLE      # full, still plugged in
    assert state_at(r, "ev-0", "17:00").state is EVState.DRIVING
    # arrives at 50% - 4.5/60, charges to 80%, gets home at 80% - 4.5/60
    assert e.energy_kwh == pytest.approx((0.8 - (0.5 - 0.075)) * 60)
    assert e.final_soc == pytest.approx(0.8 - 0.075)
    assert e.energy_driven_kwh == pytest.approx(9.0)
    assert (e.hub_departures, e.departures_below_target, e.shortfall_kwh) == (1, 0, 0)


def test_home_hub_charges_overnight_not_at_work():
    r = run(hub="home", soc=0.2, target=0.8, days=2)
    assert state_at(r, "ev-0", "00:00").state is EVState.CHARGING
    assert state_at(r, "ev-0", "12:00").location == "work"
    assert state_at(r, "ev-0", "12:00").state is EVState.AWAY
    assert r.ev_results[0].hub_departures == 2   # leaves home each weekday morning


def test_full_cars_hog_chargers_so_others_wait():
    r = run(n_evs=2, chargers=1)
    a, b = r.ev_results
    assert a.energy_kwh > 0 and b.energy_kwh == 0
    assert state_at(r, "ev-1", "12:00").state is EVState.WAITING
    assert b.departures_below_target == 1


def test_battery_cannot_go_negative():
    r = run(hub="home", soc=0.05, target=0.0, days=1)   # 3 kWh in the battery, 9 kWh of driving, never charges
    e = r.ev_results[0]
    assert e.final_soc == 0.0
    assert e.energy_driven_kwh == pytest.approx(3.0)
    assert e.shortfall_kwh == pytest.approx(6.0)


def test_run_lasts_until_end_with_drivers():
    r = run(days=2)
    assert r.ended_at == MON + timedelta(days=2)


def test_driverless_evs_unchanged():
    cfg = ScenarioConfig(price_csv=None)
    sim = Simulation(cfg)
    sim.add_ev(EV("x", cfg.battery_kwh, soc=0.0, required_soc=1.0))
    r = sim.run()
    assert r.ev_results[0].charge_finished == datetime(2025, 7, 1, 8, 30)
    assert r.timeline[-1].snapshot("x").state is EVState.DONE
    assert r.timeline[-1].snapshot("x").location is None


def test_bad_hub_location_rejected():
    with pytest.raises(ValueError):
        ScenarioConfig(hub_location="mall")


# ------------------------------------------------------------ move-your-car rule
def test_full_car_moves_after_window_and_frees_charger():
    r = run(n_evs=2, chargers=1, move_window=60)
    a, b = r.ev_results
    # ev-0 arrives at 42.5%, full (80%) at 12:15, idle until 13:15, then parks
    assert state_at(r, "ev-0", "12:15").state is EVState.IDLE
    assert state_at(r, "ev-0", "13:00").state is EVState.IDLE
    assert state_at(r, "ev-0", "13:15").state is EVState.PARKED
    assert state_at(r, "ev-0", "13:15").charger_id is None
    assert (a.moves, a.idle_plugged_hours) == (1, pytest.approx(1.0))
    # ev-1 waits until 13:15, then gets the charger and reaches 80% before 17:00
    assert state_at(r, "ev-1", "13:00").state is EVState.WAITING
    assert state_at(r, "ev-1", "13:15").state is EVState.CHARGING
    assert b.departures_below_target == 0
    assert b.energy_kwh == pytest.approx(22.5)


def test_parked_car_does_not_plug_back_in_same_day():
    r = run(n_evs=1, chargers=1, move_window=0)
    states = [rec.snapshot("ev-0").state for rec in r.timeline
              if rec.time.hour >= 13 and rec.time < MON.replace(hour=17)]
    assert set(states) == {EVState.PARKED}


def test_car_already_at_target_parks_without_a_charger():
    r = run(n_evs=1, chargers=1, soc=0.95, target=0.8, move_window=60)
    assert state_at(r, "ev-0", "09:00").state is EVState.PARKED
    assert r.ev_results[0].energy_kwh == 0


def test_rule_only_applies_at_listed_hub_locations():
    r = run(hub="home", soc=0.2, target=0.8, move_window=60, days=1)
    # home is not in move_rule_at, so the full car stays plugged in overnight
    assert r.ev_results[0].moves == 0
    assert state_at(r, "ev-0", "06:00").state is EVState.IDLE


def test_move_rule_is_on_by_default_at_work():
    cfg = ScenarioConfig()
    assert cfg.move_window_minutes == 60 and cfg.move_rule_at == ("work",)
    with pytest.raises(ValueError):
        ScenarioConfig(move_window_minutes=-5)


def test_less_efficient_ev_uses_more_energy_on_same_commute():
    r = run(hub="home", soc=0.9, target=0.0, kwh_per_mile=0.40)   # never charges
    e = r.ev_results[0]
    assert e.energy_driven_kwh == pytest.approx(30 * 0.40)
    assert e.final_soc == pytest.approx(0.9 - 12 / 60)
