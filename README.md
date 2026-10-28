# EC601-EV-Charging-Project
This repository documents work done on an EV charging optimization project.

## Running the simulation

```
pip install -r requirements.txt
python run_single_ev.py                  # 1 EV, 0% -> 100%, prints the cost
python run_single_ev.py --plot --animate # also saves outputs/single_ev_dashboard.png and single_ev_hub.gif
python run_fleet_demo.py --evs 6 --chargers 2 --plot --animate   # cars queueing for chargers
python run_fleet_demo.py --show          # open the charts in a window instead of saving
python -m pytest
```

Assumptions (battery size, charger power, peak hours, customer class, dates) live in
`ev_charging/config.py`. Charts and animations are in `ev_charging/viz/` and read the
per-step timeline that `Simulation` records (`result.timeline`).
