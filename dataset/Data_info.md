honda_prologue_specs.csv: contains kWh/mile, max AC charge rate, max DC charge rate, and more

honda_prologue_dc_curve.csv: contains honda prologue dc charging curve

charger_prices_summary.csv: contains summary of public charging prices for L2 and fast chargers. Used as the posted price at the simulation's public stations (ev_charging/sites.py).

arrival_departure_kWh.csv: Start Date: Time when the EV plugged in, End Date: Time when the EV unplugged, Energy (kWh): Amount of energy delivered during the session. City of Palo Alto public L2, 2011-2013 (9,999 sessions: median stay 2.3 h, 84% under 4 h, median 5.7 kWh). Used for the 4-hour longest stay at the public L2 lot.

driver_data/household.csv: One household; household size, income, number of workers, number of vehicles, home location type (urban/rural), housing type, and home ownership

driver_data/longdistance.csv: One trip of roughly 50 miles or more, over a longer reporting window; origin and destination type, mode, purpose, and distance.

driver_data/person.csv: One person in a household; age, sex, worker status, driver's license status, education, and the person's travel-related attributes

driver_data/trip.csv: One trip by one person on their assigned travel day; Start and end time, distance, duration, travel mode, trip purpose, and which vehicle was used

driver_data/vehicle.csv: One vehicle owned or available to a household;
make, model, model year, fuel type (gas, diesel, hybrid, plug-in hybrid, EV), annual miles, and ownership

eversource_rate_ev-l.csv: Eversource Rate EV-L (Large Electric Vehicle Charging Service), the EV charging station rate

eversource_summary_of_electric_rates.csv: Eversource CT Summary of Connecticut Electric Rates

derived/nhts_commuters.csv: built from driver_data/trip.csv by scripts/build_nhts_commuters.py. One weekday commuter per row who drove straight from home to work: work start and end times, one-way commute miles and minutes, NHTS trip weight, census division (1 = New England). Used by ev_charging/nhts.py.
