"""Animated view of the charging hub: cars arrive, wait, plug in, charge, and leave.

Layout (left to right):  [ waiting ]  [ charger bays ]  [ charged & left ]
Each car shows its id and a battery bar with its current SOC. A strip at the
bottom draws SOC over time up to the current moment, with on-peak hours shaded.

Each simulation step becomes `substeps` frames so cars glide between places
instead of jumping. Saves to .gif (no extra installs) or .mp4 (needs ffmpeg).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.dates as mdates
from matplotlib.animation import FFMpegWriter, FuncAnimation, PillowWriter
from matplotlib.patches import FancyBboxPatch, Rectangle

from ..metrics import SimulationResult
from ..recorder import EVState, StepRecord
from . import style
from .figures import new_figure, show as show_windows

# scene coordinates (data units of the scene axes)
SCENE_W, SCENE_H = 100.0, 56.0
CAR_W, CAR_H = 9.0, 4.6
WAIT_X = (1.0, 19.0)
BAY_X = (23.0, 77.0)
EXIT_X = (81.0, 99.0)
ZONE_TOP = 49.0
OFFSCREEN_LEFT = -14.0
OFFSCREEN_RIGHT = SCENE_W + 14.0
MAX_STACK = 5
MAX_FRAMES = 2400


@dataclass(frozen=True)
class _Pos:
    x: float
    y: float
    visible: bool = True


def _bay_layout(m: int) -> list[tuple[float, float]]:
    """Centres of the M charger bays, in a grid inside BAY_X."""
    cols = min(m, 4)
    rows = math.ceil(m / cols)
    width = BAY_X[1] - BAY_X[0]
    cell_w = width / cols
    cell_h = min(16.0, (ZONE_TOP - 6) / rows)
    top = (ZONE_TOP + 2) / 2 + cell_h * rows / 2      # centre the grid vertically
    centers = []
    for i in range(m):
        r, c = divmod(i, cols)
        centers.append((BAY_X[0] + cell_w * (c + 0.5), top - cell_h * (r + 0.5)))
    return centers


def _bay_size(m: int) -> tuple[float, float]:
    cols = min(m, 4)
    rows = math.ceil(m / cols)
    w = min(14.0, (BAY_X[1] - BAY_X[0]) / cols - 2)
    h = min(14.0, (ZONE_TOP - 6) / rows - 1.5)
    return w, h


def _stack_slot(zone: tuple[float, float], k: int) -> tuple[float, float]:
    x = (zone[0] + zone[1]) / 2
    return x, ZONE_TOP - 6 - k * 9.0


def _targets(rec: StepRecord, ev_ids: list[str], bays) -> dict[str, _Pos]:
    """Where every car should be during this record's interval."""
    pos: dict[str, _Pos] = {}
    waiting = [s for s in rec.evs if s.state is EVState.WAITING]
    # right-hand zone: cars that left for good (no driver) or are away from the hub (driver)
    right = [s for s in rec.evs if _in_right_zone(s)]
    if not any(s.location for s in right):
        right.reverse()          # driverless runs: latest-listed finisher on top
    for s in rec.evs:
        if s.state in (EVState.CHARGING, EVState.IDLE) and s.charger_id is not None:
            bx, by = bays[s.charger_id]
            pos[s.ev_id] = _Pos(bx, by + 0.2)
        elif s.state is EVState.WAITING:
            k = waiting.index(s)
            if k < MAX_STACK:
                pos[s.ev_id] = _Pos(*_stack_slot(WAIT_X, k))
            else:
                pos[s.ev_id] = _Pos(*_stack_slot(WAIT_X, MAX_STACK - 1), visible=False)
        elif _in_right_zone(s):
            k = right.index(s)
            if k < MAX_STACK:
                pos[s.ev_id] = _Pos(*_stack_slot(EXIT_X, k))
            else:
                pos[s.ev_id] = _Pos(OFFSCREEN_RIGHT, 0, visible=False)
        else:   # away
            pos[s.ev_id] = _Pos(OFFSCREEN_LEFT, ZONE_TOP - 6, visible=False)
    return pos


