"""Charts and animations for simulation results.

Kept separate from the core simulation so running a simulation never
requires matplotlib. Everything here reads SimulationResult.timeline.
"""
from .animation import animate_hub
from .dashboard import plot_dashboard

__all__ = ["plot_dashboard", "animate_hub"]
