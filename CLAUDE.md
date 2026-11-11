# CLAUDE.md: context for anyone (human or Claude) picking up this project

EC601 team project (Boston University, Fall 2026): **decentralized EV charging with independent
multi-agent reinforcement learning (MARL)**, compared against random, greedy and centralized
baselines, in a Python simulation priced with real Eversource Connecticut data.

Team: Nuo Lin, Kathryn Forrest, Lidia Berhe. Repo: `kforres5/EC601-EV-Charging-Project`.
Status, Nov 11 2026: simulation, pricing and two baselines built; RL not started.
See `team_notes/TODO.md` (organized by module) and the status-colored UML diagram
`resources/decentralized_ev_charging_module_UML.drawio`.

---

## Goal and framing

- **Mission:** help EV owners cut charging cost by letting each car's agent decide when, where and
  how much to charge, learning on its own with only public information (no shared driver data).
- **Question:** how close do independent learners get to a centralized optimizer with full
  information, and how do both compare with simple rules (always charge, random, greedy)?
- **Key papers:** Rate et al. 2026, *Independent MARL for EV fleets* (arXiv:2606.31347; source of
  the greedy baseline and the ~500-simulated-day PPO training budget); Park & Moon 2022;
  Cakil & Aksoy 2025. Shadow peaks under time-of-use pricing: Bailey et al. (NBER w32886, 2024).
- **Framing:** prices are Eversource **Connecticut** time-of-use (Variable Peak Pricing). Describe
  results as "Eversource CT time-of-use customers"; Massachusetts residential supply is flat.

---

## Repo map

```
ev_charging/
  config.py        every tunable assumption: ScenarioConfig (one hub), CommuteConfig,
                   WorkHubConfig, HomeChargingConfig, PublicStationConfig, PeakWindow
  pricing.py       Eversource supply price schedules (+ delivery via DeliveredPriceSchedule)
  tariffs.py       Rates 7/27/30/35 and EV-L, SiteMeter -> MonthlyBill, public prices
  vehicle.py       Honda Prologue specs and DC charging curve
  nhts.py          sample real NHTS 2022 commuter schedules
  driver.py        DriverProfile (weekday routine), Location
  itinerary.py     routine + detours to public stations (Visit)
  ev.py            EV: battery, SOC, driving, charge_capacity_kwh (AC limit / DC curve)
  station.py       ChargingStation / Charger (first come, first served)
  sites.py         Site = chargers + prices + meter; home / work / public builders
  commute.py       CommuteSimulation (home + work + public), PlanningView, results
  simulation.py    Simulation: the earlier single-hub harness (still used by 3 runners)
  strategies/      base.py (Strategy interface, AlwaysCharge), greedy.py (Greedy)
  recorder.py      per-step timeline; metrics.py: single-hub results
  run_output.py    one folder per run: outputs/runX_[parameters]/
  viz/             dashboards and animations (single hub and commute)
run_greedy.py      main runner: greedy vs always-charge, home + work + public
run_commute.py, run_fleet_demo.py, run_single_ev.py   single-hub runners
scripts/           build_nhts_commuters.py, make_pricing_diagram.py, make_uml_diagram.py
dataset/           see dataset/Data_info.md; derived/nhts_commuters.csv is generated
team_notes/        TODO.md, Modeling_Assumptions.md, TEAM.md, SPRINT1.md
resources/         UML (.drawio + PNG), pricing_data_flow (.svg + PNG)
tests/             pytest; tests/helpers.py pins round-number configs
```

---

## How to run

```
pip install -r requirements.txt          # pytest, matplotlib
python -m pytest                         # 117 tests; keep them passing
python run_greedy.py                     # 10 drivers, 3 work chargers, 1 week of July 2025
python run_greedy.py --start 2026-01-05 --plot      # winter, with dashboards
python run_greedy.py --animate --anim-days 3        # GIF: home, road, work, public stations
python run_greedy.py --sample-drivers --seed 3 --evs 12 --chargers 1 --no-home-share 0.3 --days 14
python run_commute.py --sample-drivers --region new-england          # single-hub runner
python scripts/make_uml_diagram.py       # regenerate the UML (also recounts TODO.md progress)
```

Every run writes `outputs/runX_[parameters]/` (git-ignored): `summary.txt` (printed output),
`params.json` (options + exact command) and any charts. X counts up across all runners; the name
holds the runner's main settings plus every option changed from its default.

---

## How the simulation works (CommuteSimulation)

15-minute steps. Each driver follows a weekday routine (home -> commute -> work -> commute -> home;
weekends at home) and may detour from home to a public station.

