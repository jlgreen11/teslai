import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from teslai import alerts
from teslai.db import repo
from teslai.reducer import Event

pytestmark = pytest.mark.integration


def _vehicle(engine):
    vin = ("ALERT" + uuid.uuid4().hex.upper())[:17].replace("I", "1").replace("O", "0").replace("Q", "9")
    with engine.begin() as conn:
        a = repo.create_account(conn, f"owner-{vin}")
        v = repo.create_vehicle(conn, a, vin)
    return a, v


def test_silence_fires_once_then_resolves(engine):
    a, v = _vehicle(engine)
    now = datetime.now(UTC)
    with engine.begin() as conn:
        repo.record_connectivity(conn, a, v, now - timedelta(hours=1), True)
        conn.execute(text("INSERT INTO telemetry_events (account_id, vehicle_id, ts, field, value, received_at) "
                          "VALUES (:a, :v, :t, 'Gear', '\"ShiftStateP\"', :t)"),
                     {"a": a, "v": v, "t": now - timedelta(minutes=40)})
    sent: list[tuple[str, str]] = []
    r1 = alerts.run_once(engine, a, lambda t, b: sent.append((t, b)), now=now)
    r2 = alerts.run_once(engine, a, lambda t, b: sent.append((t, b)), now=now + timedelta(minutes=1))
    assert [c.code for c in r1["fired"]] == ["TSL-INGEST-SILENT"] and r2["fired"] == []
    assert len(sent) == 1
    with engine.begin() as conn:
        repo.insert_events(conn, a, [Event(v, now + timedelta(minutes=2), "BatteryLevel", 70)])
        conn.execute(text("UPDATE telemetry_events SET received_at = :t WHERE vehicle_id = :v AND field = 'BatteryLevel'"),
                     {"t": now + timedelta(minutes=2), "v": v})
    r3 = alerts.run_once(engine, a, lambda t, b: sent.append((t, b)), now=now + timedelta(minutes=3))
    assert [c.rule for c in r3["resolved"]] == ["ingest_silence"]
    assert sent[-1][0].startswith("Resolved:")


def test_disconnected_car_is_not_silent(engine):
    a, v = _vehicle(engine)
    now = datetime.now(UTC)
    with engine.begin() as conn:
        repo.record_connectivity(conn, a, v, now - timedelta(hours=3), False)
    assert alerts.check_ingest_silence(engine.connect(), a, now) == []


def test_billing_thresholds(engine):
    a, v = _vehicle(engine)
    now = datetime(2026, 9, 20, tzinfo=UTC)
    with engine.begin() as conn:
        repo.add_usage(conn, a, v, now.date(), "signal", 60_000, "VehicleSpeed")
        repo.add_usage(conn, a, v, now.date().replace(month=8), "signal", 500_000, "VehicleSpeed")
    with engine.connect() as conn:
        conds = alerts.check_billing(conn, a, now)
    assert [c.key for c in conds] == ["50"]
    assert "$6.00" in conds[0].detail
