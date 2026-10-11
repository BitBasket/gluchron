#!/usr/bin/env python3
"""Render the CGM change in a dense glucose.csv as GluChron-styled graphs."""

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


def fmt_day(day: date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def fmt_span(start: date, end: date) -> str:
    if start == end:
        return fmt_day(start)
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {start.strftime('%b')}"
    if start.year == end.year:
        return f"{fmt_day(start)}–{fmt_day(end)}"
    return f"{fmt_day(start)} {start.year}–{fmt_day(end)} {end.year}"


def group_dates(days: list[date]) -> str:
    if not days:
        return "none"
    groups: list[tuple[date, date]] = []
    start = prev = days[0]
    for day in days[1:]:
        if day == prev + timedelta(days=1):
            prev = day
            continue
        groups.append((start, prev))
        start = prev = day
    groups.append((start, prev))
    return ", ".join(fmt_span(a, b) for a, b in groups)


def fig_size(daily: list[dict], height: float) -> tuple[float, float]:
    span = (daily[-1]["date"] - daily[0]["date"]).days
    width = 13.2 if span <= 40 else 15.6
    return width, height


def date_ticks(ax, daily: list[dict]) -> None:
    span = (daily[-1]["date"] - daily[0]["date"]).days or 1
    interval = 2 if span <= 36 else max(3, round(span / 16))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=interval))


def longest_above(readings: dict[datetime, float], threshold: float) -> dict | None:
    """Longest run strictly above threshold. Gaps over 20 minutes break the run."""
    best: dict | None = None

    def consider(start: datetime | None, end: datetime | None, low: float, high: float) -> None:
        nonlocal best
        if start is None or end is None or end <= start:
            return
        minutes = int(round((end - start).total_seconds() / 60))
        rec = {"start": start, "end": end, "minutes": minutes, "min": low, "max": high}
        if best is None or rec["minutes"] > best["minutes"]:
            best = rec

    def scan(block: list[tuple[datetime, float]]) -> None:
        start = end = None
        low = high = 0.0
        for ts, value in block:
            if value > threshold:
                if start is None:
                    start = ts
                    low = high = value
                else:
                    low = min(low, value)
                    high = max(high, value)
                end = ts
            else:
                consider(start, end, low, high)
                start = end = None
        consider(start, end, low, high)

    block: list[tuple[datetime, float]] = []
    prev: datetime | None = None
    for ts, value in sorted(readings.items()):
        if prev is not None and ts - prev > timedelta(minutes=20) and block:
            scan(block)
            block = []
        block.append((ts, value))
        prev = ts
    if block:
        scan(block)
    return best


def build_story(
    daily: list[dict],
    readings: dict[datetime, float],
    offset: timedelta,
    tz_hours: float,
) -> dict:
    first = daily[0]
    last = daily[-1]
    full = [row for row in daily if row["coverage"] >= 70]
    anchor = full[-1] if full else last
    partial = last if last["date"] != anchor["date"] and last["coverage"] < 70 else None
    early = [row for row in daily if row["date"] <= first["date"] + timedelta(days=6)]
    recent = [
        row
        for row in daily
        if anchor["date"] - timedelta(days=6) <= row["date"] <= anchor["date"]
    ]
    hypo_days = [row for row in daily if row["tbr"] > 0]
    controlled = next(
        (row for row in daily if row["tir"] >= 50 and row["mean"] < RANGE_HI),
        None,
    )
    rebound = None
    if controlled is not None:
        later = [
            row
            for row in daily
            if row["date"] > controlled["date"]
            and row["coverage"] >= 50
            and row["mean"] >= 220
        ]
        if later:
            rebound = max(later, key=lambda row: row["mean"])
    live = next((row for row in daily if row["coverage"] >= 30), first)
    nadir_ts, nadir = min(readings.items(), key=lambda item: item[1])
    return {
        "first": first,
        "last": last,
        "anchor": anchor,
        "partial": partial,
        "early": early,
        "recent": recent,
        "high": longest_above(readings, RANGE_HI),
        "nadir": nadir,
        "nadir_ts": nadir_ts,
        "peak": max(readings.values()),
        "hypo_days": hypo_days,
        "rebound": rebound,
        "live": live,
        "last_ts": max(readings),
        "offset": offset,
        "tz_hours": tz_hours,
        "inclusive_days": (last["date"] - first["date"]).days + 1,
    }


