#!/usr/bin/env python3
"""Turn the sampled log into a weekday x time-of-day picture of the commute.

Reads every data/commute_*.csv, then writes:

  report.md    plain-text tables, readable in the GitHub file view
  report.html  the same data as colour-scaled heatmaps

Median is used rather than mean throughout: a single accident on one Tuesday
should not decide which day you drive in.

Usage:  python3 scripts/analyze.py [--min-samples N]
"""

from __future__ import annotations

import argparse
import csv
import html
import statistics
from collections import defaultdict
from datetime import datetime

from config import (
    AFTERNOON,
    DATA_DIR,
    MORNING,
    REPO_ROOT,
    SAMPLE_INTERVAL_MIN,
    slot_label,
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

DIRECTIONS = [
    ("home_to_office", "Morning - home to office", MORNING),
    ("office_to_home", "Afternoon - office to home", AFTERNOON),
]


# --------------------------------------------------------------------------- #

def load_rows() -> list[dict]:
    rows = []
    for path in sorted(DATA_DIR.glob("commute_*.csv")):
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("status") != "ok" or not row.get("duration_min"):
                    continue
                try:
                    row["minutes"] = float(row["duration_min"])
                except ValueError:
                    continue
                rows.append(row)
    return rows


def slots_for(window: tuple[int, int]) -> list[str]:
    start, end = window
    return [slot_label(m) for m in range(start, end + 1, SAMPLE_INTERVAL_MIN)]


def build_grid(rows, direction, home) -> dict[tuple[str, str], list[float]]:
    grid = defaultdict(list)
    for row in rows:
        if row["direction"] == direction and row["home"] == home:
            grid[(row["weekday"], row["slot"])].append(row["minutes"])
    return grid


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #

def markdown_report(rows, homes, min_samples) -> str:
    out = ["# Commute time report", ""]

    dates = sorted({r["local_date"] for r in rows})
    out += [
        f"- Samples: **{len(rows):,}** across **{len(dates)}** days "
        f"({dates[0]} to {dates[-1]})" if dates else "- No samples yet",
        f"- Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} local",
        (f"- Cells show the **median** drive time in minutes; `-` means no "
         f"sample yet." if min_samples <= 1 else
         f"- Cells show the **median** drive time in minutes; `-` means fewer "
         f"than {min_samples} samples."),
        ("- Cells marked \u00b0 rest on a single sample -- one reading, not a "
         "median. Treat them as provisional until that weekday recurs."
         if min_samples < 2 else ""),
        "",
    ]

    for direction, title, window in DIRECTIONS:
        slots = slots_for(window)
        out += [f"## {title}", ""]

        for home in homes:
            grid = build_grid(rows, direction, home)
            out += [f"### {home}", "",
                    "| Time | " + " | ".join(WEEKDAYS) + " |",
                    "|---|" + "---|" * len(WEEKDAYS)]
            for slot in slots:
                cells = []
                for day in WEEKDAYS:
                    values = grid.get((day, slot), [])
                    if len(values) < min_samples:
                        cells.append("-")
                    else:
                        # A single reading is not a median; flag it so a
                        # provisional number is never mistaken for a settled one.
                        mark = "\u00b0" if len(values) == 1 else ""
                        cells.append(fmt(statistics.median(values)) + mark)
                out.append(f"| {slot} | " + " | ".join(cells) + " |")
            out.append("")

    out += ["## Best departure windows", ""]
    for direction, title, _ in DIRECTIONS:
        out += [f"### {title}", "",
                "| Rank | Home | Day | Depart | Median min | Samples |",
                "|---|---|---|---|---|---|"]
        ranked = []
        for home in homes:
            for (day, slot), values in build_grid(rows, direction, home).items():
                if len(values) >= min_samples:
                    ranked.append((statistics.median(values), home, day, slot,
                                   len(values)))
        ranked.sort()
        for i, (median, home, day, slot, n) in enumerate(ranked[:10], 1):
            out.append(f"| {i} | {home} | {day} | {slot} | {median:.0f} | {n} |")
        out.append("")

    out += ["## Home vs home", "",
            "| Direction | Home | Overall median | Best day | Worst day |",
            "|---|---|---|---|---|"]
    for direction, title, _ in DIRECTIONS:
        for home in homes:
            values = [r["minutes"] for r in rows
                      if r["direction"] == direction and r["home"] == home]
            if not values:
                continue
            per_day = {
                day: statistics.median([
                    r["minutes"] for r in rows
                    if r["direction"] == direction and r["home"] == home
                    and r["weekday"] == day
                ])
                for day in WEEKDAYS
                if any(r["weekday"] == day and r["direction"] == direction
                       and r["home"] == home for r in rows)
            }
            best = min(per_day, key=per_day.get) if per_day else "-"
            worst = max(per_day, key=per_day.get) if per_day else "-"
            out.append(
                f"| {title} | {home} | {statistics.median(values):.0f} min | "
                f"{best} ({per_day[best]:.0f} min) | "
                f"{worst} ({per_day[worst]:.0f} min) |"
                if per_day else
                f"| {title} | {home} | {statistics.median(values):.0f} min | - | - |"
            )
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #

CSS = """
:root { --bg:#fbfaf8; --fg:#1d1c1a; --muted:#6b6862; --line:#e2ded7; --card:#fff; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#171614; --fg:#eceae6; --muted:#9c978e; --line:#302e2a; --card:#201f1c; }
}
* { box-sizing:border-box; }
body { margin:0; padding:32px 20px 64px; background:var(--bg); color:var(--fg);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
.wrap { max-width:1040px; margin:0 auto; }
h1 { font-size:26px; margin:0 0 6px; letter-spacing:-.01em; }
h2 { font-size:19px; margin:40px 0 4px; letter-spacing:-.01em; }
h3 { font-size:14px; margin:22px 0 8px; color:var(--muted);
  text-transform:uppercase; letter-spacing:.07em; }
p.sub { color:var(--muted); margin:0 0 8px; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { padding:7px 10px; text-align:center; border-bottom:1px solid var(--line);
  white-space:nowrap; }
th { font-weight:600; font-size:13px; color:var(--muted); text-align:center; }
td.time, th.time { text-align:left; color:var(--muted); font-size:13px; }
td.cell { color:#12100e; font-weight:600; border-radius:3px; }
/* One reading, not a median: dimmed and dashed so it reads as provisional. */
td.cell.single { opacity:.62; outline:1px dashed rgba(0,0,0,.38); outline-offset:-2px; }
td.empty { color:var(--muted); font-weight:400; }
.legend { display:flex; align-items:center; gap:8px; color:var(--muted);
  font-size:13px; margin:10px 0 0; }
.swatch { width:120px; height:10px; border-radius:5px;
  background:linear-gradient(90deg,#3f9a6b,#e0c04a,#c8523f); }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; margin-top:14px; }
"""


def colour(value: float, lo: float, hi: float) -> str:
    """Green (fast) through amber to red (slow)."""
    t = 0.0 if hi <= lo else (value - lo) / (hi - lo)
    stops = [(0.0, (63, 154, 107)), (0.5, (224, 192, 74)), (1.0, (200, 82, 63))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
            r, g, b = (round(a + (b_ - a) * f) for a, b_ in zip(c0, c1))
            return f"rgba({r},{g},{b},0.85)"
    return "rgba(200,82,63,0.85)"


def html_report(rows, homes, min_samples) -> str:
    dates = sorted({r["local_date"] for r in rows})
    parts = [
        "<title>Commute time report</title>",
        f"<style>{CSS}</style>",
        '<div class="wrap">',
        "<h1>Commute time report</h1>",
        (('<p class="sub">Faded, dashed cells rest on a single sample &mdash; '
          'one reading, not a median. Provisional until that weekday recurs.</p>')
         if min_samples < 2 else ""),
        f'<p class="sub">{len(rows):,} samples over {len(dates)} days'
        + (f", {dates[0]} to {dates[-1]}" if dates else "")
        + ". Median driving minutes, live traffic.</p>",
        '<div class="legend"><span>faster</span><span class="swatch"></span>'
        "<span>slower</span></div>",
    ]

    for direction, title, window in DIRECTIONS:
        slots = slots_for(window)
        # Scale both homes on one range so the two grids are comparable.
        pool = [r["minutes"] for r in rows if r["direction"] == direction]
        lo = min(pool) if pool else 0
        hi = max(pool) if pool else 1

        parts.append(f"<h2>{html.escape(title)}</h2>")
        for home in homes:
            grid = build_grid(rows, direction, home)
            parts.append(f"<h3>{html.escape(home)}</h3>")
            parts.append('<div class="scroll"><table><thead><tr>'
                         '<th class="time">Time</th>'
                         + "".join(f"<th>{d[:3]}</th>" for d in WEEKDAYS)
                         + "</tr></thead><tbody>")
            for slot in slots:
                parts.append(f'<tr><td class="time">{slot}</td>')
                for day in WEEKDAYS:
                    values = grid.get((day, slot), [])
                    if len(values) < min_samples:
                        parts.append('<td class="empty">&ndash;</td>')
                        continue
                    median = statistics.median(values)
                    # A single reading is not a median. Mark it so a
                    # provisional number is never read as a settled one.
                    single = " single" if len(values) == 1 else ""
                    parts.append(
                        f'<td class="cell{single}" '
                        f'style="background:{colour(median, lo, hi)}" '
                        f'title="{day} {slot} &middot; n={len(values)}'
                        f'{" &middot; single sample" if len(values) == 1 else ""}">'
                        f"{median:.0f}</td>"
                    )
                parts.append("</tr>")
            parts.append("</tbody></table></div>")

    parts.append("<h2>Best departure windows</h2>")
    for direction, title, _ in DIRECTIONS:
        ranked = []
        for home in homes:
            for (day, slot), values in build_grid(rows, direction, home).items():
                if len(values) >= min_samples:
                    ranked.append((statistics.median(values), home, day, slot,
                                   len(values)))
        ranked.sort()
        parts.append(f'<div class="card"><h3>{html.escape(title)}</h3>'
                     '<table><thead><tr><th class="time">Home</th><th>Day</th>'
                     "<th>Depart</th><th>Median</th><th>n</th></tr></thead><tbody>")
        for median, home, day, slot, n in ranked[:10]:
            parts.append(
                f'<tr><td class="time">{html.escape(home)}</td><td>{day}</td>'
                f"<td>{slot}</td><td><strong>{median:.0f} min</strong></td>"
                f"<td>{n}</td></tr>"
            )
        parts.append("</tbody></table></div>")

    parts.append("</div>")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-samples", type=int, default=1,
                        help="cells with fewer samples than this are left blank")
    args = parser.parse_args()

    rows = load_rows()
    if not rows:
        print("No successful samples in data/ yet.")
        return 0

    homes = sorted({r["home"] for r in rows})

    (REPO_ROOT / "report.md").write_text(
        markdown_report(rows, homes, args.min_samples))
    (REPO_ROOT / "report.html").write_text(
        html_report(rows, homes, args.min_samples))

    print(f"{len(rows):,} samples, {len({r['local_date'] for r in rows})} days.")
    for direction, title, _ in DIRECTIONS:
        print(f"\n{title}")
        for home in homes:
            values = [r["minutes"] for r in rows
                      if r["direction"] == direction and r["home"] == home]
            if values:
                print(f"  {home}: median {statistics.median(values):.0f} min "
                      f"(best {min(values):.0f}, worst {max(values):.0f}, "
                      f"n={len(values)})")
    print("\nWrote report.md and report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
