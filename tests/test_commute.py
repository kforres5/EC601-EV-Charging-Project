"""Home + work simulation (CommuteSimulation) and the greedy strategy."""
import math
import unittest
from datetime import datetime, timedelta

from ev_charging.commute import CommuteSimulation
from ev_charging.config import (CommuteConfig, HomeChargingConfig, WorkHubConfig,
                                assign_home_chargers)
from ev_charging.ev import EV
from ev_charging.strategies import AlwaysCharge, Greedy
from ev_charging.strategies.greedy import _Slot
from ev_charging.driver import Location
from tests.helpers import SIMPLE_DRIVER

MON = datetime(2025, 7, 7)          # a Monday


def cfg(days=2, **kw) -> CommuteConfig:
    """Flat TOU prices (on-peak 0.35, off-peak 0.15, weekdays 12-20), no delivery,
    no public stations unless given."""
    work = kw.pop("work", WorkHubConfig())
    public = kw.pop("public", ())
    return CommuteConfig(start=MON, end=MON + timedelta(days=days), price_csv=None,
                         include_delivery=False, work=work, public=public, **kw)


def run(c, drivers, strategy_factory=AlwaysCharge, soc=0.5, target=0.8):
    sim = CommuteSimulation(c)
    for i, (home, driver) in enumerate(drivers, 1):
        sim.add_driver(EV.from_vehicle(f"ev-{i}", c.vehicle, soc=soc, required_soc=target,
                                       driver=driver, strategy=strategy_factory()), home)
    return sim, sim.run()


class TestConfig(unittest.TestCase):
    def test_default_rates_and_shares(self):
        c = CommuteConfig()
        self.assertEqual(c.work.site_rate, "27")
        self.assertEqual(c.home.site_rate, "7")
        self.assertAlmostEqual(sum(c.home.shares.values()), 1.0)
        self.assertEqual(c.work.driver_price_per_kwh, 0.25)
        self.assertEqual(c.work.daily_limit_hours, 4.0)

    def test_assign_home_chargers(self):
        types = assign_home_chargers(10, HomeChargingConfig(no_home_share=0.2).shares)
        self.assertEqual(len(types), 10)
        self.assertEqual(types.count("none"), 2)
        self.assertEqual(types.count("L1"), 1)
        self.assertEqual(types.count("L2"), 7)
        self.assertEqual(assign_home_chargers(3, {"L2": 1.0, "L1": 0.0, "none": 0.0}), ["L2"] * 3)

    def test_bad_values(self):
        with self.assertRaises(ValueError):
            HomeChargingConfig(no_home_share=1.5)
        with self.assertRaises(ValueError):
            WorkHubConfig(daily_limit_hours=-1)
        with self.assertRaises(ValueError):
            CommuteConfig(soc_buffer=1.0)

    def test_driver_required(self):
        sim = CommuteSimulation(cfg())
        with self.assertRaises(ValueError):
            sim.add_driver(EV("x", 60.0))
        with self.assertRaises(ValueError):
            sim.add_driver(EV("y", 60.0, driver=SIMPLE_DRIVER), "L3")


