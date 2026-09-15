import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from teslai.builder import Session
from teslai.db import repo
from teslai.live import rebuild_recent
from teslai.reducer import Event

pytestmark = pytest.mark.integration


def _vehicle(engine):
    vin = ("LIVE" + uuid.uuid4().hex.upper())[:17].replace("I", "1").replace("O", "0").replace("Q", "9")
    with engine.begin() as conn:
        a = repo.create_account(conn, f"live-{vin}")
        v = repo.create_vehicle(conn, a, vin, "Car", "America/Chicago")
    return a, v


def _drive_events(v, t0):
    evs = [Event(v, t0, "Gear", "ShiftStateD"), Event(v, t0, "Odometer", 500.0)]
    for m in range(1, 21):
        evs.append(Event(v, t0 + timedelta(minutes=m), "VehicleSpeed", 40 + m % 3))
        evs.append(Event(v, t0 + timedelta(minutes=m), "Odometer", 500.0 + m * 0.6))
    evs.append(Event(v, t0 + timedelta(minutes=21), "Gear", "ShiftStateP"))
    return evs


def _kinds(engine, a, v, start, end):
    with engine.connect() as conn:
        return [(r["kind"], r["start_ts"]) for r in repo.sessions_between(conn, a, v, start, end)]


def test_live_rebuild_creates_sessions_idempotently_and_picks_up_late_data(engine):
    a, v = _vehicle(engine)
    now = datetime.now(UTC).replace(microsecond=0)
    t0 = now - timedelta(hours=3)
    with engine.begin() as conn:
        repo.record_connectivity(conn, a, v, t0 - timedelta(minutes=5), True)
        repo.insert_events(conn, a, _drive_events(v, t0))
    assert rebuild_recent(engine, a, v, now=now) >= 2
    first = _kinds(engine, a, v, now - timedelta(days=3), now + timedelta(hours=1))
    assert ("drive", t0) in first
    assert rebuild_recent(engine, a, v, now=now) == len(first)
    assert _kinds(engine, a, v, now - timedelta(days=3), now + timedelta(hours=1)) == first
    # A charge that arrives late, after the first rebuild, appears on the next run.
    c0 = t0 + timedelta(hours=1)
    with engine.begin() as conn:
        repo.insert_events(conn, a, [
            Event(v, c0, "DetailedChargeState", "DetailedChargeStateCharging"),
            Event(v, c0, "ACChargingEnergyIn", 0.0),
            Event(v, c0 + timedelta(minutes=50), "ACChargingEnergyIn", 7.5),
            Event(v, c0 + timedelta(minutes=51), "DetailedChargeState", "DetailedChargeStateComplete")])
    rebuild_recent(engine, a, v, now=now)
    with engine.connect() as conn:
        charges = repo.sessions_between(conn, a, v, now - timedelta(days=1), now, kind="charge")
    assert len(charges) == 1 and charges[0]["energy_added_kwh"] == 7.5


def test_live_rebuild_never_touches_older_imported_history(engine):
    a, v = _vehicle(engine)
    now = datetime.now(UTC).replace(microsecond=0)
    old = now - timedelta(days=10)
    with engine.begin() as conn:
        repo.replace_sessions(conn, a, v, old - timedelta(days=1), old + timedelta(days=1), [
            Session("drive", old, old + timedelta(minutes=30), start_odometer=1.0, end_odometer=9.0)],
            "teslafi_import", 1)
        repo.record_connectivity(conn, a, v, now - timedelta(hours=2), True)
        repo.insert_events(conn, a, _drive_events(v, now - timedelta(hours=2)))
    rebuild_recent(engine, a, v, now=now)
    with engine.connect() as conn:
        sources = conn.execute(text("SELECT source, count(*) FROM sessions WHERE vehicle_id = :v "
                                    "GROUP BY source ORDER BY source"), {"v": v}).all()
    assert dict(sources)["teslafi_import"] == 1 and dict(sources)["telemetry"] >= 2


def test_live_rebuild_with_no_data_writes_nothing(engine):
    a, v = _vehicle(engine)
    assert rebuild_recent(engine, a, v) == 0
