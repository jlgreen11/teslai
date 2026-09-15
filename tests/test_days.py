from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from teslai.days import day_window, summarize_day

CHI = ZoneInfo("America/Chicago")


def test_day_window_normal_and_dst_days():
    s, e = day_window(date(2026, 7, 1), CHI)
    assert s == datetime(2026, 7, 1, 5, tzinfo=UTC) and (e - s).total_seconds() == 86400
    s, e = day_window(date(2026, 3, 8), CHI)
    assert (e - s).total_seconds() == 23 * 3600
    s, e = day_window(date(2025, 11, 2), CHI)
    assert (e - s).total_seconds() == 25 * 3600


def row(kind, h, end_h=None, so=None, eo=None, kwh=None, flags=()):
    return {"kind": kind, "start_ts": datetime(2026, 7, 1, h, tzinfo=UTC),
            "end_ts": datetime(2026, 7, 1, end_h, tzinfo=UTC) if end_h else None,
            "start_odometer": so, "end_odometer": eo, "start_battery": 80.0,
            "end_battery": 70.0, "energy_added_kwh": kwh, "charger": "ac" if kwh else None,
            "flags": list(flags)}


def test_summary_counts_excludes_short_and_localizes_times():
    rows = [row("drive", 13, 14, 1000.0, 1012.5), row("drive", 15, 16, 1012.5, 1012.52, flags=["short"]),
            row("charge", 17, 19, kwh=18.25), row("sleep", 20)]
    s = summarize_day(date(2026, 7, 1), CHI, rows)
    assert (s.drives, s.miles, s.charges, s.kwh_added) == (1, 12.5, 1, 18.25)
    assert s.sessions[0]["start"] == "2026-07-01T08:00:00-05:00"
    assert s.sessions[3]["end"] is None
    assert s.sessions[2]["distance_miles"] is None
