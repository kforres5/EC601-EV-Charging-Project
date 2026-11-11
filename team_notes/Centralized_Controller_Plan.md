# Centralized Controller: Plan

Plan for the centralized baseline (TODO section 6), agreed Nov 11, 2026. Branch: `centralized-strategy`.
Related: [TODO.md](TODO.md), [Modeling_Assumptions.md](Modeling_Assumptions.md), [CLAUDE.md](../CLAUDE.md).

## Why we need it

The project's question is how close independent learners (each car deciding alone, with public
information only) get to a planner that coordinates every car. The centralized controller is that
planner: one optimizer that schedules all cars together. Its result is the benchmark the MARL
agents, greedy and always-charge are compared against.

---

## Decisions

| # | Question | Decision | Why |
|---|---|---|---|
| 1 | What does the controller minimize? | **What drivers pay** (sum over all drivers of kWh × the price they pay at that site), plus a penalty for dropping below the charge goal | Same objective the RL drivers will have (minus value of time, which isn't built yet), so the comparison is apples-to-apples. A "system cost" mode with the sites' demand charges can come later as an option |
| 2 | What prices can it see? | **Only what's posted: on-peak prices one day ahead**, off-peak prices for the month, flat work / public prices. Beyond tomorrow it uses the latest posted on-peak price, exactly like greedy (`PlanningView.price_forecast`) | Matches how Eversource's VPP prices are published, so the controller can't do anything a real operator couldn't. The controller and greedy then see the same prices, so any saving the controller finds comes from **coordination** (who charges where and when), not from knowing future prices |
| 3 | Public stations? | **Included from the first version** | Drivers without home chargers, and crowded work hubs, depend on public charging. Without it the controller would miss the goal in exactly the scenarios where coordination matters most, and the comparison with greedy (which uses public stations) wouldn't be fair |

What "full information" means here: the controller knows every car's charge, schedule, home charger
and work-charging time used today, and every site's chargers. It does **not** know future prices
beyond what's posted. Drivers' own schedules are known in advance (they're fixed routines in the
simulation).

---

## New modules

### 1. `ev_charging/central_controller.py`: `CentralController`
Builds and solves one mixed-integer linear program (MILP) for the whole fleet, and keeps the
resulting schedule.

**Input:** a `FleetView` (full information, see below) and settings: horizon (96 h, like greedy),
solver time limit, goal penalty.

**Time:** 15-minute slots `t` over the horizon. For each car `i` the itinerary gives, per slot,
where the driver is, the driving energy `d[i,t]`, and which sites are reachable.

**Variables**
| Variable | Meaning |
|---|---|
| `x[i,t,s] ≥ 0` | battery kWh car `i` adds in slot `t` at site `s` (its home charger, work, or public station `k`) |
| `E[i,t]` | battery energy at the start of slot `t` |
| `work_on[i,t] ∈ {0,1}` | car `i` holds a work charger in slot `t` (only in slots the driver is at work) |
| `work_start[i,t] ∈ {0,1}` | a work session starts in slot `t` |
| `visit_on[i,k,t] ∈ {0,1}` | car `i` is charging at public station `k` in slot `t` (only while the driver is home, within 06:00–22:00) |
| `visit_start[i,k,t] ∈ {0,1}` | car `i` leaves home for station `k` in slot `t` |
| `slack[i,t] ≥ 0` | kWh below the buffer (allowed, but heavily penalized, so infeasible days still solve) |

**Constraints**
- Battery: `E[i,t+1] = E[i,t] + Σ_s x[i,t,s] − d[i,t] − detour energy`, with `E[i,0]` = current charge
- Charge goal: `E[i,t] + slack[i,t] ≥ 20% × battery`; target: `E[i,t] ≤ required_soc × battery`
- Home: `x[i,t,home] ≤ home kW × hours at home in slot t`, and 0 while away on a public visit
- Work chargers: `Σ_i work_on[i,t] ≤ M`; `x[i,t,work] ≤ kW × Δt × work_on[i,t]`
- Work rules, so the simulation never has to move a car mid-plan: at most one session per day
  (`Σ_day work_start ≤ 1`, `work_on[i,t] ≤ work_on[i,t-1] + work_start[i,t]`), at most
  4 h plugged in per day
- Public stations: `Σ_i visit_on[i,k,t] ≤ chargers at k`; `x[i,t,k] ≤ kW × Δt × visit_on[i,k,t]`;
  at most one visit per stretch at home; at most the station's longest stay (4 h L2, 45 min DC fast);
  back home before the next commute; detour energy (2 × detour miles × kWh/mile) counted per visit
- Each car's own max charging rate (Prologue 11.5 kW AC; DC fast uses the car's peak, the
  simulation's taper is handled by re-planning)

**How a planned visit maps onto the simulation:** the car leaves home at the start of the planned
slot, plugs in at the next slot boundary (the simulation's `_plug_time`), charges for the planned
slots, then drives home. So a visit planned to start at slot `t` charges in slots `t+1 … t+L`, and
home charging is blocked from `t` until it is back.

**Objective:** minimize `Σ x[i,t,s] / efficiency × driver price(s,t)` (prices as posted, decision 2)
`+ goal penalty × Σ slack` (e.g. $5/kWh, well above any price) `+ a tiny cost per session start`
(stops pointless plug-ins and ties).

**When it plans:** at midnight each day (new day-ahead prices), over the next 96 h, and again whenever
the actual state drifts from the plan (DC taper, rounding, a car that couldn't plug in).
**Solver:** PuLP with its built-in CBC solver (`pip install pulp`, no license), with a time limit; it
keeps the best solution found and logs solve time, optimality gap and objective.

### 2. `ev_charging/strategies/centralized.py`: `CentralizedStrategy`
A thin per-car adapter. Every car gets one, all sharing the same controller, so the simulation
treats it like any other strategy:
- `wants_charger()`: does the plan have this car on a work charger now?
- `charge_limit_kwh()`: the planned kWh for this car, this slot, at this site
- `public_visit()`: (station, planned kWh) when the plan says to leave for a station now
- `release_charger()`: True once its planned work session is over (new hook, below)

Each call first runs `controller.ensure_plan(now)`, which solves at most once per step.

---

## Changes to existing modules

| Module | Change |
|---|---|
| `commute.py` | `CommuteSimulation.fleet_view()`: read-only full information for the controller (all EVs, itineraries, sites, chargers, work time used, clock). Separate from `PlanningView` so the decentralized agents still see only public information. Price lookups go through the same day-ahead rule as `PlanningView.price_forecast` |
| `commute.py` | Voluntary unplug in step 2: if `strategy.release_charger()` is True, unplug and park. Otherwise a car that finished its planned session sits on the charger for up to 60 min (move-your-car rule) and blocks the next scheduled car |
| `strategies/base.py` | `release_charger()` hook, default False, so always-charge and greedy behave exactly as before |
| `run_greedy.py` | `--strategy` takes a list (`always,greedy,central`); add `--solver-time-limit`. All strategies run on the same drivers and land in the same run folder |
| `requirements.txt` | add `pulp` |
| Docs | TODO section 6, the diagram box (`scripts/make_uml_diagram.py`), `CLAUDE.md` |

---

## Build steps
- [ ] `release_charger()` hook + voluntary unplug in `commute.py`; test that always-charge and greedy results don't change
- [ ] `FleetView` (`CommuteSimulation.fleet_view()`), with the day-ahead price rule
- [ ] `CentralController`: slots, variables, battery / goal / home / work constraints, objective
- [ ] Public station visits in the MILP (sessions, station capacity, detours, longest stay, back before the commute)
- [ ] `CentralizedStrategy` + `ensure_plan()` re-planning (midnight + drift)
- [ ] Runner: `--strategy always,greedy,central`, solver stats in `summary.txt`
- [ ] Tests (below)
- [ ] Compare on the standard scenarios: July week (10 drivers), January week, crowded (30% without home charging, 1 work charger)
- [ ] Docs: TODO, diagram, CLAUDE.md, Modeling_Assumptions (baselines)

## Tests
Small cases where the right answer is known by hand:
- Two cars, one work charger, both need charge: sessions are staggered, never overlapping
- Home off-peak cheaper than work: charges at home off-peak; work cheaper (winter): charges at work
- Never above the target, never below the buffer when it's feasible; slack > 0 only when it isn't
- Respects the 4-hour limit and one session per day (the simulation never has to move the car)
- No home charger and no work charger: uses a public station within visit hours and is home before the commute
- Station capacity: two cars, one public charger, both need it: visits don't overlap
- Only posted prices: changing a price two days ahead doesn't change today's plan
- On the same scenario, the controller's driver cost ≤ greedy's (same information, plus coordination)

## Risks and fallbacks
- **Solve time.** About 10 cars × 384 slots: ~4,000 continuous variables and a few thousand yes/no
  variables. CBC should take seconds, but public visits add many. If it gets slow: 1-hour slots for
  public visits, a 48 h horizon, only offer public stations to cars that can't meet the goal without
  them, and a solver time limit.
- **Plan vs simulation mismatch** (DC taper, partial slots at the start and end of trips): re-plan on drift.
- **Value of time** is 0 until A7 is built, so the controller may send drivers to a public station
  to save a few cents; the per-visit cost term limits that. Add value of time when A7 lands.
