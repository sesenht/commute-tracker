"""Shared configuration for the commute tracker.

Addresses are read from the COMMUTE_ROUTES_JSON environment variable when set
(GitHub Actions secret), otherwise from scripts/routes.json. Keeping them out of
the committed CSV means the log itself contains no home addresses -- only the
labels "home1" / "home2" -- so the repository can be public if you want
unlimited Actions minutes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
ROUTES_FILE = REPO_ROOT / "scripts" / "routes.json"

# Sampling windows, local Pacific time, Monday-Friday.
# (start_minutes, end_minutes) measured from local midnight, both inclusive.
MORNING = (7 * 60, 11 * 60)          # 07:00 -> 11:00, home -> office
AFTERNOON = (14 * 60, 17 * 60 + 30)  # 14:00 -> 17:30, office -> home

SAMPLE_INTERVAL_MIN = 15

# GitHub's scheduler is best-effort and often fires a few minutes late. Accept
# runs slightly outside the window and snap them back onto the nearest slot,
# rather than dropping the first and last sample of every window.
GRACE_MIN = 10

CSV_FIELDS = [
    "sampled_at_utc",
    "local_date",
    "local_time",
    "weekday",
    "slot",
    "period",
    "direction",
    "home",
    "duration_s",
    "duration_min",
    "static_duration_s",
    "distance_m",
    "delay_ratio",
    "status",
    "note",
]

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday"]


def load_routes() -> dict:
    """Return {"office": str, "homes": {"home1": str, "home2": str}}."""
    raw = os.environ.get("COMMUTE_ROUTES_JSON", "").strip()
    if raw:
        cfg = json.loads(raw)
        source = "COMMUTE_ROUTES_JSON"
    elif ROUTES_FILE.exists():
        cfg = json.loads(ROUTES_FILE.read_text())
        source = str(ROUTES_FILE)
    else:
        raise SystemExit(
            "No route configuration found. Set the COMMUTE_ROUTES_JSON secret "
            f"or create {ROUTES_FILE} (see routes.example.json)."
        )

    if "office" not in cfg or "homes" not in cfg:
        raise SystemExit(f"Route config from {source} needs 'office' and 'homes' keys.")
    if not cfg["homes"]:
        raise SystemExit(f"Route config from {source} lists no homes.")
    return cfg


def slot_label(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def monthly_csv_path(local_dt) -> Path:
    return DATA_DIR / f"commute_{local_dt:%Y-%m}.csv"
