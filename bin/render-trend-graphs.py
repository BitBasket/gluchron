#!/usr/bin/env python3
"""Render the 19 Aug–21 Sep 2026 CGM change as GluChron-styled graphs."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.collections import LineCollection
    from matplotlib.colors import BoundaryNorm, ListedColormap
except ImportError as exc:
    raise SystemExit(
        "matplotlib and numpy are required. Example:\n"
        "  python3 -m venv /tmp/gluchron-plots\n"
        "  /tmp/gluchron-plots/bin/pip install matplotlib numpy\n"
        "  /tmp/gluchron-plots/bin/python bin/render-trend-graphs.py"
    ) from exc


BG = "#07131a"
PANEL = "#10222c"
CHART = "#081218"
INK = "#e8f4f2"
MUTED = "#8aa4ad"
LINE = "#1d3a46"
GRID = "#1a2d35"
GREEN = "#3ddc97"
YELLOW = "#f4c95d"
ORANGE = "#f08c32"
RED = "#b71c1c"
BAD = "#ff6b6b"

RANGE_LO = 70
RANGE_HI = 180
VERY_HIGH = 250
OVERNIGHT_START = 2 * 60
OVERNIGHT_END = 6 * 60


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_file",
        nargs="?",
        type=Path,
        default=root / "glucose.csv",
        help="dense YYYYMMDD + 1440 UTC-minute CSV",
    )
    parser.add_argument(
        "--tz-offset",
        type=float,
        default=3.0,
        help="local offset from UTC in hours (Cairo summer is +3)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / "public" / "graphs",
        help="output directory",
    )
    return parser.parse_args()


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "figure.facecolor": BG,
            "axes.facecolor": CHART,
            "axes.edgecolor": LINE,
            "axes.labelcolor": MUTED,
            "axes.titlecolor": INK,
            "text.color": INK,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "grid.color": GRID,
            "grid.linewidth": 0.7,
            "legend.facecolor": PANEL,
            "legend.edgecolor": LINE,
            "legend.labelcolor": INK,
            "savefig.facecolor": BG,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.28,
        }
    )


def parse_float(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def load_readings(path: Path) -> dict[datetime, float]:
    readings: dict[datetime, float] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            try:
                day = datetime.strptime(row[0].strip(), "%Y%m%d")
            except ValueError:
                continue
            for minute, raw in enumerate(row[1:1441]):
                value = parse_float(raw)
                if value is not None:
                    readings[day + timedelta(minutes=minute)] = value
    if not readings:
        raise SystemExit(f"No usable CGM readings in {path}")
    return readings


def local_parts(ts_utc: datetime, offset: timedelta) -> tuple[date, int]:
    local = ts_utc + offset
    return local.date(), local.hour * 60 + local.minute


def gmi(mean_mgdl: float) -> float:
    return 3.31 + 0.02392 * mean_mgdl


def daily_stats(readings: dict[datetime, float], offset: timedelta) -> list[dict]:
    # Day buckets follow the dense CSV's UTC calendar rows so the graphs
    # match the printed trend report. Overnight still uses local 02:00–06:00.
    by_day: dict[date, list[tuple[int, float]]] = defaultdict(list)
    for ts, glucose in readings.items():
        _local_day, minute = local_parts(ts, offset)
        by_day[ts.date()].append((minute, glucose))

    rows = []
    for day in sorted(by_day):
        points = by_day[day]
        values = [v for _, v in points]
        overnight = [
            v
            for m, v in points
            if OVERNIGHT_START <= m < OVERNIGHT_END
        ]
        n = len(values)
        mean = statistics.fmean(values)
        rows.append(
            {
                "date": day,
                "dt": datetime(day.year, day.month, day.day),
                "n": n,
                "coverage": n / 1440 * 100,
                "mean": mean,
                "median": statistics.median(values),
                "overnight": statistics.median(overnight) if overnight else math.nan,
                "min": min(values),
                "max": max(values),
                "tir": sum(RANGE_LO <= v <= RANGE_HI for v in values) / n * 100,
                "tbr": sum(v < RANGE_LO for v in values) / n * 100,
                "tar180": sum(RANGE_HI < v <= VERY_HIGH for v in values) / n * 100,
                "tar250": sum(v > VERY_HIGH for v in values) / n * 100,
                "auc180": statistics.fmean([max(0.0, v - RANGE_HI) for v in values]) * 24,
            }
        )
    return rows


def save(fig: plt.Figure, out: Path, stem: str) -> list[Path]:
    paths = []
    for ext in ("svg", "png"):
        path = out / f"{stem}.{ext}"
        fig.savefig(path, dpi=160, format=ext)
        paths.append(path)
    plt.close(fig)
    return paths


def plot_daily_mean(daily: list[dict], out: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=(13.2, 6.4))
    xs = [d["dt"] for d in daily]
    means = [d["mean"] for d in daily]
    overnight = [d["overnight"] for d in daily]
    medians = [d["median"] for d in daily]

    ax.axhspan(RANGE_LO, RANGE_HI, color=GREEN, alpha=0.10, zorder=0)
    ax.axhline(RANGE_LO, color=GREEN, lw=0.9, ls="--", alpha=0.7)
    ax.axhline(RANGE_HI, color=YELLOW, lw=0.9, ls="--", alpha=0.7)
    ax.axhline(VERY_HIGH, color=ORANGE, lw=0.9, ls="--", alpha=0.55)
    x_right = mdates.date2num(xs[-1])
    ax.text(x_right, RANGE_HI + 5, "180", color=YELLOW, fontsize=8, ha="right", va="bottom")
    ax.text(x_right, RANGE_LO - 5, "70", color=GREEN, fontsize=8, ha="right", va="top")
    ax.text(x_right, VERY_HIGH + 5, "250", color=ORANGE, fontsize=8, ha="right", va="bottom")

    ax.plot(xs, medians, color=MUTED, lw=1.2, alpha=0.85, label="Daily median")
    ax.plot(xs, means, color=INK, lw=2.4, marker="o", ms=4.5, label="Daily mean")
    ax.plot(
        xs,
        overnight,
        color=YELLOW,
        lw=1.8,
        ls="--",
        marker="s",
        ms=3.5,
        label="Overnight median (02:00–06:00 local)",
    )

    first = daily[0]
    last_full = next(d for d in reversed(daily) if d["coverage"] >= 70)
    ax.text(
        0.015,
        0.96,
        f"{first['date']:%-d %b}  mean {first['mean']:.0f}  GMI {gmi(first['mean']):.1f}%",
        transform=ax.transAxes,
        va="top",
        fontsize=9,
        color=BAD,
    )
    ax.text(
        0.985,
        0.34,
        f"{last_full['date']:%-d %b}  mean {last_full['mean']:.0f}  GMI {gmi(last_full['mean']):.1f}%",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=9,
        color=GREEN,
    )

    rebound = next(d for d in daily if d["date"] == date(2026, 9, 11))
    ax.annotate(
        "11 Sep: last full day >180",
        xy=(rebound["dt"], rebound["mean"]),
        xytext=(0, 18),
        textcoords="offset points",
        fontsize=8,
        color=ORANGE,
        ha="center",
    )
    hypo = next(d for d in daily if d["date"] == date(2026, 9, 20))
    ax.annotate(
        "19–20 Sep: first lows (nadir 52)",
        xy=(hypo["dt"], hypo["overnight"]),
        xytext=(0.58, 0.07),
        textcoords="axes fraction",
        fontsize=8,
        color=BAD,
        ha="right",
        arrowprops={"arrowstyle": "->", "color": BAD, "lw": 1.0},
    )

    ax.set_ylim(40, 450)
    ax.set_xlim(xs[0] - timedelta(days=0.6), xs[-1] + timedelta(days=0.7))
    ax.set_ylabel("mg/dL")
    ax.set_title("Daily mean collapsed from ~310 to ~136 mg/dL in 32 days, no medication")
    ax.grid(True, axis="y")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    fig.autofmt_xdate(rotation=40, ha="right")
    ax.legend(loc="upper right", framealpha=0.95, bbox_to_anchor=(0.99, 0.88))
    fig.text(
        0.01,
        0.01,
        "UTC days from glucose.csv · overnight 02:00–06:00 local UTC+3 · 21 Sep is a partial day",
        color=MUTED,
        fontsize=8,
    )
    return save(fig, out, "01-daily-mean-overnight")


def plot_time_in_range(daily: list[dict], out: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=(13.2, 6.2))
    xs = np.arange(len(daily))
    labels = [d["date"].strftime("%m-%d") for d in daily]
    tbr = np.array([d["tbr"] for d in daily])
    tir = np.array([d["tir"] for d in daily])
    tar180 = np.array([d["tar180"] for d in daily])
    tar250 = np.array([d["tar250"] for d in daily])

    ax.bar(xs, tbr, color=RED, width=0.86, label="< 70")
    ax.bar(xs, tir, bottom=tbr, color=GREEN, width=0.86, label="70–180")
    ax.bar(xs, tar180, bottom=tbr + tir, color=YELLOW, width=0.86, label="181–250")
    ax.bar(
        xs,
        tar250,
        bottom=tbr + tir + tar180,
        color=ORANGE,
        width=0.86,
        label="> 250",
    )
    ax.axhline(70, color=INK, lw=0.8, ls=":", alpha=0.55)
    ax.text(-0.4, 72.2, "70% TIR", color=MUTED, fontsize=8, ha="left")

    ax.set_ylim(0, 100)
    ax.set_ylabel("% of sampled minutes")
    ax.set_title("Time in range: from ~0% in-range / days above 250, to majority 70–180")
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=40, ha="right")
    ax.legend(
        loc="upper center",
        ncol=4,
        framealpha=0.95,
        bbox_to_anchor=(0.5, 1.16),
    )
    ax.grid(True, axis="y")
    fig.subplots_adjust(top=0.82)
    fig.text(
        0.01,
        0.01,
        "Percent of available samples that day · early LibreLink days are ~15-minute historic samples",
        color=MUTED,
        fontsize=8,
    )
    return save(fig, out, "02-time-in-range")


def downsample(readings: dict[datetime, float], minutes: int = 5) -> tuple[np.ndarray, np.ndarray]:
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for ts, value in readings.items():
        key = ts.replace(second=0, microsecond=0)
        key -= timedelta(minutes=key.minute % minutes)
        buckets[key].append(value)
    xs = np.array([mdates.date2num(ts) for ts in sorted(buckets)])
    ys = np.array([statistics.fmean(buckets[ts]) for ts in sorted(buckets)])
    return xs, ys


def plot_trace(readings: dict[datetime, float], out: Path) -> list[Path]:
    xs, ys = downsample(readings, 5)
    fig, ax = plt.subplots(figsize=(13.2, 6.4))

    ax.axhspan(RANGE_LO, RANGE_HI, color=GREEN, alpha=0.10, zorder=0)
    ax.axhline(RANGE_LO, color=GREEN, lw=0.8, ls="--", alpha=0.7)
    ax.axhline(RANGE_HI, color=YELLOW, lw=0.8, ls="--", alpha=0.7)
    ax.axhline(VERY_HIGH, color=ORANGE, lw=0.8, ls="--", alpha=0.55)

    points = np.column_stack([xs, ys])
    segments = np.stack([points[:-1], points[1:]], axis=1)
    # Break the line across gaps longer than 25 minutes.
    gap = np.diff(xs) > (25 / (24 * 60))
    segments = segments[~gap]
    seg_y = ys[:-1][~gap]

    cmap = ListedColormap([RED, GREEN, YELLOW, ORANGE])
    norm = BoundaryNorm([0, RANGE_LO, RANGE_HI, VERY_HIGH, 500], cmap.N)
    lc = LineCollection(segments, cmap=cmap, norm=norm, linewidths=1.15, zorder=3, rasterized=True)
    lc.set_array(seg_y)
    ax.add_collection(lc)

    ax.set_xlim(xs.min(), xs.max())
    ax.set_ylim(40, 450)
    ax.set_ylabel("mg/dL")
    ax.set_title("Five-minute CGM overview: 113-hour high streak in August, in-range days by late September")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    fig.autofmt_xdate(rotation=40, ha="right")
    ax.grid(True, axis="y")

    ax.axvspan(
        mdates.date2num(datetime(2026, 8, 21, 0, 13)),
        mdates.date2num(datetime(2026, 8, 25, 17, 42)),
        color=ORANGE,
        alpha=0.08,
        zorder=1,
    )
    ax.text(
        mdates.date2num(datetime(2026, 8, 23, 6, 0)),
        430,
        "113 h continuously >180",
        color=ORANGE,
        fontsize=8.5,
        ha="center",
    )

    cbar = fig.colorbar(lc, ax=ax, pad=0.015, fraction=0.03)
    cbar.set_label("mg/dL", color=MUTED)
    cbar.ax.yaxis.set_tick_params(color=MUTED)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=MUTED)
    fig.text(
        0.01,
        0.01,
        "UTC timestamps · line breaks on gaps >25 min · color bands: <70, 70–180, 181–250, >250",
        color=MUTED,
        fontsize=8,
    )
    return save(fig, out, "03-glucose-trace")


def hour_profile(
    readings: dict[datetime, float],
    offset: timedelta,
    start: date,
    end: date,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    by_hour: dict[int, list[float]] = defaultdict(list)
    for ts, value in readings.items():
        local = ts + offset
        if start <= local.date() <= end:
            by_hour[local.hour].append(value)
    hours = np.arange(24)
    med = np.full(24, np.nan)
    lo = np.full(24, np.nan)
    hi = np.full(24, np.nan)
    for hour in hours:
        vals = by_hour.get(int(hour), [])
        if not vals:
            continue
        med[hour] = statistics.median(vals)
        lo[hour] = np.percentile(vals, 25)
        hi[hour] = np.percentile(vals, 75)
    return hours, med, lo, hi


def plot_clock(readings: dict[datetime, float], offset: timedelta, out: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=(13.2, 6.2))
    hours, e_med, e_lo, e_hi = hour_profile(
        readings, offset, date(2026, 8, 19), date(2026, 8, 25)
    )
    _, r_med, r_lo, r_hi = hour_profile(
        readings, offset, date(2026, 9, 16), date(2026, 9, 21)
    )

    ax.axhspan(RANGE_LO, RANGE_HI, color=GREEN, alpha=0.10, zorder=0)
    ax.axhline(RANGE_LO, color=GREEN, lw=0.8, ls="--", alpha=0.7)
    ax.axhline(RANGE_HI, color=YELLOW, lw=0.8, ls="--", alpha=0.7)

    ax.fill_between(hours, e_lo, e_hi, color="#f08c32", alpha=0.28, label="19–25 Aug IQR")
    ax.plot(hours, e_med, color=ORANGE, lw=2.4, marker="o", ms=4, label="19–25 Aug median")
    ax.fill_between(hours, r_lo, r_hi, color=GREEN, alpha=0.22, label="16–21 Sep IQR")
    ax.plot(hours, r_med, color=GREEN, lw=2.4, marker="o", ms=4, label="16–21 Sep median")

    ax.set_xlim(0, 23)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)])
    ax.set_xlabel("Local time (UTC+3)")
    ax.set_ylabel("mg/dL")
    ax.set_ylim(40, 430)
    ax.set_title("Clock-day profile: the whole 24-hour floor dropped, overnight first")
    ax.grid(True, axis="y")
    ax.legend(loc="upper right", framealpha=0.95)
    fig.text(
        0.01,
        0.01,
        "Median and interquartile range of all samples in each local hour · 21 Sep is partial",
        color=MUTED,
        fontsize=8,
    )
    return save(fig, out, "04-early-vs-recent-clock")


def plot_story(daily: list[dict], out: Path) -> list[Path]:
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(13.2, 9.2), sharex=True, gridspec_kw={"height_ratios": [1.15, 1]}
    )
    xs = [d["dt"] for d in daily]
    means = [d["mean"] for d in daily]
    overnight = [d["overnight"] for d in daily]

    ax1.axhspan(RANGE_LO, RANGE_HI, color=GREEN, alpha=0.10, zorder=0)
    ax1.axhline(RANGE_LO, color=GREEN, lw=0.8, ls="--", alpha=0.65)
    ax1.axhline(RANGE_HI, color=YELLOW, lw=0.8, ls="--", alpha=0.65)
    ax1.plot(xs, means, color=INK, lw=2.5, marker="o", ms=4, label="Daily mean")
    ax1.plot(xs, overnight, color=YELLOW, lw=1.8, ls="--", label="Overnight median")
    ax1.set_ylim(40, 450)
    ax1.set_xlim(xs[0] - timedelta(hours=12), xs[-1] + timedelta(hours=18))
    ax1.set_ylabel("mg/dL")
    ax1.set_title("Thirty days, zero medication: hyperglycemia collapsed, then overnight lows appeared")
    ax1.grid(True, axis="y")
    ax1.legend(loc="upper right", framealpha=0.95)

    first = daily[0]
    last_full = next(d for d in reversed(daily) if d["coverage"] >= 70)
    ax1.text(
        0.015,
        0.94,
        f"{first['date']:%-d %b}  GMI {gmi(first['mean']):.1f}%",
        transform=ax1.transAxes,
        color=BAD,
        fontsize=10,
        va="top",
    )
    ax1.text(
        0.985,
        0.12,
        f"{last_full['date']:%-d %b}  GMI {gmi(last_full['mean']):.1f}%",
        transform=ax1.transAxes,
        color=GREEN,
        fontsize=10,
        ha="right",
    )

    idx = np.arange(len(daily))
    tbr = np.array([d["tbr"] for d in daily])
    tir = np.array([d["tir"] for d in daily])
    tar180 = np.array([d["tar180"] for d in daily])
    tar250 = np.array([d["tar250"] for d in daily])
    # Align bars to dates on a date axis via numeric day numbers.
    xnum = mdates.date2num(xs)
    width = 0.78
    ax2.bar(xnum, tbr, width=width, color=RED, label="< 70")
    ax2.bar(xnum, tir, width=width, bottom=tbr, color=GREEN, label="70–180")
    ax2.bar(xnum, tar180, width=width, bottom=tbr + tir, color=YELLOW, label="181–250")
    ax2.bar(
        xnum,
        tar250,
        width=width,
        bottom=tbr + tir + tar180,
        color=ORANGE,
        label="> 250",
    )
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("% of samples")
    ax2.legend(
        loc="upper center",
        ncol=4,
        framealpha=0.95,
        bbox_to_anchor=(0.5, 1.18),
    )
    ax2.grid(True, axis="y")
    fig.subplots_adjust(hspace=0.28, top=0.92)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax2.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    fig.autofmt_xdate(rotation=40, ha="right")
    fig.text(
        0.01,
        0.01,
        "GluChron dense CSV · UTC days · overnight 02:00–06:00 local UTC+3 · GMI = 3.31 + 0.02392 × mean mg/dL",
        color=MUTED,
        fontsize=8,
    )
    return save(fig, out, "00-thirty-day-change")


def write_index(out: Path, generated: list[tuple[str, str, str]]) -> Path:
    cards = []
    for stem, title, caption in generated:
        cards.append(
            f"""
    <figure>
      <img src="{stem}.svg" alt="{title}">
      <figcaption>
        <strong>{title}</strong>
        {caption}
      </figcaption>
    </figure>"""
        )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#07131a">
  <title>30-day glucose change — GluChron</title>
  <style>
    :root {{
      --bg: #07131a;
      --panel: #10222c;
      --ink: #e8f4f2;
      --muted: #8aa4ad;
      --fresh: #3ddc97;
      --line: #1d3a46;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      min-height: 100%;
      background: radial-gradient(circle at top, #123040, var(--bg) 55%);
      color: var(--ink);
      font-family: "Segoe UI", system-ui, sans-serif;
    }}
    main {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 2rem 1.25rem 3rem;
    }}
    h1 {{
      margin: 0;
      font-size: 1.1rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    .lede {{
      color: var(--muted);
      max-width: 46rem;
      line-height: 1.5;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 0.75rem;
      margin: 1.25rem 0 0.5rem;
    }}
    .stat {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 0.85rem 1rem;
    }}
    .stat b {{
      display: block;
      font-size: 1.35rem;
      color: var(--fresh);
      letter-spacing: 0.02em;
    }}
    .stat span {{ color: var(--muted); font-size: 0.85rem; }}
    figure {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 1rem;
      margin: 1.35rem 0;
    }}
    img {{
      width: 100%;
      height: auto;
      display: block;
      border-radius: 8px;
    }}
    figcaption {{
      margin-top: 0.8rem;
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.45;
    }}
    figcaption strong {{
      display: block;
      color: var(--ink);
      margin-bottom: 0.25rem;
    }}
    a {{ color: var(--fresh); }}
  </style>
</head>
<body>
  <main>
    <h1>My GluChron</h1>
    <p class="lede">
      19 August through 21 September 2026. Dense minute-grid from
      <code>glucose.csv</code>, local days UTC+3, no glucose-lowering medication.
      Daily bars use UTC calendar days from the dense CSV. Overnight medians
      use 02:00–06:00 local (UTC+3). Early days are LibreLink historic samples;
      live 1-minute GluChron begins around 2 September.
    </p>
    <div class="stats">
      <div class="stat"><b>310 → 136</b><span>daily mean, mg/dL</span></div>
      <div class="stat"><b>10.7% → 6.6%</b><span>GMI from mean glucose</span></div>
      <div class="stat"><b>0% → 75%</b><span>time in 70–180</span></div>
      <div class="stat"><b>113 hours</b><span>longest streak &gt;180, 21–25 Aug</span></div>
    </div>
    {''.join(cards)}
    <p class="lede">PNG copies sit next to each SVG. Regenerate with
      <code>bin/render-trend-graphs.py</code>.</p>
  </main>
</body>
</html>
"""
    path = out / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> None:
    args = parse_args()
    apply_style()
    offset = timedelta(minutes=round(args.tz_offset * 60))
    readings = load_readings(args.csv_file)
    daily = daily_stats(readings, offset)
    args.out.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    written += plot_story(daily, args.out)
    written += plot_daily_mean(daily, args.out)
    written += plot_time_in_range(daily, args.out)
    written += plot_trace(readings, args.out)
    written += plot_clock(readings, offset, args.out)

    index = write_index(
        args.out,
        [
            (
                "00-thirty-day-change",
                "The 30-day change",
                "Daily mean and overnight median on top; stacked time-in-range below. GMI uses 3.31 + 0.02392 × mean.",
            ),
            (
                "01-daily-mean-overnight",
                "Daily mean, median, and overnight floor",
                "The overnight median fell faster than the 24-hour mean. 11 Sep is the last fully hyperglycemic day; 19–20 Sep are the first lows.",
            ),
            (
                "02-time-in-range",
                "Time in range by day",
                "Orange is time above 250, yellow 181–250, green 70–180, dark red below 70. Green takes over after 16 Sep; red appears only on 19–20 Sep.",
            ),
            (
                "03-glucose-trace",
                "Five-minute overview trace",
                "The shaded August band is the 113-hour stretch continuously above 180, peak 433. Color follows the same 70 / 180 / 250 bands.",
            ),
            (
                "04-early-vs-recent-clock",
                "Clock-day early versus recent",
                "Hour-of-day median and IQR for 19–25 Aug versus 16–21 Sep. The whole circadian floor dropped; the overnight hours dropped furthest.",
            ),
        ],
    )
    written.append(index)
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