def period_note(story: dict) -> str:
    note = (
        f"UTC days from glucose.csv · overnight 02:00–06:00 local UTC+{story['tz_hours']:g}"
    )
    partial = story["partial"]
    if partial is not None:
        end = story["last_ts"] + story["offset"]
        note += f" · {fmt_day(partial['date'])} is partial through {end:%H:%M} local"
    return note


def endpoint_phrase(story: dict) -> str:
    first = story["first"]
    anchor = story["anchor"]
    return (
        f"{first['mean']:.0f} mg/dL on {fmt_day(first['date'])} to "
        f"{anchor['mean']:.0f} on {fmt_day(anchor['date'])}"
    )


def save(fig: plt.Figure, out: Path, stem: str) -> list[Path]:
    paths = []
    for ext in ("svg", "png"):
        path = out / f"{stem}.{ext}"
        fig.savefig(path, dpi=160, format=ext)
        paths.append(path)
    plt.close(fig)
    return paths


def plot_daily_mean(daily: list[dict], story: dict, out: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=fig_size(daily, 6.4))
    xs = [d["dt"] for d in daily]
    means = [d["mean"] for d in daily]
    overnight = [d["overnight"] for d in daily]
    medians = [d["median"] for d in daily]

    ax.axhspan(RANGE_LO, RANGE_HI, color=GREEN, alpha=0.10, zorder=0)
    ax.axhline(RANGE_LO, color=GREEN, lw=0.9, ls="--", alpha=0.7)
    ax.axhline(RANGE_HI, color=YELLOW, lw=0.9, ls="--", alpha=0.7)
    ax.axhline(VERY_HIGH, color=ORANGE, lw=0.9, ls="--", alpha=0.55)
    x_left = mdates.date2num(xs[0])
    x_right = mdates.date2num(xs[-1])
    ax.text(x_left, RANGE_HI + 6, "180", color=YELLOW, fontsize=8, ha="left", va="bottom")
    ax.text(x_left, RANGE_LO - 6, "70", color=GREEN, fontsize=8, ha="left", va="top")
    ax.text(x_right, VERY_HIGH + 6, "250", color=ORANGE, fontsize=8, ha="right", va="bottom")

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
        0.38,
        0.96,
        f"{fmt_day(last_full['date'])}  mean {last_full['mean']:.0f}  GMI {gmi(last_full['mean']):.1f}%",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        color=GREEN,
    )

    span_days = max(1, (xs[-1] - xs[0]).days)

    def side(when: datetime) -> str:
        return "right" if (when - xs[0]).days / span_days > 0.75 else "center"

    rebound = story["rebound"]
    if rebound is not None:
        ax.annotate(
            f"{fmt_day(rebound['date'])}: rebound, mean {rebound['mean']:.0f}",
            xy=(rebound["dt"], rebound["mean"]),
            xytext=(0, 16),
            textcoords="offset points",
            fontsize=8,
            color=ORANGE,
            ha=side(rebound["dt"]),
        )
    overnight_lows = [
        row
        for row in story["hypo_days"]
        if math.isfinite(row["overnight"]) and row["overnight"] < RANGE_LO
    ]
    if overnight_lows:
        hypo = min(overnight_lows, key=lambda row: row["overnight"])
        ax.annotate(
            f"{fmt_day(hypo['date'])}: overnight median {hypo['overnight']:.0f}",
            xy=(hypo["dt"], hypo["overnight"]),
            xytext=(0, 22),
            textcoords="offset points",
            fontsize=8,
            color=BAD,
            ha=side(hypo["dt"]),
            arrowprops={"arrowstyle": "->", "color": BAD, "lw": 1.0},
        )

    ax.set_ylim(40, 450)
    ax.set_xlim(xs[0] - timedelta(days=0.6), xs[-1] + timedelta(days=0.7))
    ax.set_ylabel("mg/dL")
    ax.set_title(f"Daily mean from {endpoint_phrase(story)}")
    ax.grid(True, axis="y")
    date_ticks(ax, daily)
    fig.autofmt_xdate(rotation=40, ha="right")
    ax.legend(loc="upper right", framealpha=0.95, bbox_to_anchor=(0.99, 0.88))
    fig.text(0.01, 0.01, period_note(story), color=MUTED, fontsize=8)
    return save(fig, out, "01-daily-mean-overnight")


