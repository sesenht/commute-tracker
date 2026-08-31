# Commute tracker

Samples live-traffic driving times between two homes and the an office
every 15 minutes, on a schedule, from GitHub Actions — then builds a
weekday × time-of-day heatmap so you can see which days and hours are actually
cheapest to drive.

| | |
|---|---|
| **Morning** | 07:00–11:00 PT, Mon–Fri, each home → office |
| **Afternoon** | 14:00–17:30 PT, Mon–Fri, office → each home |
| **Cadence** | every 15 minutes → 32 samples/day, 64 API calls/day |
| **Log** | `data/commute_YYYY-MM.csv`, committed by the workflow |
| **Report** | `report.md` + `report.html`, rebuilt weekly |

## Why the API and not google.com/maps

The job asks Google's **Routes API** for the same live-traffic estimate that
maps.google.com shows, using `routingPreference: TRAFFIC_AWARE_OPTIMAL`.
Driving a headless browser against Google Maps from a cloud IP breaks on layout
changes, trips bot detection, and violates the Maps ToS. The API returns the
number directly, in ~300 ms, and it is free at this volume.

**Cost: $0.** Traffic-aware `computeRoutes` bills under the Routes **Pro** SKU,
which includes 5,000 free calls per month. This job uses about **1,390/month**
(64/day × ~21.7 weekdays) — roughly 28% of the allowance. Billing must still be
enabled on the Google Cloud project, so put a budget alert at $1 if you want a
tripwire.

**GitHub Actions minutes: free.** This repo is public, and Actions minutes are
unlimited on public repos. (On a private repo the same schedule would run ~220
runs/week ≈ **950 min/month** against the 2,000 free minutes — most runs exit in
seconds without calling the API, but Actions rounds each job up to a minute.)

Nothing published here reveals where you live: the committed CSV contains only
the labels `home1` / `home2`, and the addresses live in the
`COMMUTE_ROUTES_JSON` secret, which is never printed to logs.

## Setup

**1. Create the repo**

```bash
git init && git add . && git commit -m "commute tracker"
gh repo create commute-tracker --public --source=. --push
```

**2. Get a Routes API key**

- <https://console.cloud.google.com> → new project → enable **Routes API**
- APIs & Services → Credentials → **Create credentials → API key**
- Restrict it: *API restrictions* → **Restrict key** → Routes API only.
  Skip IP restriction — GitHub runners have no stable egress IP.
- Billing must be enabled on the project or every call returns `403`.

**3. Add two repository secrets**

Settings → Secrets and variables → Actions → *New repository secret*:

| Secret | Value |
|---|---|
| `GOOGLE_MAPS_API_KEY` | the key from step 2 |
| `COMMUTE_ROUTES_JSON` | the JSON below, on one line |

```json
{"office":"<office address>","homes":{"home1":"<first home address>","home2":"<second home address>"}}
```

**4. Let the workflow commit**

Settings → Actions → General → Workflow permissions → **Read and write
permissions**. Without this the sample runs but the push is rejected.

**5. Smoke-test**

Actions → *Sample commute times* → **Run workflow** with `mock: true`. That
writes a fake row without touching the API and proves the commit path works.
Then run it again with `mock: false` to confirm the key works, and delete the
test rows from `data/` before the real collection starts.

The schedule takes over on its own from there.

## How the schedule handles Pacific time

GitHub cron is UTC-only and has no DST awareness, so the workflow schedules a
*superset* of the needed hours in UTC and `sample_commute.py` decides whether
the current **local** time is inside a window — exiting without an API call if
not. That covers PDT (UTC−7) and PST (UTC−8) with no seasonal edits, and it is
verified to produce all 32 daily slots in both offsets and across both DST
switch weekends.

Cron is also best-effort; runs fire late under load. Each sample records its
true timestamp in `local_time` and snaps to the nearest 15-minute `slot`, with a
±10-minute grace at the window edges so a delayed 07:00 run still lands on the
07:00 slot instead of being dropped.

## Data

`data/commute_YYYY-MM.csv`, one row per home per sample:

| Column | Meaning |
|---|---|
| `sampled_at_utc` | when the call was actually made |
| `local_date`, `local_time`, `weekday` | Pacific local time |
| `slot` | the 15-minute bucket the sample is assigned to |
| `period` | `morning` / `afternoon` |
| `direction` | `home_to_office` / `office_to_home` |
| `home` | `home1` / `home2` — the keys from the routes secret |
| `duration_s`, `duration_min` | drive time **with live traffic** |
| `static_duration_s` | free-flow drive time, no traffic |
| `delay_ratio` | `duration / static_duration` — 1.0 is an empty road |
| `distance_m` | route distance |
| `status`, `note` | `ok`, or `error` plus the failure text |

A failed API call writes an `error` row rather than a gap, so you can tell
"no data" apart from "the road was fine."

## Reading the results

```bash
python3 scripts/analyze.py            # writes report.md and report.html
open report.html
```

Cells are **medians**, not means — one accident on one Tuesday should not decide
which day you drive. Both homes are colour-scaled on a shared range per
direction, so the two grids are directly comparable. Cells with fewer than two
samples stay blank; pass `--min-samples 4` once you have a month of data to
suppress thin cells harder.

Give it three to four weeks before drawing conclusions. Two weeks is enough to
see the rush-hour shape, not enough to separate a genuinely quiet Friday from a
holiday week.

## Changing the setup

| To change | Edit |
|---|---|
| Window hours | `MORNING` / `AFTERNOON` in `scripts/config.py`, then widen the UTC hours in `.github/workflows/sample.yml` to match |
| Sample interval | `SAMPLE_INTERVAL_MIN` in `config.py` **and** the `*/15` in the cron |
| Add a third home | add a key under `homes` in the `COMMUTE_ROUTES_JSON` secret; nothing else changes |
| Traffic model | `ROUTING_PREFERENCE` in `sample_commute.py` (`TRAFFIC_AWARE` is cheaper and slightly less accurate) |

## Local use

```bash
cp scripts/routes.example.json scripts/routes.json     # gitignored
export GOOGLE_MAPS_API_KEY=...
python3 scripts/sample_commute.py --force              # one sample, now
python3 scripts/sample_commute.py --force --mock       # no API call
```

No dependencies beyond the Python 3.9+ standard library.
