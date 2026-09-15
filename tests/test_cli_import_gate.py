import csv
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from teslai.cli import app
from teslai.errors import TeslaiError
from teslai.importer.answer_key import load_answer_key

runner = CliRunner()
HEADER = ["Date", "state", "shift_state", "speed", "odometer", "battery_level",
          "charging_state", "latitude", "longitude"]


def day_rows(day: str, odo: float):
    return [
        [f"{day} 07:55:00", "online", "P", "0", f"{odo}", "80", "Disconnected", "39.0", "-94.5"],
        [f"{day} 08:00:00", "driving", "D", "30", f"{odo + 0.2}", "80", "Disconnected", "39", "-94.5"],
        [f"{day} 08:20:00", "driving", "D", "40", f"{odo + 12.0}", "76", "Disconnected", "39.1", "-94.6"],
        [f"{day} 08:22:00", "online", "P", "0", f"{odo + 12.3}", "76", "Disconnected", "39.1", "-94.6"],
        [f"{day} 08:30:00", "online", "P", "0", f"{odo + 12.3}", "76", "Charging", "39.1", "-94.6"],
        [f"{day} 08:31:00", "online", "P", "0", f"{odo + 12.3}", "76", "Charging", "39.1", "-94.6"],
        [f"{day} 10:30:00", "online", "P", "0", f"{odo + 12.3}", "90", "Complete", "39.1", "-94.6"],
        [f"{day} 11:00:00", "asleep", "", "", f"{odo + 12.3}", "90", "Complete", "", ""],
    ]


def write_month(tmp: Path, name: str, days: list[tuple[str, float]]) -> Path:
    p = tmp / name
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for d, odo in days:
            w.writerows(day_rows(d, odo))
    return p


@pytest.fixture()
def history(tmp_path):
    d = tmp_path / "teslafi"
    d.mkdir()
    # Files named out of chronological order on purpose.
    write_month(d, "TeslaFi82026.csv", [("2026-08-03", 1100.0)])
    write_month(d, "TeslaFi72026.csv", [("2026-07-01", 1000.0), ("2026-07-02", 1012.3)])
    return d


def test_import_dry_run_prints_monthly_totals(history):
    r = runner.invoke(app, ["import", "teslafi", str(history), "--tz", "America/Chicago"])
    assert r.exit_code == 0, r.output
    assert "2026-07       2     24.2        2" in r.output
    assert "2026-08       1     12.1        1" in r.output
    assert "Dry run" in r.output


def test_import_requires_timezone(history):
    r = runner.invoke(app, ["import", "teslafi", str(history)])
    assert r.exit_code == 2
    assert "TSL-IMPORT-TZ" in r.output


def test_gate_passes_with_matching_normalized_key(history, tmp_path):
    key = tmp_path / "key.json"
    key.write_text(json.dumps({
        "2026-07": {"drive_count": 2, "miles": 24.2, "charge_count": 2, "kwh_added": 0},
        "2026-08": {"drive_count": 1, "miles": 12.1, "charge_count": 1, "kwh_added": 0}}))
    report = tmp_path / "gate.json"
    r = runner.invoke(app, ["gate", "history", str(history), "--answer-key", str(key),
                            "--tz", "America/Chicago", "--switch-date", "2026-08-01",
                            "--report", str(report)])
    assert r.exit_code == 0, r.output
    assert "polling: 1/1 months pass" in r.output and "streaming: 1/1 months pass" in r.output
    assert json.loads(report.read_text())[0]["ok"] is True


def test_gate_fails_when_teslafi_disagrees(history, tmp_path):
    key = tmp_path / "key.json"
    key.write_text(json.dumps({
        "2026-07": {"drive_count": 2, "miles": 30.0, "charge_count": 2, "kwh_added": 0},
        "2026-08": {"drive_count": 1, "miles": 12.1, "charge_count": 1, "kwh_added": 0}}))
    r = runner.invoke(app, ["gate", "history", str(history), "--answer-key", str(key),
                            "--tz", "America/Chicago"])
    assert r.exit_code == 1
    assert "FAIL" in r.output


def test_answer_key_from_teslafi_style_records(tmp_path):
    drives = tmp_path / "drives.json"
    drives.write_text(json.dumps({"response": [
        {"startDate": "2026-07-01 08:00:00", "distance": "12.1"},
        {"startDate": "2026-07-31 22:30:00", "distance": 5},
        {"startDate": "2026-08-01 08:00:00", "distance": 7.5}]}))
    charges = tmp_path / "charges.json"
    charges.write_text(json.dumps([{"Date": "07/02/2026 09:00 PM", "charge_energy_added": 20.5}]))
    key = load_answer_key([drives, charges], ZoneInfo("America/Chicago"))
    assert key["2026-07"]["drive_count"] == 2 and round(key["2026-07"]["miles"], 1) == 17.1
    assert key["2026-07"]["charge_count"] == 1 and key["2026-07"]["kwh_added"] == 20.5
    assert key["2026-08"]["drive_count"] == 1


def test_answer_key_unknown_shape_fails_loudly(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"when": "2026-07-01", "howfar": 3}]))
    with pytest.raises(TeslaiError) as exc:
        load_answer_key([bad], ZoneInfo("UTC"))
    assert exc.value.info.code == "TSL-IMPORT-SCHEMA" and "when" in str(exc.value)
