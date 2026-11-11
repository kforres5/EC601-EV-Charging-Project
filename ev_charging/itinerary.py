"""A driver's day plus any detours to public charging stations.

DriverProfile (driver.py) is the fixed weekday routine. An Itinerary adds Visits
on top of it: while the car is at home, the driver can drive to a public
station, charge, and drive back:

    home --(detour)--> station [arrive .. depart] --(detour)--> home

A visit must fit inside a stretch at home: the driver has to be back before
the routine says they leave home again (CommuteSimulation checks this when it
books the visit). So a visit only ever replaces "home" time and never moves
the commute.

The car leaves the station once it has added visit.target_kwh, or at
visit.latest_depart, whichever comes first. Until it leaves, the itinerary
assumes it stays until `planned_depart` (an estimate the simulation extends
while the car is still charging or waiting).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Iterator, Optional

from .driver import DriverProfile, Location

if TYPE_CHECKING:
    from .sites import Site

_LOOKAHEAD_DAYS = 8


@dataclass
class Visit:
    station: "Site"
    leave: datetime                 # leaves home
    target_kwh: float               # battery-side kWh to add at the station
    latest_depart: datetime         # must leave the station by this time
    planned_depart: datetime        # current estimate of when it leaves the station
    depart: Optional[datetime] = None   # set when it actually leaves
    charged_kwh: float = 0.0
    waited_hours: float = 0.0

    @property
    def arrive(self) -> datetime:
        return self.leave + self.station.detour

    @property
    def end_of_stay(self) -> datetime:
        return self.depart if self.depart is not None else self.planned_depart

    @property
    def back(self) -> datetime:
        return self.end_of_stay + self.station.detour

    def pieces(self) -> list[tuple[datetime, datetime, Location, float]]:
        """(start, end, location, miles) for the trip out, the stay and the trip back."""
        return [(self.leave, self.arrive, Location.DRIVING, self.station.detour_miles),
                (self.arrive, self.end_of_stay, Location.PUBLIC, 0.0),
                (self.end_of_stay, self.back, Location.DRIVING, self.station.detour_miles)]


class Itinerary:
    def __init__(self, driver: DriverProfile) -> None:
        self.driver = driver
        self.visits: list[Visit] = []

    # -------------------------------------------------------------- pieces
    def _base(self, start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime, Location, float]]:
        """The routine's pieces touching [start, end), with miles per piece."""
        d = start.date()
        while datetime.combine(d, time()) < end:
            for s, e, loc in self.driver.segments(d):
                if e > start and s < end:
                    yield s, e, loc, (self.driver.trip_miles if loc is Location.DRIVING else 0.0)
            d += timedelta(days=1)

    def pieces(self, start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime, Location, float, float]]:
        """(start, end, location, miles, full_seconds) for everything touching
        [start, end). `miles` belongs to the whole piece, which lasts full_seconds
        (pieces may be clipped)."""
        for piece in self._all_pieces(start, end):
            if piece[1] > start and piece[0] < end:
                yield piece

    def _all_pieces(self, start: datetime, end: datetime):
        visit_pieces = [p for v in self.visits if v.back > start and v.leave < end
                        for p in v.pieces() if p[1] > p[0]]
        for s, e, loc, miles in self._base(start, end):
            full = (e - s).total_seconds()
            if loc is not Location.HOME or not visit_pieces:
                yield s, e, loc, miles, full
                continue
            cursor = s
            for vs, ve, vloc, vmiles in sorted(visit_pieces):
                if ve <= s or vs >= e:
                    continue
                if vs > cursor:
                    yield cursor, vs, Location.HOME, 0.0, full
                yield max(vs, s), min(ve, e), vloc, vmiles, (ve - vs).total_seconds()
                cursor = max(cursor, min(ve, e))
            if cursor < e:
                yield cursor, e, Location.HOME, 0.0, full

    # -------------------------------------------------------------- queries
    def location_at(self, t: datetime) -> Location:
        for s, e, loc, _, _ in self.pieces(t, t + timedelta(seconds=1)):
            if s <= t < e:
                return loc
        return self.driver.location_at(t)

    def fraction_at(self, location: Location, start: datetime, end: datetime) -> float:
        total = (end - start).total_seconds()
        if total <= 0:
            return 0.0
        inside = sum((min(e, end) - max(s, start)).total_seconds()
                     for s, e, loc, _, _ in self.pieces(start, end) if loc is location)
        return max(0.0, inside) / total

    def driving_miles(self, start: datetime, end: datetime) -> float:
        out = 0.0
        for s, e, loc, miles, full in self.pieces(start, end):
            if loc is Location.DRIVING and full > 0:
                out += miles * (min(e, end) - max(s, start)).total_seconds() / full
        return out

    def active_visit(self, t: datetime) -> Optional[Visit]:
        """The visit the car is on at t (driving there, at the station, or driving back)."""
        return next((v for v in self.visits if v.leave <= t < v.back), None)

    def next_home_departure(self, t: datetime) -> datetime:
        """When the routine next takes the car away from home, after t."""
        horizon = t + timedelta(days=_LOOKAHEAD_DAYS)
        for s, e, loc, _ in self._base(t, horizon):
            if loc is not Location.HOME and s >= t:
                return s
        return horizon

    def prune(self, before: datetime) -> None:
        """Forget visits that ended before `before` (keeps lookups fast)."""
        self.visits = [v for v in self.visits if v.back >= before]

    def works_on(self, d: date) -> bool:
        return self.driver.works_on(d)
