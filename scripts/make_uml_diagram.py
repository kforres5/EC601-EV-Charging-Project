"""Build resources/decentralized_ev_charging_module_UML.drawio from the current code.

    python scripts/make_uml_diagram.py            # overwrites the .drawio in resources/

Re-running replaces any hand edits made in draw.io, so either edit here and
re-run, or edit the .drawio by hand and stop using this script.
"""
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    Path(__file__).resolve().parents[1] / "resources" / "decentralized_ev_charging_module_UML.drawio")
W = 340          # class box width
ROW = 24
HEAD = 30

PALETTE = {      # package colors: (container fill, container stroke, class header fill)
    "config": ("#fff2cc", "#d6b656"),
    "data": ("#f5f5f5", "#666666"),
    "driver": ("#d5e8d4", "#82b366"),
    "sites": ("#ffe6cc", "#d79b00"),
    "core": ("#dae8fc", "#6c8ebf"),
    "strat": ("#e1d5e7", "#9673a6"),
    "results": ("#f8cecc", "#b85450"),
}

cells = []       # xml strings (containers first, then classes, then edges)
boxes = {}       # id -> (x, y, w, h, package)
_n = [0]


def nid(prefix):
    _n[0] += 1
    return f"{prefix}-{_n[0]}"


def cls(cid, title, attrs, methods, x, y, pkg, w=W, stereotype=None, planned=False, note=None):
    """A UML class box: bold name, attributes, a divider, methods."""
    fill, stroke = PALETTE[pkg]
    rows = len(attrs) + len(methods) + (1 if attrs and methods else 0) + (1 if note else 0)
    h = HEAD + ROW * rows + 6
    label = (f"&laquo;{escape(stereotype)}&raquo;<br>" if stereotype else "") + f"<b>{escape(title)}</b>"
    head = HEAD + (14 if stereotype else 0)
    h += head - HEAD
    dash = "dashed=1;dashPattern=6 4;" if planned else ""
    style = (f"swimlane;fontStyle=0;childLayout=stackLayout;horizontal=1;startSize={head};"
             f"horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=0;"
             f"marginBottom=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
             f"swimlaneFillColor=#ffffff;fontSize=12;{dash}")
    cells.append(f'<mxCell id="{cid}" parent="1" style="{style}" value={quoteattr(label)} vertex="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    yy = head
    text = ("text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=6;"
            "spacingRight=4;overflow=hidden;rotatable=0;points=[[0,0.5],[1,0.5]];portConstraint=eastwest;"
            "whiteSpace=wrap;html=1;fontSize=11;")
    for a in attrs:
        cells.append(f'<mxCell id="{nid(cid)}" parent="{cid}" style="{text}" value={quoteattr(escape(a))} vertex="1">'
                     f'<mxGeometry y="{yy}" width="{w}" height="{ROW}" as="geometry"/></mxCell>')
        yy += ROW
    if attrs and methods:
        cells.append(f'<mxCell id="{nid(cid)}" parent="{cid}" style="line;strokeWidth=1;fillColor=none;align=left;'
                     f'verticalAlign=middle;spacingTop=-1;spacingLeft=3;spacingRight=3;rotatable=0;labelPosition=right;'
                     f'points=[];portConstraint=eastwest;strokeColor={stroke};" vertex="1">'
                     f'<mxGeometry y="{yy + ROW / 2 - 4}" width="{w}" height="8" as="geometry"/></mxCell>')
        yy += ROW
    for m in methods:
        cells.append(f'<mxCell id="{nid(cid)}" parent="{cid}" style="{text}fontFamily=Courier New;fontSize=10.5;" '
                     f'value={quoteattr(escape(m))} vertex="1">'
                     f'<mxGeometry y="{yy}" width="{w}" height="{ROW}" as="geometry"/></mxCell>')
        yy += ROW
    if note:
        cells.append(f'<mxCell id="{nid(cid)}" parent="{cid}" style="{text}fontStyle=2;fontColor=#666666;" '
                     f'value={quoteattr(escape(note))} vertex="1">'
                     f'<mxGeometry y="{yy}" width="{w}" height="{ROW}" as="geometry"/></mxCell>')
    boxes[cid] = (x, y, w, h, pkg)
    return y + h


EDGE_BASE = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;fontSize=10;labelBackgroundColor=#ffffff;"
             "strokeColor=#555555;fontColor=#333333;jettySize=auto;orthogonalLoop=1;")