class TestAlwaysCharge(unittest.TestCase):
    def test_home_only_pays_pass_through(self):
        c = cfg(work=WorkHubConfig(num_chargers=0))
        _, r = run(c, [("L2", SIMPLE_DRIVER)])
        e = r.ev_results[0]
        self.assertEqual(e.work_kwh, 0)
        self.assertGreater(e.home_kwh, 0)
        # Monday 00:00 is off-peak (0.15); evening return at 17:30 is on-peak (0.35)
        self.assertAlmostEqual(e.home_cost, 0.15 * e.off_peak_kwh + 0.35 * e.on_peak_kwh, places=6)
        self.assertAlmostEqual(e.final_soc, 0.8, places=6)

    def test_no_home_charges_at_work_at_flat_fee(self):
        _, r = run(cfg(), [("none", SIMPLE_DRIVER)])
        e = r.ev_results[0]
        self.assertEqual(e.home_kwh, 0)
        self.assertGreater(e.work_kwh, 0)
        self.assertAlmostEqual(e.work_cost, 0.25 * e.work_kwh, places=6)
        self.assertAlmostEqual(r.work_revenue, e.work_cost)

    def test_work_daily_limit(self):
        c = cfg(days=1, work=WorkHubConfig(daily_limit_hours=1.0, charger_kw=3.0))
        _, r = run(c, [("none", SIMPLE_DRIVER)], soc=0.3)
        e = r.ev_results[0]
        self.assertAlmostEqual(e.work_plugged_hours, 1.0)
        self.assertAlmostEqual(e.work_kwh, 3.0)
        self.assertEqual(e.limit_moves, 1)

    def test_move_rule_after_charging_stops(self):
        # 0.79 -> 0.80 takes one step at work, then 60 min idle, then moved
        c = cfg(days=1, work=WorkHubConfig(daily_limit_hours=None))
        sim, r = run(c, [("none", SIMPLE_DRIVER)], soc=0.85)
        e = r.ev_results[0]
        self.assertEqual(e.moves, 1)
        self.assertLess(e.work_plugged_hours, 2.0)

    def test_congestion_waits(self):
        c = cfg(days=1, work=WorkHubConfig(num_chargers=1, daily_limit_hours=None))
        _, r = run(c, [("none", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)], soc=0.3)
        first, second = r.ev_results
        self.assertEqual(first.work_waiting_hours, 0)
        self.assertGreater(second.work_waiting_hours, 0)

    def test_trips_and_buffer_metrics(self):
        # no chargers anywhere, starts below the buffer: every trip ends below it
        c = cfg(days=1, work=WorkHubConfig(num_chargers=0))
        _, r = run(c, [("none", SIMPLE_DRIVER)], soc=0.1)
        e = r.ev_results[0]
        self.assertEqual(e.trips, 2)
        self.assertEqual(e.trips_below_buffer, 2)
        self.assertTrue(e.missed_goal)
        self.assertAlmostEqual(e.hours_below_buffer, 24.0)

    def test_work_bill_covers_whole_run(self):
        _, r = run(cfg(days=2), [("L2", SIMPLE_DRIVER)])
        self.assertEqual(len(r.work_bills), 1)
        self.assertAlmostEqual(r.work_bills[0].hours_covered, 48.0)

    def test_timeline_has_site_prices_and_loads(self):
        _, r = run(cfg(days=1), [("L2", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)], soc=0.3)
        rec = r.timeline[0]
        self.assertEqual(set(rec.prices), {"home", "work"})
        self.assertAlmostEqual(rec.prices["work"], 0.25)
        self.assertGreater(max(x.load_kw_at("home") for x in r.timeline), 0)
        self.assertGreater(max(x.load_kw_at("work") for x in r.timeline), 0)


