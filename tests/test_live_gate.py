from datetime import UTC, datetime, timedelta

import httpx

from teslai.live_gate import (
    LiveGateParams,
    check_continuity,
    check_energy,
    check_gaps,
    check_odometer,
    check_supercharger,
    evaluate,
    passed,
)
from teslai.tesla.telemetry_config import remove

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)
P = LiveGateParams()


def drive(h, so, eo, flags=()):
    return {"kind": "drive", "start_ts": T0 + timedelta(hours=h), "end_ts": T0 + timedelta(hours=h, minutes=30),
            "start_odometer": so, "end_odometer": eo, "flags": list(flags), "start_battery": None,
            "end_battery": None, "energy_added_kwh": None, "charger": None}


def charge(h, sb, eb, kwh, charger="ac", invoice=None):
    return {"kind": "charge", "start_ts": T0 + timedelta(hours=h), "end_ts": T0 + timedelta(hours=h + 1),
            "start_odometer": None, "end_odometer": None, "flags": [], "start_battery": sb, "end_battery": eb,
            "energy_added_kwh": kwh, "charger": charger, "invoice_total": invoice}


def test_odometer_and_continuity_pass_for_contiguous_drives():
    drives = [drive(0, 100.0, 110.0), drive(5, 110.1, 125.0), drive(9, 125.0, 140.0)]
    assert check_odometer(drives, P).ok and check_continuity(drives, P).ok


def test_missing_drive_fails_both_checks():
    drives = [drive(0, 100.0, 110.0), drive(9, 125.0, 140.0)]
    assert not check_odometer(drives, P).ok
    c = check_continuity(drives, P)
    assert not c.ok and "15.00 mi unlogged" in c.problems[0]


def test_gap_while_connected_fails_but_sleep_does_not():
    conn = [(T0, True), (T0 + timedelta(hours=2), False), (T0 + timedelta(hours=10), True)]
    events = [T0 + timedelta(minutes=m) for m in range(0, 121, 10)]
    end = T0 + timedelta(hours=10, minutes=20)
    assert check_gaps(conn, events + [T0 + timedelta(hours=10, minutes=5)], end, P).ok
    bad = [e for e in events if not (T0 + timedelta(minutes=30) < e < T0 + timedelta(minutes=90))]
    g = check_gaps(conn, bad, end, P)
    assert not g.ok and "while connected" in g.problems[0]


def test_energy_and_supercharger_are_warnings():
    charges = [charge(1, 40, 80, 31.0), charge(3, 20, 60, 12.0), charge(6, 10, 70, 45.0, "dc")]
    e = check_energy(charges, P)
    assert e.severity == "warn" and len(e.problems) == 1
    s = check_supercharger(charges, history_synced=True)
    assert not s.ok and s.severity == "warn"
    assert check_supercharger(charges, history_synced=False).ok


def test_overall_pass_ignores_warnings():
    sessions = [drive(0, 100.0, 110.0), drive(5, 110.0, 120.0), charge(8, 20, 60, 12.0)]
    checks = evaluate(sessions, [(T0, True), (T0 + timedelta(minutes=5), False)],
                      [T0], T0 + timedelta(days=1), history_synced=False)
    assert passed(checks) and not all(c.ok for c in checks)


def test_telemetry_remove_calls_delete():
    seen = {}

    def handler(req):
        seen["method"], seen["url"] = req.method, str(req.url)
        return httpx.Response(200, json={"response": {"updated_vehicles": 1}})

    remove(httpx.Client(transport=httpx.MockTransport(handler)), "https://fleet", "tok", "VIN123")
    assert seen == {"method": "DELETE", "url": "https://fleet/api/1/vehicles/VIN123/fleet_telemetry_config"}
