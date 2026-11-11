# TODO: Getting the Modeling Assumptions Running

Step-by-step work to implement everything in [Modeling_Assumptions.md](Modeling_Assumptions.md).
Tags like **(A3)** or **(M5)** point to the matching section there.
Phases are roughly in order: later phases depend on earlier ones. Within a phase, items can be
split across people. Add a name after an item when you pick it up.
Data files are described in [dataset/Data_info.md](../dataset/Data_info.md).

---

## Phase 0: Already done
- [x] Simulation harness: config, SimClock, EV, charging station with M chargers, strategy interface
- [x] Eversource CT VPP prices from the CSV, per customer class (residential / small and large C&I / last resort)
- [x] Peak window weekdays 12:00–20:00; weekends off-peak; missing weekdays filled from the same month
- [x] Per-step timeline recording, dashboard PNG, animated hub GIF
- [x] Driver model with a constant schedule: work hours, commute distance and time, energy per mile **(M1)**
- [x] Hub at work or at home; cars charge only while the driver is there; battery drains while commuting
- [x] Move-your-car rule: 60 minutes after reaching target, work hub only **(M5)**
- [x] Metrics: cost, on/off-peak kWh, energy driven, shortfall, departures below target, idle hours, moves
- [x] **Home + work simulation** (`ev_charging/commute.py`, `run_greedy.py`): each driver has their own
      home charger (L2 / L1 / none) and shares the work hub; greedy vs always-charge baselines
- [x] **Public stations** in the same simulation: a public L2 lot and a DC fast station that drivers
      detour to from home (`ev_charging/itinerary.py`), priced from `charger_prices_summary.csv`

---

## Phase 1: Get the missing data (blocks Phases 2 and 5)
- [x] Eversource CT *Summary of Connecticut Electric Rates* → `eversource_summary_of_electric_rates.csv`
  - [x] Delivery charges per kWh: Rate 7 (on/off-peak), Rate 27/30/35
  - [x] Demand charges ($/kW per month) for commercial rates
  - [x] Monthly customer (fixed) charges
- [x] Eversource CT **Rate EV-L** tariff → `eversource_rate_ev-l.csv` (8 load-factor tiers)
- [ ] Confirm whether holidays count as off-peak, and the peak window for Large C&I / Last Resort
- [ ] Find the rate for Large C&I / Last Resort customers (Rates 41/55-58); Rate 35 stands in for now
- [x] More VPP history: now Oct 2024 – Oct 2026 (539 weekdays)
- [x] NHTS 2022 tables → `driver_data/` **(M1)**
  - [x] Commute distance, departure and arrival times → `derived/nhts_commuters.csv`
  - [ ] Weekend and non-work trips (data is there, not used yet; see Phase 4)
- [x] Charging sessions: City of Palo Alto public L2 sessions, 2011–2013 → `arrival_departure_kWh.csv`
      → used for the public L2 longest stay (4 h: 84% of sessions end within 4 h, median 2.3 h).
      Workplace times come from NHTS instead of ACN-Data.
- [x] Public charging prices for L2 and DC fast → `charger_prices_summary.csv` **(A2)**
- [x] Vehicle specs: Honda Prologue kWh/mile, max AC/DC rate, DC charging curve **(A4, A9)**
- [x] Home charging access **(A1)**
  - [x] L1 vs L2 split (16% / 84%) → `home_charging.txt`, `HOME_CHARGER_MIX` in config
  - [x] Share of EV drivers with no home charger: **10%** (`HomeChargingConfig.no_home_share`).
        NREL 2030 National Charging Network study assumes 90% of EVs have reliable home charging
        (sensitivity 85–98%); surveys of today's EV drivers: 5.8% (Plug In America 2025) to 14%
        (ChargeLab 2024) without. Mass adoption would raise it (only 33% of all US vehicles park
        where home charging exists today, NREL 2021) — try `--no-home-share 0.3` or higher
  - [ ] Local value for CT/Boston: NREL's county-level home-access file (data.nrel.gov/submissions/278)

---

