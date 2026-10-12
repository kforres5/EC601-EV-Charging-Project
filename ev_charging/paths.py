"""Repo-relative paths so scripts work from any working directory (Windows or not)."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = REPO_ROOT / "dataset"
EVERSOURCE_CSV = DATASET_DIR / "Eversource_Peak_Pricing_History.csv"
