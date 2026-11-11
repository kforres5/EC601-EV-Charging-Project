"""Draw resources/pricing_data_flow.svg: how each data file feeds prices.

    python scripts/make_pricing_diagram.py

Edit the boxes below if the data or pricing code changes. The PNG next to it
was rendered from this SVG in a browser (any SVG viewer or browser can open it).
"""
from pathlib import Path
from xml.sax.saxutils import escape
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / "resources" / "pricing_data_flow.svg")
W, H = 1800, 1120

INK, INK2, MUTED, LINE, SURF, CARD = "#0b0b0b", "#52514e", "#898781", "#c3c2b7", "#fcfcfb", "#ffffff"
CAT = {
    "supply": ("#2a78d6", "Energy supply price"),
    "tariff": ("#eb6834", "Utility charges"),
    "driver": ("#1baf7a", "Driver price"),
    "vehicle": ("#6250d6", "Vehicle"),
    "people": ("#c98500", "Driver schedules"),
}
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'Cascadia Mono', Consolas, Menlo, monospace"

parts = []


def text(x, y, s, size=14, weight=400, fill=INK, anchor="start", family=FONT, italic=False):
    st = ' font-style="italic"' if italic else ""
    parts.append(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
                 f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{st}>{escape(s)}</text>')


def box(x, y, w, h, title, lines, cat=None, mono_lines=(), dashed=False, title_size=15, fill=CARD):
    stroke = LINE
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="1.2"{dash}/>')
    pad = 16
    if cat:
        color = CAT[cat][0]
        parts.append(f'<rect x="{x}" y="{y}" width="6" height="{h}" rx="3" fill="{color}"/>')
        pad = 20
    ty = y + 26
    for i, t in enumerate(title if isinstance(title, list) else [title]):
        text(x + pad, ty, t, size=title_size, weight=650,
             family=MONO if title_size < 15 else FONT)
        ty += 20
    ty += 2
    for ln in lines:
        text(x + pad, ty, ln, size=13, fill=INK2)
        ty += 18
    for ln in mono_lines:
        text(x + pad, ty + 2, ln, size=11.5, fill=MUTED, family=MONO)
        ty += 17


def arrow(points, label=None, label_at=None, dashed=False, halo=False, anchor="middle"):
    d = "M " + " L ".join(f"{px},{py}" for px, py in points)
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    if halo:
        parts.append(f'<path d="{d}" fill="none" stroke="{SURF}" stroke-width="9"/>')
    parts.append(f'<path d="{d}" fill="none" stroke="{INK2}" stroke-width="1.6"{dash} '
                 f'marker-end="url(#head)"/>')
    if label:
        lx, ly = label_at
        for i, ln in enumerate(label if isinstance(label, list) else [label]):
            text(lx, ly + i * 15, ln, size=12, fill=INK2, anchor=anchor, italic=True)


parts.append(f'<rect width="{W}" height="{H}" fill="{SURF}"/>')
parts.append(f'<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
             f'markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
             f'fill="{INK2}"/></marker></defs>')

# ---------------------------------------------------------------- header
text(40, 52, "How the data becomes prices", size=28, weight=700)
text(40, 82, "Every file in dataset/, what the simulation takes from it, and where it ends up: "
     "what drivers pay and what the charging site pays Eversource.", size=15, fill=INK2)

cols = [(40, "1. Data files  (dataset/)"), (500, "2. What the code takes from them"),
        (975, "3. In the simulation"), (1410, "4. Money out")]
for x, t in cols:
    text(x, 130, t, size=14, weight=700, fill=MUTED)
parts.append(f'<line x1="40" y1="142" x2="{W - 40}" y2="142" stroke="{LINE}" stroke-width="1"/>')

AW, BW, CW, DW = 400, 395, 360, 350
AX, BX, CX, DX = 40, 500, 975, 1410

# ---------------------------------------------------------------- column 1: files
rows = {
    "A1": (165, 100), "A2": (285, 100), "A3": (405, 100),
    "A4": (540, 84), "A5": (660, 100), "A6": (790, 100),
}
box(AX, 165, AW, 100, ["Eversource_Peak_Pricing_History.csv"],
    ["Eversource CT Variable Peak Pricing: daily on- and",
     "off-peak supply $/kWh, 4 customer classes,", "Oct 2024 to Oct 2026"], cat="supply", title_size=14)
box(AX, 285, AW, 100, ["eversource_summary_of_electric_rates.csv"],
    ["Rates 7, 27, 30, 35: delivery $/kWh (on/off-peak),",
     "demand $/kW per month, customer $/month"], cat="tariff", title_size=14)
box(AX, 405, AW, 100, ["eversource_rate_ev-l.csv"],
    ["Rate EV-L (EV charging stations): 8 tiers by the",
     "month's load factor, each with its own demand",
     "and delivery charges"], cat="tariff", title_size=14)
box(AX, 540, AW, 84, ["charger_prices_summary.csv"],
    ["Typical public prices: L2 $0.39, DC fast $0.485 /kWh"], cat="driver", title_size=14)
box(AX, 660, AW, 100, ["honda_prologue_specs.csv", "honda_prologue_dc_curve.csv"],
    ["91 kWh usable, 0.34 kWh/mile, 11.5 kW AC max,",
     "DC power by state of charge (peaks ~155 kW)"], cat="vehicle", title_size=14)
box(AX, 790, AW, 100, ["driver_data/trip.csv  (NHTS 2022)"],
    ["scripts/build_nhts_commuters.py turns it into",
     "derived/nhts_commuters.csv: 1,626 real weekday",
     "car commuters"], cat="people", title_size=14)

# ---------------------------------------------------------------- column 2: code
box(BX, 165, BW, 100, "Supply price",
    ["$/kWh at each moment, for the hub's customer", "class; on-peak = weekdays 12:00-20:00"],
    cat="supply", mono_lines=["pricing.py · customer_class, peak"])
box(BX, 285, BW, 100, "Site's Eversource rate",
    ["Delivery $/kWh on/off-peak, demand $/kW above", "the rate's threshold, customer charge"],
    cat="tariff", mono_lines=["tariffs.py · site_rate, include_delivery"])
box(BX, 405, BW, 100, "EV-L tier (if site_rate = \"EV-L\")",
    ["Tier picked each month from the hub's", "load factor (kWh / peak kW × hours)"],
    cat="tariff", mono_lines=["tariffs.py"])
box(BX, 540, BW, 84, "Flat posted price option",
    ["public-l2, public-dcfc, or any $/kWh"],
    cat="driver", mono_lines=["driver_price_per_kwh"])
box(BX, 660, BW, 100, "Vehicle limits",
    ["Battery size and miles per kWh; max charging", "power (AC cap, or DC curve at current SOC)"],
    cat="vehicle", mono_lines=["vehicle.py · cfg.vehicle"])
box(BX, 790, BW, 100, "Driver schedules",
    ["Work hours and commute: when the car is at", "the hub, and miles driven (energy used)"],
    cat="people", mono_lines=["nhts.py · NHTS median, or --sample-drivers"])

# A -> B arrows
for y in (215, 335, 455, 582, 710, 840):
    arrow([(AX + AW, y), (BX - 4, y)])

# ---------------------------------------------------------------- column 3: simulation
C1 = (CX, 200, CW, 230)
box(CX, 200, CW, 230, "Site tariff",
    ["What the hub pays Eversource:", "",
     "• supply $/kWh (from the CSV)",
     "• delivery $/kWh, on- or off-peak",
     "• demand $/kW on the month's highest",
     "   15-minute load",
     "• customer charge $/month",
     "", "Utility price per kWh = supply + delivery"])
C2 = (CX, 500, CW, 110)
box(CX, 500, CW, 110, "Driver price per kWh",
    ["Flat posted price if one is set,",
     "otherwise pass-through: the site's utility", "price per kWh (supply + delivery)"])
C3 = (CX, 680, CW, 210)
box(CX, 680, CW, 210, "Charging, every 15 minutes",
    ["Which cars are at the hub and plugged in", "(schedules, queue, move-your-car rule)", "",
     "kWh each car draws = charger kW,",
     "capped by the car's limits", "",
     "→ kWh per car, hub kWh, hub peak kW"])

# B -> C arrows (into site tariff, driver price, charging)
arrow([(BX + BW, 215), (938, 215), (938, 250), (CX - 4, 250)], "supply $/kWh", (928, 207), anchor="end")
arrow([(BX + BW, 335), (CX - 4, 335)], "rate charges", (936, 327), anchor="middle")
arrow([(BX + BW, 455), (938, 455), (938, 400), (CX - 4, 400)], "EV-L charges", (928, 472), anchor="end")
arrow([(BX + BW, 582), (CX - 4, 582)], "flat price", (936, 574))
arrow([(BX + BW, 710), (CX - 4, 710)], "max kW, battery", (936, 702))
arrow([(BX + BW, 840), (CX - 4, 840)], "at hub? miles", (936, 832))

# site tariff -> driver price (pass-through)
arrow([(CX + 180, 430), (CX + 180, 496)], ["pass-through", "(no flat price)"], (CX + 192, 458),
      dashed=True, anchor="start")

# ---------------------------------------------------------------- column 4: money
box(DX, 200, DW, 150, "Site bill  (monthly)",
    ["supply + delivery + demand + customer",
     "charges, from the hub's metered kWh and", "peak kW (fixed charges prorated for",
     "partial months)"], mono_lines=["result.site_bills"])
box(DX, 395, DW, 80, "Site margin",
    ["drivers' payments − site bill"], mono_lines=["result.site_margin"], fill="#f6f6f3")
box(DX, 520, DW, 110, "Driver cost",
    ["Σ  kWh drawn × driver price per kWh,", "for each car"],
    mono_lines=["EVResult.cost, result.total_cost"])

# C -> D
arrow([(CX + CW, 275), (DX - 4, 275)], "rates", (1385, 267))
arrow([(CX + CW, 565), (DX - 4, 565)], "$/kWh", (1373, 557), halo=True)
arrow([(CX + CW, 840), (1585, 840), (1585, 634)], "kWh per car", (1460, 832))
arrow([(CX + CW, 730), (1375, 730), (1375, 320), (DX - 4, 320)], ["hub kWh,", "peak kW"], (1366, 690),
      anchor="end")
# redraw the $/kWh arrow on top so the crossing reads as a jump
arrow([(CX + CW, 565), (DX - 4, 565)], halo=True)
# D -> margin
arrow([(DX + DW / 2, 350), (DX + DW / 2, 391)])
arrow([(DX + DW / 2, 520), (DX + DW / 2, 479)])

# ---------------------------------------------------------------- not used yet
box(AX, 935, BX + BW - AX, 132, "In the dataset, not used for pricing yet", [], dashed=True, fill=SURF)
for i, (fname, desc) in enumerate([
        ("arrival_departure_kWh.csv", "Palo Alto public L2 sessions, 2011-2013: public-station dwell time and kWh"),
        ("home_charging.txt", "L1 16% / L2 84% of home charging: kept as HOME_CHARGER_MIX for driver types"),
        ("driver_data/ (other tables)", "NHTS household, person, vehicle, long-distance: weekend trips, driver types")]):
    yy = 990 + i * 24
    text(AX + 16, yy, fname, size=12.5, weight=600, family=MONO, fill=INK)
    text(AX + 245, yy, desc, size=13, fill=INK2)

# ---------------------------------------------------------------- legend
lx, ly = 1410, 905
text(lx, ly, "Colour = what the data feeds", size=13, weight=700, fill=MUTED)
for i, (key, (color, label)) in enumerate(CAT.items()):
    yy = ly + 22 + i * 22
    parts.append(f'<rect x="{lx}" y="{yy - 11}" width="6" height="14" rx="3" fill="{color}"/>')
    text(lx + 16, yy, label, size=13, fill=INK2)

text(lx, 1052, "Grey monospace = the code file and the", size=12, fill=MUTED)
text(lx, 1068, "ev_charging/config.py settings for each step.", size=12, fill=MUTED)

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
       + "".join(parts) + "</svg>")
open(OUT, "w").write(svg)
print("wrote", OUT)
