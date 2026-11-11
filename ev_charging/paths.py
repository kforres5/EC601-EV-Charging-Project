"""Repo-relative paths so scripts work from any working directory (Windows or not)."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = REPO_ROOT / "dataset"
DERIVED_DIR = DATASET_DIR / "derived"

EVERSOURCE_CSV = DATASET_DIR / "Eversource_Peak_Pricing_History.csv"
RATE_SUMMARY_CSV = DATASET_DIR / "eversource_summary_of_electric_rates.csv"
RATE_EVL_CSV = DATASET_DIR / "eversource_rate_ev-l.csv"
PUBLIC_PRICES_CSV = DATASET_DIR / "charger_prices_summary.csv"
VEHICLE_SPECS_CSV = DATASET_DIR / "honda_prologue_specs.csv"
VEHICLE_DC_CURVE_CSV = DATASET_DIR / "honda_prologue_dc_curve.csv"
NHTS_DIR = DATASET_DIR / "driver_data"
NHTS_COMMUTERS_CSV = DERIVED_DIR / "nhts_commuters.csv"
