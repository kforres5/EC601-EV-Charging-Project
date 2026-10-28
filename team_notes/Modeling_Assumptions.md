# Modeling Assumptions & Pricing Plan

Revised assumptions and modeling for the decentralized EV charging simulation, plus how to
price charging with the data we have and what data we still need.
Items marked **TBD** are placeholders until we get the source listed in [Data still needed](#data-still-needed).

---

## Assumptions

### A1. Drivers have different home-charging access
Real-world check: most EV charging happens at home (an often-cited figure is ~80%), and a
single-car household drives ~50 miles/day (2022 NHTS), about 15 kWh. A Level 2 home charger
refills that in ~2 hours, so "home is too slow" is not true for most drivers.

We model a **mix of driver types** instead, so the drivers who must use work/public chargers
are the ones who actually would in real life:

| Driver type | Home charger | Notes |
|---|---|---|
| Home L2 | 7.2 kW | Can usually meet daily needs at home |
| Home L1 | ~1.4 kW (wall outlet) | Falls short with long commutes |
| No home charging | none | Renters / street parking; relies on work + public |

Shares of each type are scenario parameters (**TBD**: set from housing/renter data, see sources).
Long-commute or high-mileage drivers can be added the same way.

### A2. What drivers pay
- **Home:** time-of-use price. Energy part from the CSV (`residential` column). Peak is
  **weekdays 12:00–20:00**; off-peak is all other weekday hours and all weekend. Plus delivery
  charges (**TBD**).
- **Work:** a flat fee per kWh set by the employer, cheaper than public charging and more
  expensive than home. Only available while the driver is at work, for at most **X hours/day**.
- **Public stations:** a posted price per kWh made of
  - a **daily base price**, set once per day before the day starts (like a gas station), and
  - a **surge multiplier** applied when the station is busy (see A5).

  The price is **shown before plug-in and locked for the whole session** (the federal NEVI
  rule for funded chargers requires exactly this).

### A3. What charging sites pay
A site's utility bill has four parts:

| Cost | How it works | Source |
|---|---|---|
| Energy | price(t) × kWh drawn, using the CSV | CSV `small_commercial` (or `last_resort` for sites ≥ 500 kW) |
| Delivery | per kWh, may differ on/off-peak | **TBD** (Eversource CT rate summary) |
| **Demand charge** | $/kW × the site's **single highest 15-minute load in the month** | **TBD** (commercial tariff / Rate EV-L) |

cost_for_charging_site = energy + delivery + demand charge

Cost does **not** rise "per car while busy". Energy cost is linear in kWh. Simultaneous charging
is punished through the **monthly demand charge**: one busy afternoon sets the charge for the month.

### A4. Charger power and grid limits
| Charger | Power (kW) | Notes |
|---|---|---|
| Home L1 | ~1.4 | |
| Home L2 | 7.2 | |
| Work L2 | 7.2 (same as home L2) | Faster than home L1 only |
| Public L2 | 7–19 | |
| Public DC fast | 50–150+ | Slows down above ~80% charge |

- Each public site has a **grid connection cap** `P_max` (kW), smaller than all its chargers at
  full power. When total demand exceeds `P_max`, power is shared among plugged-in cars, so each
  car charges slower.
- Each car is also limited by its own maximum charging rate.
- Home and work chargers can also share a neighborhood/building transformer cap. This is what
  stops every home car from starting at exactly 20:00 (the "shadow peak").

### A5. Surge pricing is based on load, not number of cars
The surge multiplier is a function of **site load / `P_max`**, starting above 50%, not of how many
chargers are occupied. The site's cost depends on kW, not on plugged-in cars, and 10 cars sharing a
capped connection should not trigger a surge if the site's load (and cost) has not gone up.
(Real precedent: Tesla has adjusted Supercharger prices by live site utilization since Nov 2025.)

### A6. Stations never price below cost
Daily base price ≥ **cost floor** = tomorrow's energy price (on-peak price is announced a day
ahead, so this is known) + delivery + allocated demand and fixed cost per kWh.
Note: many real low-use stations do run at a loss (often subsidized). This is a deliberate
simplification.

### A7. Drivers care about time as well as money
Each driver has a **value of time** ($/hour). Going to a public station costs detour time plus
time spent charging. Without this, every driver goes to the cheapest station and prices race down
to the cost floor.

