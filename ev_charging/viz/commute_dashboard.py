"""Dashboard for CommuteSimulation (home, work and public charging).

Panels share one time axis:
  1. Price drivers pay ($/kWh): home (pass-through), work (flat fee), public stations
  2. Load (kW): all home chargers together, the work hub, all public stations
  3. State of charge (%) per EV, with the charge-goal buffer
  4. Cumulative charging cost ($) per EV
  5. Where each car charges: home (solid) / work (striped) / public (crossed),
     waiting, driving
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from ..recorder import EVState
from . import style
from .dashboard import _end_labels, _shade_peaks
from .figures import new_figure, show as show_windows


def _runs(tl, ev_id, dt):
    """(state, location, start, end) runs over the timeline."""
    runs = []
    for rec in tl[:-1]:
        s = rec.snapshot(ev_id)
        key = (s.state, s.location)
        if runs and runs[-1][0] == key:
            runs[-1][2] = rec.time + dt
        else:
            runs.append([key, rec.time, rec.time + dt])
    return [(k[0], k[1], a, b) for k, a, b in runs]


def build_commute_dashboard(result, interactive: bool = False, title: Optional[str] = None) -> Figure:
    tl = result.timeline
    if len(tl) < 2:
        raise ValueError("timeline is empty: run CommuteSimulation(..., record=True)")
    cfg = result.config
    homes = {r.ev_id: r.home_charger for r in result.ev_results}
    ev_ids = [s.ev_id for s in tl[0].evs]
    n = len(ev_ids)
    times = [r.time for r in tl]
    spans = style.peak_spans(tl)
    dt = style.step_delta(tl)
    work_cap = cfg.work.num_chargers * cfg.work.charger_kw

    with matplotlib.rc_context(style.rc_params()):
        gantt_h = max(1.2, 0.34 * n + 0.6)
        fig = new_figure(interactive, figsize=(11, 9.4 + gantt_h), layout="constrained")
        gs = fig.add_gridspec(5, 1, height_ratios=[0.9, 1.0, 1.3, 1.1, gantt_h])
        axes = [fig.add_subplot(gs[0])]
        axes += [fig.add_subplot(gs[i], sharex=axes[0]) for i in range(1, 5)]
        ax_price, ax_load, ax_soc, ax_cost, ax_gantt = axes

        trips = sum(r.trips for r in result.ev_results)
        low = sum(r.trips_below_buffer for r in result.ev_results)
        head = title or f"{result.strategy}"
        fig.suptitle(
            f"{head} · {n} driver{'s' if n != 1 else ''} · {trips - low}/{trips} trips ended above "
            f"the {cfg.soc_buffer:.0%} buffer · drivers paid ${result.total_cost:,.2f}",
            x=0.01, ha="left", fontsize=13, fontweight="bold", color=style.INK)

        for ax in axes[:4]:
            _shade_peaks(ax, spans)

        # 1. prices
        series = {"home": ([r.prices["home"] for r in tl], 1.8, "-"),
                  "work": ([r.prices["work"] for r in tl], 1.4, (0, (4, 2)))}
        for st in cfg.public:
            series[st.name] = ([r.prices[st.name] for r in tl], 1.2, (0, (1, 1.5)))
        ends = []
        for label, (px, lw, ls) in series.items():
            ax_price.step(times, px, where="post", color=style.INK_2, lw=lw, ls=ls)
            ends.append((px[-1], label, style.INK_2))
        last = None
        for y, label, c in sorted(ends):     # direct labels, nudged apart
            y_text = y if last is None else max(y, last + 0.035)
            ax_price.annotate(label, (times[-1], y_text), xytext=(4, 0), textcoords="offset points",
                              va="center", fontsize=8, color=c, annotation_clip=False)
            last = y_text
        top = max(max(px) for px, _, _ in series.values())
        ax_price.set_ylim(0, top * 1.2)
        ax_price.set_title("Price drivers pay ($/kWh): home = supply + delivery, work = flat fee, "
                           "public = posted price")

        # 2. load
        home_kw = [r.load_kw_at("home") for r in tl]
        work_kw = [r.load_kw_at("work") for r in tl]
        public_kw = [r.load_kw_at("public") for r in tl]
        ax_load.fill_between(times, home_kw, step="post", color=style.INK_2, alpha=0.14, lw=0)
        ax_load.step(times, home_kw, where="post", color=style.INK_2, lw=1.6, label="all home chargers")
        ax_load.step(times, work_kw, where="post", color=style.INK, lw=1.4, ls=(0, (4, 2)),
                     label="work hub")
        if cfg.public:
            ax_load.step(times, public_kw, where="post", color=style.MUTED, lw=1.2, ls=(0, (1, 1.5)),
                         label="public stations")
        if work_cap:
            ax_load.axhline(work_cap, color=style.MUTED, lw=0.8, ls=":")
            ax_load.annotate(f"work hub capacity {work_cap:g} kW", (times[0], work_cap),
                             xytext=(2, 3), textcoords="offset points", fontsize=8, color=style.MUTED)
        ax_load.set_ylim(0, max(home_kw + work_kw + public_kw + [work_cap]) * 1.25 or 1)
        ax_load.legend(loc="upper right", ncols=3)
        ax_load.set_title("Load (kW)")

        # 3. SOC / 4. cost
        label_lines = n <= style.MAX_DIRECT_LABELS
        soc_items, cost_items = [], []
        for i, ev_id in enumerate(ev_ids):
            c = style.ev_color(i, n)
            soc = [r.snapshot(ev_id).soc * 100 for r in tl]
            cost = [r.snapshot(ev_id).cost for r in tl]
            lw = 2 if n <= style.MAX_COLORED_EVS else 1.2
            alpha = 1 if n <= style.MAX_COLORED_EVS else 0.55
            ax_soc.plot(times, soc, color=c, lw=lw, alpha=alpha, label=ev_id)
            ax_cost.plot(times, cost, color=c, lw=lw, alpha=alpha)
            if label_lines:
                soc_items.append((soc[-1], f"{ev_id} {soc[-1]:.0f}%", c))
                cost_items.append((cost[-1], f"{ev_id} ${cost[-1]:.2f}", c))
        max_cost = max([r.cost for r in result.ev_results] + [1e-9])
        _end_labels(ax_soc, times[-1], soc_items, 9.0)
        _end_labels(ax_cost, times[-1], cost_items, 0.09 * max_cost)
        ax_soc.axhline(cfg.soc_buffer * 100, color=style.MUTED, lw=1, ls=(0, (4, 3)))
        ax_soc.annotate(f"buffer {cfg.soc_buffer:.0%}", (times[0], cfg.soc_buffer * 100),
                        xytext=(2, -10), textcoords="offset points", fontsize=8, color=style.INK_2)
        ax_soc.set_ylim(0, 105)
        ax_soc.set_title("State of charge (%)")
        if 2 <= n <= style.MAX_COLORED_EVS:
            ax_soc.legend(loc="upper left", ncols=min(n, 8))
        ax_cost.set_ylim(bottom=0)
        ax_cost.set_title("Cumulative charging cost ($)")

        # 5. where each car charges
        for i, ev_id in enumerate(ev_ids):
            c = style.ev_color(i, n)
            y = n - 1 - i
            for state, loc, a, b in _runs(tl, ev_id, dt):
                w = b - a
                if loc == "work" and state is not EVState.DRIVING:
                    ax_gantt.broken_barh([(a, w)], (y - 0.42, 0.84), facecolors=style.PEAK_BAND,
                                         edgecolors="none", zorder=0)
                if state is EVState.CHARGING and loc == "home":
                    ax_gantt.broken_barh([(a, w)], (y - 0.32, 0.64), facecolors=c,
                                         edgecolors="none", zorder=2)
                elif state is EVState.CHARGING and loc == "public":
                    ax_gantt.broken_barh([(a, w)], (y - 0.32, 0.64), facecolors=c,
                                         edgecolors="white", hatch="xxx", lw=0, zorder=2)
                elif state is EVState.CHARGING:
                    ax_gantt.broken_barh([(a, w)], (y - 0.32, 0.64), facecolors=c,
                                         edgecolors="white", hatch="////", lw=0, zorder=2)
                elif state is EVState.IDLE and loc == "work":
                    ax_gantt.broken_barh([(a, w)], (y - 0.32, 0.64), facecolors=c, alpha=0.25,
                                         edgecolors="none", zorder=2)
                elif state is EVState.WAITING:
                    ax_gantt.broken_barh([(a, w)], (y - 0.2, 0.4), facecolors="none", edgecolors=c,
                                         lw=1.2, linestyle=(0, (3, 2)), zorder=2)
                elif state is EVState.DRIVING:
                    ax_gantt.broken_barh([(a, w)], (y - 0.06, 0.12), facecolors=c,
                                         edgecolors="none", zorder=2)
        ax_gantt.set_yticks(range(n), [f"{e} ({homes[e]} home)" if homes[e] != "none"
                                       else f"{e} (no home)" for e in reversed(ev_ids)])
        ax_gantt.set_ylim(-0.7, n - 0.3)
        ax_gantt.grid(False)
        ax_gantt.set_title("Where each car charges")
        legend = [
            Patch(facecolor=style.MUTED, label="charging at home"),
            Patch(facecolor=style.MUTED, hatch="////", edgecolor="white", label="charging at work"),
            Patch(facecolor=style.MUTED, hatch="xxx", edgecolor="white", label="charging at a public station"),
            Patch(facecolor=style.MUTED, alpha=0.25, label="plugged in at work, not charging"),
            Patch(facecolor="none", edgecolor=style.MUTED, linestyle="--", label="waiting for a charger"),
            Line2D([], [], color=style.MUTED, lw=3, label="driving"),
            Patch(facecolor=style.PEAK_BAND, label="at work / on-peak hours (top panels)"),
        ]
        fig.legend(handles=legend, loc="outside lower center", ncols=4, fontsize=8)

        locator = mdates.AutoDateLocator(minticks=5, maxticks=12)
        ax_gantt.xaxis.set_major_locator(locator)
        ax_gantt.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        for ax in axes[:4]:
            ax.tick_params(labelbottom=False)
        ax_gantt.set_xlim(times[0], times[-1] + dt * 0.5)
    return fig


def plot_commute_dashboard(result, path: Optional[str | Path] = None, show: bool = False,
                           dpi: int = 130, interactive: bool = False,
                           title: Optional[str] = None) -> Figure:
    fig = build_commute_dashboard(result, interactive=show or interactive, title=title)
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi)
    if show:
        show_windows()
    return fig
