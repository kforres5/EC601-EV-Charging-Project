"""Driver model: where a driver (and so their EV) is at any moment, and how much
energy their driving uses.

For now every driver follows one constant weekday schedule:

    home --(commute)--> work [work_start .. work_end] --(commute)--> home

The morning commute ends exactly at work_start and the evening commute starts
exactly at work_end. On non-work days the car stays home all day. Driving drains
the battery evenly over each trip (commute_miles * kwh_per_mile per trip).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum


class Location(str, Enum):
    HOME = "home"
    WORK = "work"
    DRIVING = "driving"


@dataclass(frozen=True)
class DriverProfile:
    work_start: time = time(9, 0)
    work_end: time = time(17, 0)
    commute_miles: float = 15.0          # one way
    commute_minutes: int = 30            # one way
    kwh_per_mile: float = 0.30
    work_days: tuple[int, ...] = (0, 1, 2, 3, 4)   # Mon=0 .. Sun=6

    def __post_init__(self) -> None:
        if self.work_start >= self.work_end:
            raise ValueError("work_start must be before work_end")
        if self.commute_minutes <= 0:
            raise ValueError("commute_minutes must be positive")
        if self.commute_miles < 0 or self.kwh_per_mile <= 0:
            raise ValueError("commute_miles must be >= 0 and kwh_per_mile > 0")
        if not set(self.work_days) <= set(range(7)):
            raise ValueError("work_days must be weekday numbers 0 (Mon) to 6 (Sun)")
        # keep both commutes inside the same calendar day
        day = date(2000, 1, 3)
        leave = datetime.combine(day, self.work_start) - self._commute
        back = datetime.combine(day, self.work_end) + self._commute
        if leave.date() != day or back > datetime.combine(day, time()) + timedelta(days=1):
            raise ValueError("commutes must start and end on the same day")

    # ------------------------------------------------------------- basics
    @property
    def _commute(self) -> timedelta:
        return timedelta(minutes=self.commute_minutes)

    @property
    def trip_kwh(self) -> float:
        """Energy used by one one-way commute."""
        return self.commute_miles * self.kwh_per_mile

    def works_on(self, d: date) -> bool:
        return d.weekday() in self.work_days

    def daily_kwh(self, d: date) -> float:
        return 2 * self.trip_kwh if self.works_on(d) else 0.0

    # ----------------------------------------------------------- schedule
    def segments(self, d: date) -> list[tuple[datetime, datetime, Location]]:
        """The whole day d as consecutive (start, end, location) pieces."""
        midnight = datetime.combine(d, time())
        next_midnight = midnight + timedelta(days=1)
        if not self.works_on(d):
            return [(midnight, next_midnight, Location.HOME)]
        arrive_work = datetime.combine(d, self.work_start)
        leave_work = datetime.combine(d, self.work_end)
        leave_home = arrive_work - self._commute
        arrive_home = leave_work + self._commute
        pieces = [
            (midnight, leave_home, Location.HOME),
            (leave_home, arrive_work, Location.DRIVING),
            (arrive_work, leave_work, Location.WORK),
            (leave_work, arrive_home, Location.DRIVING),
            (arrive_home, next_midnight, Location.HOME),
        ]
        return [p for p in pieces if p[1] > p[0]]

    def location_at(self, t: datetime) -> Location:
        for start, end, loc in self.segments(t.date()):
            if start <= t < end:
                return loc
        return Location.HOME   # unreachable; segments cover the whole day

    def _overlaps(self, start: datetime, end: datetime):
        """Yield (seconds of overlap, location) for every piece touching [start, end)."""
        d = start.date()
        while datetime.combine(d, time()) < end:
            for s, e, loc in self.segments(d):
                overlap = (min(e, end) - max(s, start)).total_seconds()
                if overlap > 0:
                    yield overlap, loc, (e - s).total_seconds()
            d += timedelta(days=1)

    def fraction_at(self, location: Location, start: datetime, end: datetime) -> float:
        """Share of the interval [start, end) spent at `location` (0..1)."""
        total = (end - start).total_seconds()
        if total <= 0:
            return 0.0
        return sum(o for o, loc, _ in self._overlaps(start, end) if loc is location) / total

    def driving_kwh(self, start: datetime, end: datetime) -> float:
        """Energy used by driving during [start, end)."""
        return sum(self.trip_kwh * o / length
                   for o, loc, length in self._overlaps(start, end)
                   if loc is Location.DRIVING)
