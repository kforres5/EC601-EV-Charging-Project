from datetime import datetime, timedelta

import pytest

from ev_charging.ev import EV
from ev_charging.simulation import Simulation
from ev_charging.tariffs import (SiteMeter, load_evl_rate, load_public_prices,
                                 load_rate_summary)
from tests.helpers import simple_cfg

RATES = load_rate_summary()
EVL = load_evl_rate()
STEP = timedelta(minutes=15)


def test_rate_summary_loaded():
    assert set(RATES) == {"7", "27", "30", "35"}
    r7 = RATES["7"]
    assert (r7.customer_charge, r7.on_peak_delivery, r7.off_peak_delivery) == (9.62, 0.15853, 0.10125)
    assert (RATES["27"].demand_charge, RATES["27"].demand_threshold_kw) == (25.89, 2)


def test_evl_tiers_by_load_factor():
    assert EVL.tier_for(0.0).tier == 1
    assert EVL.tier_for(0.0499).tier == 1
    assert EVL.tier_for(0.05).tier == 2
    assert EVL.tier_for(0.99).tier == 8
    assert EVL.tier_for(0.12).demand_charge == pytest.approx(2.79 + 4.80)


def test_public_prices_loaded():
    assert load_public_prices() == {"L2": 0.39, "DCFC": 0.485}


def meter_full_month(kw=10.0, on_peak=False, price=0.1):
    """A meter with a constant load for all of July 2025."""
    m = SiteMeter()
    t = datetime(2025, 7, 1)
    while t < datetime(2025, 8, 1):
        m.record(t, STEP, kw * 0.25, on_peak, price)
        t += STEP
    return m


def test_bill_with_demand_threshold():
    b = meter_full_month().bills(RATES["27"])[0]
    kwh = 10 * 24 * 31
    assert b.energy_kwh == pytest.approx(kwh)
    assert b.peak_kw == pytest.approx(10)
    assert b.supply_cost == pytest.approx(kwh * 0.1)
    assert b.delivery_cost == pytest.approx(kwh * 0.00936)
    assert b.demand_cost == pytest.approx(25.89 * (10 - 2))
    assert b.customer_cost == pytest.approx(44.0)


def test_evl_bill_uses_load_factor_tier():
    m = SiteMeter()
    t = datetime(2025, 7, 1)
    while t < datetime(2025, 8, 1):   # 100 kW for 1 hour a day -> load factor 1/24 ~ 4%
        m.record(t, STEP, 25.0 if t.hour == 12 else 0.0, True, 0.1)
        t += STEP
    b = m.bills(EVL)[0]
    assert b.load_factor == pytest.approx(1 / 24)
    assert b.tier == 1 and b.demand_cost == 0
    assert b.delivery_cost == pytest.approx(31 * 100 * 0.08253)
    assert b.customer_cost == pytest.approx(350)


def test_partial_month_prorates_fixed_and_demand_charges():
    m = SiteMeter()
    t = datetime(2025, 7, 1)
    for _ in range(96):                      # one day at 10 kW
        m.record(t, STEP, 2.5, False, 0.1)
        t += STEP
    prorated = m.bills(RATES["27"])[0]
    full = m.bills(RATES["27"], prorate=False)[0]
    assert prorated.customer_cost == pytest.approx(44 / 31)
    assert prorated.demand_cost == pytest.approx(25.89 * 8 / 31)
    assert full.customer_cost == pytest.approx(44)


def run_home(**overrides):
    start = datetime(2025, 7, 1)
    cfg = simple_cfg(start=start, end=start + timedelta(days=1), hub_location="home", **overrides)
    sim = Simulation(cfg)
    sim.add_ev(EV("x", cfg.battery_kwh, soc=0.0, required_soc=1.0))
    return sim.run()


def test_delivery_added_to_pass_through_price():
    r = run_home(include_delivery=True)      # 60 kWh overnight, all off-peak, Rate 7
    assert r.ev_results[0].cost == pytest.approx(60 * (0.09161 + 0.10125))
    assert r.timeline[0].supply_price == pytest.approx(0.09161)
    assert r.timeline[0].utility_price == pytest.approx(0.09161 + 0.10125)


def test_flat_driver_price_and_site_margin():
    r = run_home(include_delivery=True, driver_price_per_kwh=0.39)
    assert r.total_cost == pytest.approx(60 * 0.39)
    bill = r.site_bills[0]
    assert bill.supply_cost == pytest.approx(60 * 0.09161)
    assert bill.delivery_cost == pytest.approx(60 * 0.10125)
    assert r.site_margin == pytest.approx(r.total_cost - r.site_cost)


def test_evl_needs_a_flat_driver_price():
    with pytest.raises(ValueError):
        run_home(include_delivery=True, site_rate="EV-L")
    r = run_home(include_delivery=True, site_rate="EV-L", driver_price_per_kwh=0.485)
    assert r.site_bills[0].tier is not None


def test_site_rate_defaults_by_customer_class():
    assert simple_cfg().site_rate == "7"                                  # residential
    assert simple_cfg(customer_class="small_commercial").site_rate == "27"
    assert simple_cfg(customer_class="last_resort").site_rate == "35"
    assert simple_cfg(customer_class="small_commercial", site_rate="EV-L").site_rate == "EV-L"
