"""Strategy interface. The decentralized RL, centralized, and random strategies
each implement decide(); Simulation never special-cases them."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class Strategy(ABC):
    @abstractmethod
    def decide(self, ev, now: datetime, price: float, is_on_peak: bool) -> bool:
        """True = charge during this timestep, False = wait."""


class AlwaysCharge(Strategy):
    """Placeholder: charge every step while plugged in."""

    def decide(self, ev, now, price, is_on_peak) -> bool:
        return True