### A8. Charge goals span days
A driver's goal is to have enough charge for **the next day's driving plus a safety buffer**
(e.g. 20%). Falling below it is penalized. This stops agents from learning to arrive at work empty.

### A9. Vehicles are identical (from the spec)
Same battery size (60 kWh default) and efficiency (~0.3 kWh/mile, **TBD**: confirm from EPA data).

---

## Modeling

### M1. Driver model
A daily schedule per driver: home → commute (distance *d*) → work (hours *h*) → home, with
weekends different. Energy used = miles × kWh/mile.
Calibrate trip distances and times from NHTS, and work arrival/departure times from ACN-Data's
JPL site (an employees-only workplace garage).

### M2. Agents
- **Drivers:** independent MARL agents. Each 15-minute step: where to charge (home / work /
  public station *i* / none) and whether to charge now.
- **Stations:** start with a **fixed pricing rule** (cost-plus base price + load surge). Make them
  learning agents (one action per day) only after driver agents train well. Two kinds of learning
  agents at once makes training much less stable (Rate et al. needed ~500 simulated days for PPO
  with one kind).

### M3. Driver objective
Minimize money spent + value of time × time spent, subject to the charge goal (A8; penalty if missed).

### M4. Station objective
Maximize profit = revenue − energy − delivery − demand charge (billed monthly) − fixed,
with base price ≥ cost floor (A6).

### M5. Work charging
Available only during work hours, at most X hours/day, with a limited number of work chargers
(first come, first served, plus a "move your car after X hours" rule).