class TestGreedy(unittest.TestCase):
    def test_allocate_picks_cheapest_earlier_slot(self):
        g = Greedy()
        t = MON
        slots = [_Slot(t, Location.HOME, 0, 10, 0.30, 1), _Slot(t, Location.HOME, 0, 10, 0.10, 1),
                 _Slot(t, Location.DRIVING, 8, 0, math.inf, 0), _Slot(t, Location.HOME, 0, 10, 0.05, 1)]
        g._allocate(slots, start=10, floor=5, cap=40)
        self.assertEqual([s.alloc_kwh for s in slots], [0, 3, 0, 0])   # later slot can't help the dip

    def test_allocate_respects_cap(self):
        g = Greedy()
        t = MON
        slots = [_Slot(t, Location.HOME, 0, 50, 0.10, 1), _Slot(t, Location.HOME, 0, 50, 0.50, 1),
                 _Slot(t, Location.DRIVING, 30, 0, math.inf, 0)]
        g._allocate(slots, start=0, floor=10, cap=25)
        self.assertAlmostEqual(slots[0].alloc_kwh, 25)    # filled to the cap
        self.assertAlmostEqual(slots[1].alloc_kwh, 0)     # can't go above the cap either
        g2 = Greedy()
        slots = [_Slot(t, Location.HOME, 0, 50, 0.10, 1),
                 _Slot(t, Location.DRIVING, 30, 0, math.inf, 0),
                 _Slot(t, Location.HOME, 0, 50, 0.50, 1),
                 _Slot(t, Location.DRIVING, 10, 0, math.inf, 0)]
        g2._allocate(slots, start=0, floor=10, cap=40)
        self.assertAlmostEqual(slots[0].alloc_kwh, 40)
        self.assertAlmostEqual(slots[2].alloc_kwh, 10)

    def test_tops_up_before_a_trip_that_would_dip(self):
        # 25% start: the 5.1 kWh morning commute would end at 19.4%, so it charges at home first
        c = cfg(days=1, work=WorkHubConfig(driver_price_per_kwh=0.05))
        _, r = run(c, [("L2", SIMPLE_DRIVER)], Greedy, soc=0.25)
        e = r.ev_results[0]
        self.assertGreater(e.home_kwh, 0)
        self.assertLess(e.home_kwh, 1.0)
        self.assertEqual(e.trips_below_buffer, 0)

    def test_home_driver_charges_off_peak_only(self):
        _, r = run(cfg(days=5), [("L2", SIMPLE_DRIVER)], Greedy, soc=0.25)
        e = r.ev_results[0]
        self.assertGreater(e.home_kwh, 0)
        self.assertEqual(e.on_peak_kwh, 0)
        self.assertEqual(e.work_kwh, 0)          # home off-peak 0.15 < work 0.25
        self.assertGreaterEqual(e.min_soc, 0.2 - 1e-6)
        self.assertFalse(e.missed_goal)

    def test_cheap_work_wins(self):
        # (start above buffer + morning commute, so nothing is needed before work)
        c = cfg(days=3, work=WorkHubConfig(driver_price_per_kwh=0.05))
        _, r = run(c, [("L2", SIMPLE_DRIVER)], Greedy, soc=0.3)
        e = r.ev_results[0]
        self.assertGreater(e.work_kwh, 0)
        self.assertEqual(e.home_kwh, 0)

    def test_never_above_target(self):
        c = cfg(days=3, work=WorkHubConfig(driver_price_per_kwh=0.0))
        sim, r = run(c, [("none", SIMPLE_DRIVER)], Greedy, soc=0.3, target=0.6)
        self.assertLessEqual(max(s.soc for x in r.timeline for s in x.evs), 0.6 + 1e-9)

    def test_blocked_driver_replans(self):
        # two no-home drivers, one work charger, nearly empty: the second waits,
        # replans, and still gets a charge later in the day
        c = cfg(days=1, work=WorkHubConfig(num_chargers=1, daily_limit_hours=None, charger_kw=11.0))
        g = Greedy()
        _, r = run(c, [("none", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)], lambda: g, soc=0.26)
        first, second = r.ev_results
        self.assertGreater(second.work_waiting_hours, 0)
        self.assertGreater(second.work_kwh, 0)
        self.assertFalse(first.missed_goal)
        self.assertFalse(second.missed_goal)

    def test_needs_commute_sim(self):
        with self.assertRaises(TypeError):
            Greedy().decide(None, MON, 0.1, False)

    def test_infeasible_driver_reports_miss(self):
        # 2 h at work and no home charger can't cover a 100-mile day
        from ev_charging.driver import DriverProfile
        from datetime import time
        far = DriverProfile(time(9), time(11), 50.0, 60)
        c = cfg(days=3, work=WorkHubConfig(charger_kw=3.0))
        _, r = run(c, [("none", far)], Greedy, soc=0.3)
        self.assertTrue(r.ev_results[0].missed_goal)


