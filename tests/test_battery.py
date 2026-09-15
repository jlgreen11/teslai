from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from teslai.battery import build_report

CHI = ZoneInfo("America/Chicago")
T0 = datetime(2025, 1, 5, 23, tzinfo=UTC)


def row(days, level, rng):
    return {"end_ts": T0 + timedelta(days=days), "end_battery": level, "end_rated_range": rng}


def test_report_baseline_current_loss_and_months():
    # est_100 = (300 - 0.02 d) / 0.9: 333.3 on day 0, falling ~0.22 per 10 days.
    rows = [row(d, 90, 300 - d * 0.02) for d in range(0, 400, 10)]
    rows.append(row(5, 20, 50))       # low level: excluded
    rows.append(row(6, 90, None))     # no range: excluded
    r = build_report(rows, CHI)
    assert len(r.points) == 40
    # Baseline: median of the 5 highest in the first 90 days -> day 20 -> 332.9.
    # Current: median of the last 5 (days 350-390) -> day 370 -> 325.1.
    assert r.baseline == 332.9 and r.current == 325.1
    assert r.loss_pct == 2.34
    assert r.months[0]["month"] == "2025-01" and r.max_estimate == 333.3


def test_single_outlier_does_not_move_current():
    rows = [row(d, 80, 240) for d in range(0, 50, 5)] + [row(60, 80, 200)]
    assert build_report(rows, CHI).current == 300.0


def test_empty_report():
    r = build_report([row(1, 10, 30)], CHI)
    assert r.points == [] and r.baseline is None and r.loss_pct is None
