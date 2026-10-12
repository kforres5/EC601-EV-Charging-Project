"""Shared colours and helpers for every chart and animation."""
from __future__ import annotations

from datetime import datetime, timedelta

from ..recorder import EVSnapshot, EVState, StepRecord

# Validated categorical palette (light surface). Colour follows the EV, in this
# fixed order; past 8 EVs everything folds to one colour and rows are labelled.
EV_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
             "#e87ba4", "#008300", "#6250d6", "#e34948"]
FOLD_COLOR = EV_COLORS[0]
MAX_COLORED_EVS = len(EV_COLORS)
MAX_DIRECT_LABELS = 4

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
PEAK_BAND = "#f0efec"
FONT = ["Segoe UI", "DejaVu Sans", "Arial", "sans-serif"]


def ev_color(index: int, n_evs: int) -> str:
    return EV_COLORS[index] if n_evs <= MAX_COLORED_EVS else FOLD_COLOR


def rc_params() -> dict:
    return {
        "font.family": "sans-serif",
        "font.sans-serif": FONT,
        "font.size": 9,
        "axes.facecolor": SURFACE,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 10,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": INK_2,
        "ytick.labelcolor": INK_2,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "lines.linewidth": 2,
    }


def step_delta(timeline: list[StepRecord]) -> timedelta:
    if len(timeline) >= 2:
        return timeline[1].time - timeline[0].time
    return timedelta(minutes=15)


def peak_spans(timeline: list[StepRecord]) -> list[tuple[datetime, datetime]]:
    """Merge consecutive on-peak intervals into (start, end) spans.
    The closing snapshot has no interval, so it is left out."""
    spans: list[tuple[datetime, datetime]] = []
    dt = step_delta(timeline)
    start = None
    for rec in timeline[:-1]:
        if rec.on_peak and start is None:
            start = rec.time
        elif not rec.on_peak and start is not None:
            spans.append((start, rec.time))
            start = None
    if start is not None:
        spans.append((start, timeline[-2].time + dt))
    return spans


def soc_or_nan(snap: EVSnapshot) -> float:
    """SOC in %, or NaN before the car arrives so lines start at arrival."""
    return float("nan") if snap.state is EVState.AWAY else snap.soc * 100
