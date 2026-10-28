"""Static dashboard: what happened over time in one simulation run.

Panels share one time axis (each panel has a single y-axis):
  1. Price ($/kWh) with on-peak hours shaded
  2. Hub load (kW): total power drawn by all chargers
  3. State of charge (%) per EV
  4. Cumulative cost ($) per EV
  5. Where each car is: waiting / charging / plugged-in idle, per EV
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from ..metrics import SimulationResult
from ..recorder import EVState
from . import style
from .figures import new_figure, show as show_windows


def _shade_peaks(ax, spans) -> None:
    for a, b in spans:
        ax.axvspan(a, b, color=style.PEAK_BAND, zorder=0, lw=0)


def _end_label(ax, x, y, text, color) -> None:
    ax.annotate(text, (x, y), xytext=(6, 0), textcoords="offset points",
                va="center", fontsize=8, color=style.INK_2)
    ax.plot([x], [y], marker="o", ms=4, color=color, zorder=4)


def build_dashboard(result: SimulationResult, interactive: bool = False) -> Figure:
    tl = result.timeline
    if len(tl) < 2:
        raise ValueError("timeline is empty: run Simulation(..., record=True)")

    ev_ids = [s.ev_id for s in tl[0].evs]
    n = len(ev_ids)
    times = [r.time for r in tl]
    spans = style.peak_spans(tl)
    dt = style.step_delta(tl)
    hub_kw = (result.config.num_chargers * result.config.charger_kw) if result.config else None

    with matplotlib.rc_context(style.rc_params()):
        gantt_h = max(1.0, 0.32 * n + 0.6)
        fig = new_figure(interactive, figsize=(11, 9.2 + gantt_h), layout="constrained")
        gs = fig.add_gridspec(5, 1, height_ratios=[1.0, 1.0, 1.3, 1.1, gantt_h])
        axes = [fig.add_subplot(gs[0])]
        axes += [fig.add_subplot(gs[i], sharex=axes[0]) for i in range(1, 5)]
        ax_price, ax_load, ax_soc, ax_cost, ax_gantt = axes

        # headline
        total = result.total_cost
        departures = sum(r.hub_departures for r in result.ev_results)
        if departures:   # commuting drivers: judge each time a car leaves the hub
            ok = departures - sum(r.departures_below_target for r in result.ev_results)
            goal = f"{ok}/{departures} hub departures at target charge"
        else:
            done = sum(r.reached_required_soc for r in result.ev_results)
            goal = f"{done}/{n} reached target charge"
        fig.suptitle(
            f"{n} EV{'s' if n != 1 else ''} · {goal} · total cost ${total:,.2f}",
            x=0.01, ha="left", fontsize=13, fontweight="bold", color=style.INK)

        for ax in axes[:4]:
            _shade_peaks(ax, spans)

        # 1. price
        ax_price.step(times, [r.price for r in tl], where="post", color=style.INK_2, lw=1.6)
        ax_price.set_title("Electricity price ($/kWh)")
        ax_price.set_ylim(bottom=0)
        if spans:
            a, b = spans[0]
            ax_price.text(a + (b - a) / 2, 1.0, "on-peak", transform=ax_price.get_xaxis_transform(),
                          ha="center", va="bottom", fontsize=8, color=style.MUTED)

        # 2. hub load
        load = [r.hub_load_kw for r in tl]
        ax_load.fill_between(times, load, step="post", color=style.EV_COLORS[0], alpha=0.18, lw=0)
        ax_load.step(times, load, where="post", color=style.EV_COLORS[0], lw=2)
        if hub_kw:
            ax_load.axhline(hub_kw, color=style.MUTED, lw=1, ls=(0, (4, 3)))
            ax_load.annotate(f"hub capacity {hub_kw:g} kW", (times[0], hub_kw),
                             xytext=(2, 3), textcoords="offset points",
                             fontsize=8, color=style.INK_2)
            ax_load.set_ylim(0, hub_kw * 1.25)
        ax_load.set_title("Hub load (kW)")

        # 3. SOC  /  4. cumulative cost, one line per EV
        label_lines = n <= style.MAX_DIRECT_LABELS
        soc_ends: dict[str, list] = {}    # rounded end value -> EVs, so equal lines share a label
        cost_ends: dict[str, list] = {}
        for i, ev_id in enumerate(ev_ids):
            c = style.ev_color(i, n)
            soc = [style.soc_or_nan(r.snapshot(ev_id)) for r in tl]
            cost = [r.snapshot(ev_id).cost for r in tl]
            lw = 2 if n <= style.MAX_COLORED_EVS else 1.2
            alpha = 1 if n <= style.MAX_COLORED_EVS else 0.55
            ax_soc.plot(times, soc, color=c, lw=lw, alpha=alpha, label=ev_id)
            ax_cost.plot(times, cost, color=c, lw=lw, alpha=alpha, label=ev_id)
            if label_lines:
                if soc[-1] == soc[-1]:   # skip NaN (car never arrived)
                    soc_ends.setdefault(f"{soc[-1]:.0f}%", []).append((ev_id, soc[-1], c))
                cost_ends.setdefault(f"${cost[-1]:.2f}", []).append((ev_id, cost[-1], c))
        for ax, ends in ((ax_soc, soc_ends), (ax_cost, cost_ends)):
            for text, evs in ends.items():
                names = ", ".join(e for e, _, _ in evs)
                _end_label(ax, times[-1], evs[0][1], f"{names} {text}", evs[0][2])
        ax_soc.set_ylim(0, 105)
        ax_soc.set_title("State of charge (%)")
        ax_cost.set_ylim(bottom=0)
        ax_cost.set_title("Cumulative charging cost ($)")
        if 2 <= n <= style.MAX_COLORED_EVS:
            ax_soc.legend(loc="upper left", ncols=min(n, 8))
        elif n > style.MAX_COLORED_EVS:
            ax_soc.text(0.01, 0.97, f"each line = one EV ({n} total)",
                        transform=ax_soc.transAxes, va="top", fontsize=8, color=style.INK_2)

        # 5. where each car is
        for i, ev_id in enumerate(ev_ids):
            c = style.ev_color(i, n)
            y = n - 1 - i
            runs = _state_runs(tl, ev_id, dt)
            for state, start, end, charger in runs:
                width = end - start
                if state is EVState.CHARGING:
                    ax_gantt.broken_barh([(start, width)], (y - 0.34, 0.68),
                                         facecolors=c, edgecolors=style.SURFACE, lw=1)
                    if charger is not None:
                        mid = start + width / 2
                        ax_gantt.text(mid, y, f"C{charger + 1}", ha="center", va="center",
                                      fontsize=7, color="white", fontweight="bold",
                                      clip_on=True)
                elif state is EVState.IDLE:
                    ax_gantt.broken_barh([(start, width)], (y - 0.34, 0.68),
                                         facecolors=c, alpha=0.3, edgecolors=c, lw=1,
                                         hatch="////")
                elif state is EVState.WAITING:
                    ax_gantt.broken_barh([(start, width)], (y - 0.2, 0.4),
                                         facecolors="none", edgecolors=c, lw=1.2,
                                         linestyle=(0, (3, 2)))
                elif state is EVState.DRIVING:
                    ax_gantt.broken_barh([(start, width)], (y - 0.06, 0.12),
                                         facecolors=c, edgecolors="none")
                elif state is EVState.PARKED:
                    ax_gantt.broken_barh([(start, width)], (y - 0.06, 0.12),
                                         facecolors="none", edgecolors=c, lw=1,
                                         linestyle=(0, (1, 1.5)))
        ax_gantt.set_yticks(range(n), list(reversed(ev_ids)))
        ax_gantt.set_ylim(-0.7, n - 0.3)
        ax_gantt.grid(False)
        ax_gantt.set_title("Where each car is")
        legend = [
            Patch(facecolor=style.MUTED, label="charging (C# = charger)"),
            Patch(facecolor=style.MUTED, alpha=0.3, hatch="////", edgecolor=style.MUTED,
                  label="plugged in, not charging"),
            Patch(facecolor="none", edgecolor=style.MUTED, linestyle="--", label="waiting for a charger"),
        ]
        if any(s.state is EVState.DRIVING for r in tl for s in r.evs):
            legend.append(Line2D([], [], color=style.MUTED, lw=3, label="driving"))
        if any(s.state is EVState.PARKED for r in tl for s in r.evs):
            legend.append(Patch(facecolor="none", edgecolor=style.MUTED, linestyle=":",
                                label="moved off charger"))
        legend.append(Patch(facecolor=style.PEAK_BAND, label="on-peak hours"))
        fig.legend(handles=legend, loc="outside lower center", ncols=len(legend), fontsize=8)

        # shared time axis
        locator = mdates.AutoDateLocator(minticks=5, maxticks=12)
        ax_gantt.xaxis.set_major_locator(locator)
        ax_gantt.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        for ax in axes[:4]:
            ax.tick_params(labelbottom=False)
        ax_gantt.set_xlim(times[0], times[-1] + dt * 0.5)
    return fig


def _state_runs(tl, ev_id, dt):
    """Collapse per-step states into (state, start, end, charger_id) runs."""
    runs = []
    for rec in tl[:-1]:
        s = rec.snapshot(ev_id)
        if runs and runs[-1][0] is s.state and runs[-1][3] == s.charger_id:
            runs[-1][2] = rec.time + dt
        else:
            runs.append([s.state, rec.time, rec.time + dt, s.charger_id])
    return [tuple(r) for r in runs]


def plot_dashboard(result: SimulationResult, path: Optional[str | Path] = None,
                   show: bool = False, dpi: int = 130, interactive: bool = False) -> Figure:
    """Build the dashboard; save it to `path` (PNG/SVG/PDF) and/or open a window.

    show=True opens the window right away (blocks until closed).
    interactive=True makes a window-ready figure but leaves calling
    matplotlib.pyplot.show() to you, so several windows can open together.
    """
    fig = build_dashboard(result, interactive=show or interactive)
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi)
    if show:
        show_windows()
    return fig
