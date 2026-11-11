"""Charts and animations for simulation results.

Kept separate from the core simulation so running a simulation never
requires matplotlib. Everything here reads the result's timeline.
"""
from .animation import animate_hub
from .commute_animation import animate_commute
from .commute_dashboard import plot_commute_dashboard
from .dashboard import plot_dashboard

__all__ = ["plot_dashboard", "plot_commute_dashboard", "animate_hub", "animate_commute"]