_AWAY_STATES = (EVState.AWAY, EVState.DRIVING, EVState.PARKED)


def _in_right_zone(s) -> bool:
    return s.state is EVState.DONE or (s.state in _AWAY_STATES and s.location is not None)


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def _lerp(a: _Pos, b: _Pos, t: float) -> _Pos:
    # appear by sliding in from the left; disappear by sliding out to the right
    if not a.visible and b.visible:
        a = _Pos(OFFSCREEN_LEFT, b.y, True)
    if a.visible and not b.visible:
        b = _Pos(OFFSCREEN_RIGHT if b.x >= a.x else a.x, b.y, True)
        e = _ease(t)
        return _Pos(a.x + (b.x - a.x) * e, a.y + (b.y - a.y) * e, t < 1.0)
    if not a.visible and not b.visible:
        return b
    e = _ease(t)
    return _Pos(a.x + (b.x - a.x) * e, a.y + (b.y - a.y) * e, True)


def animate_hub(result: SimulationResult, path: Optional[str | Path] = None, *,
                show: bool = False, fps: int = 12, substeps: int = 3,
                start: Optional[datetime] = None, end: Optional[datetime] = None,
                every: int = 1, dpi: int = 90, interactive: bool = False):
    """Animate a simulation run. Use start/end/every to keep long runs short:
    e.g. every=4 shows one frame-group per hour with 15-minute steps.

    show=True plays it in a window (blocks until closed). interactive=True
    prepares a window but leaves matplotlib.pyplot.show() to you; keep the
    returned object alive until then or the animation stops.
    """
    tl = [r for r in result.timeline
          if (start is None or r.time >= start) and (end is None or r.time <= end)]
    tl = tl[::max(1, every)] + ([tl[-1]] if tl and (len(tl) - 1) % max(1, every) else [])
    if len(tl) < 2:
        raise ValueError("not enough timeline records to animate (record=True? window too small?)")
    n_frames = (len(tl) - 1) * substeps + fps   # + ~1 s hold at the end
    if n_frames > MAX_FRAMES:
        raise ValueError(f"{n_frames} frames is too long; narrow start/end or raise `every`")

    cfg = result.config
    ev_ids = [s.ev_id for s in tl[0].evs]
    has_drivers = any(s.location is not None for r in tl for s in r.evs)
    n = len(ev_ids)
    m = cfg.num_chargers if cfg else 1 + max((s.charger_id or 0) for r in tl for s in r.evs)
    hub_kw = (cfg.num_chargers * cfg.charger_kw) if cfg else None
    colors = {ev: style.ev_color(i, n) for i, ev in enumerate(ev_ids)}
    bays = _bay_layout(m)
    targets = [_targets(r, ev_ids, bays) for r in tl]
    spans = style.peak_spans(result.timeline)
    t0, t1 = tl[0].time, tl[-1].time

    with matplotlib.rc_context(style.rc_params()):
        fig = new_figure(show or interactive, figsize=(11, 7.2))
        ax_head = fig.add_axes([0.02, 0.88, 0.96, 0.10])
        ax = fig.add_axes([0.02, 0.30, 0.96, 0.58])
        ax_soc = fig.add_axes([0.07, 0.07, 0.89, 0.18])
        for a in (ax_head, ax):
            a.set_axis_off()
        ax.set_xlim(0, SCENE_W)
        ax.set_ylim(0, SCENE_H)
        ax.set_aspect("auto")

        # static scene: zones and charger bays
        for (x0, x1), title in ((WAIT_X, "Arriving / waiting"), (BAY_X, f"Chargers ({m})"),
                                (EXIT_X, "Away from chargers" if has_drivers else "Charged & left")):
            ax.add_patch(FancyBboxPatch((x0, 2), x1 - x0, ZONE_TOP - 2 + 3,
                                        boxstyle="round,pad=0,rounding_size=1.5",
                                        fc="#f6f6f3", ec=style.GRID, lw=1, zorder=0))
            ax.text((x0 + x1) / 2, ZONE_TOP + 4.6, title, ha="center", va="center",
                    fontsize=10, fontweight="bold", color=style.INK_2)
        bay_patches, bay_bolts = [], []
        bay_w, bay_h = _bay_size(m)
        for i, (bx, by) in enumerate(bays):
            p = FancyBboxPatch((bx - bay_w / 2, by - bay_h / 2), bay_w, bay_h,
                               boxstyle="round,pad=0,rounding_size=1", fc=style.SURFACE,
                               ec=style.AXIS, lw=1.4, ls=(0, (4, 2)), zorder=1)
            ax.add_patch(p)
            bay_patches.append(p)
            ax.text(bx, by + bay_h / 2 - 1.6, f"Charger {i + 1}", ha="center", va="center",
                    fontsize=8, color=style.MUTED, zorder=2)
            bay_bolts.append(ax.text(bx + bay_w / 2 - 1.4, by + bay_h / 2 - 1.6, "",
                                     ha="center", va="center", fontsize=9,
                                     color=style.INK, fontweight="bold", zorder=2))

        # cars: body, id label, battery bar
        cars = {}
        for ev in ev_ids:
            body = FancyBboxPatch((0, 0), CAR_W, CAR_H, boxstyle="round,pad=0,rounding_size=1.2",
                                  fc=colors[ev], ec=style.SURFACE, lw=1.5, zorder=5)
            label = ax.text(0, 0, ev, ha="center", va="center", fontsize=7.5,
                            color="white", fontweight="bold", zorder=6)
            batt_bg = Rectangle((0, 0), CAR_W, 1.1, fc="white", ec=style.AXIS, lw=0.8, zorder=5)
            batt = Rectangle((0, 0), 0, 1.1, fc=colors[ev], ec="none", zorder=6)
            pct = ax.text(0, 0, "", ha="center", va="top", fontsize=7, color=style.INK_2, zorder=6)
            for art in (body, batt_bg, batt):
                ax.add_patch(art)
            cars[ev] = (body, label, batt_bg, batt, pct)
        more_wait = ax.text(sum(WAIT_X) / 2, 4.5, "", ha="center", fontsize=8, color=style.INK_2)
        more_away = ax.text(sum(EXIT_X) / 2, 4.5, "", ha="center", fontsize=8, color=style.INK_2)

        head_time = ax_head.text(0, 0.62, "", fontsize=15, fontweight="bold",
                                 color=style.INK, va="center")
        head_info = ax_head.text(0, 0.12, "", fontsize=10, color=style.INK_2, va="center")
        head_cost = ax_head.text(1, 0.62, "", fontsize=15, fontweight="bold",
                                 color=style.INK, va="center", ha="right")
        head_cost_sub = ax_head.text(1, 0.12, "total cost so far", fontsize=9,
                                     color=style.MUTED, va="center", ha="right")

        # SOC strip
        for a, b in spans:
            if b >= t0 and a <= t1:
                ax_soc.axvspan(a, b, color=style.PEAK_BAND, lw=0, zorder=0)
        ax_soc.set_xlim(t0, t1)
        ax_soc.set_ylim(0, 105)
        ax_soc.set_title("State of charge (%) · shaded = on-peak", fontsize=9)
        locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
        ax_soc.xaxis.set_major_locator(locator)
        ax_soc.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        soc_lines = {ev: ax_soc.plot([], [], color=colors[ev],
                                     lw=2 if n <= style.MAX_COLORED_EVS else 1,
                                     alpha=1 if n <= style.MAX_COLORED_EVS else 0.6)[0]
                     for ev in ev_ids}
        cursor = ax_soc.axvline(t0, color=style.INK_2, lw=1)
        times = [r.time for r in tl]
        soc_series = {ev: [style.soc_or_nan(r.snapshot(ev)) for r in tl] for ev in ev_ids}

        def draw(frame: int):
            last = len(tl) - 1
            k = min(frame // substeps, last)
            local = (frame - k * substeps) / substeps       # >1 during the end hold
            frac = min(local, 1.0) if k < last else 0.0
            rec = tl[k]
            nxt = tl[min(k + 1, last)]
            now = rec.time + (nxt.time - rec.time) * frac

            prev_t = targets[max(k - 1, 0)]
            cur_t = targets[k]
            move = min(1.0, local * 2.5) if k > 0 else 1.0   # glide early in the step

            for ev in ev_ids:
                body, label, batt_bg, batt, pct = cars[ev]
                p = _lerp(prev_t[ev], cur_t[ev], move)
                snap, snap_next = rec.snapshot(ev), nxt.snapshot(ev)
                soc = snap.soc + (snap_next.soc - snap.soc) * frac
                x0, y0 = p.x - CAR_W / 2, p.y - CAR_H / 2
                body.set_x(x0); body.set_y(y0)
                label.set_position((p.x, p.y))
                batt_bg.set_xy((x0, y0 - 1.7))
                batt.set_xy((x0, y0 - 1.7))
                batt.set_width(CAR_W * soc)
                pct.set_position((p.x, y0 - 1.9))
                if snap.state is EVState.PARKED:
                    where = " · parked"
                elif snap.location and snap.state in _AWAY_STATES:
                    where = f" · {snap.location}"
                else:
                    where = ""
                pct.set_text(f"{soc * 100:.0f}%{where}")
                for art in (body, label, batt_bg, batt, pct):
                    art.set_visible(p.visible)

            charging = {s.charger_id for s in rec.evs if s.state is EVState.CHARGING}
            occupied = {s.charger_id for s in rec.evs if s.state is EVState.IDLE} | charging
            for i, (patch, bolt) in enumerate(zip(bay_patches, bay_bolts)):
                active = i in charging and k < last
                patch.set_edgecolor(style.INK if active else style.AXIS)
                patch.set_linestyle("-" if i in occupied else (0, (4, 2)))
                patch.set_linewidth(2 if active else 1.4)
                bolt.set_text("⚡" if active else "")

            n_wait = sum(s.state is EVState.WAITING for s in rec.evs)
            more_wait.set_text(f"+{n_wait - MAX_STACK} more waiting" if n_wait > MAX_STACK else "")
            n_right = sum(_in_right_zone(s) for s in rec.evs)
            more_away.set_text(f"+{n_right - MAX_STACK} more" if n_right > MAX_STACK else "")
            n_drive = sum(s.state is EVState.DRIVING for s in rec.evs)

            load = rec.hub_load_kw if k < last else 0.0
            cost = sum(s.cost for s in rec.evs) + sum(
                (s2.cost - s.cost) * frac for s, s2 in zip(rec.evs, nxt.evs))
            head_time.set_text(now.strftime("%a %b %d %Y  ·  %H:%M"))
            period = "on-peak" if rec.on_peak else "off-peak"
            cap = f" of {hub_kw:g} kW" if hub_kw else ""
            head_info.set_text(f"${rec.price:.4f}/kWh ({period})   ·   hub load {load:g} kW{cap}"
                               f"   ·   {sum(s.state is EVState.CHARGING for s in rec.evs)} charging, "
                               f"{n_wait} waiting" + (f", {n_drive} driving" if has_drivers else ""))
            head_cost.set_text(f"${cost:,.2f}")

            upto = k + 1
            for ev in ev_ids:
                xs = times[:upto] + ([now] if frac else [])
                series = soc_series[ev]
                ys = series[:upto] + ([series[k] + (series[min(k + 1, last)] - series[k]) * frac]
                                      if frac else [])
                soc_lines[ev].set_data(xs, ys)
            cursor.set_xdata([now, now])
            return []

        anim = FuncAnimation(fig, draw, frames=n_frames, interval=1000 / fps, blit=False)

        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() == ".mp4":
                writer = FFMpegWriter(fps=fps)
            else:
                writer = PillowWriter(fps=fps)
            anim.save(path, writer=writer, dpi=dpi)
        if show:
            show_windows()
    return anim
