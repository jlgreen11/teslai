import csv
import io
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from teslai.costs import load_tariffs
from teslai.totals import CSV_COLUMNS, sessions_csv, totals

CHI = ZoneInfo("America/Chicago")


def r(kind, start, minutes, so=None, eo=None, kwh=None, flags=(), place=None, place_kind=None):
    return {"kind": kind, "start_ts": start, "end_ts": start + timedelta(minutes=minutes) if minutes else None,
            "start_odometer": so, "end_odometer": eo, "start_battery": 70.0, "end_battery": 60.0,
            "energy_added_kwh": kwh, "charger": "ac" if kwh else None, "flags": list(flags),
            "start_place": place, "end_place": place, "start_place_kind": place_kind,
            "end_place_kind": place_kind}


ROWS = [
    r("drive", datetime(2026, 7, 31, 4, 30, tzinfo=UTC), 30, 1000.0, 1010.0),   # July 30 local
    r("drive", datetime(2026, 7, 31, 15, tzinfo=UTC), 20, 1010.0, 1025.5),
    r("drive", datetime(2026, 7, 31, 16, tzinfo=UTC), 1, 1025.5, 1025.51, flags=["short"]),
    r("charge", datetime(2026, 8, 1, 1, tzinfo=UTC), 120, kwh=10.0, place="Home", place_kind="home"),
    r("drive", datetime(2026, 8, 2, 15, tzinfo=UTC), 40, 1025.51, 1060.0),
    r("sleep", datetime(2026, 8, 3, 3, tzinfo=UTC), 0),
]


def test_monthly_totals_use_local_dates_and_skip_short_and_open():
    t = totals(ROWS, CHI, "month", tariffs=load_tariffs())
    assert [x["period"] for x in t] == ["2026-07", "2026-08"]
    jul, aug = t
    assert (jul["drives"], jul["miles"], jul["drive_minutes"]) == (2, 25.5, 50)
    assert (jul["charges"], jul["kwh_added"]) == (1, 10.0)  # 8pm July 31 local
    assert jul["charging_cost"] > 0
    assert (aug["drives"], round(aug["miles"], 2)) == (1, 34.49)


def test_day_and_year_grouping_and_bad_group():
    assert [x["period"] for x in totals(ROWS, CHI, "day")] == ["2026-07-30", "2026-07-31", "2026-08-02"]
    assert [x["period"] for x in totals(ROWS, CHI, "year")] == ["2026"]
    with pytest.raises(ValueError):
        totals(ROWS, CHI, "week")


def test_csv_export_columns_local_times_and_blanks():
    text = sessions_csv(ROWS, CHI, tariffs=load_tariffs())
    reader = csv.DictReader(io.StringIO(text))
    assert reader.fieldnames == CSV_COLUMNS
    rows = list(reader)
    assert len(rows) == 6
    assert rows[0]["start"] == "2026-07-30T23:30:00-05:00" and rows[0]["distance_miles"] == "10.0"
    assert rows[2]["flags"] == "short"
    assert rows[3]["cost"] != "" and rows[3]["end_place"] == "Home"
    assert rows[5]["end"] == "" and rows[5]["duration_minutes"] == ""