def plot_time_in_range(daily: list[dict], story: dict, out: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=fig_size(daily, 6.2))
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
    ax.set_title(
        f"Time in range by day, {fmt_span(story['first']['date'], story['last']['date'])}"
    )
    span = len(daily)
    step = 1 if span <= 36 else 2 if span <= 70 else 3
    ax.set_xticks(xs[::step])
    ax.set_xticklabels(labels[::step], rotation=40, ha="right")
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


def plot_trace(readings: dict[datetime, float], daily: list[dict], story: dict, out: Path) -> list[Path]:
    xs, ys = downsample(readings, 5)
    fig, ax = plt.subplots(figsize=fig_size(daily, 6.4))

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
    ax.set_title(
        f"Five-minute CGM overview, {fmt_span(story['first']['date'], story['last']['date'])}"
    )
    date_ticks(ax, daily)
    fig.autofmt_xdate(rotation=40, ha="right")
    ax.grid(True, axis="y")

    high = story["high"]
    if high is not None:
        ax.axvspan(
            mdates.date2num(high["start"]),
            mdates.date2num(high["end"]),
            color=ORANGE,
            alpha=0.08,
            zorder=1,
        )
        mid = high["start"] + (high["end"] - high["start"]) / 2
        ax.text(
            mdates.date2num(mid),
            (RANGE_LO + RANGE_HI) / 2,
            f"{high['minutes'] // 60} h continuously >180",
            color=ORANGE,
            fontsize=8.5,
            ha="center",
            va="center",
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


def plot_clock(readings: dict[datetime, float], offset: timedelta, story: dict, out: Path) -> list[Path]:
    fig, ax = plt.subplots(figsize=(13.2, 6.2))
    early = story["early"]
    recent = story["recent"]
    early_label = fmt_span(early[0]["date"], early[-1]["date"])
    recent_label = fmt_span(recent[0]["date"], recent[-1]["date"])
    hours, e_med, e_lo, e_hi = hour_profile(
        readings, offset, early[0]["date"], early[-1]["date"]
    )
    _, r_med, r_lo, r_hi = hour_profile(
        readings, offset, recent[0]["date"], recent[-1]["date"]
    )

    ax.axhspan(RANGE_LO, RANGE_HI, color=GREEN, alpha=0.10, zorder=0)
    ax.axhline(RANGE_LO, color=GREEN, lw=0.8, ls="--", alpha=0.7)
    ax.axhline(RANGE_HI, color=YELLOW, lw=0.8, ls="--", alpha=0.7)

    ax.fill_between(hours, e_lo, e_hi, color="#f08c32", alpha=0.28, label=f"{early_label} IQR")
    ax.plot(hours, e_med, color=ORANGE, lw=2.4, marker="o", ms=4, label=f"{early_label} median")
    ax.fill_between(hours, r_lo, r_hi, color=GREEN, alpha=0.22, label=f"{recent_label} IQR")
    ax.plot(hours, r_med, color=GREEN, lw=2.4, marker="o", ms=4, label=f"{recent_label} median")

    ax.set_xlim(0, 23)
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)])
    ax.set_xlabel(f"Local time (UTC+{story['tz_hours']:g})")
    ax.set_ylabel("mg/dL")
    ax.set_ylim(40, 430)
    ax.set_title(f"Clock-day profile: {early_label} versus {recent_label}")
    ax.grid(True, axis="y")
    ax.legend(loc="upper right", framealpha=0.95)
    fig.text(
        0.01,
        0.01,
        f"Median and IQR of samples in each local hour · {early_label} is sparse LibreLink history",
        color=MUTED,
        fontsize=8,
    )
    return save(fig, out, "04-early-vs-recent-clock")