class TestCommuteDashboard(unittest.TestCase):
    def test_renders(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        from ev_charging.viz import plot_commute_dashboard
        _, r = run(cfg(days=1), [("L2", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)], Greedy, soc=0.3)
        fig = plot_commute_dashboard(r)
        self.assertEqual(len(fig.axes), 5)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- public charging
from ev_charging.config import PublicStationConfig, default_public_stations  # noqa: E402
from ev_charging.itinerary import Itinerary, Visit  # noqa: E402

L2_LOT, DC_FAST = default_public_stations()
NO_WORK = WorkHubConfig(num_chargers=0)


class TestPublicConfig(unittest.TestCase):
    def test_defaults(self):
        self.assertAlmostEqual(CommuteConfig().home.no_home_share, 0.10)
        self.assertEqual(L2_LOT.site_rate, "27")
        self.assertEqual(DC_FAST.site_rate, "EV-L")
        self.assertEqual(DC_FAST.charger_type, "DC")
        self.assertEqual(DC_FAST.customer_class, "large_commercial")
        self.assertEqual(L2_LOT.max_dwell_minutes, 240)

    def test_bad_values(self):
        with self.assertRaises(ValueError):
            PublicStationConfig(kind="L3")
        with self.assertRaises(ValueError):
            CommuteConfig(public=(L2_LOT, L2_LOT))
        with self.assertRaises(ValueError):
            CommuteConfig(public_visit_hours=(22, 6))


class TestItinerary(unittest.TestCase):
    def test_visit_replaces_home_time(self):
        from types import SimpleNamespace
        from datetime import time
        st = SimpleNamespace(detour=timedelta(minutes=10), detour_miles=3.0)
        it = Itinerary(SIMPLE_DRIVER)
        t0 = MON.replace(hour=19)
        it.visits.append(Visit(st, t0, 10.0, t0 + timedelta(hours=1), t0 + timedelta(minutes=40)))
        loc = lambda m: it.location_at(t0 + timedelta(minutes=m))
        self.assertEqual([loc(0), loc(15), loc(45), loc(55)],
                         [Location.DRIVING, Location.PUBLIC, Location.DRIVING, Location.HOME])
        day = it.driving_miles(MON, MON + timedelta(days=1))
        self.assertAlmostEqual(day, 2 * 15 + 2 * 3)          # commute + detour there and back
        self.assertEqual(it.next_home_departure(t0), datetime(2025, 7, 8, 8, 30))
        self.assertEqual(it.next_home_departure(MON.replace(hour=6)), MON.replace(hour=8, minute=30))
        self.assertIs(it.active_visit(t0 + timedelta(minutes=30)), it.visits[0])
        self.assertIsNone(it.active_visit(t0 + timedelta(hours=2)))


class TestPublicCharging(unittest.TestCase):
    def test_always_charge_fills_up_at_dc_fast(self):
        c = cfg(days=1, work=NO_WORK, public=(L2_LOT, DC_FAST))
        sim, r = run(c, [("none", SIMPLE_DRIVER)], soc=0.3)
        e = r.ev_results[0]
        self.assertGreaterEqual(e.public_visits, 1)
        self.assertEqual(set(e.public_kwh_by_kind), {"DCFC"})      # fastest first
        self.assertAlmostEqual(e.public_cost, 0.485 * e.public_kwh, places=6)   # dataset price
        self.assertFalse(e.missed_goal)
        dc = next(s for s in r.stations if s.name == "public-dcfc")
        self.assertAlmostEqual(dc.revenue, e.public_cost)
        self.assertEqual(dc.bills[0].rate, "EV-L")
        self.assertIsNotNone(dc.bills[0].tier)
        self.assertAlmostEqual(dc.bills[0].hours_covered, 24.0)
        # visit started in allowed hours and the car was home before its commute
        v = sim.itinerary["ev-1"].visits[0]
        self.assertGreaterEqual(v.leave.hour, 6)
        self.assertLessEqual(v.back, MON.replace(hour=8, minute=30))

    def test_no_visit_needed_with_home_charger(self):
        c = cfg(days=2, work=NO_WORK, public=(L2_LOT, DC_FAST))
        _, r = run(c, [("L2", SIMPLE_DRIVER)], soc=0.3)
        self.assertEqual(r.ev_results[0].public_visits, 0)

    def test_greedy_picks_cheaper_l2_when_there_is_time(self):
        c = cfg(days=2, work=NO_WORK, public=(L2_LOT, DC_FAST))
        _, r = run(c, [("none", SIMPLE_DRIVER)], Greedy, soc=0.3)
        e = r.ev_results[0]
        self.assertGreater(e.public_kwh, 0)
        self.assertEqual(set(e.public_kwh_by_kind), {"L2"})
        self.assertAlmostEqual(e.public_cost, 0.39 * e.public_kwh, places=6)
        self.assertFalse(e.missed_goal)
        self.assertGreater(e.public_hours, 0)

    def test_greedy_uses_dc_fast_when_l2_is_too_slow(self):
        slow = PublicStationConfig(name="slow-l2", charger_kw=1.0, max_dwell_minutes=30)
        c = cfg(days=2, work=NO_WORK, public=(slow, DC_FAST))
        _, r = run(c, [("none", SIMPLE_DRIVER)], Greedy, soc=0.3)
        e = r.ev_results[0]
        self.assertIn("DCFC", e.public_kwh_by_kind)
        self.assertFalse(e.missed_goal)

    def test_visits_wait_for_allowed_hours(self):
        # nearly empty at midnight: still waits until 06:00 to head out
        c = cfg(days=1, work=NO_WORK, public=(DC_FAST,))
        sim, _ = run(c, [("none", SIMPLE_DRIVER)], soc=0.21)
        self.assertEqual(sim.itinerary["ev-1"].visits[0].leave, MON.replace(hour=6))

    def test_station_queue(self):
        one = PublicStationConfig(name="one-l2", num_chargers=1)
        c = cfg(days=1, work=NO_WORK, public=(one,))
        _, r = run(c, [("none", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)], soc=0.3)
        waits = sorted(e.public_waiting_hours for e in r.ev_results)
        self.assertEqual(waits[0], 0)
        self.assertGreater(waits[1], 0)

    def test_timeline_marks_public(self):
        c = cfg(days=1, work=NO_WORK, public=(L2_LOT, DC_FAST))
        _, r = run(c, [("none", SIMPLE_DRIVER)], soc=0.3)
        self.assertIn("public-dcfc", r.timeline[0].prices)
        self.assertGreater(max(x.load_kw_at("public") for x in r.timeline), 0)


class TestCommuteAnimation(unittest.TestCase):
    def test_saves_gif(self):
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        import tempfile
        from pathlib import Path
        from ev_charging.viz import animate_commute
        c = cfg(days=1, work=WorkHubConfig(num_chargers=1), public=(L2_LOT, DC_FAST))
        _, r = run(c, [("L2", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)], Greedy, soc=0.3)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.gif"
            animate_commute(r, path, every=8, fps=4, dpi=40)
            self.assertGreater(path.stat().st_size, 0)

    def test_targets_cover_every_place(self):
        from ev_charging.viz.commute_animation import _Layout
        c = cfg(days=1, work=NO_WORK, public=(L2_LOT, DC_FAST))
        _, r = run(c, [("none", SIMPLE_DRIVER)], soc=0.3)
        lay = _Layout(r, ["ev-1"])
        places = {(r_.snapshot("ev-1").location, lay.targets(r_)["ev-1"].visible) for r_ in r.timeline}
        self.assertIn(("public", True), places)
        self.assertIn(("driving", True), places)
