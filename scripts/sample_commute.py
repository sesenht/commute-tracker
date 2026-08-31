#!/usr/bin/env python3
"""Sample traffic-aware driving times between home(s) and the office.

Runs from GitHub Actions every 15 minutes. Each invocation decides for itself
whether the current Pacific local time falls inside a sampling window; if not it
exits quietly without spending an API call.

  morning   07:00-11:00 PT, Mon-Fri, home -> office
  afternoon 14:00-17:30 PT, Mon-Fri, office -> home

Results are appended to data/commute_YYYY-MM.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from config import (
    AFTERNOON,
    CSV_FIELDS,
    DATA_DIR,
    GRACE_MIN,
    LOCAL_TZ,
    MORNING,
    SAMPLE_INTERVAL_MIN,
    WEEKDAY_NAMES,
    load_routes,
    monthly_csv_path,
    slot_label,
)

ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"

# TRAFFIC_AWARE_OPTIMAL is the highest-fidelity live-traffic model and is what
# google.com/maps itself shows. It bills under the Routes "Pro" SKU, which
# includes 5,000 free calls per month -- roughly 3.5x this job's usage.
ROUTING_PREFERENCE = "TRAFFIC_AWARE_OPTIMAL"
FIELD_MASK = "routes.duration,routes.staticDuration,routes.distanceMeters"

MAX_ATTEMPTS = 4


# --------------------------------------------------------------------------- #
# Window logic
# --------------------------------------------------------------------------- #

def classify(local_dt) -> tuple[str, str, int] | None:
    """Return (period, direction, slot_minutes) or None if outside a window."""
    if local_dt.weekday() > 4:  # Saturday / Sunday
        return None

    minutes = local_dt.hour * 60 + local_dt.minute

    for period, (start, end), direction in (
        ("morning", MORNING, "home_to_office"),
        ("afternoon", AFTERNOON, "office_to_home"),
    ):
        if start - GRACE_MIN <= minutes <= end + GRACE_MIN:
            # Snap a late-firing run back onto the grid, then clamp into range.
            snapped = round(minutes / SAMPLE_INTERVAL_MIN) * SAMPLE_INTERVAL_MIN
            snapped = max(start, min(end, snapped))
            return period, direction, snapped

    return None


# --------------------------------------------------------------------------- #
# Routes API
# --------------------------------------------------------------------------- #

def compute_route(origin: str, destination: str, api_key: str) -> dict:
    """Call the Routes API once. Raises RuntimeError on unrecoverable failure."""
    body = json.dumps({
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "DRIVE",
        "routingPreference": ROUTING_PREFERENCE,
        "computeAlternativeRoutes": False,
        "languageCode": "en-US",
        "units": "IMPERIAL",
    }).encode()

    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        },
    )

    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
            routes = payload.get("routes") or []
            if not routes:
                raise RuntimeError(f"no route returned: {payload}")
            return routes[0]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            last_error = f"HTTP {exc.code}: {detail}"
            # 4xx other than 429 will not fix themselves; stop early.
            if exc.code != 429 and 400 <= exc.code < 500:
                break
        except Exception as exc:  # noqa: BLE001 - network flakiness
            last_error = f"{type(exc).__name__}: {exc}"

        if attempt < MAX_ATTEMPTS:
            time.sleep(2 ** attempt + random.random())

    raise RuntimeError(last_error or "unknown error")


def seconds(value) -> float | None:
    """Routes API durations look like '1234s'."""
    if not value:
        return None
    try:
        return float(str(value).rstrip("s"))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #

def append_rows(path, rows) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="sample even if the current time is outside a window")
    parser.add_argument("--mock", action="store_true",
                        help="fabricate plausible durations instead of calling the API")
    args = parser.parse_args()

    now_utc = datetime.now(timezone.utc)
    local_dt = now_utc.astimezone(LOCAL_TZ)

    window = classify(local_dt)
    if window is None:
        if not args.force:
            print(f"{local_dt:%Y-%m-%d %H:%M %Z} is outside the sampling windows; "
                  "nothing to do.")
            return 0
        # Forced run outside a window: attribute it to the nearer direction.
        minutes = local_dt.hour * 60 + local_dt.minute
        if minutes < 12 * 60 + 30:
            window = ("morning", "home_to_office",
                      round(minutes / SAMPLE_INTERVAL_MIN) * SAMPLE_INTERVAL_MIN)
        else:
            window = ("afternoon", "office_to_home",
                      round(minutes / SAMPLE_INTERVAL_MIN) * SAMPLE_INTERVAL_MIN)

    period, direction, slot_minutes = window

    routes_cfg = load_routes()
    office = routes_cfg["office"]
    homes = routes_cfg["homes"]

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key and not args.mock:
        print("GOOGLE_MAPS_API_KEY is not set.", file=sys.stderr)
        return 1

    base_row = {
        "sampled_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local_date": local_dt.strftime("%Y-%m-%d"),
        "local_time": local_dt.strftime("%H:%M"),
        "weekday": WEEKDAY_NAMES[local_dt.weekday()],
        "slot": slot_label(slot_minutes),
        "period": period,
        "direction": direction,
    }

    rows, failures = [], 0
    for home_label, home_address in sorted(homes.items()):
        origin, destination = (
            (home_address, office) if direction == "home_to_office"
            else (office, home_address)
        )
        row = dict(base_row, home=home_label)

        try:
            if args.mock:
                base = 45 * 60 if home_label == "home1" else 40 * 60
                duration = base * random.uniform(0.85, 1.6)
                route = {
                    "duration": f"{duration:.0f}s",
                    "staticDuration": f"{base * 0.8:.0f}s",
                    "distanceMeters": 64000,
                }
            else:
                route = compute_route(origin, destination, api_key)

            duration_s = seconds(route.get("duration"))
            static_s = seconds(route.get("staticDuration"))
            row.update({
                "duration_s": f"{duration_s:.0f}" if duration_s else "",
                "duration_min": f"{duration_s / 60:.1f}" if duration_s else "",
                "static_duration_s": f"{static_s:.0f}" if static_s else "",
                "distance_m": route.get("distanceMeters", ""),
                "delay_ratio": (f"{duration_s / static_s:.3f}"
                                if duration_s and static_s else ""),
                "status": "ok",
                "note": "",
            })
            print(f"  {home_label} {direction}: {duration_s / 60:.1f} min")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            row.update({
                "duration_s": "", "duration_min": "", "static_duration_s": "",
                "distance_m": "", "delay_ratio": "",
                "status": "error", "note": str(exc)[:300].replace("\n", " "),
            })
            print(f"  {home_label} {direction}: FAILED - {exc}", file=sys.stderr)

        rows.append(row)

    append_rows(monthly_csv_path(local_dt), rows)
    print(f"Wrote {len(rows)} row(s) for slot {base_row['slot']} "
          f"({base_row['weekday']} {base_row['local_date']}).")

    # A transient API failure is recorded as an error row, not a red build. Only
    # a total failure -- every leg down -- is worth alerting on.
    return 1 if failures == len(rows) else 0


if __name__ == "__main__":
    sys.exit(main())
