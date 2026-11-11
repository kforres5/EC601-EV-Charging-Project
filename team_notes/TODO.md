# TODO: Getting the Modeling Assumptions Running

Work needed to implement everything in [Modeling_Assumptions.md](Modeling_Assumptions.md),
organized by **module**, matching the packages in the UML diagram
([resources/decentralized_ev_charging_module_UML.drawio](../resources/decentralized_ev_charging_module_UML.drawio),
where green = built, amber = partly built, red = not built yet).
Tags like **(A3)** or **(M5)** point to the matching section of Modeling_Assumptions.md.
Add your name after an item when you pick it up. Data files are described in
[dataset/Data_info.md](../dataset/Data_info.md). The diagram's progress panel is counted from
the checkboxes below (`python scripts/make_uml_diagram.py`).

---

## 1. Configuration (`config.py`)
- [x] One-hub scenario config (`ScenarioConfig`) and home + work + public config (`CommuteConfig`)
- [x] Peak window weekdays 12:00–20:00; weekends off-peak (`PeakWindow`)
  - [ ] Confirm whether holidays count as off-peak (`PeakWindow.holidays`)
  - [ ] Confirm the peak window for Large C&I / Last Resort customers
- [x] Work hub: flat **$0.25/kWh**, **4 hours/day** plugged in, move your car 60 minutes after it
      stops charging (`WorkHubConfig`) **(M5)**
- [x] Home charging: L2 7.2 kW 84% / L1 1.4 kW 16% (`HOME_CHARGER_MIX`, `home_charging.txt`) **(A1)**
- [x] Share of EV drivers with no home charger: **10%** (`HomeChargingConfig.no_home_share`) **(A1)**.
      NREL 2030 National Charging Network study assumes 90% of EVs have reliable home charging
      (sensitivity 85–98%); surveys of today's EV drivers: 5.8% (Plug In America 2025) to 14%
      (ChargeLab 2024) without. Mass adoption would raise it (only 33% of all US vehicles park
      where home charging exists today, NREL 2021): try `--no-home-share 0.3` or higher
  - [ ] Local value for CT/Boston: NREL's county-level home-access file (data.nrel.gov/submissions/278)
- [x] Public stations: L2 lot and DC fast, dataset prices, longest stay 4 h / 45 min (`PublicStationConfig`)
  - [ ] Real station locations and detour distances (now placeholders: 1 mi / 5 min, 3 mi / 10 min) **(A7)**
- [x] Charge goal: SOC never below a **20%** buffer (`CommuteConfig.soc_buffer`) **(A8)**

---

## 2. Data and pricing (`pricing.py`, `tariffs.py`, `vehicle.py`, `nhts.py`, `dataset/`)
- [x] Eversource CT VPP supply prices per customer class, Oct 2024 – Oct 2026 (539 weekdays);
      missing weekdays filled from the same month
- [x] Eversource CT *Summary of Connecticut Electric Rates* → `eversource_summary_of_electric_rates.csv`
  - [x] Delivery charges per kWh: Rate 7 (on/off-peak), Rate 27/30/35
  - [x] Demand charges ($/kW per month) for commercial rates
  - [x] Monthly customer (fixed) charges, prorated for partial months
- [x] Eversource CT **Rate EV-L** tariff → `eversource_rate_ev-l.csv` (8 load-factor tiers)
- [x] Delivery added to prices (`site_rate`, `include_delivery`) **(A2, A3)**
- [x] Driver price: pass-through of the utility price, or a flat posted price (`driver_price_per_kwh`;
      `run_commute.py --driver-price public-l2 / public-dcfc / <number>`)
- [x] Site bill: supply + delivery + demand (highest 15-minute load) + customer charge;
      Rate EV-L by the month's load-factor tier (`SiteMeter`, `MonthlyBill`) **(A3)**