## Phase 2: Pricing layers (A2, A3, A6)
- [ ] Add a second home price mode `fixed_tou` using the 6-month Rate 7 table (already in the doc)
- [x] Delivery charges per kWh (on/off-peak) from the rate summary (`site_rate`, `include_delivery`)
- [x] Split prices into two things:
  - [x] **Site cost**: monthly site bill = supply + delivery + demand + customer charges (`result.site_bills`)
  - [x] **Driver price**: pass-through of the utility price, or a flat posted price (`driver_price_per_kwh`;
        `run_commute.py --driver-price public-l2 / public-dcfc / <number>`)
- [x] Work charging fee: **flat $0.25/kWh** (`WorkHubConfig.driver_price_per_kwh`), between home off-peak
      (~$0.19 in July 2025, ~$0.27 in January 2026) and public L2 ($0.39)
- [x] Demand charge: each site's highest 15-minute load per month, above the rate's threshold
- [x] Rate EV-L: demand and delivery charges by the month's load-factor tier
- [ ] Fixed monthly costs per site
  - [x] Utility customer charge (prorated for partial months)
  - [ ] Network and maintenance costs (MA EVICC example: ~$1,700/yr for 2 L2 ports)
- [x] ~~Mark results "energy-only"~~: no longer needed, real delivery and demand charges are in

---

## Phase 3: Multiple sites and driver types (A1, A4)
- [ ] Refactor the single `station` into a list of **sites**, each with: location, chargers, charger kW,
      customer class, grid cap. Types: home charger (one per driver), work hub, public station(s)
  - [x] Home charger per driver + work hub (`ev_charging/sites.py`, used by `CommuteSimulation`)
  - [x] Public stations: L2 lot (2 x 7.2 kW) and DC fast (2 x 150 kW), each with its own bill
  - [ ] Grid cap per site
- [x] Driver types: home L2 / home L1 / no home charger, with shares set in config **(A1)**
      (`HomeChargingConfig`, `assign_home_chargers`, `run_greedy.py --home-types`)
- [ ] Charger power levels: L1 1.4 kW, L2 7.2 kW, public L2 7–19 kW, DC fast 50–150 kW **(A4)**
  - [x] Home L1 1.4 kW / L2 7.2 kW (`HOME_CHARGER_KW`)
  - [x] Hub chargers can be AC or DC at any kW (`charger_type`, `charger_kw`)
  - [x] Different charger types per site (home AC, work AC or DC)
- [x] Limit charging by each car's own max charging rate (Prologue: 11.5 kW AC)
- [x] DC fast charging follows the car's charging curve (slows above ~80%)
- [ ] Site grid cap `P_max`: when demand is over the cap, share power among plugged-in cars
- [ ] Neighborhood/building transformer cap for home chargers (prevents the 8 PM "shadow peak")
- [ ] Update dashboard and animation to show more than one site
  - [x] Dashboard: `plot_commute_dashboard` (home vs work prices and load, where each car charges)
  - [x] Animation: `animate_commute` / `run_greedy.py --animate` (home, road, work, public stations)

---

## Phase 4: Driver model upgrades (M1, M5, A7, A8)
- [x] Default schedule = NHTS weekday medians (arrive 7:45, leave 16:30, 10.5 mi / 25 min each way)
- [x] Per-driver variation: sample real NHTS commuters (`ev_charging/nhts.py`, `run_commute.py --sample-drivers`)
- [ ] Weekend trips (errands) instead of staying home all day
- [x] Next-day charge goal: enough for the driving ahead + a 20% buffer, i.e. SOC never below
      `CommuteConfig.soc_buffer` **(A8)**. Metrics: trips ending below the buffer, hours below it,
      shortfall, `missed_goal`
  - [ ] Penalty for missing it (needs the reward in Phase 6)
- [ ] Value of time ($/hour) for each driver **(A7)**
- [ ] Detour time/distance from the commute to each public station **(A7)**
  - [x] Detours from home, with placeholder distances (L2 lot 1 mi / 5 min, DC fast 3 mi / 10 min);
        visits only start 06:00–22:00 and must end before the next commute
  - [ ] Real station locations; stopping on the way home from work instead of a separate trip
- [x] Work charging limit: **4 hours/day** plugged in (`WorkHubConfig.daily_limit_hours`) **(M5)**
- [ ] *On hold:* overstay penalty: drivers who don't move on time, plus an hourly overstay fee

