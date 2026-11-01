"""Shared test settings. `simple_cfg` pins round numbers (60 kWh battery,
0.30 kWh/mile, 9-17 schedule with a 15 mi / 30 min commute, no delivery
charges) so tests can check the arithmetic by hand, independent of the
data-driven defaults (Honda Prologue, NHTS schedule, Eversource delivery)."""
from datetime import time

from ev_charging.config import ScenarioConfig
from ev_charging.driver import DriverProfile

SIMPLE_DRIVER = DriverProfile(work_start=time(9), work_end=time(17),
                              commute_miles=15.0, commute_minutes=30)


def simple_cfg(**overrides) -> ScenarioConfig:
    kw = dict(battery_kwh=60.0, kwh_per_mile=0.30, include_delivery=False, driver=SIMPLE_DRIVER)
    kw.update(overrides)
    return ScenarioConfig(**kw)
