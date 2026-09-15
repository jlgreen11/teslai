"""Battery degradation from charge sessions.

For each charge that ends at or above `min_level` percent with a known rated
range, the full-charge range is estimated as

    est_100 = rated_range_at_end / battery_level_at_end × 100

Low end levels are excluded because range estimates extrapolate poorly from them.

    baseline  median of the 5 highest estimates in the first 90 days of data
    current   median of the latest 5 estimates
    loss %    (baseline − current) / baseline × 100

Medians keep one odd reading (a cold morning, a calibration jump) from moving
the headline number.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class RangePoint:
    ts: datetime
    battery_level: float
    rated_range: float

    @property
    def est_100(self) -> float:
        return self.rated_range / self.battery_level * 100


@dataclass
class BatteryReport:
    points: list[dict]
    months: list[dict]
    baseline: float | None
    current: float | None
    loss_pct: float | None
    max_estimate: float | None


def build_report(rows: list[dict], tz: ZoneInfo, min_level: float = 50.0) -> BatteryReport:
    points = sorted(
        (RangePoint(r["end_ts"], float(r["end_battery"]), float(r["end_rated_range"]))
         for r in rows
         if r.get("end_ts") and r.get("end_battery") and r.get("end_rated_range")
         and float(r["end_battery"]) >= min_level and float(r["end_rated_range"]) > 0),
        key=lambda p: p.ts)
    if not points:
        return BatteryReport([], [], None, None, None, None)
    by_month: dict[str, list[float]] = defaultdict(list)
    for p in points:
        by_month[f"{p.ts.astimezone(tz):%Y-%m}"].append(p.est_100)
    early = [p.est_100 for p in points if p.ts - points[0].ts <= timedelta(days=90)]
    baseline = median(sorted(early, reverse=True)[:5])
    current = median([p.est_100 for p in points[-5:]])
    return BatteryReport(
        points=[{"date": p.ts.astimezone(tz).date().isoformat(), "battery_level": p.battery_level,
                 "est_100_range": round(p.est_100, 1)} for p in points],
        months=[{"month": m, "median_est_100_range": round(median(v), 1), "charges": len(v)}
                for m, v in sorted(by_month.items())],
        baseline=round(baseline, 1),
        current=round(current, 1),
        loss_pct=round((baseline - current) / baseline * 100, 2),
        max_estimate=round(max(p.est_100 for p in points), 1),
    )
