"""Centralized controller (central_controller.py) and CentralizedStrategy."""
import unittest
from datetime import datetime, time, timedelta

from ev_charging.central_controller import CentralController
from ev_charging.commute import CommuteSimulation
from ev_charging.config import CommuteConfig, PublicStationConfig, WorkHubConfig, default_public_stations
from ev_charging.driver import DriverProfile
from ev_charging.ev import EV
from ev_charging.strategies import Greedy
from ev_charging.strategies.centralized import CentralizedStrategy
from tests.helpers import SIMPLE_DRIVER

try:
    import scipy  # noqa: F401
    HAVE_SCIPY = True
except ImportError:
    HAVE_SCIPY = False

MON = datetime(2025, 7, 7)
L2_LOT, DC_FAST = default_public_stations()


def cfg(days=1, **kw) -> CommuteConfig:
    """Flat TOU prices (on-peak 0.35, off-peak 0.15), no delivery, no public stations."""
    return CommuteConfig(start=MON, end=MON + timedelta(days=days), price_csv=None,
                         include_delivery=False, work=kw.pop("work", WorkHubConfig()),
                         public=kw.pop("public", ()), **kw)


def run(c, drivers, soc=0.3, target=0.8, central=True, horizon=48, **ctl):
    sim = CommuteSimulation(c)
    if central:
        controller = CentralController(sim.fleet_view(), horizon_hours=horizon, time_limit=30, **ctl)
        strategy = CentralizedStrategy(controller)
    else:
        controller, strategy = None, Greedy()
    for i, (home, driver) in enumerate(drivers, 1):
        sim.add_driver(EV.from_vehicle(f"ev-{i}", c.vehicle, soc=soc, required_soc=target,
                                       driver=driver, strategy=strategy), home)
    return sim, sim.run(), controller, strategy


@unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
class TestCentralBasics(unittest.TestCase):
    def test_home_driver_charges_off_peak(self):
        _, r, ctl, st = run(cfg(days=2, work=WorkHubConfig(num_chargers=0)), [("L2", SIMPLE_DRIVER)], soc=0.25)
        e = r.ev_results[0]
        self.assertGreater(e.home_kwh, 0)
        self.assertEqual(e.on_peak_kwh, 0)
        self.assertFalse(e.missed_goal)
        self.assertEqual(st.fallback_calls, 0)
        self.assertEqual(ctl.failures, 0)

    def test_cheap_work_wins(self):
        c = cfg(days=2, work=WorkHubConfig(driver_price_per_kwh=0.05))
        _, r, _, _ = run(c, [("L2", SIMPLE_DRIVER)], soc=0.3)
        e = r.ev_results[0]
        self.assertGreater(e.work_kwh, 0)
        self.assertEqual(e.home_kwh, 0)

    def test_never_above_target(self):
        c = cfg(days=2, work=WorkHubConfig(driver_price_per_kwh=0.0))
        _, r, _, _ = run(c, [("none", SIMPLE_DRIVER)], soc=0.3, target=0.6)
        self.assertLessEqual(max(s.soc for x in r.timeline for s in x.evs), 0.6 + 1e-6)

    def test_releases_charger_instead_of_being_moved(self):
        _, r, _, _ = run(cfg(days=1), [("none", SIMPLE_DRIVER)], soc=0.3)
        e = r.ev_results[0]
        self.assertGreater(e.work_kwh, 0)
        self.assertEqual(e.moves + e.limit_moves, 0)
        self.assertEqual(e.releases, 1)

    def test_respects_daily_limit(self):
        c = cfg(days=1, work=WorkHubConfig(daily_limit_hours=1.0, charger_kw=3.0))
        _, r, _, _ = run(c, [("none", SIMPLE_DRIVER)], soc=0.21)
        e = r.ev_results[0]
        self.assertLessEqual(e.work_plugged_hours, 1.0 + 1e-9)
        self.assertEqual(e.limit_moves, 0)       # the plan stopped in time; the rule never had to

    def test_strategy_needs_commute_sim(self):
        with self.assertRaises(TypeError):
            CentralizedStrategy(None).decide(None, MON, 0.1, False)


@unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
class TestCentralCoordination(unittest.TestCase):
    def test_shares_one_work_charger_without_waiting(self):
        # two drivers without home chargers, one work charger: greedy queues, central takes turns
        c = cfg(days=1, work=WorkHubConfig(num_chargers=1, daily_limit_hours=None, charger_kw=11.0))
        drivers = [("none", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)]
        _, central, _, _ = run(c, drivers, soc=0.26)
        _, greedy, _, _ = run(c, drivers, soc=0.26, central=False)
        self.assertGreater(sum(e.work_waiting_hours for e in greedy.ev_results), 0)
        self.assertEqual(sum(e.work_waiting_hours for e in central.ev_results), 0)
        for e in central.ev_results:
            self.assertGreater(e.work_kwh, 0)
            self.assertFalse(e.missed_goal)

    def test_costs_no_more_than_greedy(self):
        c = cfg(days=2, work=WorkHubConfig(num_chargers=1, driver_price_per_kwh=0.10))
        drivers = [("L2", SIMPLE_DRIVER), ("L1", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)]
        _, central, _, _ = run(c, drivers, soc=0.3)
        _, greedy, _, _ = run(c, drivers, soc=0.3, central=False)
        kwh = lambda r: sum(e.energy_kwh for e in r.ev_results)
        self.assertLessEqual(central.total_cost / kwh(central), greedy.total_cost / kwh(greedy) + 1e-6)
        self.assertFalse(any(e.missed_goal for e in central.ev_results))


@unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
class TestCentralPublic(unittest.TestCase):
    NO_WORK = WorkHubConfig(num_chargers=0)

    def test_uses_public_station_within_hours(self):
        c = cfg(days=1, work=self.NO_WORK, public=(L2_LOT, DC_FAST))
        sim, r, _, _ = run(c, [("none", SIMPLE_DRIVER)], soc=0.3)
        e = r.ev_results[0]
        self.assertGreater(e.public_kwh, 0)
        self.assertEqual(set(e.public_kwh_by_kind), {"L2"})       # cheaper, and there's time
        self.assertFalse(e.missed_goal)
        for v in sim.itinerary["ev-1"].visits:
            self.assertGreaterEqual(v.leave.hour, 6)
            self.assertLess(v.leave.hour, 22)

    def test_station_capacity(self):
        one = PublicStationConfig(name="one-l2", num_chargers=1)
        c = cfg(days=1, work=self.NO_WORK, public=(one,))
        _, r, _, _ = run(c, [("none", SIMPLE_DRIVER), ("none", SIMPLE_DRIVER)], soc=0.3)
        self.assertEqual(sum(e.public_waiting_hours for e in r.ev_results), 0)
        for e in r.ev_results:
            self.assertGreater(e.public_kwh, 0)
            self.assertFalse(e.missed_goal)


@unittest.skipUnless(HAVE_SCIPY, "scipy not installed")
class TestCentralPrices(unittest.TestCase):
    def test_only_posted_prices(self):
        """Changing on-peak prices more than a day ahead doesn't change the plan."""
        c = CommuteConfig(start=MON, end=MON + timedelta(days=1), public=(),
                          work=WorkHubConfig(num_chargers=0))
        def plan(bump):
            sim = CommuteSimulation(c, record=False)
            ctl = CentralController(sim.fleet_view(), horizon_hours=96, time_limit=30)
            sim.add_driver(EV.from_vehicle("ev-1", c.vehicle, soc=0.25, required_soc=0.8,
                                           driver=SIMPLE_DRIVER, strategy=CentralizedStrategy(ctl)), "L2")
            if bump:
                util = sim._home_factory.utility
                orig = util.price_at
                util.price_at = lambda t: orig(t) + (5.0 if t.date() > MON.date() + timedelta(days=1)
                                                    and util.is_on_peak(t) else 0.0)
            return ctl.ensure_plan().cars["ev-1"].home
        self.assertEqual(list(plan(False)), list(plan(True)))

    def test_falls_back_to_greedy_without_a_plan(self):
        c = cfg(days=1, work=WorkHubConfig(num_chargers=0))
        sim = CommuteSimulation(c, record=False)
        ctl = CentralController(sim.fleet_view())
        ctl._solve = lambda now, public_for: None    # solver "fails"
        st = CentralizedStrategy(ctl)
        sim.add_driver(EV.from_vehicle("ev-1", c.vehicle, soc=0.25, driver=SIMPLE_DRIVER, strategy=st), "L2")
        r = sim.run()
        self.assertGreater(st.fallback_calls, 0)
        self.assertFalse(r.ev_results[0].missed_goal)


if __name__ == "__main__":
    unittest.main()