- [x] Public charging prices for L2 and DC fast → `charger_prices_summary.csv` **(A2)**
- [x] Vehicle specs: Honda Prologue kWh/mile, max AC/DC rate, DC charging curve **(A4, A9)**
- [x] NHTS 2022 commuters → `derived/nhts_commuters.csv` (`scripts/build_nhts_commuters.py`) **(M1)**
- [x] City of Palo Alto public L2 sessions (`arrival_departure_kWh.csv`) → 4-hour longest stay at
      public L2 (84% of sessions end within 4 h, median 2.3 h). Workplace times come from NHTS
      instead of ACN-Data.
- [ ] Rates for Large C&I / Last Resort customers (Rates 41/55-58); Rate 35 stands in for now
- [ ] Second home price mode `fixed_tou` using the 6-month Rate 7 table (in Modeling_Assumptions.md)

---

## 3. Simulation core (`commute.py`, `simulation.py`, `clock.py`)
- [x] Simulation harness: config, SimClock (15-minute steps), EV, station with M chargers, strategies
- [x] Single-hub `Simulation` (hub at work or at home, move-your-car rule) for the earlier runners
- [x] **`CommuteSimulation`**: home + work + public in one run; cars charge only where the driver is,
      battery drains while driving; step order documented in `commute.py`
- [x] `PlanningView`: what one driver can see (own SOC, schedule, posted prices with on-peak one day
      ahead, own work limits). First version of the agent's observation **(M2)**
- [x] One output folder per run: `outputs/runX_[parameters]/` with summary.txt and params.json

---

## 4. Drivers and vehicles (`ev.py`, `driver.py`, `itinerary.py`)
- [x] Driver model: work hours, commute distance and time; energy per mile on the EV **(M1)**
- [x] Default schedule = NHTS weekday medians (arrive 7:45, leave 16:30, 10.5 mi / 25 min each way)
- [x] Per-driver variation: sample real NHTS commuters (`--sample-drivers`, `--region new-england`)
- [x] Each car's own max charging rate (Prologue: 11.5 kW AC); DC fast follows the charging curve
- [x] Detours to public stations from home (`Itinerary`, `Visit`): start 06:00–22:00, back home
      before the next commute **(A7)**
- [ ] Weekend and errand trips instead of staying home all day (NHTS trip data is in `driver_data/`) **(M1)**
- [ ] Value of time ($/hour) for each driver **(A7)**
- [ ] Stop at a public station on the way home from work instead of a separate trip from home
- [ ] *On hold:* overstay penalty: drivers who don't move on time, plus an hourly overstay fee

---

## 5. Sites and chargers (`sites.py`, `station.py`)
- [x] Sites refactor: a home charger per driver, one work hub, public stations; each site has its
      own chargers, prices and meter (`Site`, `HomeSiteFactory`, `build_work_site`, `build_public_site`)
- [x] Driver types: home L2 / home L1 / no home charger, shares set in config
      (`assign_home_chargers`, `run_greedy.py --home-types`) **(A1)**
- [x] Charger power: home L1 1.4 kW / L2 7.2 kW, work AC or DC at any kW, public L2 7.2 kW,
      DC fast 150 kW **(A4)**
  - [ ] Try faster public L2 (up to 19 kW) and other DC sizes (50–150 kW)
- [x] First come, first served queues at work and at public stations; waiting time tracked
- [ ] Network and maintenance costs per site (MA EVICC example: ~$1,700/yr for 2 L2 ports) **(M4)**
- (Grid caps per site: see section 10)

---

## 6. Strategies (`strategies/`)
- [x] Strategy interface: `decide()` (single hub), `wants_charger()` (plug in at work?),
      `charge_limit_kwh()` (how much now), `public_visit()` (go to a station? which? how much?)
