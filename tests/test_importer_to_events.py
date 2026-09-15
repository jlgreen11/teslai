import csv
from datetime import UTC, datetime

from teslai.builder import build_sessions
from teslai.importer.teslafi import read_rows, to_events

HEADER = ["Date", "state", "shift_state", "speed", "odometer", "battery_level",
          "charging_state", "latitude", "longitude"]


def test_teslafi_csv_day_builds_expected_sessions(tmp_path):
    rows = [
        ["2026-07-01 07:55:00", "online", "P", "0", "1000.0", "80", "Disconnected", "39.0", "-94.5"],
        ["2026-07-01 08:00:00", "driving", "D", "30", "1000.2", "80", "Disconnected", "39.0", "-94.5"],
        ["2026-07-01 08:01:00", "driving", "D", "45", "1001.0", "79", "Disconnected", "39.0", "-94.5"],
        ["2026-07-01 08:20:00", "driving", "D", "40", "1012.0", "76", "Disconnected", "39.1", "-94.6"],
        ["2026-07-01 08:22:00", "online", "P", "0", "1012.3", "76", "Disconnected", "39.1", "-94.6"],
        ["2026-07-01 08:30:00", "online", "P", "0", "1012.3", "76", "Charging", "39.1", "-94.6"],
        ["2026-07-01 10:30:00", "online", "P", "0", "1012.3", "90", "Complete", "39.1", "-94.6"],
        ["2026-07-01 11:00:00", "asleep", "", "", "1012.3", "90", "Complete", "", ""],
    ]
    p = tmp_path / "TeslaFi72026.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    parsed, report = read_rows(p, "America/Chicago")
    events, conn = to_events(list(parsed), vehicle_id=1)
    assert [c.connected for c in conn] == [True, False]
    sessions = build_sessions(events, conn, until=datetime(2026, 7, 1, 17, tzinfo=UTC))
    assert [s.kind for s in sessions] == ["idle", "drive", "idle", "charge", "idle", "sleep"]
    drive = sessions[1]
    assert round(drive.distance, 1) == 12.1
    assert drive.start == datetime(2026, 7, 1, 13, 0, tzinfo=UTC)
    assert sessions[3].start_battery == 76 and sessions[3].end_battery == 90
    assert report.rows_imported == 8


def test_charge_energy_added_becomes_ac_or_dc_counter(tmp_path):
    header = HEADER + ["charge_energy_added", "fast_charger_present"]
    rows = [
        ["2026-07-01 08:00:00", "online", "P", "0", "1000.0", "40", "Disconnected", "39", "-94", "0", "0"],
        ["2026-07-01 08:10:00", "online", "P", "0", "1000.0", "40", "Charging", "39", "-94", "0.0", "0"],
        ["2026-07-01 09:10:00", "online", "P", "0", "1000.0", "60", "Charging", "39", "-94", "11.5", "0"],
        ["2026-07-01 09:20:00", "online", "P", "0", "1000.0", "62", "Complete", "39", "-94", "12.25", "0"],
        ["2026-07-01 12:00:00", "online", "P", "0", "1000.0", "30", "Charging", "39", "-94", "0.0", "1"],
        ["2026-07-01 12:30:00", "online", "P", "0", "1000.0", "80", "Charging", "39", "-94", "38.0", "1"],
        ["2026-07-01 12:31:00", "online", "P", "0", "1000.0", "80", "Complete", "39", "-94", "38.0", "1"],
    ]
    p = tmp_path / "t.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    parsed, _ = read_rows(p, "UTC")
    events, conn = to_events(list(parsed), vehicle_id=1)
    assert {e.field for e in events if "EnergyIn" in e.field} == {"ACChargingEnergyIn", "DCChargingEnergyIn"}
    sessions = build_sessions(events, conn, until=datetime(2026, 7, 1, 18, tzinfo=UTC))
    charges = [s for s in sessions if s.kind == "charge"]
    assert [(c.charger, c.energy_added_kwh) for c in charges] == [("ac", 12.25), ("dc", 38.0)]