def plot_story(daily: list[dict], story: dict, out: Path) -> list[Path]:
    width, _height = fig_size(daily, 9.2)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(width, 9.2), sharex=True, gridspec_kw={"height_ratios": [1.15, 1]}
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
    ax1.set_title(
        f"{story['inclusive_days']} days: daily mean {endpoint_phrase(story)}"
    )
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
        0.42,
        0.93,
        f"{fmt_day(last_full['date'])}  GMI {gmi(last_full['mean']):.1f}%",
        transform=ax1.transAxes,
        color=GREEN,
        fontsize=10,
        ha="left",
        va="top",
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
    date_ticks(ax2, daily)
    fig.autofmt_xdate(rotation=40, ha="right")
    fig.text(
        0.01,
        0.01,
        period_note(story) + " · GMI = 3.31 + 0.02392 × mean mg/dL",
        color=MUTED,
        fontsize=8,
    )
    return save(fig, out, "00-thirty-day-change")


def lede_html(story: dict) -> str:
    first = story["first"]["date"]
    last = story["last"]["date"]
    live = story["live"]["date"]
    partial = ""
    if story["partial"] is not None:
        end = story["last_ts"] + story["offset"]
        partial = f" {fmt_day(story['partial']['date'])} is partial, through {end:%H:%M} local."
    return (
        f"{first.day} {first.strftime('%B')} through {last.day} {last.strftime('%B %Y')}. "
        "Dense minute-grid from <code>glucose.csv</code>, "
        f"local time UTC+{story['tz_hours']:g}. "
        "Daily bars use UTC calendar days. Overnight medians use 02:00–06:00 local. "
        f"Early days are sparse LibreLink samples; denser readings begin {live.day} {live.strftime('%B')}."
        f"{partial}"
    )


def stats_html(story: dict) -> str:
    first = story["first"]
    anchor = story["anchor"]
    high = story["high"]
    if high is None:
        streak = "—"
        streak_label = "longest streak &gt;180"
    else:
        streak = f"{high['minutes'] // 60} hours"
        streak_label = (
            "longest streak &gt;180, "
            + fmt_span(high["start"].date(), high["end"].date())
        )
    cards = [
        (
            f"{first['mean']:.0f} → {anchor['mean']:.0f}",
            f"daily mean, {fmt_day(first['date'])} → {fmt_day(anchor['date'])}",
        ),
        (
            f"{gmi(first['mean']):.1f}% → {gmi(anchor['mean']):.1f}%",
            "GMI from those daily means",
        ),
        (
            f"{first['tir']:.0f}% → {anchor['tir']:.0f}%",
            "time in 70–180",
        ),
        (streak, streak_label),
    ]
    return "\n".join(
        f'      <div class="stat"><b>{value}</b><span>{label}</span></div>'
        for value, label in cards
    )