- [x] Baseline: always charge when plugged in (`AlwaysCharge`; fills up at the fastest public
      station when home can't cover tomorrow)
- [x] Baseline: greedy (cheapest slots across home and work over 96 h, keeps the 20% buffer,
      replans when blocked, cheapest public station that fits; `strategies/greedy.py`)
- [ ] Baseline: random
- [ ] Baseline: centralized optimization with full information (MILP, e.g. PuLP or OR-Tools).
      Branch `centralized-strategy` exists (no code yet; update it from `main` first)
- [ ] Independent learners: contextual bandit (LinTS) first, then PPO (Stable-Baselines3) **(M2)**

---

## 7. Results and visualization (`commute.py`, `metrics.py`, `recorder.py`, `viz/`)
- [x] Per-step timeline recording; single-hub dashboard and animated hub GIF
- [x] Home + work + public dashboard (`plot_commute_dashboard`) and animation (`animate_commute`,
      `run_greedy.py --animate`)
- [x] Driver metrics by driver type: cost, $/kWh, share at work / public, on-peak share, missed goal,
      trips below the buffer, waiting hours, time on public charging trips **(M7)**
- [x] Station metrics: revenue, monthly utility bill, margin, energy sold, peak kW per station **(M4, M7)**
  - [ ] Utilization
  - [ ] Include network and maintenance costs in profit (needs section 5)
- [x] Grid metrics: peak load of all home chargers together, and of the work hub **(M7)**
  - [ ] Share of time at `P_max` / transformer cap (needs section 10)

---

## 8. Not built yet: RL environment and reward
- [ ] Wrap `CommuteSimulation` as a multi-agent environment (Gymnasium / PettingZoo style
      `reset(seed)` / `step(actions)`)
- [ ] Observation per driver, starting from `PlanningView` (public info only, no shared data) **(M2)**
- [ ] Action per driver: where (home / work / public station / none), when, and how much to charge
- [ ] Driver reward: −(money + value of time × time) − penalty for missing the charge goal **(M3, A8)**
- [ ] Training runs and checkpoints (Rate et al. needed ~500 simulated days for PPO)

---

## 9. Not built yet: Public station pricing
- [x] First version: posted price from the dataset (L2 $0.39, DC fast $0.485), fixed for the run
- [ ] Daily base price, set once per day before the day starts, using tomorrow's known energy price
- [ ] Cost floor: base price ≥ energy + delivery + allocated demand and fixed cost per kWh **(A6)**
- [ ] Surge multiplier based on site load / `P_max` above 50% **(A5)**
- [ ] Show the price before plug-in and lock it for the whole session
- [ ] Start with a fixed pricing rule (cost-plus + surge)
- [ ] Learning station agents (one pricing action per day), only after driver agents train well **(M2)**

---

## 10. Not built yet: Grid limits
- [ ] Site grid cap `P_max`: when demand is over the cap, share power among plugged-in cars **(A4)**
- [ ] Neighborhood/building transformer cap for home chargers. Greedy now creates a midnight
      "shadow peak" (every home starts at once); this cap is what limits it **(A4)**

---

## 11. Not built yet: Experiments
- [ ] Train/test split by whole months (price data covers Oct 2024 – Oct 2026,
      e.g. train Oct 2024 – Jun 2026, test Jul – Oct 2026) **(M8)**
- [ ] Stress tests: July 2025 (big gap), March 2026 (small gap), January 2026 (flipped prices, 81.8¢ spike)
- [ ] Run each experiment with several random seeds; compare against all baselines
- [ ] Results tables and charts for the final presentation

---

## 12. Docs and housekeeping
- [x] UML diagram, colored by status (`scripts/make_uml_diagram.py` → `.drawio` + PNG)
- [x] README: how to run each scenario
- [x] `CLAUDE.md`: project context for teammates and Claude sessions
- [ ] Keep `Modeling_Assumptions.md` in sync (A9 still says 60 kWh / 0.3 kWh/mi; the price CSV
      description still says Jul 2025 – Jun 2026)
- [ ] Add a `.gitattributes` so Windows checkouts stop showing every file as modified (line endings)

---

## Sprint plan (adjust as needed)
| Sprint | Dates | Lead | Focus |
|---|---|---|---|
| Sprint 3 | Oct 26 – Nov 8 | Kathryn | Data, pricing layers, sites refactor (done) |
| Sprint 4 | Nov 9 – Nov 22 | Nuo | Random + centralized baselines (6), RL environment + reward (8), station pricing (9) |
| Sprint 5 | Nov 23 – Dec 7 | Lidia & Kathryn | Train MARL agents (6, 8), experiments (11), docs and final presentation |

If time runs short, drop learning station agents (9) and grid caps (10) first.