KIND = {
    "assoc": "endArrow=open;endSize=8;",
    "has": "startArrow=diamondThin;startFill=1;startSize=12;endArrow=open;endSize=8;",
    "uses": "endArrow=open;endSize=8;dashed=1;",
    "impl": "endArrow=block;endFill=0;endSize=12;dashed=1;",
}


def edge(src, dst, label="", kind="assoc", exit=None, entry=None, points=(), label_at=None):
    style = EDGE_BASE + KIND[kind]
    if exit:
        style += f"exitX={exit[0]};exitY={exit[1]};exitDx=0;exitDy=0;"
    if entry:
        style += f"entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;"
    pts = ""
    if points:
        pts = "<Array as=\"points\">" + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in points) + "</Array>"
    cells.append(f'<mxCell id="{nid("e")}" edge="1" parent="1" source="{src}" target="{dst}" '
                 f'style="{style}" value={quoteattr(escape(label))}>'
                 f'<mxGeometry {f"x={chr(34)}{label_at}{chr(34)} " if label_at is not None else ""}'
                 f'relative="1" as="geometry">{pts}</mxGeometry></mxCell>')


containers = []


def package(pkg, title, ids, pad=24, top=40):
    xs = [boxes[i][0] for i in ids]
    ys = [boxes[i][1] for i in ids]
    x2 = [boxes[i][0] + boxes[i][2] for i in ids]
    y2 = [boxes[i][1] + boxes[i][3] for i in ids]
    x, y = min(xs) - pad, min(ys) - top
    w, h = max(x2) - x + pad, max(y2) - y + pad
    fill, stroke = PALETTE[pkg]
    style = (f"rounded=1;arcSize=2;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
             f"opacity=55;align=left;verticalAlign=top;spacingLeft=12;spacingTop=6;fontSize=15;fontStyle=1;"
             f"fontColor=#333333;")
    containers.append(f'<mxCell id="pkg-{pkg}" parent="1" style="{style}" value={quoteattr(escape(title))} '
                      f'vertex="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def note(nid_, text, x, y, w, h):
    style = ("shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;size=14;align=left;"
             "verticalAlign=top;spacingLeft=8;spacingTop=4;fontSize=11;fillColor=#ffffff;strokeColor=#999999;")
    cells.append(f'<mxCell id="{nid_}" parent="1" style="{style}" value={quoteattr(text)} vertex="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    boxes[nid_] = (x, y, w, h, None)


# ======================================================================= layout
C = [0, 380, 760, 1140, 1520, 1900]      # column x
GAP = 30

# ---------------------------------------------------------------- 1. configuration
y = 60
y_cc = cls("CommuteConfig", "CommuteConfig", [
    "start, end, step_minutes (15)",
    "work: WorkHubConfig",
    "home: HomeChargingConfig",
    "public: tuple[PublicStationConfig]",
    "vehicle: VehicleSpec (Honda Prologue)",
    "soc_buffer = 0.20  (charge goal, A8)",
    "peak: PeakWindow",
    "include_delivery, prorate_fixed_charges",
    "public_visit_hours = (6, 22)",
], [], C[0], y, "config", stereotype="config: home + work + public")
y_pub = cls("PublicStationConfig", "PublicStationConfig", [
    "name, kind: L2 | DCFC",
    "num_chargers, charger_kw (7.2 / 150)",
    "detour_minutes, detour_miles (placeholders)",
    "max_dwell_minutes (L2 240 / DC 45)",
    "driver_price_per_kwh (None = dataset)",
    "customer_class, site_rate (27 / EV-L)",
], [], C[0], y_cc + GAP, "config")
y_sc = cls("ScenarioConfig", "ScenarioConfig", [
    "start, end, step_minutes",
    "num_chargers M, charger_kw, charger_type",
    "hub_location (work | home), driver",
    "move_window_minutes, customer_class",
    "site_rate, driver_price_per_kwh",
], [], C[0], y_pub + GAP, "config", stereotype="config: one hub")

y_work = cls("WorkHubConfig", "WorkHubConfig", [
    "num_chargers (M), charger_kw, charger_type",
    "customer_class = small C&I, site_rate = 27",
    "driver_price_per_kwh = $0.25 flat",
    "daily_limit_hours = 4",
    "move_window_minutes = 60",
], [], C[1], y, "config")
y_home = cls("HomeChargingConfig", "HomeChargingConfig", [
    "customer_class = residential, site_rate = 7",
    "charger_kw: L2 7.2 kW, L1 1.4 kW",
    "L2 84% / L1 16% of home chargers",
    "no_home_share = 0.10 (NREL 2030 study)",
], ["shares -> {L2, L1, none}", "assign_home_chargers(n, shares)"], C[1], y_work + GAP, "config")
y_peak = cls("PeakWindow", "PeakWindow", [
    "weekdays 12:00-20:00 on-peak",
    "holidays (TBD)",
], ["is_on_peak(t) -> bool"], C[1], y_home + GAP, "config")
package("config", "Configuration  (config.py)",
        ["CommuteConfig", "PublicStationConfig", "ScenarioConfig", "WorkHubConfig", "HomeChargingConfig", "PeakWindow"])

# ---------------------------------------------------------------- 2. data and pricing
y = 60
y_ps = cls("PriceSchedule", "PriceSchedule", [], [
    "price_at(t) -> $/kWh",
    "is_on_peak(t) -> bool",
], C[2] + 40, y, "data", stereotype="protocol")
y_es = cls("EversourcePriceSchedule", "EversourcePriceSchedule", [
    "daily on/off-peak supply price per class",
    "Oct 2024 - Oct 2026, gaps filled in-month",
], [], C[2] + 40, y_ps + GAP, "data", note="Eversource_Peak_Pricing_History.csv")
y_dp = cls("DeliveredPriceSchedule", "DeliveredPriceSchedule", [
    "supply + on/off-peak delivery $/kWh",
], [], C[2] + 40, y_es + GAP, "data")
y_flat = cls("FlatTOUPriceSchedule", "FlatTOUPriceSchedule", [
    "two fixed prices (tests / no data)",
], [], C[2] + 40, y_dp + GAP, "data")

y_dr = cls("DeliveryRate", "DeliveryRate / EVLRate", [
    "Rate 7, 27, 30, 35: customer, demand, delivery",
    "Rate EV-L: 8 load-factor tiers",
], ["get_rate(rate)", "load_public_prices() -> L2, DCFC"], C[3] + 40, y, "data",
    note="eversource_*.csv, charger_prices_summary.csv")
y_meter = cls("SiteMeter", "SiteMeter", [
    "15-min load blocks per site",
], ["record(t, step, kWh, on_peak, price)", "bills(rate) -> list[MonthlyBill]"], C[3] + 40, y_dr + GAP, "data")
y_bill = cls("MonthlyBill", "MonthlyBill", [
    "supply + delivery + demand + customer",
    "peak_kw, load_factor, EV-L tier",
], [], C[3] + 40, y_meter + GAP, "data")
y_veh = cls("VehicleSpec", "VehicleSpec", [
    "Honda Prologue: 91 kWh, 0.34 kWh/mi",
    "max 11.5 kW AC, 155 kW DC, DC curve",
], ["dc_power_at(soc) -> kW"], C[4] + 40, y, "data", note="honda_prologue_*.csv")
y_nhts = cls("NHTS", "nhts.py", [
    "1,626 weekday NHTS 2022 commuters",
], ["sample_driver_profiles(n, seed, region)", "  -> list[DriverProfile]", "median_profile()"],
    C[4] + 40, y_veh + GAP, "data",
    stereotype="module", note="derived/nhts_commuters.csv")
note("palo", "<b>Palo Alto public L2 sessions</b><br>arrival_departure_kWh.csv<br>"
     "median stay 2.3 h, 84% under 4 h<br>&rarr; public L2 max stay = 4 h", C[4] + 40, y_nhts + GAP, W, 74)
package("data", "Data and pricing  (pricing.py, tariffs.py, vehicle.py, nhts.py, dataset/)",
        ["PriceSchedule", "EversourcePriceSchedule", "DeliveredPriceSchedule", "FlatTOUPriceSchedule",
         "DeliveryRate", "SiteMeter", "MonthlyBill", "VehicleSpec", "NHTS", "palo"])

# ---------------------------------------------------------------- 3. simulation core
Y3 = max(y_sc, y_peak, y_flat, y_bill, boxes["palo"][1] + 74) + 140
y_csim = cls("CommuteSimulation", "CommuteSimulation", [
    "work: Site,  homes: {ev_id: Site},  public: {name: Site}",
    "evs: list[EV],  itinerary: {ev_id: Itinerary}",
    "clock: SimClock,  recorder: TimelineRecorder",
], [
    "add_driver(ev, home_charger: L2 | L1 | none)",
    "run() -> CommuteResult",
    "_step(): 0 public visits  1 leave  2 work rules",
    "         3 plug in / wait  4 charge  5 drive",
], C[1], Y3, "core", w=420)
y_view = cls("PlanningView", "PlanningView", [
    "what one driver can see (public info only)",
    "own SOC, schedule, home charger, work limits",
], [
    "price_forecast(site, t)  (on-peak: 1 day ahead)",
    "work_hours_left(day),  visit_window(station)",
    "site_for(location, t),  power_kw(site)",
], C[1], y_csim + GAP, "core", w=420)
y_clock = cls("SimClock", "SimClock", ["now, step (15 min)"], ["advance()"], C[0], Y3, "core")
y_sim = cls("Simulation", "Simulation", [
    "one hub: ChargingStation + SiteMeter",
    "move-your-car rule, driverless or commuting EVs",
], ["run() -> SimulationResult"], C[0], y_clock + GAP, "core", stereotype="single hub (earlier harness)")
package("core", "Simulation core  (commute.py, simulation.py, clock.py)",
        ["CommuteSimulation", "PlanningView", "SimClock", "Simulation"])

# ---------------------------------------------------------------- 4. drivers and vehicles
X4 = C[2] + 140
y_ev = cls("EV", "EV", [
    "ev_id, battery_kwh, soc, required_soc",
    "kwh_per_mile, vehicle: VehicleSpec",
    "driver: DriverProfile, strategy: Strategy",
    "energy_drawn_kwh, cost, shortfall_kwh",
], [
    "from_vehicle(id, spec, ...)",
    "charge_capacity_kwh(kW, AC|DC, hours)",
    "add_energy(kWh),  drive(miles)",
], X4, Y3, "driver")
y_drv = cls("DriverProfile", "DriverProfile", [
    "work_start 7:45, work_end 16:30 (NHTS median)",
    "commute 10.5 mi / 25 min, work_days Mon-Fri",
], ["segments(day),  location_at(t)", "driving_miles(start, end)"], X4, y_ev + GAP, "driver")
y_loc = cls("Location", "Location", ["HOME, WORK, DRIVING, PUBLIC"], [], X4, y_drv + GAP, "driver",
            stereotype="enum")
X4b = X4 + W + 40
y_it = cls("Itinerary", "Itinerary", [
    "driver: DriverProfile, visits: list[Visit]",
], [
    "location_at(t),  fraction_at(loc, a, b)",
    "driving_miles(a, b)  (commute + detours)",
    "next_home_departure(t),  active_visit(t)",
], X4b, Y3, "driver")
y_vis = cls("Visit", "Visit", [
    "station: Site, leave, target_kwh",
    "latest_depart, planned_depart, depart",
    "charged_kwh, waited_hours",
], [], X4b, y_it + GAP, "driver",
    note="home -> detour -> station -> detour -> home")
package("driver", "Drivers and vehicles  (ev.py, driver.py, itinerary.py)",
        ["EV", "DriverProfile", "Location", "Itinerary", "Visit"])

# ---------------------------------------------------------------- 5. sites and chargers
Y5 = max(y_view, y_sim, y_loc, y_vis) + 130
y_site = cls("Site", "Site", [
    "name, location (HOME | WORK | PUBLIC)",
    "station: ChargingStation, meter: SiteMeter (bill)",
    "supply, utility: PriceSchedule, rate",
    "flat_price (work $0.25, public $0.39 / $0.485)",
    "owner (home), move_window, daily_limit (work)",
    "public_kind, detour, detour_miles, max_dwell",
], ["driver_price(t),  is_on_peak(t)"], C[1], Y5, "sites", w=420)
y_cs = cls("ChargingStation", "ChargingStation", ["chargers: list[Charger]  (first come, first served)"],
           ["plug_in(ev),  unplug(ev),  num_available"], C[0], Y5, "sites")
y_ch = cls("Charger", "Charger", ["charger_id, rate_kw, kind (AC | DC)", "occupied_by: EV | None"], [],
           C[0], y_cs + GAP, "sites")
y_build = cls("SiteBuilders", "site builders", [
    "home: own L2/L1 charger, residential + Rate 7",
    "work: M chargers, small C&I + Rate 27",
    "public L2: Rate 27,  DC fast: Rate EV-L",
], ["HomeSiteFactory.make(ev_id, type)", "build_work_site(cfg)", "build_public_site(cfg, p)"],
    C[1], y_site + GAP, "sites", w=420, stereotype="sites.py")
package("sites", "Sites and chargers  (sites.py, station.py)", ["Site", "ChargingStation", "Charger", "SiteBuilders"])

# ---------------------------------------------------------------- 6. strategies
X6 = 1100
y_st = cls("Strategy", "Strategy", ["name"], [
    "decide(ev, now, price, on_peak) -> bool",
    "wants_charger(ev, ctx) -> bool   (at work)",
    "charge_limit_kwh(ev, ctx) -> kWh (plugged in)",
    "public_visit(ev, view) -> (station, kWh)",
], X6, Y5, "strat", w=380, stereotype="abstract")
y_ctx = cls("ChargeContext", "ChargeContext", ["now, step, site, price, is_on_peak", "view: PlanningView"], [],
            X6 + 420, Y5, "strat")
Y6b = max(y_st, y_ctx) + 70
y_al = cls("AlwaysCharge", "AlwaysCharge", [
    "plug in whenever possible, full power to target",
    "public: if home can't cover next 24 h + buffer,",
    "   fill up at the fastest station (DC first)",
], [], X6 - 200, Y6b, "strat", w=360, stereotype="baseline: uncontrolled")
y_gr = cls("Greedy", "Greedy", [
    "96 h plan, cheapest slots across home / work",
    "keeps SOC >= 20% buffer, never above target",
    "replans when blocked or off plan (Rate et al.)",
    "public: cheapest station covering next 24 h",
], ["plan(ev, view) -> Plan", "_allocate(slots, start, floor, cap)"], X6 + 190, Y6b, "strat", w=360,
    stereotype="baseline: greedy")
Y6c = max(y_al, y_gr) + 60
y_rand = cls("RandomStrategy", "Random", ["random charger / time, ignores price", "seeded RNG"], [],
             X6 - 200, Y6c, "strat", w=360, planned=True, stereotype="planned baseline")
y_cent = cls("Centralized", "Centralized + CentralController", [
    "sees all EVs; joint schedule (MILP: PuLP / OR-Tools)",
], [], X6 + 190, Y6c, "strat", w=360, planned=True, stereotype="planned baseline")
y_marl = cls("MARL", "Independent MARL agent", [
    "one agent per EV: LinTS bandit, then PPO",
    "reward: -(money + value of time) - missed goal",
    "sees only PlanningView (no shared data)",
], [], X6 + 580, Y6c, "strat", w=360, planned=True, stereotype="planned: the project's method")
package("strat", "Strategies  (strategies/)", ["Strategy", "ChargeContext", "AlwaysCharge", "Greedy",
                                              "RandomStrategy", "Centralized", "MARL"])

# ---------------------------------------------------------------- 7. results and viz
Y7 = max(y_build, y_ch, y_rand, y_cent, y_marl) + 130
y_cr = cls("CommuteResult", "CommuteResult", [
    "ev_results, stations, work_bills, timeline",
    "peak_home_kw (+ when), peak_work_kw",
], ["total_cost, work_revenue, work_margin"], C[0], Y7, "results")
y_cer = cls("CommuteEVResult", "CommuteEVResult", [
    "home / work / public kWh and $",
    "on- vs off-peak kWh, $/kWh",
    "trips_below_buffer, hours_below_buffer, shortfall",
    "work + public waiting hours, visits, moves",
], ["missed_goal -> bool"], C[1], Y7, "results")
y_sr = cls("StationResult", "StationResult", ["name, kind, price, revenue, energy, peak_kw", "bills"],
           ["margin = revenue - utility bill"], C[2], Y7, "results")
y_tl = cls("TimelineRecorder", "TimelineRecorder", [
    "StepRecord: time, prices {home, work, public}",
    "EVSnapshot: state, location, SOC, kW, cost",
], ["load_kw_at(location)"], C[3], Y7, "results")
y_viz = cls("viz", "viz/", [], [
    "plot_commute_dashboard(result)",
    "animate_commute(result)  (home/road/work/public)",
    "plot_dashboard(result),  animate_hub(result)",
], C[4], Y7, "results", stereotype="module")
y_srz = cls("SimulationResult", "SimulationResult / EVResult", ["single-hub results + site_bills"], [],
            C[0], y_cr + GAP, "results")
note("runners", "<b>Runners</b><br>run_greedy.py: greedy vs always-charge<br>"
     "&nbsp;&nbsp;(home + work + public; --plot, --animate)<br>run_commute.py, run_fleet_demo.py,<br>"
     "run_single_ev.py: single-hub runs", C[4], y_viz + GAP, W, 100)
package("results", "Results and visualization  (commute.py, metrics.py, recorder.py, viz/)",
        ["CommuteResult", "CommuteEVResult", "StationResult", "TimelineRecorder", "viz", "SimulationResult",
         "runners"])

# ---------------------------------------------------------------- title + legend
cells.insert(0, '<mxCell id="title" parent="1" style="text;html=1;fontSize=22;fontStyle=1;align=left;'
                'verticalAlign=top;" value="Decentralized EV charging simulation: module UML (Nov 2026)" '
                'vertex="1"><mxGeometry x="-24" y="-40" width="1200" height="34" as="geometry"/></mxCell>')
note("legend", "<b>Legend</b><br>&#9670;&rarr; has / owns &nbsp;&nbsp; &rarr; uses &nbsp;&nbsp; "
     "- - &rarr; depends on<br>- - &#9655; implements &nbsp;&nbsp; dashed box = planned, not built yet",
     C[4] + 440, -40, 330, 62)

# ======================================================================= edges
edge("CommuteConfig", "WorkHubConfig", "work", "has", exit=(1, 0.15), entry=(0, 0.3))
edge("CommuteConfig", "HomeChargingConfig", "home", "has", exit=(1, 0.45), entry=(0, 0.3))
edge("CommuteConfig", "PublicStationConfig", "public 0..*", "has", exit=(0.5, 1), entry=(0.5, 0))
edge("CommuteConfig", "PeakWindow", "peak", "has", exit=(1, 0.8), entry=(0, 0.5))
edge("EversourcePriceSchedule", "PriceSchedule", "", "impl", exit=(0.15, 0), entry=(0.15, 1))
edge("DeliveredPriceSchedule", "EversourcePriceSchedule", "wraps supply", "uses", exit=(0.5, 0), entry=(0.5, 1))
edge("FlatTOUPriceSchedule", "PriceSchedule", "", "impl", exit=(0, 0.5), entry=(0, 0.7),
     points=[(C[2] + 20, boxes["FlatTOUPriceSchedule"][1] + 30), (C[2] + 20, boxes["PriceSchedule"][1] + 50)])
edge("SiteMeter", "MonthlyBill", "bills monthly", "assoc", exit=(0.5, 1), entry=(0.5, 0))
edge("SiteMeter", "DeliveryRate", "priced by", "uses", exit=(0.5, 0), entry=(0.5, 1))

edge("CommuteSimulation", "CommuteConfig", "configured by", "uses", exit=(0.05, 0), entry=(1, 0.95),
     points=[(C[1] + 21, Y3 - 70), (360, Y3 - 70),
             (360, boxes["CommuteConfig"][1] + 0.95 * boxes["CommuteConfig"][3])])
edge("CommuteSimulation", "SimClock", "ticks", "has", exit=(0, 0.35), entry=(1, 0.5))
edge("Simulation", "ScenarioConfig", "configured by", "uses", exit=(0, 0.3), entry=(0, 0.6),
     points=[(-12, boxes["Simulation"][1] + 0.3 * boxes["Simulation"][3]),
             (-12, boxes["ScenarioConfig"][1] + 0.6 * boxes["ScenarioConfig"][3])])
edge("CommuteSimulation", "PlanningView", "builds per driver", "assoc", exit=(0.5, 1), entry=(0.5, 0))
edge("CommuteSimulation", "EV", "N drivers", "has", exit=(1, 0.2), entry=(0, 0.2))
edge("CommuteSimulation", "Itinerary", "one per EV", "has", exit=(0.8, 0), entry=(0.5, 0),
     points=[(C[1] + 0.8 * 420, Y3 - 50), (X4b + W / 2, Y3 - 50)])
_sy = boxes["SimClock"][1] + boxes["SimClock"][3] + GAP / 2 + 50
edge("CommuteSimulation", "Site", "homes N, work 1, public K", "has",
     exit=(0, (_sy - boxes["CommuteSimulation"][1]) / boxes["CommuteSimulation"][3]), entry=(0.05, 0),
     points=[(360, _sy), (360, Y5 - 25), (C[1] + 21, Y5 - 25)], label_at=0.55)
_gap_y = boxes["SimClock"][1] + boxes["SimClock"][3] + GAP / 2
_frac = (_gap_y - boxes["CommuteSimulation"][1]) / boxes["CommuteSimulation"][3]
edge("CommuteSimulation", "CommuteResult", "run() produces", "assoc", exit=(0, _frac), entry=(0.1, 0),
     points=[(C[0] - 50, _gap_y),
             (C[0] - 50, Y7 - 60), (C[0] + 0.1 * W, Y7 - 60)])

edge("EV", "DriverProfile", "driver", "assoc", exit=(0.5, 1), entry=(0.5, 0))
edge("EV", "Strategy", "strategy", "assoc", exit=(1, 0.92), entry=((1260 - X6) / 380, 0),
     points=[(1260, boxes["EV"][1] + 0.92 * boxes["EV"][3])])
edge("Itinerary", "DriverProfile", "routine", "assoc", exit=(0, 0.7), entry=(1, 0.3))
edge("Itinerary", "Visit", "visits 0..*", "has", exit=(0.5, 1), entry=(0.5, 0))
edge("Visit", "Site", "public station", "assoc", exit=(0.5, 1), entry=(0.85, 0),
     points=[(X4b + W / 2, Y5 - 62), (C[1] + 0.85 * 420, Y5 - 62)])
edge("DriverProfile", "Location", "", "uses", exit=(0.5, 1), entry=(0.5, 0))

edge("Site", "ChargingStation", "station", "has", exit=(0, 0.2), entry=(1, 0.5))
edge("ChargingStation", "Charger", "M chargers", "has", exit=(0.5, 1), entry=(0.5, 0))
edge("SiteBuilders", "Site", "creates", "assoc", exit=(0.5, 0), entry=(0.5, 1))

edge("AlwaysCharge", "Strategy", "", "impl", exit=(0.5, 0), entry=(0.2, 1))
edge("Greedy", "Strategy", "", "impl", exit=(0.5, 0), entry=(0.8, 1))
edge("RandomStrategy", "Strategy", "", "impl", exit=(0, 0.5), entry=(0, 0.8),
     points=[(X6 - 230, boxes["RandomStrategy"][1] + 30), (X6 - 230, Y5 + 0.8 * boxes["Strategy"][3])])
edge("Centralized", "Strategy", "", "impl", exit=(0.5, 0), entry=(0.5, 1),
     points=[(X6 + 190 + 180, Y6c - 30), (X6 + 190, Y6c - 30)])
edge("MARL", "Strategy", "", "impl", exit=(0.5, 0), entry=(1, 0.8),
     points=[(X6 + 580 + 180, Y5 + 0.8 * boxes["Strategy"][3])])
edge("Strategy", "ChargeContext", "receives", "uses", exit=(1, 0.3), entry=(0, 0.5))
edge("ChargeContext", "PlanningView", "view", "uses", exit=(0.5, 0), entry=(1, 0.5),
     points=[(X6 + 420 + W / 2, Y5 - 48), (850, Y5 - 48),
             (850, boxes["PlanningView"][1] + boxes["PlanningView"][3] / 2)])

edge("CommuteResult", "CommuteEVResult", "per EV", "has", exit=(1, 0.3), entry=(0, 0.3))
edge("CommuteResult", "StationResult", "per station", "has", exit=(1, 0.8), entry=(0, 0.5),
     points=[(C[1] - 20, boxes["CommuteResult"][1] + 0.8 * boxes["CommuteResult"][3]),
             (C[1] - 20, Y7 + boxes["CommuteEVResult"][3] + 15), (C[2] - 20, Y7 + boxes["CommuteEVResult"][3] + 15),
             (C[2] - 20, Y7 + boxes["StationResult"][3] / 2)])
edge("CommuteResult", "TimelineRecorder", "timeline", "has", exit=(0.5, 0), entry=(0.5, 0),
     points=[(C[0] + W / 2, Y7 - 25), (C[3] + W / 2, Y7 - 25)])
edge("viz", "CommuteResult", "plots", "uses", exit=(0.5, 1), entry=(0.5, 1),
     points=[(C[4] + W / 2 - 60, boxes["SimulationResult"][1] + boxes["SimulationResult"][3] + 40),
             (C[0] + W / 2, boxes["SimulationResult"][1] + boxes["SimulationResult"][3] + 40)])

xml = ('<mxfile host="Electron">\n  <diagram name="Module UML" id="ev-uml">\n'
       '    <mxGraphModel dx="1600" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
       'arrows="1" fold="1" page="0" pageScale="1" pageWidth="2400" pageHeight="2600" math="0" shadow="0">\n'
       '      <root>\n        <mxCell id="0"/>\n        <mxCell id="1" parent="0"/>\n'
       + "".join(f"        {c}\n" for c in containers + cells)
       + '      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n')
OUT.write_text(xml, encoding="utf-8")
print("wrote", OUT, len(cells), "cells")
