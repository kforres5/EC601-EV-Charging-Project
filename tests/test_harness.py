from datetime import date, datetime

import pytest

from ev_charging.clock import SimClock
from ev_charging.config import PeakWindow, ScenarioConfig
from ev_charging.ev import EV
from ev_charging.paths import EVERSOURCE_CSV
from ev_charging.pricing import EversourcePriceSchedule
from ev_charging.simulation import Simulation


def run(cfg):
    sim = Simulation(cfg)
    sim.add_ev(EV("ev-1", cfg.battery_kwh, soc=0.0, required_soc=1.0))
    return sim.run().ev_results[0]


@pytest.fixture(scope="module")
def eversource():
    return EversourcePriceSchedule(EVERSOURCE_CSV, "residential", PeakWindow())


# ---------------------------------------------------------- pricing data
def test_reads_known_row(eversource):
    assert eversource.rates_for(date(2025, 7, 1)) == (0.15764, 0.09161)


def test_customer_class_switch():
    sched = EversourcePriceSchedule(EVERSOURCE_CSV, "small_commercial", PeakWindow())
    assert sched.rates_for(date(2025, 7, 1)) == (0.15157, 0.09328)


def test_weekend_uses_same_month_rates(eversource):
    # Sat 2025-11-01: nearest same-month row is Mon 11/03, not Fri 10/31
    assert eversource.rates_for(date(2025, 11, 1))[1] == 0.08615


def test_missing_weekday_filled(eversource):
    assert eversource.rates_for(date(2025, 9, 30)) == eversource.rates_for(date(2025, 9, 29))


def test_out_of_range_raises(eversource):
    with pytest.raises(KeyError):
        eversource.rates_for(date(2026, 7, 1))


def test_weekend_is_off_peak_all_day(eversource):
    sat_noon = datetime(2025, 7, 5, 12)
    assert not eversource.is_on_peak(sat_noon)
    assert eversource.price_at(sat_noon) == 0.09161


# ---------------------------------------------------------- peak window
def test_default_peak_window():
    p = PeakWindow()
    assert not p.is_on_peak(datetime(2025, 7, 1, 11, 45))
    assert p.is_on_peak(datetime(2025, 7, 1, 12, 0))
    assert p.is_on_peak(datetime(2025, 7, 1, 19, 45))
    assert not p.is_on_peak(datetime(2025, 7, 1, 20, 0))


def test_peak_window_is_configurable():
    p = PeakWindow(start_hour=16, end_hour=21, weekdays_only=False,
                   holidays=(date(2025, 7, 4),))
    assert p.is_on_peak(datetime(2025, 7, 5, 17))       # Saturday counts now
    assert not p.is_on_peak(datetime(2025, 7, 4, 17))   # holiday
    with pytest.raises(ValueError):
        PeakWindow(start_hour=20, end_hour=10)


# ---------------------------------------------------------- end-to-end
def test_base_scenario_cost_matches_hand_calc():
    # 0:00-8:30 is all before the noon peak: 60 kWh at July's off-peak 0.09161
    r = run(ScenarioConfig())
    assert r.reached_required_soc
    assert r.off_peak_kwh == pytest.approx(60.0)
    assert r.on_peak_kwh == pytest.approx(0.0)
    assert r.cost == pytest.approx(60.0 * 0.09161)
    assert r.charge_finished == datetime(2025, 7, 1, 8, 30)


def test_charging_into_the_peak_costs_more():
    # start 09:00: 3 h off-peak (21.6 kWh), the remaining 38.4 kWh on-peak at 0.15764
    r = run(ScenarioConfig(start=datetime(2025, 7, 1, 9)))
    assert r.off_peak_kwh == pytest.approx(21.6)
    assert r.on_peak_kwh == pytest.approx(38.4)
    assert r.cost == pytest.approx(21.6 * 0.09161 + 38.4 * 0.15764)


def test_flat_fallback_pricing():
    cfg = ScenarioConfig(price_csv=None, fallback_on_peak_price=0.2, fallback_off_peak_price=0.2)
    assert run(cfg).cost == pytest.approx(12.0)


def test_efficiency_increases_billed_energy():
    cfg = ScenarioConfig(price_csv=None, charging_efficiency=0.9)
    assert run(cfg).energy_kwh == pytest.approx(60.0 / 0.9)


def test_run_stops_at_end_if_not_enough_time():
    r = run(ScenarioConfig(end=datetime(2025, 7, 1, 2)))
    assert not r.reached_required_soc
    assert r.energy_kwh == pytest.approx(14.4)


def test_clock():
    c = SimClock(datetime(2025, 7, 1), datetime(2025, 7, 1, 1), 15)
    n = 0
    while not c.done:
        c.advance(); n += 1
    assert n == 4


def test_bad_config_rejected():
    with pytest.raises(ValueError):
        ScenarioConfig(customer_class="industrial")
    with pytest.raises(ValueError):
        ScenarioConfig(step_minutes=7)