Step order: 0 public visits (leave station when done / head out) -> 1 unplug cars that left ->
2 work rules (4 h/day limit, move-your-car 60 min after charging stops) -> 3 plug in (home always;
work asks the strategy; no free charger = wait) -> 4 charge (strategy picks kWh; at a station the
visit's target) -> 5 drive (battery drains; trip and buffer metrics).

Strategy interface (`strategies/base.py`): `decide()` (single hub), `wants_charger()` (at work),
`charge_limit_kwh()` (plugged in), `public_visit()` (at home: go to a station?). A strategy only
sees `PlanningView`: own SOC, schedule, home charger, posted prices (on-peak one day ahead),
own work limits. New strategies (random, centralized, MARL) plug in here.

- **AlwaysCharge** (uncontrolled): plug in whenever possible, full power to 80%; if home can't
  cover the next 24 h + buffer, fill up at the fastest public station.
- **Greedy:** plans 96 h ahead (so a Friday-midnight plan sees Monday), buys the cheapest
  home/work slots that keep SOC >= 20%, never above target, replans when blocked or off plan;
  books the cheapest public station that covers the next 24 h of shortfall.

---

## Key modeling decisions (and sources)

| Topic | Decision | Source / reason |
|---|---|---|
| Vehicle | Honda Prologue: 91 kWh usable, 0.34 kWh/mi, 11.5 kW AC, 155 kW DC with curve | `dataset/honda_prologue_*.csv` |
| Driver default | at work 7:45-16:30, 10.5 mi / 25 min each way | weighted medians, 2022 NHTS drive-alone commuters (1,626) |
| Peak window | weekdays 12:00-20:00; weekends off-peak | Eversource / EnergizeCT (Rate 7, Rate 27) |
| Supply prices | daily on-peak, monthly off-peak, Oct 2024 - Oct 2026 | Eversource VPP history CSV |
| Home price | residential supply + Rate 7 delivery, pass-through | home bills not modelled (household pays anyway) |
| Home chargers | L2 7.2 kW 84% / L1 1.4 kW 16%; **10% have none** | J.D. Power 2024; NREL 2030 National Charging Network (90% home access, 85-98% sensitivity); surveys 5.8% (Plug In America 2025) to 14% (ChargeLab 2024) |
| Work | flat **$0.25/kWh**, **4 h/day** plugged in, move car 60 min after charging stops; site on small C&I supply + Rate 27 | between home off-peak and public L2; BU/WPI 4 h limits |
| Public | L2 lot 2 x 7.2 kW $0.39, DC fast 2 x 150 kW $0.485; max stay 4 h / 45 min; detours from home only, 06:00-22:00 | `charger_prices_summary.csv`; Palo Alto sessions (84% end within 4 h, median 2.3 h); detours are placeholders |
| Site bills | supply + delivery + demand (15-min peak) + customer charge (prorated); public L2 Rate 27, DC fast Rate EV-L | Eversource CT rate summary, Rate EV-L tariff |
| Charge goal | SOC never below **20%** buffer (enough for the driving ahead + 20%) | assumption A8 |
| Holidays, large C&I rates | TBD; Rate 35 stands in for large C&I / Last Resort | open items |

Full reasoning: `team_notes/Modeling_Assumptions.md` (A1-A9, M1-M8). Data notes: `dataset/Data_info.md`.

---

## Results so far (for context, not final)

- July 2025 week, 10 drivers: greedy pays ~$0.20/kWh vs ~$0.25 always-charge; greedy 0% on-peak,
  always-charge starts home charging at 17:00 (on-peak). No missed goals.
- January 2026: home off-peak (~$0.27 incl. delivery) costs more than the $0.25 work fee, so greedy
  moves ~70% of charging to work.
- Crowded (30% no home charger, 1 work charger): drivers use public charging; greedy picks L2,
  always-charge picks DC fast. One greedy driver still dips below 20% when the work charger is
  taken (it can only go public from home).
- Greedy creates a midnight "shadow peak" (all homes start together). `--tie-break latest` exists.
- Work hub and both public stations lose money at these volumes (demand charges; DC fast's
  $350/month EV-L customer charge).

---

## Conventions

- **Windows repo, CRLF line endings.** Keep files CRLF. A checkout that shows every file as
  modified with equal insertions/deletions is line-ending noise only (`git diff --ignore-cr-at-eol`).
- Every tunable assumption goes in `config.py` with a comment naming its source; placeholders say
  PLACEHOLDER/TBD and get a TODO item.
- Docs: plain wording; spell out acronyms on first use (the team asked for full words).
- When something lands: tick `team_notes/TODO.md`, update `Modeling_Assumptions.md` if an
  assumption changed, set the box's `status=`/`todo=` in `scripts/make_uml_diagram.py` and re-run it
  (the diagram's progress panel is counted from TODO.md checkboxes).
- Tests: add to `tests/`; use `tests/helpers.py` (`simple_cfg`, `SIMPLE_DRIVER`) for round numbers;
  commute tests use `price_csv=None` flat prices (0.35 / 0.15) and no public stations by default.
- Price data ends Oct 2026; dates outside raise `KeyError`. Rate EV-L can't be a pass-through
  driver price (it depends on the monthly load factor).
- The commute animation fits at most 16 cars; long runs pick a frame step automatically.

## Git workflow

Branch per feature, pull request into `main`, majority vote on disagreements (`team_notes/TEAM.md`).
`main` has everything through PR #8 (Nov 11). Branch `centralized-strategy` was cut from the
Oct 31 commit, so update it from `main` before building on it.

## Sprints

| Sprint | Dates | Lead | Focus |
|---|---|---|---|
| 4 | Nov 9 - 22 | Nuo | centralized + random baselines, RL environment + reward, station pricing |
| 5 | Nov 23 - Dec 7 | Lidia & Kathryn | train MARL agents, experiments, final presentation |

If time runs short, drop learning station agents and grid caps first.