def mean_caption(story: dict) -> str:
    early_on = [row["overnight"] for row in story["early"] if math.isfinite(row["overnight"])]
    recent_on = [row["overnight"] for row in story["recent"] if math.isfinite(row["overnight"])]
    parts = []
    if early_on and recent_on:
        parts.append(
            "Overnight medians averaged "
            f"{statistics.fmean(early_on):.0f} in {fmt_span(story['early'][0]['date'], story['early'][-1]['date'])} "
            f"and {statistics.fmean(recent_on):.0f} in "
            f"{fmt_span(story['recent'][0]['date'], story['recent'][-1]['date'])}. "
            "All-day means averaged "
            f"{statistics.fmean(row['mean'] for row in story['early']):.0f} and "
            f"{statistics.fmean(row['mean'] for row in story['recent']):.0f}."
        )
    rebound = story["rebound"]
    if rebound is not None:
        parts.append(f"{fmt_day(rebound['date'])} rebounds to a daily mean of {rebound['mean']:.0f}.")
    if story["hypo_days"]:
        parts.append(
            "Readings below 70 fall on "
            f"{group_dates([row['date'] for row in story['hypo_days']])}. "
            f"The lowest value is {story['nadir']:.0f}."
        )
    anchor = story["anchor"]
    parts.append(
        f"Endpoint stats use the last day with at least 70% of minutes filled, {fmt_day(anchor['date'])}."
    )
    return " ".join(parts)


def tir_caption(story: dict) -> str:
    parts = [
        "Orange is time above 250, yellow 181–250, green 70–180, dark red below 70."
    ]
    recent = story["recent"]
    if recent and all(row["tir"] >= 50 for row in recent):
        parts.append(
            f"{fmt_span(recent[0]['date'], recent[-1]['date'])} is mostly 70–180."
        )
    if story["hypo_days"]:
        parts.append(
            "Time below 70 shows on "
            f"{group_dates([row['date'] for row in story['hypo_days']])}."
        )
    return " ".join(parts)


def trace_caption(story: dict) -> str:
    high = story["high"]
    if high is None:
        return "Color bands are below 70, 70–180, 181–250, and above 250."
    return (
        f"The shaded band is {high['minutes'] // 60} hours {high['minutes'] % 60} minutes "
        f"continuously above 180 "
        f"({fmt_span(high['start'].date(), high['end'].date())}), peak {story['peak']:.0f}. "
        "Color follows the same 70 / 180 / 250 bands."
    )


def clock_caption(story: dict) -> str:
    early = fmt_span(story["early"][0]["date"], story["early"][-1]["date"])
    recent = fmt_span(story["recent"][0]["date"], story["recent"][-1]["date"])
    return (
        f"Hour-of-day median and IQR for {early} versus {recent}. "
        f"{early} is sparse LibreLink history; {recent} is the latest week of filled days."
    )


def write_index(out: Path, generated: list[tuple[str, str, str]], story: dict) -> Path:
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
  <title>Glucose change — GluChron</title>
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
      {lede_html(story)}
    </p>
    <div class="stats">
{stats_html(story)}
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
    story = build_story(daily, readings, offset, args.tz_offset)
    args.out.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    written += plot_story(daily, story, args.out)
    written += plot_daily_mean(daily, story, args.out)
    written += plot_time_in_range(daily, story, args.out)
    written += plot_trace(readings, daily, story, args.out)
    written += plot_clock(readings, offset, story, args.out)

    window = fmt_span(story["first"]["date"], story["last"]["date"])
    index = write_index(
        args.out,
        [
            (
                "00-thirty-day-change",
                f"The change, {window}",
                "Daily mean and overnight median on top; stacked time-in-range below. GMI uses 3.31 + 0.02392 × mean.",
            ),
            (
                "01-daily-mean-overnight",
                "Daily mean, median, and overnight floor",
                mean_caption(story),
            ),
            (
                "02-time-in-range",
                "Time in range by day",
                tir_caption(story),
            ),
            (
                "03-glucose-trace",
                "Five-minute overview trace",
                trace_caption(story),
            ),
            (
                "04-early-vs-recent-clock",
                "Clock-day early versus recent",
                clock_caption(story),
            ),
        ],
        story,
    )
    written.append(index)
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