### M6. Time scales
| What | How often |
|---|---|
| Driver decisions, energy billing | every 15 minutes |
| Station base price | once per day |
| Demand charge | once per month (on the month's peak) |

### M7. Metrics
- **Drivers:** total cost, time spent charging/detouring, missed-goal rate. Report per driver type.
- **Stations:** profit, utilization, monthly peak kW.
- **Grid:** peak load, share of time at `P_max` / transformer cap.

Baselines: random, greedy (cheapest slot), and centralized optimization with full information.

### M8. Train / test split
Hold out **whole months**, not random days (e.g. train Jul 2025–Mar 2026, test Apr–Jun 2026).
Make sure test data includes unusual months (see the January notes below).

---

## How to simulate prices with the CSV we have

**What the CSV is:** Eversource **Connecticut** *Variable Peak Pricing* (VPP) history,
Jul 2025–Jun 2026, weekdays only. It is the **energy (supply) part only**, with no delivery or
demand charges. The on-peak price changes daily (announced a day ahead). The off-peak price is
fixed for each month.

### Which column for whom
| Who | Column | Avg on-peak | Avg off-peak | Ratio | Days on-peak < off-peak |
|---|---|---|---|---|---|
| Home (Rate 7 customers) | `residential` | 14.7¢ | 9.9¢ | 1.49 | 21 / 258 |
| Work & public sites (< 500 kW) | `small_commercial` | 13.9¢ | 9.8¢ | 1.42 | 34 / 258 |
| Large hubs (≥ 500 kW) | `last_resort` | 11.8¢ | 10.7¢ | 1.10 | **156 / 258** |

`large_commercial` is nearly identical to `small_commercial`. For `last_resort`, on-peak is
cheaper than off-peak on most days, so a large hub has almost no reason to avoid on-peak.

### Rules for turning the CSV into a price at any time
1. **Peak window:** weekdays 12:00–20:00 (confirmed by Eversource and EnergizeCT for Rate 7, and
   for Rate 27 small business). Set `PeakWindow(start_hour=12, end_hour=20)`.
   The current `config.py` default is still 7–23 and needs this change.
   Large C&I / Last Resort windows are **TBD** (confirm in the tariff).
2. **Weekends:** off-peak all day, using that month's off-peak price. Already handled.
3. **Holidays:** **TBD** whether they count as off-peak. The CSV has rows on 7/4, 12/25 and 1/1.
   `PeakWindow.holidays` can list them once confirmed.
4. **Missing weekdays** (9/30/2025, 6/1/2026, 6/29/2026): borrow the nearest same-month row.
   Already handled.
5. **What agents can see:** tomorrow's on-peak price is public a day ahead, so stations setting a
   daily price and drivers planning tomorrow may see it. Test a "yesterday only" version too.
6. **Add what the CSV is missing:** delivery (per kWh, on/off-peak) and, for sites, the demand
   charge and fixed costs. Until we have real numbers, run with clearly labeled placeholders and
   report results as "energy-only".

### Things in the data worth testing on purpose
- **July 2025:** biggest on/off-peak gap (residential ratio ~2.2). Strongest reason to shift.
- **March 2026:** smallest gap (~1.2). Weakest reason to shift.
- **January 2026:** on-peak cheaper than off-peak on 9 of 22 weekdays, then a spike to 81.8¢ on
  1/27. A strategy that avoids peak "by the clock" loses money here; one that reads the price doesn't.

### Optional second home-price mode: fixed Rate 7 TOU
Most TOU customers are not on VPP. Standard Rate 7 has fixed energy prices for 6 months at a time
(same noon–8 PM peak), per EnergizeCT:

| Period | Peak (¢/kWh) | Off-peak (¢/kWh) |
|---|---|---|
| Jul–Dec 2025 | 12.282 | 8.782 |
| Jan–Jun 2026 | 15.246 | 11.746 |
| Jul–Dec 2026 | 14.129 | 10.629 |

Adding this as `price_mode="fixed_tou"` lets us compare "fixed TOU" vs "daily VPP" for home charging.

### Framing
This is **Connecticut** data. Describe results as "Eversource Connecticut time-of-use customers".
Massachusetts residential customers currently pay one flat supply price at every hour.

---

## Data still needed

| Priority | What | Why | Where |
|---|---|---|---|
| 1 | Eversource CT *Summary of Connecticut Electric Rates* | Delivery charges (Rate 7 on/off-peak, Rate 27/30/35), demand charges $/kW | eversource.com → CT rates & tariffs (PDF wouldn't load for us; download manually) |
| 1 | Eversource CT **Rate EV-L** tariff | The EV charging station rate; likely the real tariff for our sites | eversource.com CT tariffs (rate-ev-l.pdf) |
| 2 | More VPP history | More than one year for training/testing | eversource.com/clp/vpp/vpphistory.aspx |
| 2 | NHTS 2022 | Commute distances, trip times, daily miles | nhts.ornl.gov |
| 2 | ACN-Data (JPL site) | Real workplace arrival/departure/kWh | ev.caltech.edu/dataset |
| 3 | Public charging prices in CT | Realistic posted prices for L2 and DC fast | Network price lists; MA EVICC fee guidance ($0.30–0.40/kWh L2) |
| 3 | Vehicle specs | kWh/mile, max AC rate, DC charging curve | fueleconomy.gov (EPA) |
| 3 | Home charging access | Shares of driver types (A1) | Census ACS (renters / housing type), NREL home-charging studies |
| Optional | ISO-NE hourly wholesale prices | A wholesale-indexed price scenario | iso-ne.com pricing reports, or the `gridstatus` Python library |

---

## References
- Eversource CT Variable Peak Pricing: https://www.eversource.com/clp/vpp/vpp.aspx
- EnergizeCT residential standard service rates (Rate 7): https://www.energizect.com/rate-board-residential-standard-service-generation-rates
- Eversource CT Time-of-Day Rate 7: https://www.eversource.com/residential/account-billing/manage-bill/about-your-bill/rates-tariffs/connecticut-time-of-day-rate-7
- 23 CFR 680.116 (NEVI price display): https://www.law.cornell.edu/cfr/text/23/680.116
- Tesla dynamic Supercharger pricing (Nov 2025): https://www.notateslaapp.com/news/3330/tesla-adds-dynamic-supercharger-pricing-to-550-locations
- DOE FOTW #1332, daily miles (2022 NHTS): https://www.energy.gov/node/4838556
- MA EVICC charging fee guidance: https://www.mass.gov/doc/determining-an-appropriate-energy-based-charging-fee/download
- Bailey et al., EV shadow peaks under TOU (NBER w32886, 2024): https://www.nber.org/papers/w32886
- Rate et al., Independent MARL for EV fleets (arXiv:2606.31347): https://arxiv.org/abs/2606.31347
- ACN-Data paper: https://ev.caltech.edu/assets/pub/ACN_Data_Analysis_and_Applications.pdf
