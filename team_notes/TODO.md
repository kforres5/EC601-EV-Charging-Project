# TODO: Getting the Modeling Assumptions Running

Step-by-step work to implement everything in [Modeling_Assumptions.md](Modeling_Assumptions.md).
Tags like **(A3)** or **(M5)** point to the matching section there.
Phases are roughly in order: later phases depend on earlier ones. Within a phase, items can be
split across people. Add a name after an item when you pick it up.

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

---

## Phase 1: Get the missing data (blocks Phases 2 and 5)
- [ ] Download Eversource CT *Summary of Connecticut Electric Rates* (PDF) into `dataset/`
  - [ ] Delivery charges per kWh: Rate 7 (on/off-peak), Rate 27/30/35
  - [ ] Demand charges ($/kW per month) for commercial rates
  - [ ] Monthly customer (fixed) charges
- [ ] Download Eversource CT **Rate EV-L** tariff (EV charging station rate) and summarize its terms
- [ ] Confirm whether holidays count as off-peak, and the peak window for Large C&I / Last Resort
- [ ] Pull more years of VPP history from eversource.com/clp/vpp/vpphistory.aspx (more train/test data)
- [ ] NHTS 2022: typical commute distance, departure and arrival times, weekend trips **(M1)**
- [ ] ACN-Data, JPL site: workplace arrival/departure times and kWh per session **(M1, M5)**
- [ ] Public charging prices in CT for L2 and DC fast (network price lists) **(A2)**
- [ ] Vehicle specs from fueleconomy.gov: kWh/mile, max AC charging rate, DC charging curve **(A4, A9)**
- [ ] Home charging access: share of renters / no home charger, L1 vs L2 (Census ACS, NREL) **(A1)**

---

## Phase 2: Pricing layers (A2, A3, A6)
- [ ] Add a second home price mode `fixed_tou` using the 6-month Rate 7 table (already in the doc)
- [ ] Add delivery charges per kWh (on/off-peak) as config values; start with labeled placeholders
- [ ] Split prices into two things:
  - [ ] **Site cost**: what the site pays the utility (energy + delivery)
  - [ ] **Driver price**: what the driver pays (home = utility bill; work = flat employer fee; public = posted price)
- [ ] Work charging: flat fee per kWh set in config (between home and public); employer's cost uses `small_commercial`
- [ ] Demand charge: track each site's highest 15-minute load per month and bill it monthly
- [ ] Fixed monthly costs per site (customer charge, network, maintenance)
- [ ] Mark results "energy-only" until real delivery and demand numbers are in

---

## Phase 3: Multiple sites and driver types (A1, A4)
- [ ] Refactor the single `station` into a list of **sites**, each with: location, chargers, charger kW,
      customer class, grid cap. Types: home charger (one per driver), work hub, public station(s)
- [ ] Driver types: home L2 / home L1 / no home charger, with shares set in config **(A1)**
- [ ] Charger power levels: L1 1.4 kW, L2 7.2 kW, public L2 7–19 kW, DC fast 50–150 kW **(A4)**
- [ ] Limit charging by each car's own max charging rate
- [ ] DC fast charging slows above ~80% charge (charging curve)
- [ ] Site grid cap `P_max`: when demand is over the cap, share power among plugged-in cars
- [ ] Neighborhood/building transformer cap for home chargers (prevents the 8 PM "shadow peak")
- [ ] Update dashboard and animation to show more than one site

---

## Phase 4: Driver model upgrades (M1, M5, A7, A8)
- [ ] Replace constant schedules with distributions from NHTS / ACN-Data (per-driver variation)
- [ ] Weekend trips (errands) instead of staying home all day
- [ ] Next-day charge goal: enough for tomorrow's driving + a buffer (e.g. 20%), penalty if below **(A8)**
- [ ] Value of time ($/hour) for each driver **(A7)**
- [ ] Detour time/distance from the commute to each public station **(A7)**
- [ ] Work charging limit of X hours/day (value **TBD**) **(M5)**
- [ ] *On hold:* overstay penalty: drivers who don't move on time, plus an hourly overstay fee

---

## Phase 5: Public station pricing (A5, A6, M4)
- [ ] Daily base price, set once per day before the day starts, using tomorrow's known energy price
- [ ] Cost floor: base price ≥ energy + delivery + allocated demand and fixed cost per kWh **(A6)**
- [ ] Surge multiplier based on site load / `P_max` above 50% **(A5)**
- [ ] Show the price before plug-in and lock it for the whole session
- [ ] Station profit accounting: revenue − energy − delivery − demand charge − fixed **(M4)**
- [ ] Start with a fixed pricing rule (cost-plus + surge); learning stations come in Phase 6

---

## Phase 6: Agents and strategies (M2, M3)
- [ ] Decide what each driver agent sees (public info only: prices, own SOC, schedule, station prices)
- [ ] Extend the strategy interface so a driver chooses **where** to charge, not just charge/wait
- [ ] Baselines:
  - [x] Always charge when plugged in (`AlwaysCharge`)
  - [ ] Random
  - [ ] Greedy (cheapest available slot/site)
  - [ ] Centralized optimization with full information (MILP, e.g. PuLP or OR-Tools)
- [ ] Wrap the simulation as a multi-agent RL environment (Gymnasium / PettingZoo style `reset`/`step`)
- [ ] Driver reward: −(money + value of time × time) − penalty for missing the charge goal **(M3)**
- [ ] Independent learners: contextual bandit (LinTS) first, then PPO (Stable-Baselines3)
- [ ] Learning station agents (one pricing action per day), only after driver agents train well

---

## Phase 7: Metrics and evaluation (M7, M8)
- [ ] Driver metrics by driver type: cost, time spent charging/detouring, missed-goal rate
- [ ] Station metrics: profit, utilization, monthly peak kW
- [ ] Grid metrics: peak load, share of time at `P_max` / transformer cap
- [ ] Train/test split by whole months (e.g. train Jul 2025–Mar 2026, test Apr–Jun 2026)
- [ ] Stress tests: July 2025 (big gap), March 2026 (small gap), January 2026 (flipped prices, 81.8¢ spike)
- [ ] Run each experiment with several random seeds; compare against all baselines

---

## Phase 8: Docs and housekeeping
- [ ] Update the UML diagram (`resources/`) with drivers, sites, and pricing layers
- [ ] Keep `Modeling_Assumptions.md` in sync as TBDs get filled in
- [ ] README: how to run each scenario

---

## Suggested sprint split (adjust as needed)
| Sprint | Dates | Focus |
|---|---|---|
| Sprint 3 | Oct 26 – Nov 8 | Phase 1 (data), Phase 2 (pricing layers), start the Phase 3 site refactor |
| Sprint 4 | Nov 9 – Nov 22 | Finish Phase 3, Phases 4–5, baselines from Phase 6 |
| Sprint 5 | Nov 23 – Dec 7 | MARL agents (Phase 6), evaluation (Phase 7), docs and final presentation |
