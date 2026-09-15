from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from teslai.builder import Session
from teslai.gate import compare, render_table, summarize, totals_from_sessions

CHI = ZoneInfo("America/Chicago")


def drive(day, odo, miles, month=7, flags=()):
    start = datetime(2026, month, day, 14, tzinfo=UTC)
    return Session("drive", start, start + timedelta(minutes=30), start_odometer=odo,
                   end_odometer=odo + miles, flags=set(flags))


def charge(day, kwh, month=7):
    start = datetime(2026, month, day, 23, tzinfo=UTC)
    return Session("charge", start, start + timedelta(hours=2), energy_added_kwh=kwh)


def test_totals_by_local_month_and_short_drives_excluded():
    # 2026-08-01 03:00 UTC is still July 31 in Chicago.
    late = Session("drive", datetime(2026, 8, 1, 3, tzinfo=UTC),
                   datetime(2026, 8, 1, 3, 20, tzinfo=UTC), start_odometer=1030.0,
                   end_odometer=1040.0)
    s = [drive(1, 1000.0, 10.0), drive(2, 1010.0, 20.0), late,
         drive(3, 1040.0, 0.01, flags={"short"}), charge(2, 30.0), charge(5, 12.5),
         Session("idle", datetime(2026, 7, 9, tzinfo=UTC))]
    t = totals_from_sessions(s, CHI)
    assert list(t) == ["2026-07"]
    jul = t["2026-07"]
    assert (jul.drive_count, round(jul.miles, 2), jul.charge_count, jul.kwh_added) == \
           (3, 40.0, 2, 42.5)
    assert jul.odometer_delta == 40.0


def test_compare_passes_within_one_percent_and_splits_eras():
    ours = totals_from_sessions([drive(1, 1000.0, 100.0), charge(1, 50.0),
                                 drive(1, 2000.0, 80.0, month=9), charge(2, 40.0, month=9)], CHI)
    theirs = {"2026-07": {"drive_count": 1, "miles": 100.5, "charge_count": 1, "kwh_added": 50.2},
              "2026-09": {"drive_count": 1, "miles": 80.0, "charge_count": 1, "kwh_added": 40.0}}
    results = compare(ours, theirs, switch_date=date(2026, 8, 15))
    assert all(r.ok for r in results)
    assert summarize(results) == {"polling": {"months": 1, "passed": 1},
                                  "streaming": {"months": 1, "passed": 1}}
    assert "PASS" in render_table(results)


def test_compare_fails_on_miles_off_by_more_than_one_percent():
    ours = totals_from_sessions([drive(1, 1000.0, 100.0)], CHI)
    theirs = {"2026-07": {"drive_count": 1, "miles": 103.0, "charge_count": 0, "kwh_added": 0}}
    [r] = compare(ours, theirs)
    assert not r.ok
    miles = next(m for m in r.metrics if m.metric == "miles")
    assert not miles.ok and round(miles.rel_diff, 3) == -0.029


def test_counts_allow_one_session_difference():
    ours = totals_from_sessions([drive(d, 1000.0 + d * 10, 10.0) for d in range(1, 4)], CHI)
    theirs = {"2026-07": {"drive_count": 4, "miles": 30.0, "charge_count": 0, "kwh_added": 0}}
    [r] = compare(ours, theirs)
    assert next(m for m in r.metrics if m.metric == "drive_count").ok


def test_odometer_cross_check_catches_matching_but_wrong_numbers():
    # Two drives whose distances sum to 30 while the odometer moved 60: a gap
    # where a drive was lost on both sides would still "match" TeslaFi.
    ours = totals_from_sessions([drive(1, 1000.0, 10.0), drive(2, 1040.0, 20.0)], CHI)
    theirs = {"2026-07": {"drive_count": 2, "miles": 30.0, "charge_count": 0, "kwh_added": 0}}
    [r] = compare(ours, theirs)
    assert r.odometer_ok is False and not r.ok
    assert "odometer delta" in r.notes[0]


def test_month_missing_from_answer_key_fails():
    ours = totals_from_sessions([drive(1, 1000.0, 10.0)], CHI)
    [r] = compare(ours, {})
    assert not r.ok and "missing" in r.notes[0]
