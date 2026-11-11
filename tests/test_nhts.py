from datetime import time

from ev_charging.driver import DriverProfile
from ev_charging.nhts import NEW_ENGLAND, load_commuters, median_profile, sample_driver_profiles


def test_commuters_load_and_are_valid():
    cs = load_commuters()
    assert len(cs) > 1000
    assert all(isinstance(c.profile, DriverProfile) and c.weight > 0 for c in cs)
    assert 50 < len(load_commuters(region=NEW_ENGLAND)) < len(cs)


def test_defaults_match_nhts_medians():
    m, d = median_profile(), DriverProfile()
    assert (m.work_start, m.work_end, m.commute_minutes) == (d.work_start, d.work_end, d.commute_minutes)
    assert abs(m.commute_miles - d.commute_miles) < 0.5
    assert d.work_start == time(7, 45) and d.work_end == time(16, 30)


def test_sampling_is_repeatable_and_varied():
    a = sample_driver_profiles(20, seed=3)
    assert a == sample_driver_profiles(20, seed=3)
    assert len({p.work_start for p in a}) > 1
    assert all(p.work_days == (0, 1, 2, 3, 4) for p in a)