---

## Phase 5: Public station pricing (A5, A6, M4)
- [x] Posted price from the dataset (L2 $0.39, DC fast $0.485), fixed for the run (first version)
- [ ] Daily base price, set once per day before the day starts, using tomorrow's known energy price
- [ ] Cost floor: base price ≥ energy + delivery + allocated demand and fixed cost per kWh **(A6)**
- [ ] Surge multiplier based on site load / `P_max` above 50% **(A5)**
- [ ] Show the price before plug-in and lock it for the whole session
- [ ] Station profit accounting: revenue − energy − delivery − demand charge − fixed **(M4)**
  - [x] Utility side: `result.site_margin` = drivers' payments − site utility bill
  - [x] Public stations: `CommuteResult.stations` (revenue, monthly bill on Rate 27 / Rate EV-L, margin)
  - [ ] Add network and maintenance costs
- [ ] Start with a fixed pricing rule (cost-plus + surge); learning stations come in Phase 6

---

## Phase 6: Agents and strategies (M2, M3)
- [ ] Decide what each driver agent sees (public info only: prices, own SOC, schedule, station prices)
- [ ] Extend the strategy interface so a driver chooses **where** to charge, not just charge/wait
  - [x] Home vs work: `wants_charger()` (plug in at work?) and `charge_limit_kwh()` (how much now)
  - [x] Public stations: `public_visit()` (go now? which station? how much?)
- [ ] Baselines:
  - [x] Always charge when plugged in (`AlwaysCharge`)
  - [ ] Random
  - [x] Greedy (cheapest slots across home and work, replans when blocked; `strategies/greedy.py`)
  - [ ] Centralized optimization with full information (MILP, e.g. PuLP or OR-Tools)
- [ ] Wrap the simulation as a multi-agent RL environment (Gymnasium / PettingZoo style `reset`/`step`)
- [ ] Driver reward: −(money + value of time × time) − penalty for missing the charge goal **(M3)**
- [ ] Independent learners: contextual bandit (LinTS) first, then PPO (Stable-Baselines3)
- [ ] Learning station agents (one pricing action per day), only after driver agents train well

---

## Phase 7: Metrics and evaluation (M7, M8)
- [ ] Driver metrics by driver type: cost, time spent charging/detouring, missed-goal rate
  - [x] Cost, $/kWh, share at work, missed goal, work waiting hours (`run_greedy.py` prints by type)
  - [x] Time spent on public charging trips, detours included (`public_hours`), and waiting there
- [ ] Station metrics: profit, utilization, monthly peak kW
  - [x] Profit (utility side), energy sold, peak kW per public station
- [ ] Grid metrics: peak load, share of time at `P_max` / transformer cap
  - [x] Peak load of all home chargers together, and of the work hub (`CommuteResult`)
- [ ] Train/test split by whole months (price data now covers Oct 2024 – Oct 2026,
      e.g. train Oct 2024 – Jun 2026, test Jul – Oct 2026)
- [ ] Stress tests: July 2025 (big gap), March 2026 (small gap), January 2026 (flipped prices, 81.8¢ spike)
- [ ] Run each experiment with several random seeds; compare against all baselines

---

## Phase 8: Docs and housekeeping
- [x] Update the UML diagram (`resources/decentralized_ev_charging_module_UML.drawio`, PNG next to it;
      regenerate with `scripts/make_uml_diagram.py`) with drivers, sites, pricing, strategies, results
- [ ] Keep `Modeling_Assumptions.md` in sync as TBDs get filled in
- [x] README: how to run each scenario
- [x] One output folder per run: `outputs/runX_[parameters]/` with summary.txt and params.json

---

## Suggested sprint split (adjust as needed)
| Sprint | Dates | Focus |
|---|---|---|
| Sprint 3 | Oct 26 – Nov 8 | Phase 1 (data), Phase 2 (pricing layers), start the Phase 3 site refactor |
| Sprint 4 | Nov 9 – Nov 22 | Finish Phase 3, Phases 4–5, baselines from Phase 6 |
| Sprint 5 | Nov 23 – Dec 7 | MARL agents (Phase 6), evaluation (Phase 7), docs and final presentation |
