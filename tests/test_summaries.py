from datetime import UTC, datetime, timedelta

from teslai.costs import load_tariffs
from teslai.rules import RuleConfig
from teslai.summaries import summary_conditions

T0 = datetime(2026, 9, 3, 13, tzinfo=UTC)


def row(kind, minutes, so=None, eo=None, kwh=None, flags=(), sp=None, ep=None, ep_kind=None):
    return {"vehicle_id": 1, "timezone": "America/Chicago", "kind": kind, "start_ts": T0,
            "end_ts": T0 + timedelta(minutes=minutes), "start_odometer": so, "end_odometer": eo,
            "start_battery": 80.0, "end_battery": 74.0, "energy_added_kwh": kwh,
            "charger": "ac" if kwh else None, "flags": list(flags), "start_place": sp, "end_place": ep,
            "start_place_kind": None, "end_place_kind": ep_kind}


def test_drive_and_charge_text_and_thresholds():
    rows = [row("drive", 32, 1000.0, 1020.0, sp="Coffee", ep="Home"),
            row("drive", 3, 1020.0, 1020.4),
            row("drive", 30, 1020.0, 1030.0, flags=["short"]),
            row("charge", 120, kwh=6.0, ep="Home", ep_kind="home"),
            row("charge", 10, kwh=0.3)]
    conds = summary_conditions(rows, RuleConfig(), tariffs=load_tariffs())
    assert len(conds) == 2 and all(c.informational for c in conds)
    drive, charge = conds
    assert drive.detail == "Drive Thu Sep 3 8:00 AM–8:32 AM, Coffee → Home, 20.0 mi, battery 80% → 74%"
    assert charge.detail.startswith("Charge Thu Sep 3 8:00 AM–10:00 AM at Home, 6.0 kWh AC, ")
    assert drive.key == f"1:drive:{T0.isoformat()}"


def test_summaries_respect_configured_minimums():
    cfg = RuleConfig(summary_drive_min_miles=25, summary_charge_min_kwh=10)
    rows = [row("drive", 32, 1000.0, 1020.0), row("charge", 120, kwh=6.0)]
    assert summary_conditions(rows, cfg) == []
