"""SimClock: single source of truth for simulated time."""
from __future__ import annotations

from datetime import datetime, timedelta


class SimClock:
    def __init__(self, start: datetime, end: datetime, step_minutes: int) -> None:
        self.start = start
        self.end = end
        self.step = timedelta(minutes=step_minutes)
        self._now = start

    @property
    def now(self) -> datetime:
        return self._now

    @property
    def step_hours(self) -> float:
        return self.step.total_seconds() / 3600.0

    @property
    def done(self) -> bool:
        return self._now >= self.end

    def advance(self) -> datetime:
        self._now += self.step
        return self._now

    def reset(self) -> None:
        self._now = self.start
