import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from teslai.errors import TeslaiError
from teslai.importer.teslafi import read_rows

HEADER = ["Date", "state", "shift_state", "speed", "odometer", "battery_level",
          "charging_state", "latitude", "longitude", "locked", "outside_temp", "extra_col"]


def write_csv(path: Path, rows: list[list[str]], header=HEADER) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def row(date, state="online", gear="", speed="", odo="31000.0", batt="70", chg="Disconnected",
        lat="39.0", lon="-94.5", locked="1", temp="20.5"):
    return [date, state, gear, speed, odo, batt, chg, lat, lon, locked, temp, "ignored"]


def test_basic_row_maps_to_telemetry_names(tmp_path):
    p = write_csv(tmp_path / "t.csv", [row("2026-07-01 08:00:00", gear="D", speed="35")])
    rows, report = read_rows(p, "America/Chicago")
    [r] = list(rows)
    assert r.ts == datetime(2026, 7, 1, 13, 0, tzinfo=UTC)
    assert r.fields["Gear"] == "D"
    assert r.fields["VehicleSpeed"] == 35.0
    assert r.fields["Locked"] is True
    assert r.fields["Location"] == {"latitude": 39.0, "longitude": -94.5}
    assert r.connected is True
    assert report.rows_imported == 1 and not report.skipped


def test_none_and_empty_values_are_dropped_not_zeroed(tmp_path):
    p = write_csv(tmp_path / "t.csv", [row("2026-07-01 08:00:00", speed="None", batt="",
                                          lat="None", lon="None")])
    [r] = list(read_rows(p, "America/Chicago")[0])
    assert "VehicleSpeed" not in r.fields
    assert "BatteryLevel" not in r.fields
    assert "Location" not in r.fields


def test_fall_back_hour_repeated_times_stay_increasing(tmp_path):
    # 2025-11-02 America/Chicago: 01:00-01:59 CDT happens, then again as CST.
    dates = ["2025-11-02 00:50:00", "2025-11-02 01:10:00", "2025-11-02 01:50:00",
             "2025-11-02 01:10:00", "2025-11-02 01:50:00", "2025-11-02 02:10:00"]
    p = write_csv(tmp_path / "t.csv", [row(d) for d in dates])
    rows, report = read_rows(p, "America/Chicago")
    ts = [r.ts for r in rows]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)
    assert ts[1] == datetime(2025, 11, 2, 6, 10, tzinfo=UTC)   # CDT, UTC-5
    assert ts[3] == datetime(2025, 11, 2, 7, 10, tzinfo=UTC)   # CST, UTC-6
    assert report.ambiguous_resolved == 4
    assert report.out_of_order == 0


def test_spring_forward_gap_time_is_shifted_and_counted(tmp_path):
    # 2026-03-08 America/Chicago: 02:00-02:59 does not exist.
    p = write_csv(tmp_path / "t.csv", [row("2026-03-08 01:55:00"), row("2026-03-08 02:30:00"),
                                      row("2026-03-08 03:05:00")])
    rows, report = read_rows(p, "America/Chicago")
    ts = [r.ts for r in rows]
    assert ts == sorted(ts)
    assert ts[1] == datetime(2026, 3, 8, 8, 0, tzinfo=UTC)  # the 02:00 CST -> 03:00 CDT instant
    assert report.nonexistent_shifted == 1


def test_missing_required_column_fails_loudly(tmp_path):
    header = [h for h in HEADER if h != "odometer"]
    p = write_csv(tmp_path / "t.csv", [], header=header)
    rows, _ = read_rows(p, "America/Chicago")
    with pytest.raises(TeslaiError) as exc:
        list(rows)
    assert exc.value.info.code == "TSL-IMPORT-SCHEMA"
    assert "odometer" in str(exc.value)


def test_timezone_is_required_and_validated(tmp_path):
    p = write_csv(tmp_path / "t.csv", [])
    for tz in (None, "", "Mars/Olympus"):
        with pytest.raises(TeslaiError) as exc:
            read_rows(p, tz)
        assert exc.value.info.code == "TSL-IMPORT-TZ"


def test_bad_rows_are_skipped_and_reported(tmp_path):
    p = write_csv(tmp_path / "t.csv", [
        row("not-a-date"),
        row("2026-07-01 08:00:00", locked="maybe"),
        row("2026-07-01 08:01:00", lat="123.0", lon="10.0"),
        row("2026-07-01 08:02:00"),
    ])
    rows, report = read_rows(p, "UTC")
    assert len(list(rows)) == 1
    assert [line for line, _ in report.skipped] == [2, 3, 4]
    assert report.rows_read == 4


def test_sleep_state_maps_to_disconnected(tmp_path):
    p = write_csv(tmp_path / "t.csv", [row("2026-07-01 08:00:00", state="asleep"),
                                      row("2026-07-01 08:05:00", state="unknownstate")])
    r1, r2 = list(read_rows(p, "UTC")[0])
    assert r1.connected is False
    assert r2.connected is None
