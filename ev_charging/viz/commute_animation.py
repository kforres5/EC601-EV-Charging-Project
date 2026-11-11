"""Animated view of a CommuteSimulation run: home, the road, work, public stations.

Layout (left to right):
    [ Home ]  [ On the road ]  [ Work: chargers + lot ]  [ Public: L2 lot, DC fast ]

Every car has its own spot at home (labelled with its home charger, or "street
parking"). Cars glide between zones as their drivers commute or detour to a
public station; each car shows its SOC (number and bar), with a bolt while it
charges. Work and public chargers light up while in use. The header shows
the time, what drivers pay at each site, and the total spent so far; a strip
at the bottom draws SOC over time with the charge-goal buffer.

Saves to .gif (no extra installs) or .mp4 (needs ffmpeg).
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

from ..recorder import EVState, StepRecord
from . import style
from .figures import new_figure, show as show_windows

SCENE_W, SCENE_H = 100.0, 60.0
ZONE_TOP = 53.0
HOME_X = (1.0, 25.0)
ROAD_X = (27.0, 39.0)
WORK_X = (41.0, 71.0)
PUBLIC_X = (73.0, 99.0)
CAR_W, CAR_H = 8.6, 4.2
MAX_FRAMES = 2400
MAX_CARS = 16


@dataclass(frozen=True)
class _Pos:
    x: float
    y: float
    visible: bool = True


def _grid(x0: float, x1: float, top: float, bottom: float, n: int, cols: int):
    """Centres of n cells in a grid filling [x0, x1] x [bottom, top], row by row."""
    cols = max(1, min(cols, n)) if n else 1
    rows = max(1, math.ceil(n / cols))
    cw, rh = (x1 - x0) / cols, (top - bottom) / rows
    return [(x0 + cw * (c + 0.5), top - rh * (r + 0.5))
            for r, c in (divmod(i, cols) for i in range(n))], rh


def _auto_every(steps: int, substeps: int, target: int = 720) -> int:
    return max(1, math.ceil(steps * substeps / target))


class _Layout:
    def __init__(self, result, ev_ids: list[str]) -> None:
        cfg = result.config
        n = len(ev_ids)
        self.home, self.home_row = _grid(*HOME_X, ZONE_TOP - 1, 3, n, 2)
        self.home = dict(zip(ev_ids, self.home))
        m = cfg.work.num_chargers
        self.work_bays, self.work_bay_h = _grid(*WORK_X, ZONE_TOP - 1, ZONE_TOP - 1 - 9.5 * math.ceil(m / 3),
                                                m, 3) if m else ([], 0)
        lot_top = ZONE_TOP - 3 - 9.5 * math.ceil(m / 3) if m else ZONE_TOP - 3
        self.work_lot, _ = _grid(WORK_X[0], WORK_X[1], lot_top, 3, 12, 3)
        self.stations = [p.name for p in cfg.public]
        self.station_bays: dict[str, list] = {}
        self.station_wait: dict[str, list] = {}
        self.station_box: dict[str, tuple] = {}
        k = max(1, len(cfg.public))
        h = (ZONE_TOP - 3) / k
        for i, p in enumerate(cfg.public):
            top = ZONE_TOP - 1 - h * i
            bays, _ = _grid(PUBLIC_X[0], PUBLIC_X[1], top - 2.5, top - 2.5 - 8.5, p.num_chargers, 3)
            wait, _ = _grid(PUBLIC_X[0], PUBLIC_X[1], top - 11.5, top - h + 1, 6, 3)
            self.station_bays[p.name] = bays
            self.station_wait[p.name] = wait
            self.station_box[p.name] = (top, top - h + 0.6)
        self.road, _ = _grid(*ROAD_X, ZONE_TOP - 3, 3, 8, 1)

    def targets(self, rec: StepRecord) -> dict[str, _Pos]:
        pos: dict[str, _Pos] = {}
        driving = [s for s in rec.evs if s.state is EVState.DRIVING]
        lot = [s for s in rec.evs if s.location == "work" and s.charger_id is None]
        lot.sort(key=lambda s: s.state is not EVState.WAITING)      # waiting cars first
        waits: dict[str, list] = {}
        for s in rec.evs:
            if s.location == "public" and s.charger_id is None:
                waits.setdefault(s.site, []).append(s)
        for s in rec.evs:
            plugged = s.charger_id is not None and s.state in (EVState.CHARGING, EVState.IDLE)
            if s.state is EVState.DRIVING:
                k = driving.index(s)
                pos[s.ev_id] = _Pos(*self.road[k]) if k < len(self.road) else _Pos(*self.road[-1], False)
            elif s.location == "work" and plugged and s.charger_id < len(self.work_bays):
                pos[s.ev_id] = _Pos(*self.work_bays[s.charger_id])
            elif s.location == "work":
                k = lot.index(s)
                pos[s.ev_id] = _Pos(*self.work_lot[k]) if k < len(self.work_lot) else _Pos(*self.work_lot[-1], False)
            elif s.location == "public" and s.site in self.station_bays:
                if plugged and s.charger_id < len(self.station_bays[s.site]):
                    pos[s.ev_id] = _Pos(*self.station_bays[s.site][s.charger_id])
                else:
                    k = waits.get(s.site, []).index(s) if s in waits.get(s.site, []) else 0
                    spots = self.station_wait[s.site]
                    pos[s.ev_id] = _Pos(*spots[min(k, len(spots) - 1)], k < len(spots))
            else:
                hx, hy = self.home[s.ev_id]
                pos[s.ev_id] = _Pos(hx, hy - 0.9)      # below the spot's label
        return pos


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def _lerp(a: _Pos, b: _Pos, t: float) -> _Pos:
    e = _ease(t)
    return _Pos(a.x + (b.x - a.x) * e, a.y + (b.y - a.y) * e, b.visible if t >= 1 else (a.visible or b.visible))


def animate_commute(result, path: Optional[str | Path] = None, *, show: bool = False,
                    fps: int = 12, substeps: int = 3, start: Optional[datetime] = None,
                    end: Optional[datetime] = None, every: int = 0, dpi: int = 90,
                    interactive: bool = False, title: Optional[str] = None):
    """Animate a CommuteSimulation result. every=0 picks a step size that keeps
    the animation under ~60 s; use start/end to zoom in on a few days."""
    tl = [r for r in result.timeline
          if (start is None or r.time >= start) and (end is None or r.time <= end)]
    if len(tl) < 2:
        raise ValueError("not enough timeline records to animate (record=True? window too small?)")
    every = every or _auto_every(len(tl) - 1, substeps)
    tl = tl[::every] + ([tl[-1]] if (len(tl) - 1) % every else [])
    n_frames = (len(tl) - 1) * substeps + fps
    if n_frames > MAX_FRAMES:
        raise ValueError(f"{n_frames} frames is too long; narrow start/end or raise `every`")

    cfg = result.config
    ev_ids = [s.ev_id for s in tl[0].evs]
    n = len(ev_ids)
    if n > MAX_CARS:
        raise ValueError(f"the animation fits at most {MAX_CARS} cars; use the dashboard for {n}")
    homes = {r.ev_id: r.home_charger for r in result.ev_results}
    colors = {ev: style.ev_color(i, n) for i, ev in enumerate(ev_ids)}
    lay = _Layout(result, ev_ids)
    targets = [lay.targets(r) for r in tl]
    spans = style.peak_spans(result.timeline)
    t0, t1 = tl[0].time, tl[-1].time
    price_names = {p.name: p for p in cfg.public}

    with matplotlib.rc_context(style.rc_params()):
        fig = new_figure(show or interactive, figsize=(12, 7.6))
        ax_head = fig.add_axes([0.02, 0.88, 0.96, 0.11])
        ax = fig.add_axes([0.01, 0.27, 0.98, 0.61])
        ax_soc = fig.add_axes([0.06, 0.06, 0.90, 0.16])
        for a in (ax_head, ax):
            a.set_axis_off()
        ax.set_xlim(0, SCENE_W)
        ax.set_ylim(0, SCENE_H)

        def zone(x0, x1, label, y_top=ZONE_TOP + 2, y_bot=1.5):
            ax.add_patch(FancyBboxPatch((x0, y_bot), x1 - x0, y_top - y_bot,
                                        boxstyle="round,pad=0,rounding_size=1.2",
                                        fc="#f6f6f3", ec=style.GRID, lw=1, zorder=0))
            ax.text((x0 + x1) / 2, y_top + 2.4, label, ha="center", va="center",
                    fontsize=10, fontweight="bold", color=style.INK_2)

        zone(*HOME_X, "Home")
        zone(*ROAD_X, "On the road")
        w = cfg.work
        chargers = f"{w.num_chargers} charger{'s' if w.num_chargers != 1 else ''}"
        zone(*WORK_X, f"Work · {chargers} · ${w.driver_price_per_kwh:.2f}/kWh"
             if w.driver_price_per_kwh is not None else f"Work · {chargers}")
        ax.text(SCENE_W / 2, -0.6, "number = battery %   ·   ⚡ charging   ·   dashed outline = waiting for a "
                "charger   ·   faded = driving   ·   red bar = below the buffer", ha="center", va="top",
                fontsize=7.5, color=style.MUTED)
        zone(*PUBLIC_X, "Public stations" if cfg.public else "Public stations (none)")

        # home spots
        home_spots = {}
        for ev, (x, y) in lay.home.items():
            kind = homes[ev]
            tag = f"{kind} charger" if kind != "none" else "street parking"
            p = FancyBboxPatch((x - CAR_W / 2 - 0.8, y - lay.home_row / 2 + 0.6), CAR_W + 1.6, lay.home_row - 1.2,
                               boxstyle="round,pad=0,rounding_size=0.8", fc=style.SURFACE,
                               ec=style.AXIS, lw=1, ls="-" if kind != "none" else (0, (2, 2)), zorder=1)
            ax.add_patch(p)
            ax.text(x, y + lay.home_row / 2 - 1.3, tag, ha="center", va="center", fontsize=6.5,
                    color=style.MUTED, zorder=2)
            home_spots[ev] = p

        def bays(centers, label_fmt, bay_h=8.0):
            out = []
            for i, (bx, by) in enumerate(centers):
                p = FancyBboxPatch((bx - CAR_W / 2 - 0.6, by - bay_h / 2 + 0.3), CAR_W + 1.2, bay_h - 0.6,
                                   boxstyle="round,pad=0,rounding_size=0.8", fc=style.SURFACE,
                                   ec=style.AXIS, lw=1.2, ls=(0, (4, 2)), zorder=1)
                ax.add_patch(p)
                ax.text(bx, by + bay_h / 2 - 1.3, label_fmt.format(i + 1), ha="center", va="center",
                        fontsize=6.5, color=style.MUTED, zorder=2)
                out.append(p)
            return out

        work_bays = bays(lay.work_bays, "charger {}", 9.0)
        if lay.work_lot:
            ys = [y for _, y in lay.work_lot]
            ax.text(sum(WORK_X) / 2, max(ys) + 4.0, "parking lot (waiting or done)", ha="center",
                    va="center", fontsize=7, color=style.MUTED)
        station_bays = {}
        for name, (top, bot) in lay.station_box.items():
            p = price_names[name]
            ax.add_patch(Rectangle((PUBLIC_X[0] + 0.6, bot), PUBLIC_X[1] - PUBLIC_X[0] - 1.2, top - bot,
                                   fc="none", ec=style.GRID, lw=0.8, zorder=0.5))
            kind = "DC fast" if p.kind == "DCFC" else "Level 2"
            price = next((r.prices[name] for r in tl if r.prices and name in r.prices), None)
            ax.text(sum(PUBLIC_X) / 2, top - 1.1, f"{kind} {p.charger_kw:g} kW"
                    + (f" · ${price:.3f}/kWh" if price is not None else ""),
                    ha="center", va="center", fontsize=7.5, color=style.INK_2, fontweight="bold")
            station_bays[name] = bays(lay.station_bays[name], "{}", 8.0)

        # cars
        cars = {}
        for ev in ev_ids:
            body = FancyBboxPatch((0, 0), CAR_W, CAR_H, boxstyle="round,pad=0,rounding_size=1.0",
                                  fc=colors[ev], ec=style.SURFACE, lw=1.4, zorder=5)
            label = ax.text(0, 0, ev, ha="center", va="center", fontsize=6.5, color="white",
                            fontweight="bold", zorder=6)
            batt_bg = Rectangle((0, 0), CAR_W, 1.0, fc="white", ec=style.AXIS, lw=0.7, zorder=5)
            batt = Rectangle((0, 0), 0, 1.0, fc=colors[ev], ec="none", zorder=6)
            for art in (body, batt_bg, batt):
                ax.add_patch(art)
            cars[ev] = (body, label, batt_bg, batt)

        head_time = ax_head.text(0, 0.66, "", fontsize=15, fontweight="bold", color=style.INK, va="center")
        head_info = ax_head.text(0, 0.16, "", fontsize=9.5, color=style.INK_2, va="center")
        head_cost = ax_head.text(1, 0.66, "", fontsize=15, fontweight="bold", color=style.INK,
                                 va="center", ha="right")
        ax_head.text(1, 0.16, (title or result.strategy) + " · drivers' total so far", fontsize=9,
                     color=style.MUTED, va="center", ha="right")

        for a, b in spans:
            if b >= t0 and a <= t1:
                ax_soc.axvspan(a, b, color=style.PEAK_BAND, lw=0, zorder=0)
        ax_soc.axhline(cfg.soc_buffer * 100, color=style.MUTED, lw=1, ls=(0, (4, 3)))
        ax_soc.set_xlim(t0, t1)
        ax_soc.set_ylim(0, 105)
        ax_soc.set_title(f"State of charge (%) · dashed = {cfg.soc_buffer:.0%} buffer · shaded = on-peak",
                         fontsize=9)
        locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
        ax_soc.xaxis.set_major_locator(locator)
        ax_soc.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        soc_lines = {ev: ax_soc.plot([], [], color=colors[ev], lw=1.6 if n <= style.MAX_COLORED_EVS else 1,
                                     alpha=1 if n <= style.MAX_COLORED_EVS else 0.6)[0] for ev in ev_ids}
        cursor = ax_soc.axvline(t0, color=style.INK_2, lw=1)
        times = [r.time for r in tl]
        soc_series = {ev: [r.snapshot(ev).soc * 100 for r in tl] for ev in ev_ids}

        def light(patch, active, used):
            patch.set_edgecolor(style.INK if active else style.AXIS)
            patch.set_linewidth(2 if active else 1.2)
            patch.set_linestyle("-" if used else (0, (4, 2)))

        def draw(frame: int):
            last = len(tl) - 1
            k = min(frame // substeps, last)
            local = (frame - k * substeps) / substeps
            frac = min(local, 1.0) if k < last else 0.0
            rec, nxt = tl[k], tl[min(k + 1, last)]
            now = rec.time + (nxt.time - rec.time) * frac
            prev_t, cur_t = targets[max(k - 1, 0)], targets[k]
            move = min(1.0, local * 2.5) if k > 0 else 1.0

            for ev in ev_ids:
                body, label, batt_bg, batt = cars[ev]
                p = _lerp(prev_t[ev], cur_t[ev], move)
                snap, snap_next = rec.snapshot(ev), nxt.snapshot(ev)
                soc = snap.soc + (snap_next.soc - snap.soc) * frac
                x0, y0 = p.x - CAR_W / 2, p.y - CAR_H / 2
                body.set_x(x0)
                body.set_y(y0)
                body.set_alpha(0.55 if snap.state is EVState.DRIVING else 1.0)
                body.set_linestyle((0, (2, 1.5)) if snap.state is EVState.WAITING else "-")
                body.set_edgecolor(style.INK if snap.state is EVState.WAITING else style.SURFACE)
                label.set_position((p.x, p.y))
                bolt = " ⚡" if snap.state is EVState.CHARGING and k < last else ""
                label.set_text(f"{ev}  {soc * 100:.0f}%{bolt}")
                batt_bg.set_xy((x0, y0 - 1.4))
                batt.set_xy((x0, y0 - 1.4))
                batt.set_width(CAR_W * soc)
                batt.set_facecolor("#e34948" if soc < cfg.soc_buffer else colors[ev])
                for art in (body, label, batt_bg, batt):
                    art.set_visible(p.visible)
                if ev in home_spots:
                    light(home_spots[ev], snap.state is EVState.CHARGING and snap.location == "home",
                          homes[ev] != "none")
                    home_spots[ev].set_linestyle("-" if homes[ev] != "none" else (0, (2, 2)))

            def site_bays(site, patches):
                active = {s.charger_id for s in rec.evs if s.site == site and s.state is EVState.CHARGING}
                used = {s.charger_id for s in rec.evs if s.site == site and s.charger_id is not None}
                for i, patch in enumerate(patches):
                    light(patch, i in active and k < last, i in used)

            site_bays("work", work_bays)
            for name, patches in station_bays.items():
                site_bays(name, patches)

            cost = sum(s.cost for s in rec.evs) + sum((b.cost - a.cost) * frac for a, b in zip(rec.evs, nxt.evs))
            head_time.set_text(now.strftime("%a %b %d %Y  ·  %H:%M"))
            px = rec.prices or {}
            period = "on-peak" if rec.on_peak else "off-peak"
            counts = {loc: sum(s.state is EVState.CHARGING and s.location == loc for s in rec.evs)
                      for loc in ("home", "work", "public")}
            head_info.set_text(
                f"home ${px.get('home', 0):.3f}/kWh ({period})   ·   charging: {counts['home']} at home, "
                f"{counts['work']} at work, {counts['public']} public   ·   "
                f"load: home {rec.load_kw_at('home'):.0f} kW, work {rec.load_kw_at('work'):.0f} kW, "
                f"public {rec.load_kw_at('public'):.0f} kW")
            head_cost.set_text(f"${cost:,.2f}")

            upto = k + 1
            for ev in ev_ids:
                series = soc_series[ev]
                xs = times[:upto] + ([now] if frac else [])
                ys = series[:upto] + ([series[k] + (series[min(k + 1, last)] - series[k]) * frac] if frac else [])
                soc_lines[ev].set_data(xs, ys)
            cursor.set_xdata([now, now])
            return []

        anim = FuncAnimation(fig, draw, frames=n_frames, interval=1000 / fps, blit=False)
        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            writer = FFMpegWriter(fps=fps) if path.suffix.lower() == ".mp4" else PillowWriter(fps=fps)
            anim.save(path, writer=writer, dpi=dpi)
        if show:
            show_windows()
    return anim
